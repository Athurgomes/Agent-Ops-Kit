"""API admin da plataforma (fase 2): auth por chave de bootstrap, cadastro, tokens."""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.auth import hash_token
from aok_platform.models import AgentCredential
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

KEY = "chave-de-teste-nao-secreta"
H = {"Authorization": f"Bearer {KEY}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    return TestClient(create_app("sqlite:///:memory:"))


def _agent(client, slug="rag-demo", area_name="Financeiro"):
    area = client.post("/v1/admin/areas", json={"name": area_name}, headers=H).json()
    r = client.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": slug, "name": "RAG"}, headers=H
    )
    return area, r


def test_admin_sem_env_responde_503(monkeypatch):
    monkeypatch.delenv("AOK_ADMIN_BOOTSTRAP_KEY", raising=False)
    c = TestClient(create_app("sqlite:///:memory:"))
    assert c.post("/v1/admin/areas", json={"name": "x"}, headers=H).status_code == 503


def test_admin_env_vazia_responde_503(monkeypatch):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", "")
    c = TestClient(create_app("sqlite:///:memory:"))
    assert c.post("/v1/admin/areas", json={"name": "x"}).status_code == 503


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer errada"}, {"Authorization": KEY}]
)
def test_admin_sem_chave_ou_errada_responde_401(client, headers):
    assert client.post("/v1/admin/areas", json={"name": "x"}, headers=headers).status_code == 401


def test_cria_area_subarea_e_agente(client):
    macro = client.post("/v1/admin/areas", json={"name": "Financeiro"}, headers=H)
    assert macro.status_code == 201 and macro.json()["parent_id"] is None
    sub = client.post(
        "/v1/admin/areas", json={"name": "Contas", "parent_id": macro.json()["id"]}, headers=H
    )
    assert sub.status_code == 201 and sub.json()["parent_id"] == macro.json()["id"]
    r = client.post(
        "/v1/admin/agents",
        json={"area_id": sub.json()["id"], "slug": "rag-demo", "name": "RAG"},
        headers=H,
    )
    assert r.status_code == 201
    assert r.json()["active"] is True and r.json()["area_id"] == sub.json()["id"]


def test_subarea_com_pai_inexistente_404(client):
    r = client.post("/v1/admin/areas", json={"name": "x", "parent_id": 999}, headers=H)
    assert r.status_code == 404


def test_patch_area_nome_pai_e_ciclo(client):
    a = client.post("/v1/admin/areas", json={"name": "A"}, headers=H).json()
    b = client.post("/v1/admin/areas", json={"name": "B", "parent_id": a["id"]}, headers=H).json()
    r = client.patch(f"/v1/admin/areas/{b['id']}", json={"name": "B2"}, headers=H)
    assert r.json()["name"] == "B2" and r.json()["parent_id"] == a["id"]
    # ciclo: A dentro de B (filha de A)
    assert (
        client.patch(
            f"/v1/admin/areas/{a['id']}", json={"parent_id": b["id"]}, headers=H
        ).status_code
        == 422
    )
    # parent_id null explícito vira macro-área
    r = client.patch(f"/v1/admin/areas/{b['id']}", json={"parent_id": None}, headers=H)
    assert r.json()["parent_id"] is None


@pytest.mark.parametrize("slug", ["", "Maiusc", "com espaco", "a_b", "x" * 65, "ação"])
def test_slug_invalido_422(client, slug):
    area = client.post("/v1/admin/areas", json={"name": "A"}, headers=H).json()
    r = client.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": slug, "name": "n"}, headers=H
    )
    assert r.status_code == 422


def test_agente_exige_area_existente_e_slug_unico(client):
    r = client.post("/v1/admin/agents", json={"area_id": 42, "slug": "a", "name": "n"}, headers=H)
    assert r.status_code == 404
    area, first = _agent(client)
    assert first.status_code == 201
    dup = client.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": "rag-demo", "name": "n"}, headers=H
    )
    assert dup.status_code == 409


def test_patch_agente_move_desativa_e_recusa_slug(client):
    _area, r = _agent(client)
    agent = r.json()
    other = client.post("/v1/admin/areas", json={"name": "RH"}, headers=H).json()
    p = client.patch(
        f"/v1/admin/agents/{agent['id']}", json={"area_id": other["id"], "active": False}, headers=H
    )
    assert (
        p.status_code == 200 and p.json()["area_id"] == other["id"] and p.json()["active"] is False
    )
    assert (
        client.patch(
            f"/v1/admin/agents/{agent['id']}", json={"slug": "novo"}, headers=H
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/v1/admin/agents/{agent['id']}", json={"area_id": 999}, headers=H
        ).status_code
        == 404
    )


def test_token_mostrado_uma_vez_e_so_hash_no_banco(client):
    _, r = _agent(client)
    agent_id = r.json()["id"]
    t = client.post(f"/v1/admin/agents/{agent_id}/tokens", headers=H)
    assert t.status_code == 201
    token = t.json()["token"]
    assert len(token) >= 43  # token_urlsafe(32)
    with Session(client.app.state.engine) as s:
        creds = s.scalars(select(AgentCredential)).all()
    assert len(creds) == 1
    assert creds[0].token_hash == hash_token(token) and creds[0].token_hash != token
    assert creds[0].revoked_at is None and creds[0].last_used_at is None
    # nenhuma rota devolve o token de novo
    assert (
        token
        not in client.patch(f"/v1/admin/agents/{agent_id}", json={"name": "z"}, headers=H).text
    )
    # tokens distintos a cada emissão
    t2 = client.post(f"/v1/admin/agents/{agent_id}/tokens", headers=H).json()
    assert t2["token"] != token and t2["token_id"] != t.json()["token_id"]


def test_token_de_agente_inexistente_404(client):
    assert client.post("/v1/admin/agents/999/tokens", headers=H).status_code == 404


def test_revogar_marca_revoked_at_sem_apagar(client):
    _, r = _agent(client)
    agent_id = r.json()["id"]
    tid = client.post(f"/v1/admin/agents/{agent_id}/tokens", headers=H).json()["token_id"]
    d = client.delete(f"/v1/admin/agents/{agent_id}/tokens/{tid}", headers=H)
    assert d.status_code == 200 and d.json()["revoked_at"] and d.json()["token"] is None
    first = d.json()["revoked_at"]
    with Session(client.app.state.engine) as s:
        cred = s.get(AgentCredential, tid)
        assert cred is not None and cred.revoked_at is not None
    again = client.delete(f"/v1/admin/agents/{agent_id}/tokens/{tid}", headers=H)
    assert again.json()["revoked_at"] == first


def test_revogar_token_de_outro_agente_404(client):
    _, r1 = _agent(client, slug="a1", area_name="A")
    _, r2 = _agent(client, slug="a2", area_name="B")
    tid = client.post(f"/v1/admin/agents/{r1.json()['id']}/tokens", headers=H).json()["token_id"]
    assert (
        client.delete(f"/v1/admin/agents/{r2.json()['id']}/tokens/{tid}", headers=H).status_code
        == 404
    )
    assert (
        client.delete(f"/v1/admin/agents/{r1.json()['id']}/tokens/999", headers=H).status_code
        == 404
    )
    assert client.delete(f"/v1/admin/agents/{r1.json()['id']}/tokens/{tid}").status_code == 401
