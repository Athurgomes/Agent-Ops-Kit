"""Recuperação de senha dos usuários das organizações (por e-mail, opcional).

Só existe com AOK_SMTP_HOST e AOK_PUBLIC_URL definidos; sem isso forgot/reset respondem 404 e
`GET /v1/auth/capabilities` devolve {"password_reset": false}. Anti-enumeração: `forgot` responde SEMPRE
202 com o mesmo corpo (exista ou não o e-mail, usuário ou organização ativos ou não) e faz todo o
trabalho (consulta, token, e-mail) DEPOIS de responder, em segundo plano. Token: token_urlsafe(32), só o
hash SHA-256 no banco, uso único, 30 min, no FRAGMENTO do link (não vai para logs nem Referer). Limites
em memória, por processo, como o do login. O operador da plataforma não usa este fluxo.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.background import BackgroundTask

from . import mailer
from .auth import MIN_PASSWORD, hash_password, hash_token, new_token, org_is_active
from .models import AdminEvent, PasswordReset, User, UserSession, utcnow

log = logging.getLogger("aok_platform.recovery")

TOKEN_TTL = timedelta(minutes=30)
HOUR = 3600
FORGOT_PER_EMAIL = 3
FORGOT_PER_IP = 10
RESET_FAILS_PER_IP = 10
GENERIC = {"status": "accepted", "detail": "If the email belongs to an active account, a reset link has been sent."}
INVALID = "invalid or expired token"


class HourlyLimiter:
    """Contador por chave numa janela fixa de 1 hora, em memória (por processo)."""

    def __init__(self, maximum: int, window: float = HOUR, clock=time.monotonic):
        self.maximum, self.window, self.clock = maximum, window, clock
        self._state: dict[str, list[float]] = {}  # chave -> [início da janela, contagem]
        self._lock = threading.Lock()

    def _entry(self, key: str) -> list[float]:
        now = self.clock()
        if len(self._state) > 10_000:  # poda simples das janelas vencidas
            self._state = {k: v for k, v in self._state.items() if now - v[0] < self.window}
        st = self._state.get(key)
        if st is None or now - st[0] >= self.window:
            st = self._state[key] = [now, 0]
        return st

    def hit(self, key: str) -> bool:
        """Conta mais um pedido; True se ainda está dentro do limite."""
        with self._lock:
            st = self._entry(key)
            st[1] += 1
            return st[1] <= self.maximum

    def exceeded(self, key: str) -> bool:
        with self._lock:
            return self._entry(key)[1] >= self.maximum


class ForgotIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=MIN_PASSWORD, max_length=256)


def mask_email(email: str) -> str:
    """a***@e***.com: o log nunca traz o destinatário completo."""
    local, _, domain = email.partition("@")
    name, dot, tld = domain.rpartition(".")
    return f"{local[:1]}***@{name[:1]}***{dot}{tld}" if domain else f"{local[:1]}***"


def _safe_send(to: str, subject: str, text: str, html: str) -> None:
    """Melhor esforço: falha de SMTP nunca vaza para o cliente; o log não leva destinatário nem token."""
    try:
        mailer.send_mail(to, subject, text, html)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de envio vira só um log genérico
        log.warning("password recovery mail failed (%s) for %s", type(exc).__name__, mask_email(to))


def _forgot_mail(link: str) -> tuple[str, str, str]:
    text = (
        "Someone asked to reset the password of your Farol account.\n\n"
        f"Open this link to choose a new password (valid for 30 minutes, single use):\n{link}\n\n"
        "If you didn't request this, ignore it: your password stays the same.\n"
    )
    html = (
        "<p>Someone asked to reset the password of your Farol account.</p>"
        f'<p><a href="{escape(link, quote=True)}">Choose a new password</a> (valid for 30 minutes, single use).</p>'
        "<p>If you didn't request this, ignore it: your password stays the same.</p>"
    )
    return "Reset your Farol password", text, html


def _process_forgot(factory: sessionmaker[Session], email: str, allowed: bool) -> None:
    """Roda DEPOIS da resposta 202: só aqui se descobre se o e-mail existe."""
    if not allowed:
        return
    base = mailer.public_url()
    if base is None:
        return
    try:
        with factory() as s:
            user = s.scalar(select(User).where(User.email == email))
            if user is None or not user.active or not org_is_active(s, user.org_id):
                return
            now = utcnow()
            s.execute(  # um novo pedido invalida os anteriores ainda pendentes
                update(PasswordReset)
                .where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))
                .values(used_at=now)
            )
            token = new_token()
            s.add(PasswordReset(user_id=user.id, token_hash=hash_token(token), created_at=now, expires_at=now + TOKEN_TTL))
            s.commit()
            to = user.email
    except Exception as exc:  # noqa: BLE001
        log.warning("password recovery request failed (%s)", type(exc).__name__)
        return
    subject, text, html = _forgot_mail(f"{base}/reset-password#token={token}")
    _safe_send(to, subject, text, html)


def _notify_changed(email: str) -> None:
    _safe_send(
        email,
        "Your Farol password was changed",
        "Your Farol password was just changed.\n\nIf this wasn't you, contact your organization's admin right away.\n",
        "<p>Your Farol password was just changed.</p><p>If this wasn't you, contact your organization's admin right away.</p>",
    )


def _ip(request: Request) -> str:
    # Atrás de proxy este é o IP do proxy (não confiamos em X-Forwarded-For sem configuração): ver README.
    return request.client.host if request.client else "unknown"


def build_recovery_router(get_session, factory: sessionmaker[Session], limiters: dict[str, HourlyLimiter]) -> APIRouter:
    r = APIRouter(prefix="/v1/auth")

    @r.get("/capabilities")
    def capabilities():
        return {"password_reset": mailer.recovery_enabled()}

    @r.post("/password/forgot", status_code=202)
    def forgot(body: ForgotIn, request: Request):
        if not mailer.recovery_enabled():
            raise HTTPException(404, "not found")
        email = body.email.strip().lower()
        by_email = limiters["email"].hit(email)  # os dois contadores sempre andam: comportamento idêntico
        by_ip = limiters["ip"].hit(_ip(request))
        return JSONResponse(
            GENERIC, status_code=202, background=BackgroundTask(_process_forgot, factory, email, by_email and by_ip)
        )

    @r.post("/password/reset", status_code=204)
    def reset(body: ResetIn, request: Request, s: Session = Depends(get_session)):
        if not mailer.recovery_enabled():
            raise HTTPException(404, "not found")
        ip = _ip(request)
        if limiters["fail"].exceeded(ip):
            raise HTTPException(429, "too many attempts; try again later")

        def invalid():
            limiters["fail"].hit(ip)
            return HTTPException(400, INVALID)  # mesma resposta para qualquer motivo

        now = utcnow()
        row = s.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(body.token)))
        user = s.get(User, row.user_id) if row is not None else None
        if (
            row is None
            or row.used_at is not None
            or row.expires_at <= now
            or user is None
            or not user.active
            or not org_is_active(s, user.org_id)
        ):
            raise invalid()
        claimed = s.execute(  # uso único mesmo com duas requisições simultâneas
            update(PasswordReset).where(PasswordReset.id == row.id, PasswordReset.used_at.is_(None)).values(used_at=now)
        )
        if claimed.rowcount != 1:
            s.rollback()
            raise invalid()
        user.password_hash = hash_password(body.new_password)
        s.execute(update(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)).values(used_at=now))
        for sess in s.scalars(select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))):
            sess.revoked_at = now  # todas as sessões caem; não há login automático
        s.add(AdminEvent(org_id=user.org_id, actor_user_id=user.id, action="user.password_reset", target_type="user", target_id=user.id))
        email = user.email
        s.commit()
        return Response(status_code=204, background=BackgroundTask(_notify_changed, email))

    return r
