"""Autenticação admin por chave de bootstrap (AOK_ADMIN_BOOTSTRAP_KEY) e tokens de agente."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import Header, HTTPException

BOOTSTRAP_ENV = "AOK_ADMIN_BOOTSTRAP_KEY"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def require_admin(authorization: str | None = Header(default=None)) -> None:
    key = os.environ.get(BOOTSTRAP_ENV)
    if not key:  # nunca existe chave padrão
        raise HTTPException(503, f"rotas admin desativadas: defina {BOOTSTRAP_ENV}")
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        given.strip().encode("utf-8"), key.encode("utf-8")
    ):
        raise HTTPException(
            401, "chave de admin ausente ou inválida", {"WWW-Authenticate": "Bearer"}
        )
