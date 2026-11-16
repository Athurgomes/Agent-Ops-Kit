"""Login, logout e /me (fase 3). Sessão em cookie HttpOnly; o token só é guardado como hash."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import (
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    burn_password_check,
    cookie_secure,
    hash_token,
    is_org_admin,
    new_token,
    org_is_active,
    verify_password,
)
from .models import Membership, User, UserSession, utcnow

MAX_FAILURES = 5
LOCK_SECONDS = 300


class LoginThrottle:
    """Falhas por e-mail em memória (por processo): 5 falhas travam o e-mail por 5 minutos."""

    def __init__(self, max_failures=MAX_FAILURES, lock_seconds=LOCK_SECONDS, clock=time.monotonic):
        self.max_failures, self.lock_seconds, self.clock = max_failures, lock_seconds, clock
        self._state: dict[str, list[float]] = {}  # email -> [falhas, travado_até]
        self._lock = threading.Lock()

    def retry_after(self, email: str) -> int:
        with self._lock:
            st = self._state.get(email)
            left = (st[1] - self.clock()) if st else 0
            return int(left) + 1 if left > 0 else 0

    def fail(self, email: str) -> None:
        with self._lock:
            now = self.clock()
            if len(self._state) > 10_000:  # poda simples: descarta entradas sem trava ativa
                self._state = {k: v for k, v in self._state.items() if v[1] > now}
            st = self._state.setdefault(email, [0, 0.0])
            if st[1] and st[1] <= now:  # trava expirou: recomeça a contagem
                st[0], st[1] = 0, 0.0
            st[0] += 1
            if st[0] >= self.max_failures:
                st[0], st[1] = 0, now + self.lock_seconds

    def ok(self, email: str) -> None:
        with self._lock:
            self._state.pop(email, None)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class MeOut(BaseModel):
    id: int
    email: str
    is_org_admin: bool
    memberships: list[dict]


def _me(s: Session, user: User) -> MeOut:
    rows = s.scalars(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)
    )
    return MeOut(
        id=user.id,
        email=user.email,
        is_org_admin=is_org_admin(s, user),
        memberships=[{"area_id": m.area_id, "role": m.role} for m in rows],
    )


def build_auth_router(get_session, current_user, throttle: LoginThrottle) -> APIRouter:
    r = APIRouter(prefix="/v1/auth")

    @r.post("/login", response_model=MeOut)
    def login(body: LoginIn, response: Response, s: Session = Depends(get_session)):
        email = body.email.strip().lower()
        wait = throttle.retry_after(email)
        if wait:
            raise HTTPException(
                429, "muitas tentativas; tente novamente mais tarde", {"Retry-After": str(wait)}
            )
        user = s.scalar(select(User).where(User.email == email))
        if user is None or not user.active or not org_is_active(s, user.org_id):
            burn_password_check(body.password)
            good = False
        else:
            good = verify_password(body.password, user.password_hash)
        if not good:
            throttle.fail(email)
            raise HTTPException(401, "e-mail ou senha inválidos")  # mesma resposta nos 3 casos
        throttle.ok(email)
        token = new_token()
        now = utcnow()
        s.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + timedelta(seconds=SESSION_TTL_SECONDS),
            )
        )
        s.commit()
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="strict",
            secure=cookie_secure(),
            path="/",
        )
        return _me(s, user)

    @r.post("/logout", status_code=204)
    def logout(request: Request, response: Response, s: Session = Depends(get_session)):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            row = s.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
            if row is not None and row.revoked_at is None:
                row.revoked_at = utcnow()
                s.commit()
        response.delete_cookie(
            SESSION_COOKIE, path="/", httponly=True, samesite="strict", secure=cookie_secure()
        )

    @r.get("/me", response_model=MeOut)
    def me(user: User = Depends(current_user), s: Session = Depends(get_session)):
        return _me(s, user)

    return r
