"""Engine e sessão. URL via AOK_DATABASE_URL; padrão SQLite local (dev e testes)."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import StaticPool, create_engine, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, Organization

DEFAULT_URL = "sqlite:///./aok_platform.db"
DEFAULT_ORG_NAME = "default"
DEFAULT_ORG_SLUG = "default"


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("AOK_DATABASE_URL") or DEFAULT_URL
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url in ("sqlite://", "sqlite:///"):
            kwargs["poolclass"] = StaticPool  # uma conexão só: o banco em memória é compartilhado
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


def _slugify(name: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64]
    return slug or fallback


def ensure_schema(engine: Engine) -> None:
    """Cria tabelas que faltam e ADICIONA colunas novas às tabelas já existentes (sem Alembic).

    Idempotente; usa o inspector do SQLAlchemy (SQLite e Postgres). Só adiciona: nunca remove nem
    altera coluna. As colunas entram anuláveis e são preenchidas (backfill) em seguida. Limite
    conhecido (dívida: migração formal com Alembic): em bancos antigos a restrição `UNIQUE(slug)`
    de `agent` continua valendo no SQLite (só o Postgres a remove aqui); o SQLite só passa a ter
    slug único por organização em banco novo ou depois de recriar a tabela.
    """
    Base.metadata.create_all(engine)
    quote = engine.dialect.identifier_preparer.quote
    added: set[tuple[str, str]] = set()
    with engine.begin() as conn:
        insp = inspect(conn)
        for table in Base.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f"ALTER TABLE {quote(table.name)} ADD COLUMN {quote(col.name)} {ddl}"))
                    added.add((table.name, col.name))
        org = Organization.__table__
        rows = conn.execute(select(org.c.id, org.c.name).where(org.c.slug.is_(None))).all()
        taken = {r[0] for r in conn.execute(select(org.c.slug).where(org.c.slug.is_not(None)))}
        for oid, name in rows:
            slug = _slugify(name, f"org-{oid}")
            if slug in taken:
                slug = f"{slug[:55]}-{oid}"
            taken.add(slug)
            conn.execute(update(org).where(org.c.id == oid).values(slug=slug))
        conn.execute(update(org).where(org.c.active.is_(None)).values(active=True))
        conn.execute(update(org).where(org.c.created_at.is_(None)).values(created_at=datetime.now(UTC)))
        conn.execute(
            text(
                "UPDATE agent SET org_id = (SELECT area.org_id FROM area WHERE area.id = agent.area_id)"
                " WHERE org_id IS NULL"
            )
        )
        if ("organization", "slug") in added:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_slug ON organization (slug)"))
        if ("agent", "org_id") in added:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_org_slug ON agent (org_id, slug)"))
            if engine.dialect.name == "postgresql":
                conn.execute(text("ALTER TABLE agent DROP CONSTRAINT IF EXISTS agent_slug_key"))


def init_db(engine: Engine) -> None:
    """Garante o esquema (ensure_schema) e a organização padrão se ainda não houver nenhuma."""
    ensure_schema(engine)
    with Session(engine) as s:
        if s.scalar(select(Organization.id).limit(1)) is None:
            s.add(Organization(name=DEFAULT_ORG_NAME, slug=DEFAULT_ORG_SLUG, active=True))
            s.commit()


def session_dependency(factory: sessionmaker[Session]):
    def get_session() -> Iterator[Session]:
        with factory() as s:
            yield s

    return get_session
