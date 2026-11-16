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
    return user if user is not None and user.active else None


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
        s: Session = Depends(get_session),
    ) -> Actor:
        """Chave de bootstrap (Bearer) OU sessão de org_admin. Devolve quem agiu e a organização."""
        key = os.environ.get(BOOTSTRAP_ENV)
        scheme, _, given = (authorization or "").partition(" ")
        if (
            key
            and scheme.lower() == "bearer"
            and hmac.compare_digest(given.strip().encode("utf-8"), key.encode("utf-8"))
        ):
            org_id = s.scalar(select(Organization.id).order_by(Organization.id).limit(1))
            return Actor(None, org_id)  # uma organização só por enquanto: a primeira
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
