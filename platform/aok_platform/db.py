"""Engine e sessão. URL via AOK_DATABASE_URL; padrão SQLite local (dev e testes)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import StaticPool, create_engine, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .migrate import run_migrations
from .models import Organization

DEFAULT_URL = "sqlite:///./aok_platform.db"
DEFAULT_ORG_NAME = "default"
DEFAULT_ORG_SLUG = "default"


def auto_migrate_enabled() -> bool:
    """Lê `AOK_AUTO_MIGRATE` (padrão True; '0', 'false', 'no', 'off' desativam)."""
    raw = os.environ.get("AOK_AUTO_MIGRATE")
    if raw is None or not raw.strip():
        return True
    val = raw.strip().lower()
    return val not in {"0", "false", "no", "off"}


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("AOK_DATABASE_URL") or DEFAULT_URL
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool  # uma conexão só: o banco em memória é compartilhado
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


def ensure_schema(engine: Engine) -> None:
    """Aplica migrações pendentes via Alembic (idempotente, SQLite e Postgres)."""
    run_migrations(engine)


def init_db(engine: Engine) -> None:
    """Aplica migrações se AOK_AUTO_MIGRATE estiver ativo e garante a organização padrão."""
    if auto_migrate_enabled():
        ensure_schema(engine)
    elif not inspect(engine).has_table("organization"):
        raise RuntimeError(
            "Banco sem esquema aplicado e AOK_AUTO_MIGRATE=false; "
            "execute 'python -m aok_platform.migrate upgrade'."
        )
    with Session(engine) as s:
        if s.scalar(select(Organization.id).limit(1)) is None:
            s.add(Organization(name=DEFAULT_ORG_NAME, slug=DEFAULT_ORG_SLUG, active=True))
            try:
                s.commit()
            except IntegrityError:
                s.rollback()


def session_dependency(factory: sessionmaker[Session]):
    def get_session() -> Iterator[Session]:
        with factory() as s:
            yield s

    return get_session
