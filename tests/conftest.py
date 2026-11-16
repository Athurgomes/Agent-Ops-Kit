"""Testes de plataforma em SQLite (padrão) ou em Postgres (se AOK_TEST_DATABASE_URL estiver definida).

Com a variável definida, todo `create_app("sqlite:///:memory:", ...)` dos testes passa a usar um SCHEMA NOVO
do Postgres (um por teste, via search_path), apagado no fim do teste (DROP SCHEMA ... CASCADE): isolamento
sem lixo e sem mexer nos testes. Testes que pedem um arquivo SQLite continuam em SQLite (são sobre SQLite).
Sem a variável nada muda. Ex.: AOK_TEST_DATABASE_URL=postgresql+psycopg://postgres:SENHA@127.0.0.1:55432/postgres
"""

from __future__ import annotations

import os
import uuid

import pytest

TEST_DB_URL = os.environ.get("AOK_TEST_DATABASE_URL", "").strip()


def pg_schema_url(schema: str) -> str:
    """A URL de teste com o search_path apontando para `schema`."""
    from sqlalchemy.engine import make_url

    url = make_url(TEST_DB_URL)
    return url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(hide_password=False)


@pytest.fixture(autouse=True)
def _platform_test_database(monkeypatch):
    if not TEST_DB_URL:
        yield
        return
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("aok_platform")
    from aok_platform import app as app_module
    from aok_platform import db as db_module
    from sqlalchemy import create_engine, text

    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    schemas: list[str] = []
    engines: list = []
    real_make_engine = db_module.make_engine

    def make_engine(url=None):
        if url is not None and url.startswith("sqlite") and ":memory:" in url:
            schema = f"t_{uuid.uuid4().hex[:12]}"
            with admin.connect() as conn:
                conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            schemas.append(schema)
            engine = create_engine(pg_schema_url(schema), pool_pre_ping=True)
            engines.append(engine)
            return engine
        return real_make_engine(url)

    monkeypatch.setattr(app_module, "make_engine", make_engine)
    try:
        yield
    finally:
        for engine in engines:  # fecha as conexões do teste antes de apagar os schemas
            engine.dispose()
        with admin.connect() as conn:
            for schema in schemas:
                conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
