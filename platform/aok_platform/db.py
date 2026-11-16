"""Engine e sessão. URL via AOK_DATABASE_URL; padrão SQLite local (dev e testes)."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import StaticPool, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Organization

DEFAULT_URL = "sqlite:///./aok_platform.db"
DEFAULT_ORG_NAME = "default"


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("AOK_DATABASE_URL") or DEFAULT_URL
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool  # uma conexão só: o banco em memória é compartilhado
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


def init_db(engine: Engine) -> None:
    """create_all (sem Alembic) e organização padrão (multiempresa fica para depois da fase 4)."""
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        if s.scalar(select(Organization.id).limit(1)) is None:
            s.add(Organization(name=DEFAULT_ORG_NAME))
            s.commit()


def session_dependency(factory: sessionmaker[Session]):
    def get_session() -> Iterator[Session]:
        with factory() as s:
            yield s

    return get_session
