"""Ambiente de execução das migrações Alembic (SQLite e Postgres)."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from aok_platform.db import DEFAULT_URL, make_engine
from aok_platform.models import Base
from sqlalchemy import text

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata

# Chave fixa de 64 bits ("aok_migr" em ASCII) para advisory lock transacional no Postgres.
PG_ADVISORY_LOCK_KEY = 7020949325937117042


def _resolve_url() -> str:
    return (
        config.attributes.get("url")
        or config.get_main_option("sqlalchemy.url")
        or os.environ.get("AOK_DATABASE_URL")
        or DEFAULT_URL
    )


def _run_with_connection(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=(connection.dialect.name == "sqlite"),
        compare_type=True,
    )
    with context.begin_transaction():
        if connection.dialect.name == "postgresql":
            connection.execute(
                text("SELECT pg_advisory_xact_lock(:key)"),
                {"key": PG_ADVISORY_LOCK_KEY},
            )
        context.run_migrations()


def run_migrations_offline() -> None:
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run_with_connection(connection)
        return

    connectable = make_engine(_resolve_url())
    try:
        with connectable.connect() as conn:
            _run_with_connection(conn)
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
