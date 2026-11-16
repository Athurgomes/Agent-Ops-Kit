"""Autenticação: chave de bootstrap, tokens de agente, senhas (scrypt) e sessão por cookie."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Area, Membership, Organization, User, UserSession, utcnow

BOOTSTRAP_ENV = "AOK_ADMIN_BOOTSTRAP_KEY"
SESSION_COOKIE = "aok_session"
SESSION_TTL_SECONDS = 8 * 3600
MIN_PASSWORD = 12
ORG_ADMIN = "org_admin"
AREA_VIEWER = "area_viewer"

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def cookie_secure() -> bool:
    """AOK_COOKIE_SECURE: padrão true; só 0/false/no/off desliga (dev local sem HTTPS)."""
    return os.environ.get("AOK_COOKIE_SECURE", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


# ---- senhas -----------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        expected = base64.b64decode(dk)
        got = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            dklen=len(expected),
            n=int(n),
            r=int(r),
            p=int(p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, expected)


_DUMMY_HASH: str | None = None


def burn_password_check(password: str) -> None:
    """Gasta o mesmo tempo de um login real quando o e-mail não existe (evita enumeração)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _DUMMY_HASH)


_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"  # sem caracteres ambíguos


def generate_password(length: int = 20) -> str:
    """Senha aleatória do servidor (secrets). Quem a gera mostra UMA vez e nunca a guarda em claro."""
    return "".join(secrets.choice(_PW_ALPHABET) for _ in range(max(length, 16)))


# ---- sessão e perfis --------------------------------------------------------------------------


def session_user(request: Request, s: Session) -> User | None:
    """Usuário da sessão do cookie; None se ausente, expirada, revogada ou usuário inativo."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = s.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        return None
    user = s.get(User, row.user_id)
    if user is None or not user.active or not org_is_active(s, user.org_id):
        return None  # usuário ou organização inativos: a sessão para de valer, nada é apagado
    return user


def org_is_active(s: Session, org_id: int | None) -> bool:
    org = s.get(Organization, org_id) if org_id is not None else None
    return org is not None and bool(org.active)


def is_org_admin(s: Session, user: User) -> bool:
    return (
        s.scalar(
            select(Membership.id)
            .where(Membership.user_id == user.id, Membership.role == ORG_ADMIN)
            .limit(1)
        )
        is not None
    )


def visible_area_ids(s: Session, user: User) -> set[int]:
    """org_admin: toda a organização. area_viewer: a área do vínculo e todas as descendentes."""
    if is_org_admin(s, user):
        return set(s.scalars(select(Area.id).where(Area.org_id == user.org_id)))
    roots = select(Membership.area_id).where(
        Membership.user_id == user.id, Membership.role == AREA_VIEWER
    )
    tree = select(Area.id).where(Area.id.in_(roots)).cte("tree", recursive=True)
    tree = tree.union_all(select(Area.id).join(tree, Area.parent_id == tree.c.id))
    return set(
        s.scalars(select(Area.id).where(Area.id.in_(select(tree.c.id)), Area.org_id == user.org_id))
    )


@dataclass(frozen=True)
class Actor:
    """Quem faz uma ação admin: usuário da sessão, ou a chave de bootstrap (user_id None)."""

    user_id: int | None
    org_id: int


def _bootstrap_org(s: Session, slug: str | None) -> int:
    if slug is not None and slug.strip():
        org = s.scalar(select(Organization).where(Organization.slug == slug.strip().lower()))
        if org is None or not org.active:
            raise HTTPException(404, "organização não encontrada")
        return org.id
    ids = list(s.scalars(select(Organization.id).order_by(Organization.id).limit(2)))
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise HTTPException(404, "organização não encontrada")
    raise HTTPException(400, "há mais de uma organização: envie o cabeçalho X-Org-Slug")


def make_dependencies(get_session):
    """Dependências que precisam da sessão de banco (mesma instância por requisição)."""

    def current_user(request: Request, s: Session = Depends(get_session)) -> User:
        user = session_user(request, s)
        if user is None:
            raise HTTPException(401, "não autenticado")
        return user

    def current_org_admin(
        user: User = Depends(current_user), s: Session = Depends(get_session)
    ) -> User:
        if not is_org_admin(s, user):
            raise HTTPException(403, "requer org_admin")
        return user

    def require_admin(
        request: Request,
        authorization: str | None = Header(default=None),
        x_org_slug: str | None = Header(default=None),
        s: Session = Depends(get_session),
    ) -> Actor:
        """Chave de bootstrap (Bearer) OU sessão de org_admin. Devolve quem agiu e a organização.

        Sessão: a organização é a do usuário (X-Org-Slug é ignorado). Bootstrap: com exatamente uma
        organização ela é usada; com duas ou mais o cabeçalho X-Org-Slug é obrigatório. Nunca "a primeira".
        """
        key = os.environ.get(BOOTSTRAP_ENV)
        scheme, _, given = (authorization or "").partition(" ")
        if (
            key
            and scheme.lower() == "bearer"
            and hmac.compare_digest(given.strip().encode("utf-8"), key.encode("utf-8"))
        ):
            return Actor(None, _bootstrap_org(s, x_org_slug))
        user = session_user(request, s)
        if user is not None:
            if not is_org_admin(s, user):
                raise HTTPException(403, "requer org_admin")
            return Actor(user.id, user.org_id)
        if not key:  # nunca existe chave padrão
            raise HTTPException(503, f"rotas admin desativadas: defina {BOOTSTRAP_ENV}")
        raise HTTPException(
            401, "chave de admin ausente ou inválida", {"WWW-Authenticate": "Bearer"}
        )

    return current_user, current_org_admin, require_admin
