"""Testes das migrações Alembic da plataforma (SQLite novo, legado, roundtrip, CLI e Postgres)."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import uuid

import pytest

pytest.importorskip("alembic")
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from aok_platform.app import create_app
from aok_platform.db import init_db, make_engine
from aok_platform.migrate import alembic_config, run_migrations
from aok_platform.models import Agent, Base, Organization
from conftest import TEST_DB_URL, pg_schema_url
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

EXPECTED_TABLES = {
    "organization",
    "area",
    "agent",
    "agent_credential",
    "report_version",
    "user",
    "membership",
    "session",
    "password_reset",
    "download_log",
    "admin_event",
    "platform_operator",
    "operator_session",
    "operator_event",
    "rate_limit_entry",
    "agent_public_keys",
}

EXPECTED_INDEXES = {
    "agent": {"ix_agent_org_id"},
    "agent_credential": {"ix_agent_credential_agent_id"},
    "report_version": {"ix_report_version_agent_id"},
    "membership": {"ix_membership_user_id"},
    "session": {"ix_session_user_id"},
    "password_reset": {"ix_password_reset_user_id"},
    "download_log": {"ix_download_log_report_version_id", "ix_download_log_user_id"},
    "admin_event": {"ix_admin_event_org_id", "ix_admin_event_at"},
    "operator_session": {"ix_operator_session_operator_id"},
    "operator_event": {"ix_operator_event_at", "ix_operator_event_operator_id"},
    "rate_limit_entry": {"ix_rate_limit_entry_expires_at"},
    "agent_public_keys": {"ix_agent_public_keys_agent_id"},
}


def _schema_diffs(engine) -> list:
    with engine.connect() as conn:
        mc = MigrationContext.configure(
            conn,
            opts={"compare_type": True, "render_as_batch": engine.dialect.name == "sqlite"},
        )
        return compare_metadata(mc, Base.metadata)


def _alembic_revisions(engine) -> list[str]:
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version"))]


def test_sqlite_novo_cria_tabelas_indices_e_alembic_version_idempotente(tmp_path):
    db_path = tmp_path / "fresh.db"
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        run_migrations(engine)
        run_migrations(engine)  # 2ª execução idempotente

        insp = inspect(engine)
        tables = set(insp.get_table_names())
        assert EXPECTED_TABLES <= tables
        assert "alembic_version" in tables
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert _schema_diffs(engine) == []

        for table, expected_ix in EXPECTED_INDEXES.items():
            got = {ix["name"] for ix in insp.get_indexes(table)}
            assert expected_ix <= got
    finally:
        engine.dispose()


def _create_legacy_sqlite(path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE organization (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL);
        CREATE TABLE area (id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL,
                           parent_id INTEGER);
        CREATE TABLE agent (id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, slug VARCHAR(64) NOT NULL UNIQUE,
                            name VARCHAR(200) NOT NULL, active BOOLEAN);
        INSERT INTO organization (id, name) VALUES (1, 'Acme'), (2, 'Beta');
        INSERT INTO area (id, org_id, name) VALUES (1, 1, 'Geral'), (2, 2, 'Ops');
        INSERT INTO agent (id, area_id, slug, name, active)
            VALUES (1, 1, 'bot-comum', 'Bot Acme', 1),
                   (2, 2, 'bot-outro', 'Bot Beta', 1);
        """
    )
    con.commit()
    con.close()


def test_sqlite_legado_remove_unique_global_de_slug_preserva_dados_e_idempotente(tmp_path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_sqlite(db_path)
    engine = make_engine(f"sqlite:///{db_path}")
    try:
        run_migrations(engine)
        run_migrations(engine)  # idempotente

        insp = inspect(engine)
        assert EXPECTED_TABLES <= set(insp.get_table_names())
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert "ix_agent_org_id" in {ix["name"] for ix in insp.get_indexes("agent")}

        with Session(engine) as s:
            orgs = list(s.scalars(select(Organization).order_by(Organization.id)))
            assert [o.slug for o in orgs] == ["acme", "beta"]
            assert all(o.active is True and o.created_at is not None for o in orgs)
            agents = {a.id: (a.org_id, a.slug, a.name) for a in s.scalars(select(Agent))}
            assert agents == {
                1: (1, "bot-comum", "Bot Acme"),
                2: (2, "bot-outro", "Bot Beta"),
            }

            # Mesmo slug em organização diferente agora é permitido
            s.add(Agent(org_id=2, area_id=2, slug="bot-comum", name="Bot Comum Beta", active=True))
            s.commit()

            # Mesmo slug na mesma organização falha com IntegrityError
            s.add(Agent(org_id=1, area_id=1, slug="bot-comum", name="Duplicado", active=True))
            with pytest.raises(IntegrityError):
                s.commit()
            s.rollback()
    finally:
        engine.dispose()


def test_sqlite_roundtrip_upgrade_downgrade_upgrade(tmp_path):
    db_path = tmp_path / "roundtrip.db"
    url = f"sqlite:///{db_path}"
    engine = make_engine(url)
    try:
        run_migrations(engine)
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())

        cfg = alembic_config(url)
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")

        remaining = set(inspect(engine).get_table_names()) - {"alembic_version"}
        assert remaining == set()
        assert _alembic_revisions(engine) == []

        run_migrations(engine)
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert _schema_diffs(engine) == []
    finally:
        engine.dispose()


