"""ensure_schema sobre um banco LEGADO no Postgres (esquema da fase 2). Só roda com AOK_TEST_DATABASE_URL."""

import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
from conftest import TEST_DB_URL, pg_schema_url

pytestmark = pytest.mark.skipif(not TEST_DB_URL, reason="defina AOK_TEST_DATABASE_URL (Postgres) para rodar")

from aok_platform.app import create_app
from aok_platform.db import ensure_schema
from aok_platform.models import Agent, Area, Organization
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

LEGACY = """
CREATE TABLE organization (id SERIAL PRIMARY KEY, name VARCHAR(200) NOT NULL);
CREATE TABLE area (id SERIAL PRIMARY KEY, org_id INTEGER NOT NULL REFERENCES organization(id),
                   name VARCHAR(200) NOT NULL, parent_id INTEGER REFERENCES area(id));
CREATE TABLE agent (id SERIAL PRIMARY KEY, area_id INTEGER NOT NULL REFERENCES area(id),
                    slug VARCHAR(64) NOT NULL UNIQUE, name VARCHAR(200) NOT NULL, active BOOLEAN);
INSERT INTO organization (name) VALUES ('Empresa Legada');
INSERT INTO area (org_id, name) VALUES (1, 'Financeiro');
INSERT INTO agent (area_id, slug, name, active) VALUES (1, 'ag-legado', 'Agente Legado', true);
"""


@pytest.fixture
def legacy_url():
    schema = f"t_legacy_{uuid.uuid4().hex[:10]}"
    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = pg_schema_url(schema)
    engine = create_engine(url)
    with engine.begin() as conn:
        for stmt in LEGACY.strip().split(";\n"):
            conn.execute(text(stmt))
    engine.dispose()
    yield url
    with admin.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    admin.dispose()


def _constraints(engine):
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = 'agent'::regclass"))}


def _indexes(engine, table):
    return {i["name"]: i for i in inspect(engine).get_indexes(table)}


def test_migra_sem_perder_dados_e_libera_slug_por_org(legacy_url, monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", "chave-de-teste-nao-secreta")
    engine = create_engine(legacy_url)
    assert "agent_slug_key" in _constraints(engine)  # confirma o ponto de partida: slug global

    app = create_app(legacy_url, data_dir=tmp_path / "d")  # init_db -> ensure_schema
    ensure_schema(app.state.engine)  # idempotente (segunda rodada não muda nada)
    eng = app.state.engine

    cols = {c["name"] for c in inspect(eng).get_columns("organization")}
    assert {"slug", "active", "created_at"} <= cols
    assert "org_id" in {c["name"] for c in inspect(eng).get_columns("agent")}
    with Session(eng) as s:
        org = s.scalars(select(Organization).order_by(Organization.id)).first()
        assert (org.name, org.slug, org.active) == ("Empresa Legada", "empresa-legada", True) and org.created_at
        agent = s.scalars(select(Agent)).one()
        assert (agent.slug, agent.name, agent.active, agent.org_id) == ("ag-legado", "Agente Legado", True, org.id)
        assert s.scalar(select(Area.name)) == "Financeiro"
        orgs = s.scalars(select(Organization)).all()
        assert len(orgs) == 1  # a migração não inventa organização (a padrão só nasce em banco vazio)

    # a restrição global saiu; entraram os índices únicos novos
    assert "agent_slug_key" not in _constraints(eng)
    assert _indexes(eng, "agent")["uq_agent_org_slug"]["unique"] is True
    assert _indexes(eng, "organization")["uq_organization_slug"]["unique"] is True

    # dois agentes com o mesmo slug em organizações diferentes: agora pode; na mesma organização, não
    with Session(eng) as s:
        org2 = Organization(name="Outra", slug="outra", active=True)
        s.add(org2)
        s.flush()
        area2 = Area(org_id=org2.id, name="Dados")
        s.add(area2)
        s.flush()
        s.add(Agent(org_id=org2.id, area_id=area2.id, slug="ag-legado", name="Mesmo slug", active=True))
        s.commit()
        org1 = s.scalars(select(Organization).where(Organization.slug == "empresa-legada")).one()
        area1 = s.scalars(select(Area).where(Area.org_id == org1.id)).one()
        s.add(Agent(org_id=org1.id, area_id=area1.id, slug="ag-legado", name="Duplicado", active=True))
        with pytest.raises(IntegrityError):
            s.commit()
        s.rollback()
        with pytest.raises(IntegrityError):  # slug de organização também é único
            s.add(Organization(name="X", slug="outra", active=True))
            s.commit()

    # a API sobe sobre o banco migrado (com 2 orgs a chave de bootstrap exige X-Org-Slug)
    c = TestClient(app)
    key = {"Authorization": "Bearer chave-de-teste-nao-secreta"}
    assert c.get("/v1/admin/areas", headers=key).status_code == 400
    r = c.get("/v1/admin/agents", headers={**key, "X-Org-Slug": "empresa-legada"})
    assert r.status_code == 200 and [a["slug"] for a in r.json()] == ["ag-legado"]
    r = c.get("/v1/admin/agents", headers={**key, "X-Org-Slug": "outra"})
    assert r.status_code == 200 and [a["name"] for a in r.json()] == ["Mesmo slug"]
