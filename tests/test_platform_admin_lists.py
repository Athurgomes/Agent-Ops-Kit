"""Listagens admin, registro de eventos e escopo por organização. Sem rede."""

import hashlib
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.models import (
    AdminEvent,
    Agent,
    AgentCredential,
    Area,
    Membership,
    Organization,
    User,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

KEY = "chave-de-teste-nao-secreta"
H = {"Authorization": f"Bearer {KEY}", "X-Org-Slug": "default"}  # a fixture cria uma 2ª org
PWD = "senha-de-teste-123"
GET_PATHS = [
    "/v1/admin/areas",
    "/v1/admin/agents",
    "/v1/admin/agents/1/tokens",
    "/v1/admin/users",
    "/v1/admin/memberships",
]


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package(slug):
    js = {
        "generated_at": "2026-01-02T03:04:05-03:00",
        "agent": {"name": slug, "model": "m"},
        "semaphore": {"color": "green", "triggered": []},
        "eval": {"baseline": "v1", "candidate": "v2", "n_cases": 5},
    }
    files = {"relatorio.json": json.dumps(js), "relatorio.md": "# r\n", "relatorio.html": "<p>r</p>"}
    return {
        "agent_id": slug,
        "timestamp": "20260102T030405Z",
        "semaphore": "green",
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
    }


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Org 1: áreas A > A1, B; agentes ag-a (A) e ag-b (B); usuários admin e viewer(A).
    Org 2: uma área, um agente, um usuário e um token (nunca devem aparecer para a org 1)."""
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    c = TestClient(app)
    ids = {}
    for name, parent in (("A", None), ("A1", "A"), ("B", None)):
        body = {"name": name, "parent_id": ids.get(parent)}
        ids[name] = c.post("/v1/admin/areas", json=body, headers=H).json()["id"]
    secrets = {}
    for slug, area in (("ag-a", "A"), ("ag-b", "B")):
        ag = c.post(
            "/v1/admin/agents", json={"area_id": ids[area], "slug": slug, "name": slug}, headers=H
        ).json()
        ids[slug] = ag["id"]
    for _ in range(2):  # dois tokens no ag-a; o segundo é revogado
        tok = c.post(f"/v1/admin/agents/{ids['ag-a']}/tokens", headers=H).json()
        secrets.setdefault("tokens", []).append(tok["token"])
        last_token_id = tok["token_id"]
    c.delete(f"/v1/admin/agents/{ids['ag-a']}/tokens/{last_token_id}", headers=H)
    pub = c.post(
        "/v1/reports",
        json=_package("ag-a"),
        headers={"Authorization": f"Bearer {secrets['tokens'][0]}"},
    )
    assert pub.status_code == 201
    for email, role, area in (("admin@x.com", "org_admin", None), ("viewer@x.com", "area_viewer", "A")):
        u = c.post("/v1/admin/users", json={"email": email, "password": PWD}, headers=H).json()
        ids[email] = u["id"]
        body = {"user_id": u["id"], "role": role}
        if area:
            body["area_id"] = ids[area]
        assert c.post("/v1/admin/memberships", json=body, headers=H).status_code == 201
    with Session(app.state.engine) as s:  # organização 2, criada direto no banco
        org2 = Organization(name="outra", slug="outra", active=True)
        s.add(org2)
        s.flush()
        a2 = Area(org_id=org2.id, name="Area Alheia")
        s.add(a2)
        s.flush()
        g2 = Agent(org_id=org2.id, area_id=a2.id, slug="ag-alheio", name="Agente Alheio", active=True)
        u2 = User(org_id=org2.id, email="alheio@y.com", password_hash="scrypt$x", active=True)
        s.add_all([g2, u2])
        s.flush()
        s.add(Membership(user_id=u2.id, area_id=a2.id, role="area_viewer"))
        s.add(AgentCredential(agent_id=g2.id, token_hash="f" * 64))
        s.commit()
        ids["foreign"] = {"area": a2.id, "agent": g2.id, "user": u2.id}
    return app, c, ids, secrets


def _session(app, email, password=PWD):
    client = TestClient(app)
    assert client.post("/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    return client


# ---- acesso --------------------------------------------------------------------------------


@pytest.mark.parametrize("path", GET_PATHS)
def test_listagens_exigem_admin(env, path):
    app, c, _, _ = env
    assert TestClient(app).get(path).status_code == 401  # sem credencial
    assert TestClient(app).get(path, headers={"Authorization": "Bearer errada"}).status_code == 401
    assert _session(app, "viewer@x.com").get(path).status_code == 403  # viewer
    assert c.get(path, headers=H).status_code == 200  # bootstrap
    assert _session(app, "admin@x.com").get(path).status_code == 200  # org_admin por sessão


def test_events_so_org_admin_por_sessao(env):
    app, c, _, _ = env
    assert TestClient(app).get("/v1/admin/events").status_code == 401
    assert c.get("/v1/admin/events", headers=H).status_code == 401  # a chave de bootstrap não lê
    assert _session(app, "viewer@x.com").get("/v1/admin/events").status_code == 403
    assert _session(app, "admin@x.com").get("/v1/admin/events").status_code == 200


# ---- conteúdo e contagens --------------------------------------------------------------------


def test_areas_com_contagem_e_pai(env):
    _, c, ids, _ = env
    rows = {r["name"]: r for r in c.get("/v1/admin/areas", headers=H).json()}
    assert set(rows) == {"A", "A1", "B"}  # nada da organização 2
    assert rows["A1"]["parent_id"] == ids["A"] and rows["A"]["parent_id"] is None
    assert (rows["A"]["agent_count"], rows["A1"]["agent_count"], rows["B"]["agent_count"]) == (1, 0, 1)


def test_agentes_inclui_inativos_tokens_e_ultimo_relatorio(env):
    _, c, ids, _ = env
    assert c.patch(f"/v1/admin/agents/{ids['ag-b']}", json={"active": False}, headers=H).status_code == 200
    rows = {r["slug"]: r for r in c.get("/v1/admin/agents", headers=H).json()}
    assert set(rows) == {"ag-a", "ag-b"}
    assert rows["ag-b"]["active"] is False and rows["ag-b"]["area_name"] == "B"
    assert rows["ag-a"]["tokens_active_count"] == 1  # 2 emitidos, 1 revogado
    assert rows["ag-a"]["last_report_at"] is not None and rows["ag-b"]["last_report_at"] is None
    assert rows["ag-b"]["tokens_active_count"] == 0


def test_tokens_so_metadados(env):
    _, c, ids, _ = env
    rows = c.get(f"/v1/admin/agents/{ids['ag-a']}/tokens", headers=H).json()
    assert len(rows) == 2
    for r in rows:
        assert set(r) == {"token_id", "created_at", "revoked_at", "last_used_at"}
    assert sorted(r["revoked_at"] is None for r in rows) == [False, True]
    assert any(r["last_used_at"] for r in rows)  # o token usado na publicação


def test_usuarios_e_vinculos_resumidos(env):
    _, c, ids, _ = env
    users = {u["email"]: u for u in c.get("/v1/admin/users", headers=H).json()}
    assert set(users) == {"admin@x.com", "viewer@x.com"}
    assert users["viewer@x.com"]["memberships"] == [
        {"id": users["viewer@x.com"]["memberships"][0]["id"], "area_id": ids["A"], "area_name": "A", "role": "area_viewer"}
    ]
    assert users["admin@x.com"]["memberships"][0]["role"] == "org_admin"
    assert users["admin@x.com"]["memberships"][0]["area_name"] is None
    ms = c.get("/v1/admin/memberships", headers=H).json()
    assert {m["user_email"] for m in ms} == {"admin@x.com", "viewer@x.com"}
    assert {m["role"] for m in ms} == {"org_admin", "area_viewer"}


def test_nenhum_segredo_em_nenhuma_resposta(env):
    app, c, ids, secrets = env
    admin = _session(app, "admin@x.com")
    texts = [c.get(p, headers=H).text for p in GET_PATHS] + [admin.get("/v1/admin/events").text]
    # também as respostas de escrita (exceto a emissão do token, que o mostra uma vez de propósito)
    texts.append(c.patch(f"/v1/admin/users/{ids['viewer@x.com']}", json={"password": "outra-senha-9876"}, headers=H).text)
    texts.append(c.patch(f"/v1/admin/agents/{ids['ag-a']}", json={"name": "novo"}, headers=H).text)
    blob = "\n".join(texts)
    with Session(app.state.engine) as s:
        hashes = [h for h in s.scalars(select(AgentCredential.token_hash))]
        pw_hashes = [h for h in s.scalars(select(User.password_hash))]
    for secret in [*secrets["tokens"], PWD, "outra-senha-9876", *hashes, *pw_hashes]:
        assert secret not in blob
    for word in ("password", "token_hash", "scrypt$"):
        assert word not in blob


# ---- escopo por organização ------------------------------------------------------------------


def test_escrita_e_leitura_nao_cruzam_organizacao(env):
    app, c, ids, _ = env
    f = ids["foreign"]
    admin = _session(app, "admin@x.com")
    for client, hdr in ((c, H), (admin, {})):
        assert client.patch(f"/v1/admin/areas/{f['area']}", json={"name": "x"}, headers=hdr).status_code == 404
        assert client.patch(f"/v1/admin/agents/{f['agent']}", json={"name": "x"}, headers=hdr).status_code == 404
        assert client.patch(f"/v1/admin/users/{f['user']}", json={"active": False}, headers=hdr).status_code == 404
        assert client.get(f"/v1/admin/agents/{f['agent']}/tokens", headers=hdr).status_code == 404
        assert client.post(f"/v1/admin/agents/{f['agent']}/tokens", headers=hdr).status_code == 404
        r = client.post("/v1/admin/agents", json={"area_id": f["area"], "slug": "z", "name": "z"}, headers=hdr)
        assert r.status_code == 404
        r = client.post("/v1/admin/memberships", json={"user_id": f["user"], "role": "org_admin"}, headers=hdr)
        assert r.status_code == 404
        r = client.post("/v1/admin/areas", json={"name": "x", "parent_id": f["area"]}, headers=hdr)
        assert r.status_code == 404
    with Session(app.state.engine) as s:
        foreign_m = s.scalar(select(Membership.id).where(Membership.user_id == f["user"]))
    assert c.delete(f"/v1/admin/memberships/{foreign_m}", headers=H).status_code == 404
    assert not any("alheio" in c.get(p, headers=H).text.lower() for p in GET_PATHS[:2] + GET_PATHS[3:])


def test_eventos_de_outra_organizacao_nao_aparecem(env):
    app, _, ids, _ = env
    with Session(app.state.engine) as s:
        org2 = s.scalar(select(Organization.id).where(Organization.name == "outra"))
        s.add(AdminEvent(org_id=org2, actor_user_id=ids["foreign"]["user"], action="area.create", target_type="area", target_id=99))
        s.commit()
    events = _session(app, "admin@x.com").get("/v1/admin/events?limit=500").json()
    assert events and all(e["target_id"] != 99 for e in events)


# ---- PATCH de agente e de usuário ------------------------------------------------------------


def test_patch_agente_ativa_renomeia_e_move(env):
    _, c, ids, _ = env
    url = f"/v1/admin/agents/{ids['ag-a']}"
    r = c.patch(url, json={"active": False, "name": "Novo nome", "area_id": ids["B"]}, headers=H)
    assert r.status_code == 200
    assert (r.json()["active"], r.json()["name"], r.json()["area_id"]) == (False, "Novo nome", ids["B"])
    assert c.patch(url, json={"active": True}, headers=H).json()["active"] is True
    assert c.patch(url, json={"area_id": 99999}, headers=H).status_code == 404


def test_patch_usuario_senha_nova_nao_volta_e_revoga_sessoes(env):
    app, c, ids, _ = env
    viewer = _session(app, "viewer@x.com")
    assert viewer.get("/v1/auth/me").status_code == 200
    url = f"/v1/admin/users/{ids['viewer@x.com']}"
    assert c.patch(url, json={"password": "curta"}, headers=H).status_code == 422  # mínimo de 12
    new = "senha-nova-bem-longa-1"
    r = c.patch(url, json={"password": new}, headers=H)
    assert r.status_code == 200 and new not in r.text and set(r.json()) == {"id", "org_id", "email", "active", "created_at"}
    assert viewer.get("/v1/auth/me").status_code == 401  # sessão antiga revogada
    assert TestClient(app).post("/v1/auth/login", json={"email": "viewer@x.com", "password": PWD}).status_code == 401
    assert _session(app, "viewer@x.com", new).get("/v1/auth/me").status_code == 200
    again = _session(app, "viewer@x.com", new)
    assert c.patch(url, json={"active": False}, headers=H).json()["active"] is False
    assert again.get("/v1/auth/me").status_code == 401  # desativar também encerra


# ---- admin_event -----------------------------------------------------------------------------


def test_eventos_gravam_acoes_sem_segredo(env):
    app, _, ids, secrets = env
    admin = _session(app, "admin@x.com")
    area = admin.post("/v1/admin/areas", json={"name": "Nova"}).json()
    admin.patch(f"/v1/admin/areas/{area['id']}", json={"name": "Nova 2"})
    ag = admin.post("/v1/admin/agents", json={"area_id": area["id"], "slug": "novo", "name": "N"}).json()
    admin.patch(f"/v1/admin/agents/{ag['id']}", json={"active": False})
    tok = admin.post(f"/v1/admin/agents/{ag['id']}/tokens").json()
    admin.delete(f"/v1/admin/agents/{ag['id']}/tokens/{tok['token_id']}")
    u = admin.post("/v1/admin/users", json={"email": "n@x.com", "password": "senha-qualquer-123"}).json()
    admin.patch(f"/v1/admin/users/{u['id']}", json={"password": "outra-senha-qualquer-1"})
    m = admin.post("/v1/admin/memberships", json={"user_id": u["id"], "role": "area_viewer", "area_id": area["id"]}).json()
    assert admin.delete(f"/v1/admin/memberships/{m['id']}").status_code == 204

    events = admin.get("/v1/admin/events?limit=500").json()
    mine = [e for e in events if e["actor_user_id"] == ids["admin@x.com"]]
    assert [e["action"] for e in mine] == [  # mais recente primeiro
        "membership.delete",
        "membership.create",
        "user.password_change",
        "user.create",
        "token.revoke",
        "token.issue",
        "agent.deactivate",
        "agent.create",
        "area.update",
        "area.create",
    ]
    assert {e["actor_email"] for e in mine} == {"admin@x.com"}
    assert {(e["action"], e["target_id"]) for e in mine} >= {("area.create", area["id"]), ("token.issue", tok["token_id"])}
    boot = [e for e in events if e["actor_user_id"] is None]  # as ações do fixture, via bootstrap
    assert boot and all(e["actor_email"] is None for e in boot)
    blob = json.dumps(events)
    for secret in [*secrets["tokens"], tok["token"], PWD, "outra-senha-qualquer-1", "senha-qualquer-123"]:
        assert secret not in blob
    assert set(events[0]) == {"id", "at", "actor_user_id", "actor_email", "action", "target_type", "target_id"}


def test_eventos_paginacao_e_ordem(env):
    app, _, _, _ = env
    admin = _session(app, "admin@x.com")
    allv = admin.get("/v1/admin/events?limit=500").json()
    assert len(allv) >= 10
    assert [e["id"] for e in allv] == sorted((e["id"] for e in allv), reverse=True)
    p1 = admin.get("/v1/admin/events?limit=4").json()
    p2 = admin.get("/v1/admin/events?limit=4&offset=4").json()
    assert [e["id"] for e in p1 + p2] == [e["id"] for e in allv[:8]]
    assert admin.get("/v1/admin/events?limit=0").status_code == 422
    assert admin.get("/v1/admin/events?limit=501").status_code == 422


def test_evento_e_imutavel(env):
    app, _, _, _ = env
    with Session(app.state.engine) as s:
        ev = s.scalars(select(AdminEvent)).first()
        ev.action = "adulterado"
        with pytest.raises(RuntimeError):
            s.commit()


# ---- proteção contra auto-bloqueio -----------------------------------------------------------


def _second_admin(c, ids):
    u = c.post("/v1/admin/users", json={"email": "admin2@x.com", "password": PWD}, headers=H).json()
    m = c.post("/v1/admin/memberships", json={"user_id": u["id"], "role": "org_admin"}, headers=H).json()
    ids["admin2"], ids["admin2_m"] = u["id"], m["id"]


def _admin_membership(app, user_id):
    with Session(app.state.engine) as s:
        return s.scalar(select(Membership.id).where(Membership.user_id == user_id, Membership.role == "org_admin"))


def _event_count(app):
    with Session(app.state.engine) as s:
        return len(list(s.scalars(select(AdminEvent.id))))


def test_admin_nao_desativa_a_propria_conta(env):
    app, c, ids, _ = env
    _second_admin(c, ids)  # há outro admin: mesmo assim a própria conta é protegida
    admin = _session(app, "admin@x.com")
    before = _event_count(app)
    r = admin.patch(f"/v1/admin/users/{ids['admin@x.com']}", json={"active": False})
    assert r.status_code == 409 and "própria conta" in r.json()["detail"]
    assert admin.get("/v1/auth/me").status_code == 200  # nada mudou
    assert _event_count(app) == before  # tentativa bloqueada não gera evento
    # o bootstrap não é usuário: pode desativar um admin quando sobra outro
    assert c.patch(f"/v1/admin/users/{ids['admin@x.com']}", json={"active": False}, headers=H).status_code == 200


def test_admin_nao_revoga_o_proprio_org_admin(env):
    app, c, ids, _ = env
    _second_admin(c, ids)
    admin = _session(app, "admin@x.com")
    mid = _admin_membership(app, ids["admin@x.com"])
    before = _event_count(app)
    r = admin.delete(f"/v1/admin/memberships/{mid}")
    assert r.status_code == 409 and "próprio acesso" in r.json()["detail"]
    assert _admin_membership(app, ids["admin@x.com"]) == mid and _event_count(app) == before
    # a chave de bootstrap pode revogar o de outro admin quando sobra um
    assert c.delete(f"/v1/admin/memberships/{ids['admin2_m']}", headers=H).status_code == 204


def test_ultimo_org_admin_ativo_nao_sai_por_nenhum_ator(env):
    app, c, ids, _ = env
    before = _event_count(app)
    url = f"/v1/admin/users/{ids['admin@x.com']}"
    r = c.patch(url, json={"active": False}, headers=H)  # bootstrap também é barrado
    assert r.status_code == 409 and "última" in r.json()["detail"]
    mid = _admin_membership(app, ids["admin@x.com"])
    r = c.delete(f"/v1/admin/memberships/{mid}", headers=H)
    assert r.status_code == 409 and "última" in r.json()["detail"]
    assert _event_count(app) == before
    # com um segundo admin ativo, um deles pode sair; o que sobra passa a ser o último
    _second_admin(c, ids)
    admin2 = _session(app, "admin2@x.com")
    assert admin2.patch(url, json={"active": False}).status_code == 200  # desativa o outro
    r = c.patch(f"/v1/admin/users/{ids['admin2']}", json={"active": False}, headers=H)
    assert r.status_code == 409 and "última" in r.json()["detail"]
    assert c.delete(f"/v1/admin/memberships/{ids['admin2_m']}", headers=H).status_code == 409


def test_admin_inativo_nao_conta_como_ativo_e_viewer_nao_e_afetado(env):
    _, c, ids, _ = env
    _second_admin(c, ids)
    assert c.patch(f"/v1/admin/users/{ids['admin2']}", json={"active": False}, headers=H).status_code == 200
    # admin2 está inativo: revogar o vínculo dele não deixa a org sem admin ativo
    assert c.delete(f"/v1/admin/memberships/{ids['admin2_m']}", headers=H).status_code == 204
    # mas desativar o único admin ativo continua barrado, e o viewer pode ser desativado
    assert c.patch(f"/v1/admin/users/{ids['admin@x.com']}", json={"active": False}, headers=H).status_code == 409
    assert c.patch(f"/v1/admin/users/{ids['viewer@x.com']}", json={"active": False}, headers=H).status_code == 200