def test_sqlite_incremental_0001_para_0002_e_downgrade_parcial(tmp_path):
    db_path = tmp_path / "inc.db"
    url = f"sqlite:///{db_path}"
    engine = make_engine(url)
    try:
        run_migrations(engine, revision="0001_initial_schema")
        assert _alembic_revisions(engine) == ["0001_initial_schema"]
        assert "rate_limit_entry" not in set(inspect(engine).get_table_names())

        run_migrations(engine)
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert "rate_limit_entry" in set(inspect(engine).get_table_names())
        assert _schema_diffs(engine) == []

        cfg = alembic_config(url)
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0001_initial_schema")
        assert _alembic_revisions(engine) == ["0001_initial_schema"]
        assert "rate_limit_entry" not in set(inspect(engine).get_table_names())

        run_migrations(engine)
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert "rate_limit_entry" in set(inspect(engine).get_table_names())
        assert _schema_diffs(engine) == []
    finally:
        engine.dispose()


def test_sqlite_0003_preserva_dados_e_downgrade_para_0002(tmp_path):
    url = f"sqlite:///{tmp_path / 'sig.db'}"
    engine = make_engine(url)
    try:
        run_migrations(engine, revision="0002_rate_limit_entry")
        assert "agent_public_keys" not in set(inspect(engine).get_table_names())
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO organization (id, name, slug, active, created_at) "
                              "VALUES (7, 'O', 'o', 1, '2026-01-01')"))
            conn.execute(text("INSERT INTO area (id, org_id, name) VALUES (7, 7, 'A')"))
            conn.execute(text("INSERT INTO agent (id, org_id, area_id, slug, name, active) "
                              "VALUES (7, 7, 7, 'ag', 'Ag', 1)"))
        run_migrations(engine)
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert _schema_diffs(engine) == []
        with engine.connect() as conn:
            assert conn.execute(text("SELECT require_signature FROM agent")).scalar() in (0, False)

        cfg = alembic_config(url)
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0002_rate_limit_entry")
        insp = inspect(engine)
        assert "agent_public_keys" not in set(insp.get_table_names())
        assert "require_signature" not in {c["name"] for c in insp.get_columns("agent")}
        assert {"signed", "key_fingerprint"}.isdisjoint(
            {c["name"] for c in insp.get_columns("report_version")}
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize("flag", ["false", "0", "no", "off"])
def test_auto_migrate_false_impede_criacao_em_banco_vazio_e_aceita_banco_premigrado(
    monkeypatch, tmp_path, flag
):
    db_path = tmp_path / f"manual_{flag}.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("AOK_AUTO_MIGRATE", flag)

    engine = make_engine(url)
    try:
        with pytest.raises(RuntimeError, match="migrate upgrade"):
            init_db(engine)
        assert inspect(engine).get_table_names() == []

        with pytest.raises(RuntimeError, match="migrate upgrade"):
            create_app(url, data_dir=tmp_path / "data")
        assert inspect(engine).get_table_names() == []

        # Após migrar explicitamente, o startup com AOK_AUTO_MIGRATE=false funciona normalmente
        run_migrations(engine)
    finally:
        engine.dispose()

    app = create_app(url, data_dir=tmp_path / "data")
    client = TestClient(app)
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    with Session(app.state.engine) as s:
        assert s.scalar(select(Organization.slug)) == "default"
    app.state.engine.dispose()


def test_cli_migrate_upgrade_current_heads_independente_de_cwd(tmp_path):
    db_path = tmp_path / "cli.db"
    url = f"sqlite:///{db_path}"

    heads = subprocess.run(
        [sys.executable, "-m", "aok_platform.migrate", "heads"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0004_report_verification" in heads.stdout

    subprocess.run(
        [sys.executable, "-m", "aok_platform.migrate", "upgrade", "--url", url],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    current = subprocess.run(
        [sys.executable, "-m", "aok_platform.migrate", "--url", url, "current"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0004_report_verification" in current.stdout

    engine = make_engine(url)
    try:
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.skipif(not TEST_DB_URL, reason="defina AOK_TEST_DATABASE_URL (Postgres) para rodar")
def test_postgres_novo_upgrade_idempotente_e_roundtrip():
    schema = f"t_mig_{uuid.uuid4().hex[:10]}"
    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = pg_schema_url(schema)
    engine = make_engine(url)
    try:
        run_migrations(engine)
        run_migrations(engine)  # idempotente com pg_advisory_xact_lock

        insp = inspect(engine)
        assert EXPECTED_TABLES <= set(insp.get_table_names())
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert _schema_diffs(engine) == []
        for table, expected_ix in EXPECTED_INDEXES.items():
            assert expected_ix <= {ix["name"] for ix in insp.get_indexes(table)}

        cfg = alembic_config(url)
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0001_initial_schema")
        assert _alembic_revisions(engine) == ["0001_initial_schema"]
        assert "rate_limit_entry" not in set(inspect(engine).get_table_names())

        run_migrations(engine)
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert _schema_diffs(engine) == []

        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) - {"alembic_version"} == set()

        run_migrations(engine)
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
        assert _alembic_revisions(engine) == ["0004_report_verification"]
        assert _schema_diffs(engine) == []
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
