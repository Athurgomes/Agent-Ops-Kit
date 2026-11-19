"""Paginação retrocompatível (limit/offset + X-Total-Count) nas rotas admin e do operador."""

import hashlib
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.auth import hash_password
from aok_platform.models import PlatformOperator
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

KEY = "chave-de-teste-nao-secreta"
OP_EMAIL, OP_PWD = "ops@plataforma.test", "senha-do-operador-123"
USER_PWD = "senha-valida-123"


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch):
    monkeypatch.setattr("aok_platform.auth._SCRYPT", {"n": 2**4, "r": 8, "p": 1})


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    monkeypatch.setenv("AOK_OPS_ENABLED", "true")
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    with Session(app.state.engine) as s:
        s.add(PlatformOperator(email=OP_EMAIL, password_hash=hash_password(OP_PWD), active=True))
        s.commit()
    ops_client = TestClient(app)
    r = ops_client.post("/v1/ops/auth/login", json={"email": OP_EMAIL, "password": OP_PWD})
    assert r.status_code == 200
    return app, ops_client


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package(slug: str, tag: str) -> dict:
    js = {
        "generated_at": "2026-01-02T03:04:05-03:00",
        "agent": {"name": slug, "model": "m"},
        "semaphore": {"color": "green", "triggered": []},
        "eval": {"baseline": "v1", "candidate": "v2", "n_cases": 5, "tag": tag},
    }
    files = {
        "relatorio.json": json.dumps(js),
        "relatorio.md": f"# {tag}\n",
        "relatorio.html": f"<p>{tag}</p>",
    }
    return {
        "agent_id": slug,
        "timestamp": "20260102T030405Z",
        "semaphore": "green",
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
    }


def _new_org_admin(app, ops_client: TestClient, slug: str, name: str) -> tuple[int, TestClient]:
    org = ops_client.post("/v1/ops/organizations", json={"slug": slug, "name": name}).json()
    adm = ops_client.post(
        f"/v1/ops/organizations/{org['id']}/admins", json={"email": f"admin@{slug}.test"}
    ).json()
    ac = TestClient(app)
    r = ac.post("/v1/auth/login", json={"email": adm["email"], "password": adm["password"]})
    assert r.status_code == 200
    return org["id"], ac


def test_admin_listagens_paginacao_ordem_e_isolamento(env):
    app, ops_client = env
    _, ac_a = _new_org_admin(app, ops_client, "alfa", "Alfa")
    _, ac_b = _new_org_admin(app, ops_client, "beta", "Beta")

    # Cria áreas fora de ordem alfabética (incluindo nome repetido para testar desempate por id)
    areas_a = [
        ac_a.post("/v1/admin/areas", json={"name": name}).json()
        for name in ("Zebra", "Alfa", "Alfa", "Meio", "Delta")
    ]
    assert len(areas_a) == 5
    # Outra organização não interfere nos totais nem nas páginas de Alfa
    area_b = ac_b.post("/v1/admin/areas", json={"name": "BetaArea"}).json()
    ac_b.post(
        "/v1/admin/agents", json={"area_id": area_b["id"], "slug": "b-ag", "name": "B"}
    )
    ac_b.post("/v1/admin/users", json={"email": "u@beta.test", "password": USER_PWD})

    # /v1/admin/areas: completo sem query params, ordenado por (name, id)
    full_areas = ac_a.get("/v1/admin/areas")
    assert full_areas.status_code == 200
    assert full_areas.headers["x-total-count"] == "5"
    full_area_ids = [a["id"] for a in full_areas.json()]
    assert [(a["name"], a["id"]) for a in full_areas.json()] == sorted(
        [(a["name"], a["id"]) for a in areas_a]
    )

    p1 = ac_a.get("/v1/admin/areas?limit=2&offset=0")
    p2 = ac_a.get("/v1/admin/areas?limit=2&offset=2")
    p3 = ac_a.get("/v1/admin/areas?limit=2&offset=4")
    p_end = ac_a.get("/v1/admin/areas?limit=2&offset=5")
    p_off = ac_a.get("/v1/admin/areas?offset=3")
    assert all(r.headers["x-total-count"] == "5" for r in (p1, p2, p3, p_end, p_off))
    assert [a["id"] for a in p1.json() + p2.json() + p3.json()] == full_area_ids
    assert p_end.json() == []
    assert [a["id"] for a in p_off.json()] == full_area_ids[3:]

    # /v1/admin/agents: inclui desempate por id, tokens e last_report_at na página
    agents_a = []
    for i, (slug, name) in enumerate(
        [("ag-z", "Zeta"), ("ag-a2", "Beta"), ("ag-a1", "Beta"), ("ag-c", "Gama"), ("ag-b", "Alfa")]
    ):
        ag = ac_a.post(
            "/v1/admin/agents",
            json={"area_id": areas_a[i]["id"], "slug": slug, "name": name},
        ).json()
        agents_a.append(ag)
    tok = ac_a.post(f"/v1/admin/agents/{agents_a[1]['id']}/tokens").json()
    ac_a.post(f"/v1/admin/agents/{agents_a[1]['id']}/tokens")
    assert (
        TestClient(app)
        .post(
            "/v1/reports",
            json=_package("ag-a2", "v1"),
            headers={"Authorization": f"Bearer {tok['token']}"},
        )
        .status_code
        == 201
    )

    full_agents = ac_a.get("/v1/admin/agents")
    assert full_agents.status_code == 200
    assert full_agents.headers["x-total-count"] == "5"
    full_ag_list = full_agents.json()
    assert [(a["name"], a["id"]) for a in full_ag_list] == sorted(
        [(a["name"], a["id"]) for a in full_ag_list]
    )

    ap1 = ac_a.get("/v1/admin/agents?limit=2&offset=0")
    ap2 = ac_a.get("/v1/admin/agents?limit=2&offset=2")
    ap3 = ac_a.get("/v1/admin/agents?limit=2&offset=4")
    ap_end = ac_a.get("/v1/admin/agents?limit=2&offset=10")
    assert all(r.headers["x-total-count"] == "5" for r in (ap1, ap2, ap3, ap_end))
    assert ap1.json() + ap2.json() + ap3.json() == full_ag_list
    assert ap_end.json() == []

    # /v1/admin/agents/{id}/tokens paginado
    tk_full = ac_a.get(f"/v1/admin/agents/{agents_a[1]['id']}/tokens")
    assert tk_full.headers["x-total-count"] == "2" and len(tk_full.json()) == 2
    tk_p1 = ac_a.get(f"/v1/admin/agents/{agents_a[1]['id']}/tokens?limit=1&offset=0")
    tk_p2 = ac_a.get(f"/v1/admin/agents/{agents_a[1]['id']}/tokens?limit=1&offset=1")
    tk_end = ac_a.get(f"/v1/admin/agents/{agents_a[1]['id']}/tokens?limit=1&offset=2")
    assert all(r.headers["x-total-count"] == "2" for r in (tk_p1, tk_p2, tk_end))
    assert tk_p1.json() + tk_p2.json() == tk_full.json() and tk_end.json() == []

    # /v1/admin/users + /v1/admin/memberships (1 admin criado + 4 novos = 5 usuários em Alfa)
    for email in ("zeta@alfa.test", "carlos@alfa.test", "bruno@alfa.test", "ana@alfa.test"):
        u = ac_a.post(
            "/v1/admin/users", json={"email": email, "password": USER_PWD}
        ).json()
        ac_a.post(
            "/v1/admin/memberships",
            json={"user_id": u["id"], "role": "area_viewer", "area_id": areas_a[0]["id"]},
        )

    full_users = ac_a.get("/v1/admin/users")
    assert full_users.status_code == 200
    assert full_users.headers["x-total-count"] == "5"
    full_u_list = full_users.json()
    assert [u["email"] for u in full_u_list] == sorted(u["email"] for u in full_u_list)

    up1 = ac_a.get("/v1/admin/users?limit=2&offset=0")
    up2 = ac_a.get("/v1/admin/users?limit=2&offset=2")
    up3 = ac_a.get("/v1/admin/users?limit=2&offset=4")
    up_end = ac_a.get("/v1/admin/users?limit=2&offset=5")
    assert all(r.headers["x-total-count"] == "5" for r in (up1, up2, up3, up_end))
    assert up1.json() + up2.json() + up3.json() == full_u_list
    assert up_end.json() == []

    full_mem = ac_a.get("/v1/admin/memberships")
    assert full_mem.headers["x-total-count"] == "5"
    mp1 = ac_a.get("/v1/admin/memberships?limit=2&offset=0")
    mp2 = ac_a.get("/v1/admin/memberships?limit=2&offset=2")
    mp3 = ac_a.get("/v1/admin/memberships?limit=2&offset=4")
    mp_end = ac_a.get("/v1/admin/memberships?limit=2&offset=5")
    assert all(r.headers["x-total-count"] == "5" for r in (mp1, mp2, mp3, mp_end))
    assert mp1.json() + mp2.json() + mp3.json() == full_mem.json()
    assert mp_end.json() == []

    # Confirma isolamento na outra organização (Beta tem 1 usuário admin + 1 criado = 2)
    assert ac_b.get("/v1/admin/areas").headers["x-total-count"] == "1"
    assert ac_b.get("/v1/admin/agents").headers["x-total-count"] == "1"
    assert ac_b.get("/v1/admin/users").headers["x-total-count"] == "2"


def test_ops_organizations_paginacao_e_total(env):
    app, ops_client = env
    # Cria 3 organizações além da "default" (total = 4), fora de ordem alfabética
    _new_org_admin(app, ops_client, "zebra", "Zebra SA")
    _new_org_admin(app, ops_client, "alfa", "Alfa Ltda")
    _new_org_admin(app, ops_client, "meio", "Alfa Ltda")  # mesmo name, desempate por id

    full = ops_client.get("/v1/ops/organizations")
    assert full.status_code == 200
    assert full.headers["x-total-count"] == "4"
    full_list = full.json()
    assert [(o["name"], o["id"]) for o in full_list] == sorted(
        [(o["name"], o["id"]) for o in full_list]
    )

    p1 = ops_client.get("/v1/ops/organizations?limit=2&offset=0")
    p2 = ops_client.get("/v1/ops/organizations?limit=2&offset=2")
    p_end = ops_client.get("/v1/ops/organizations?limit=2&offset=4")
    p_off = ops_client.get("/v1/ops/organizations?offset=2")
    assert all(r.headers["x-total-count"] == "4" for r in (p1, p2, p_end, p_off))
    assert p1.json() + p2.json() == full_list
    assert p_end.json() == []
    assert p_off.json() == full_list[2:]


def test_ops_org_detail_paginacao_versoes_e_org_sem_agentes(env):
    app, ops_client = env
    empty_org_id, _ = _new_org_admin(app, ops_client, "vazia", "Org Vazia")
    empty_resp = ops_client.get(f"/v1/ops/organizations/{empty_org_id}")
    assert empty_resp.status_code == 200
    assert empty_resp.headers["x-total-count"] == "0"
    assert empty_resp.json()["agents"] == []
    assert empty_resp.json()["reports"] == []

    org_id, ac = _new_org_admin(app, ops_client, "alfa", "Alfa")
    area = ac.post("/v1/admin/areas", json={"name": "Ops"}).json()
    ag1 = ac.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": "ag-1", "name": "Ag 1"}
    ).json()
    ag2 = ac.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": "ag-2", "name": "Ag 2"}
    ).json()
    t1 = ac.post(f"/v1/admin/agents/{ag1['id']}/tokens").json()["token"]
    t2 = ac.post(f"/v1/admin/agents/{ag2['id']}/tokens").json()["token"]

    pub = TestClient(app)
    for idx, (slug, tok) in enumerate(
        [("ag-1", t1), ("ag-2", t2), ("ag-1", t1), ("ag-2", t2), ("ag-1", t1)]
    ):
        r = pub.post(
            "/v1/reports",
            json=_package(slug, f"rel-{idx}"),
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 201

    full = ops_client.get(f"/v1/ops/organizations/{org_id}")
    assert full.status_code == 200
    assert full.headers["x-total-count"] == "5"
    full_data = full.json()
    full_reports = full_data["reports"]
    assert len(full_reports) == 5

    p1 = ops_client.get(f"/v1/ops/organizations/{org_id}?limit=2&offset=0")
    p2 = ops_client.get(f"/v1/ops/organizations/{org_id}?limit=2&offset=2")
    p3 = ops_client.get(f"/v1/ops/organizations/{org_id}?limit=2&offset=4")
    p_end = ops_client.get(f"/v1/ops/organizations/{org_id}?limit=2&offset=5")
    assert all(r.headers["x-total-count"] == "5" for r in (p1, p2, p3, p_end))
    combined = p1.json()["reports"] + p2.json()["reports"] + p3.json()["reports"]
    assert combined == full_reports
    assert len({r["id"] for r in combined}) == 5
    assert p_end.json()["reports"] == []
    assert p1.json()["areas"] == full_data["areas"]
    assert p1.json()["agents"] == full_data["agents"]
    assert p1.json()["users"] == full_data["users"]


@pytest.mark.parametrize("query", ["limit=0", "limit=501", "offset=-1"])
def test_paginacao_parametros_invalidos_422(env, query):
    app, ops_client = env
    org_id, ac = _new_org_admin(app, ops_client, "alfa", "Alfa")
    area = ac.post("/v1/admin/areas", json={"name": "Ops"}).json()
    ag = ac.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": "ag-1", "name": "Ag 1"}
    ).json()

    for path in (
        "/v1/admin/areas",
        "/v1/admin/agents",
        f"/v1/admin/agents/{ag['id']}/tokens",
        "/v1/admin/users",
        "/v1/admin/memberships",
    ):
        assert ac.get(f"{path}?{query}").status_code == 422

    for path in ("/v1/ops/organizations", f"/v1/ops/organizations/{org_id}"):
        assert ops_client.get(f"{path}?{query}").status_code == 422
