"""Operador da plataforma (/v1/ops): desligado por padrão, login próprio, CRUD de org, privacidade."""

import hashlib
import json
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform import create_operator
from aok_platform.app import create_app
from aok_platform.auth import hash_password
from aok_platform.models import (
    AgentCredential,
    OperatorEvent,
    OperatorSession,
    PlatformOperator,
    ReportVersion,
    User,
    utcnow,
)
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

KEY = "chave-de-teste-nao-secreta"
OP_EMAIL, OP_PWD = "ops@plataforma.test", "senha-do-operador-123"
BOOT = {"Authorization": f"Bearer {KEY}"}
FORBIDDEN_KEYS = {
    "summary", "summary_json", "limitations", "file_md", "file_html", "file_json",
    "token", "token_hash", "password_hash", "password", "sha256", "files",
}  # fmt: skip


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch):
    monkeypatch.setattr("aok_platform.auth._SCRYPT", {"n": 2**4, "r": 8, "p": 1})  # só acelera o teste


def _make_app(monkeypatch, tmp_path, enabled=True, url="sqlite:///:memory:"):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    if enabled:
        monkeypatch.setenv("AOK_OPS_ENABLED", "true")
    else:
        monkeypatch.delenv("AOK_OPS_ENABLED", raising=False)
    return create_app(url, data_dir=tmp_path / "data")


def _add_operator(app, email=OP_EMAIL, password=OP_PWD, active=True):
    with Session(app.state.engine) as s:
        s.add(PlatformOperator(email=email, password_hash=hash_password(password), active=active))
        s.commit()


def _ops_login(app, email=OP_EMAIL, password=OP_PWD):
    c = TestClient(app)
    r = c.post("/v1/ops/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def ops(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    _add_operator(app)
    return app, _ops_login(app)


def _keys(obj):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _keys(v)
    return out


def _sha(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def _package(slug, tag="x", color="green"):
    js = {
        "generated_at": "2026-01-02T03:04:05-03:00",
        "agent": {"name": slug, "model": "m"},
        "semaphore": {"color": color, "triggered": []},
        "eval": {"baseline": "v1", "candidate": "v2", "n_cases": 5, "tag": tag},
        "limitations": ["texto de ressalva secreto"],
    }
    files = {"relatorio.json": json.dumps(js), "relatorio.md": f"# {tag} conteudo\n", "relatorio.html": f"<p>{tag}</p>"}
    return {
        "agent_id": slug,
        "timestamp": "20260102T030405Z",
        "semaphore": color,
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
    }


# ---- desligado por padrão ---------------------------------------------------------------------

OPS_PATHS = [
    ("POST", "/v1/ops/auth/login"),
    ("POST", "/v1/ops/auth/logout"),
    ("GET", "/v1/ops/auth/me"),
    ("GET", "/v1/ops/organizations"),
    ("POST", "/v1/ops/organizations"),
    ("GET", "/v1/ops/organizations/1"),
    ("PATCH", "/v1/ops/organizations/1"),
    ("POST", "/v1/ops/organizations/1/admins"),
    ("POST", "/v1/ops/organizations/1/admins/1/reset-password"),
    ("GET", "/v1/ops/organizations/1/events"),
    ("GET", "/v1/ops/events"),
]


@pytest.mark.parametrize("flag", [None, "false", "0", ""])
@pytest.mark.parametrize("method,path", OPS_PATHS)
def test_ops_desligado_responde_404_em_tudo(monkeypatch, tmp_path, flag, method, path):
    app = _make_app(monkeypatch, tmp_path, enabled=False)
    if flag is not None:
        monkeypatch.setenv("AOK_OPS_ENABLED", flag)
        app = create_app("sqlite:///:memory:", data_dir=tmp_path / "d2")
    c = TestClient(app)
    r = c.request(method, path, json={"email": "a@b.co", "password": "x"} if method == "POST" else None)
    assert r.status_code == 404


# ---- login, sessão, throttle -------------------------------------------------------------------


def test_login_cookie_me_e_logout(ops):
    app, _ = ops
    c = TestClient(app)
    r = c.post("/v1/ops/auth/login", json={"email": " OPS@plataforma.test ", "password": OP_PWD})
    assert r.status_code == 200 and r.json()["email"] == OP_EMAIL
    cookie = r.headers["set-cookie"].lower()
    assert "aok_ops_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/v1/ops" in cookie and "aok_session" not in cookie.replace("aok_ops_session", "")
    assert c.get("/v1/ops/auth/me").json()["email"] == OP_EMAIL
    assert c.post("/v1/ops/auth/logout").status_code == 204
    assert c.get("/v1/ops/auth/me").status_code == 401


def test_cookie_secure_por_padrao(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    monkeypatch.delenv("AOK_COOKIE_SECURE")
    _add_operator(app)
    r = TestClient(app).post("/v1/ops/auth/login", json={"email": OP_EMAIL, "password": OP_PWD})
    assert "secure" in r.headers["set-cookie"].lower()


def test_erro_de_login_e_generico_e_igual_nos_tres_casos(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    _add_operator(app)
    _add_operator(app, "inativo@plataforma.test", OP_PWD, active=False)
    c = TestClient(app)
    bodies = []
    for email, pwd in ((OP_EMAIL, "errada-errada-1"), ("ninguem@x.test", OP_PWD), ("inativo@plataforma.test", OP_PWD)):
        r = c.post("/v1/ops/auth/login", json={"email": email, "password": pwd})
        assert r.status_code == 401
        bodies.append(r.json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_throttle_trava_apos_5_falhas(ops):
    app, _ = ops
    c = TestClient(app)
    for _ in range(5):
        assert c.post("/v1/ops/auth/login", json={"email": OP_EMAIL, "password": "errada-errada-1"}).status_code == 401
    r = c.post("/v1/ops/auth/login", json={"email": OP_EMAIL, "password": OP_PWD})  # até a senha certa
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_sessao_expirada_revogada_ou_operador_inativo_da_401(ops):
    app, c = ops
    assert c.get("/v1/ops/auth/me").status_code == 200
    with Session(app.state.engine) as s:
        s.execute(update(PlatformOperator).values(active=False))
        s.commit()
    assert c.get("/v1/ops/auth/me").status_code == 401
    with Session(app.state.engine) as s:
        s.execute(update(PlatformOperator).values(active=True))
        s.execute(update(OperatorSession).values(expires_at=utcnow().replace(year=2000)))
        s.commit()
    assert c.get("/v1/ops/auth/me").status_code == 401


def test_operador_e_usuario_sao_mundos_separados(ops):
    app, _ = ops
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": OP_EMAIL, "password": OP_PWD}).status_code == 401
    # e-mail/senha de um admin de org não abre /v1/ops
    admin = _new_org_admin(ops, "acme")
    assert TestClient(app).post("/v1/ops/auth/login", json={"email": admin["email"], "password": admin["password"]}).status_code == 401


# ---- sessões cruzadas ----------------------------------------------------------------------------


def _new_org_admin(ops, slug, email=None):
    _app, c = ops
    org = c.post("/v1/ops/organizations", json={"slug": slug, "name": slug.title()})
    assert org.status_code == 201, org.text
    adm = c.post(f"/v1/ops/organizations/{org.json()['id']}/admins", json={"email": email or f"admin@{slug}.test"})
    assert adm.status_code == 201, adm.text
    return {"org_id": org.json()["id"], **adm.json()}


def test_sessoes_cruzadas_sao_recusadas_nos_dois_sentidos(ops):
    app, c = ops
    adm = _new_org_admin(ops, "acme")
    org_c = TestClient(app)
    assert org_c.post("/v1/auth/login", json={"email": adm["email"], "password": adm["password"]}).status_code == 200
    org_cookie = org_c.cookies.get("aok_session")
    ops_cookie = c.cookies.get("aok_ops_session")
    assert org_c.get("/v1/admin/areas").status_code == 200  # a sessão de org funciona na org
    # org_admin (cookie enviado de propósito) e bootstrap não servem em /v1/ops
    raw = TestClient(app)
    for path in ("/v1/ops/auth/me", "/v1/ops/organizations", "/v1/ops/events"):
        assert raw.get(path, headers={"Cookie": f"aok_session={org_cookie}"}).status_code == 401
        assert raw.get(path, headers=BOOT).status_code == 401
        assert org_c.get(path).status_code == 401
    assert raw.post("/v1/ops/organizations", json={"slug": "x", "name": "x"}, headers=BOOT).status_code == 401
    # a sessão do operador, mesmo enviada, não serve nas rotas de organização
    for path in ("/v1/auth/me", "/v1/areas", "/v1/admin/areas", "/v1/admin/events", "/v1/me/downloads"):
        r = raw.get(path, headers={"Cookie": f"aok_ops_session={ops_cookie}"})
        assert r.status_code in (401, 503), (path, r.status_code)
    assert raw.get("/v1/admin/areas", headers={"Cookie": f"aok_ops_session={ops_cookie}", **BOOT, "X-Org-Slug": "acme"}).status_code == 200  # só a chave de bootstrap abre


# ---- CRUD de organização, admins e isolamento ------------------------------------------------------


def test_crud_de_organizacao(ops):
    _app, c = ops
    assert c.post("/v1/ops/organizations", json={"slug": "Slug Ruim", "name": "x"}).status_code == 422
    assert c.post("/v1/ops/organizations", json={"slug": "ok", "name": ""}).status_code == 422
    assert c.post("/v1/ops/organizations", json={"slug": "ok", "name": "Ok", "extra": 1}).status_code == 422
    created = c.post("/v1/ops/organizations", json={"slug": "acme", "name": "Acme"})
    assert created.status_code == 201 and created.json()["active"] is True
    assert c.post("/v1/ops/organizations", json={"slug": "acme", "name": "Outra"}).status_code == 409
    oid = created.json()["id"]
    r = c.patch(f"/v1/ops/organizations/{oid}", json={"name": "Acme SA", "active": False})
    assert r.status_code == 200 and (r.json()["name"], r.json()["active"]) == ("Acme SA", False)
    assert c.patch(f"/v1/ops/organizations/{oid}", json={"active": True}).json()["active"] is True
    assert c.patch("/v1/ops/organizations/999", json={"name": "x"}).status_code == 404
    assert c.delete(f"/v1/ops/organizations/{oid}").status_code in (404, 405)  # sem DELETE
    slugs = {o["slug"] for o in c.get("/v1/ops/organizations").json()}
    assert slugs == {"default", "acme"}


def test_admin_criado_loga_e_so_ve_a_propria_org(ops):
    app, c = ops
    a = _new_org_admin(ops, "alfa")
    b = _new_org_admin(ops, "beta")
    assert len(a["password"]) >= 16 and a["password"] != b["password"]
    ca, cb = TestClient(app), TestClient(app)
    assert ca.post("/v1/auth/login", json={"email": a["email"], "password": a["password"]}).status_code == 200
    assert cb.post("/v1/auth/login", json={"email": b["email"], "password": b["password"]}).status_code == 200
    me = ca.get("/v1/auth/me").json()
    assert me["is_org_admin"] is True
    area = ca.post("/v1/admin/areas", json={"name": "Area da Alfa"})
    assert area.status_code == 201
    assert [x["name"] for x in ca.get("/v1/areas").json()] == ["Area da Alfa"]
    assert cb.get("/v1/areas").json() == [] and "Alfa" not in cb.get("/v1/admin/areas").text
    assert cb.patch(f"/v1/admin/areas/{area.json()['id']}", json={"name": "x"}).status_code == 404
    # e-mail repetido (global) e inválido
    assert c.post(f"/v1/ops/organizations/{b['org_id']}/admins", json={"email": a["email"]}).status_code == 409
    assert c.post(f"/v1/ops/organizations/{b['org_id']}/admins", json={"email": "sem-arroba"}).status_code == 422
    assert c.post("/v1/ops/organizations/999/admins", json={"email": "x@y.co"}).status_code == 404


def test_reset_de_senha_revoga_sessoes_e_devolve_a_senha_uma_vez(ops):
    app, c = ops
    a, b = _new_org_admin(ops, "alfa"), _new_org_admin(ops, "beta")
    admin_c = TestClient(app)
    assert admin_c.post("/v1/auth/login", json={"email": a["email"], "password": a["password"]}).status_code == 200
    r = c.post(f"/v1/ops/organizations/{a['org_id']}/admins/{a['user_id']}/reset-password")
    assert r.status_code == 200 and len(r.json()["password"]) >= 16 and r.json()["password"] != a["password"]
    assert admin_c.get("/v1/auth/me").status_code == 401  # sessão antiga revogada
    assert TestClient(app).post("/v1/auth/login", json={"email": a["email"], "password": a["password"]}).status_code == 401
    assert TestClient(app).post("/v1/auth/login", json={"email": a["email"], "password": r.json()["password"]}).status_code == 200
    # admin de outra org, usuário que não é admin e id inexistente: 404
    assert c.post(f"/v1/ops/organizations/{a['org_id']}/admins/{b['user_id']}/reset-password").status_code == 404
    assert c.post(f"/v1/ops/organizations/{a['org_id']}/admins/9999/reset-password").status_code == 404
    with Session(app.state.engine) as s:
        viewer = User(org_id=a["org_id"], email="v@alfa.test", password_hash="x", active=True)
        s.add(viewer)
        s.commit()
        vid = viewer.id
    assert c.post(f"/v1/ops/organizations/{a['org_id']}/admins/{vid}/reset-password").status_code == 404


def test_desativar_org_corta_usuarios_e_reativar_devolve(ops):
    app, c = ops
    a = _new_org_admin(ops, "alfa")
    admin_c = TestClient(app)
    admin_c.post("/v1/auth/login", json={"email": a["email"], "password": a["password"]})
    assert admin_c.get("/v1/areas").status_code == 200
    assert c.patch(f"/v1/ops/organizations/{a['org_id']}", json={"active": False}).status_code == 200
    assert admin_c.get("/v1/auth/me").status_code == 401
    fresh = TestClient(app).post("/v1/auth/login", json={"email": a["email"], "password": a["password"]})
    assert fresh.status_code == 401 and fresh.json()["detail"] == "e-mail ou senha inválidos"
    assert c.patch(f"/v1/ops/organizations/{a['org_id']}", json={"active": True}).status_code == 200
    assert admin_c.get("/v1/auth/me").status_code == 200  # nada foi apagado


# ---- privacidade: só metadados -----------------------------------------------------------------------


def _populated_org(ops, tmp_path):
    """Org com área, agente, token, relatório publicado, um download e um usuário viewer."""
    app, _c = ops
    adm = _new_org_admin(ops, "alfa")
    ac = TestClient(app)
    ac.post("/v1/auth/login", json={"email": adm["email"], "password": adm["password"]})
    area = ac.post("/v1/admin/areas", json={"name": "Financeiro"}).json()
    sub = ac.post("/v1/admin/areas", json={"name": "Contas", "parent_id": area["id"]}).json()
    ag = ac.post("/v1/admin/agents", json={"area_id": sub["id"], "slug": "rag-fin", "name": "RAG Fin"}).json()
    tok = ac.post(f"/v1/admin/agents/{ag['id']}/tokens").json()
    pub = TestClient(app).post("/v1/reports", json=_package("rag-fin", "conteudo-secreto"),
                               headers={"Authorization": f"Bearer {tok['token']}"})
    assert pub.status_code == 201
    rid = pub.json()["seq"]
    assert ac.get("/v1/reports/1/download?format=md").status_code == 200
    viewer = ac.post("/v1/admin/users", json={"email": "viewer@alfa.test", "password": "senha-do-viewer-123"}).json()
    ac.post("/v1/admin/memberships", json={"user_id": viewer["id"], "role": "area_viewer", "area_id": area["id"]})
    return {"adm": adm, "token": tok["token"], "viewer_pwd": "senha-do-viewer-123", "area": area, "agent": ag, "seq": rid, "ac": ac}


def test_visao_geral_so_metadados_e_nenhum_vazamento(ops, tmp_path):
    app, c = ops
    w = _populated_org(ops, tmp_path)
    oid = w["adm"]["org_id"]
    lst = c.get("/v1/ops/organizations").json()
    alfa = next(o for o in lst if o["slug"] == "alfa")
    assert (alfa["areas_count"], alfa["agents_count"], alfa["users_count"]) == (2, 1, 2)
    assert (alfa["tokens_active_count"], alfa["reports_count"]) == (1, 1) and alfa["last_report_at"]
    detail = c.get(f"/v1/ops/organizations/{oid}").json()
    assert [a["name"] for a in detail["areas"]] == ["Financeiro"] and detail["areas"][0]["children"][0]["name"] == "Contas"
    ag = detail["agents"][0]
    assert (ag["slug"], ag["area_name"], ag["tokens_active_count"], ag["latest_semaforo"]) == ("rag-fin", "Contas", 1, "green")
    assert {u["email"] for u in detail["users"]} == {w["adm"]["email"], "viewer@alfa.test"}
    viewer = next(u for u in detail["users"] if u["email"] == "viewer@alfa.test")
    assert viewer["access"] == [{"role": "area_viewer", "area_name": "Financeiro"}]
    rep = detail["reports"][0]
    assert (rep["agent_slug"], rep["seq"], rep["status_semaforo"], rep["n_cases"], rep["model"]) == ("rag-fin", 1, "green", 5, "m")
    assert rep["generated_at"] and rep["published_at"]

    # varredura: nenhuma rota /v1/ops devolve conteúdo de relatório, token, hash ou senha
    paths = ["/v1/ops/auth/me", "/v1/ops/organizations", f"/v1/ops/organizations/{oid}",
             f"/v1/ops/organizations/{oid}/events", "/v1/ops/events"]
    with Session(app.state.engine) as s:
        secrets = [w["token"], w["viewer_pwd"], w["adm"]["password"], *s.scalars(select(AgentCredential.token_hash)),
                   *s.scalars(select(User.password_hash)), *s.scalars(select(ReportVersion.sha256))]
    for p in paths:
        r = c.get(p)
        assert r.status_code == 200, p
        assert not (_keys(r.json()) & FORBIDDEN_KEYS), (p, _keys(r.json()) & FORBIDDEN_KEYS)
        blob = r.text
        for sec in secrets:
            assert sec not in blob, p
        for word in ("conteudo-secreto", "ressalva secreto", "relatorio.", "scrypt$"):
            assert word not in blob, (p, word)
    # não existe rota de conteúdo nem download no /v1/ops
    for p in ("/v1/ops/reports/1", "/v1/ops/reports/1/download?format=md", f"/v1/ops/organizations/{oid}/reports/1"):
        assert c.get(p).status_code == 404


def test_operador_nao_usa_rotas_de_portal_nem_baixa_relatorio(ops, tmp_path):
    _app, c = ops
    _populated_org(ops, tmp_path)
    assert c.get("/v1/reports/1").status_code == 401
    assert c.get("/v1/reports/1/download?format=md").status_code == 401
    assert c.get("/v1/areas").status_code == 401


# ---- operator_event ----------------------------------------------------------------------------------


def test_operator_event_grava_acoes_sem_segredo_e_e_imutavel(ops):
    app, c = ops
    a = _new_org_admin(ops, "alfa")
    c.patch(f"/v1/ops/organizations/{a['org_id']}", json={"name": "Alfa 2"})
    c.patch(f"/v1/ops/organizations/{a['org_id']}", json={"active": False})
    c.patch(f"/v1/ops/organizations/{a['org_id']}", json={"active": True})
    reset = c.post(f"/v1/ops/organizations/{a['org_id']}/admins/{a['user_id']}/reset-password").json()
    events = c.get("/v1/ops/events?limit=500").json()
    actions = [e["action"] for e in events]
    assert actions == [
        "org.admin_password_reset", "org.activate", "org.deactivate", "org.update",
        "org.admin_create", "org.create", "auth.login",
    ]  # fmt: skip
    assert {e["operator_email"] for e in events} == {OP_EMAIL}
    created = next(e for e in events if e["action"] == "org.create")
    assert (created["target_org_slug"], created["target_type"], created["target_id"]) == ("alfa", "organization", a["org_id"])
    blob = json.dumps(events)
    for sec in (a["password"], reset["password"], OP_PWD):
        assert sec not in blob
    assert set(events[0]) == {"id", "at", "operator_id", "operator_email", "action", "target_org_id",
                              "target_org_slug", "target_type", "target_id"}  # fmt: skip
    # paginação e ordem
    p1 = c.get("/v1/ops/events?limit=3").json()
    p2 = c.get("/v1/ops/events?limit=3&offset=3").json()
    assert [e["id"] for e in p1 + p2] == [e["id"] for e in events[:6]]
    assert c.get("/v1/ops/events?limit=0").status_code == 422
    with Session(app.state.engine) as s:
        ev = s.scalars(select(OperatorEvent)).first()
        ev.action = "adulterado"
        with pytest.raises(RuntimeError):
            s.commit()


def test_eventos_admin_da_org_visiveis_ao_operador_somente_leitura(ops):
    app, c = ops
    a = _new_org_admin(ops, "alfa")
    ac = TestClient(app)
    ac.post("/v1/auth/login", json={"email": a["email"], "password": a["password"]})
    ac.post("/v1/admin/areas", json={"name": "Nova"})
    ev = c.get(f"/v1/ops/organizations/{a['org_id']}/events").json()
    assert [e["action"] for e in ev] == ["area.create"] and ev[0]["actor_email"] == a["email"]
    other = _new_org_admin(ops, "beta")
    assert c.get(f"/v1/ops/organizations/{other['org_id']}/events").json() == []  # cada org só vê os seus
    assert c.post(f"/v1/ops/organizations/{a['org_id']}/events").status_code == 405
    assert c.get("/v1/ops/organizations/999/events").status_code == 404


# ---- CLI ---------------------------------------------------------------------------------------------


def test_cli_cria_operador_imprime_senha_uma_vez_e_recusa_duplicado(monkeypatch, tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'ops.db'}"
    monkeypatch.setenv("AOK_DATABASE_URL", url)
    assert create_operator.main(["--email", "Novo@Ops.Test"]) == 0
    out = capsys.readouterr().out
    pwd = next(ln.strip() for ln in out.splitlines() if ln.startswith("  "))
    assert len(pwd) >= 16 and out.count(pwd) == 1 and "novo@ops.test" in out
    with Session(create_app(url, data_dir=tmp_path / "d").state.engine) as s:
        op = s.scalar(select(PlatformOperator))
        assert op.email == "novo@ops.test" and pwd not in op.password_hash and op.password_hash.startswith("scrypt$")
    with pytest.raises(SystemExit):  # e-mail duplicado
        create_operator.main(["--email", "novo@ops.test"])
    with pytest.raises(SystemExit):  # reset de quem não existe
        create_operator.main(["--email", "ninguem@ops.test", "--reset-password"])
    with pytest.raises(SystemExit):
        create_operator.main(["--email", "invalido"])
    # a senha impressa abre o login; o reset gera outra e a antiga para de valer
    monkeypatch.setenv("AOK_OPS_ENABLED", "true")
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    app = create_app(url, data_dir=tmp_path / "d")
    old = _ops_login(app, "novo@ops.test", pwd)
    assert create_operator.main(["--email", "novo@ops.test", "--reset-password"]) == 0
    new_pwd = next(ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.startswith("  "))
    assert new_pwd != pwd
    assert old.get("/v1/ops/auth/me").status_code == 401  # sessão antiga encerrada
    assert TestClient(app).post("/v1/ops/auth/login", json={"email": "novo@ops.test", "password": pwd}).status_code == 401
    _ops_login(app, "novo@ops.test", new_pwd)


# ---- ajustes do crivo: no-store, LIMIT em SQL, reativação explícita ----------------------------------


def test_respostas_com_senha_nao_podem_ser_cacheadas(ops):
    _app, c = ops
    org = c.post("/v1/ops/organizations", json={"slug": "alfa", "name": "Alfa"}).json()
    r = c.post(f"/v1/ops/organizations/{org['id']}/admins", json={"email": "a@alfa.test"})
    assert r.status_code == 201 and r.headers["cache-control"] == "no-store" and r.headers["pragma"] == "no-cache"
    uid = r.json()["user_id"]
    r = c.post(f"/v1/ops/organizations/{org['id']}/admins/{uid}/reset-password")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store" and r.headers["pragma"] == "no-cache"


def test_detalhe_aplica_limit_em_sql_e_busca_o_ultimo_relatorio_a_parte(ops, tmp_path):
    from sqlalchemy import event

    app, c = ops
    w = _populated_org(ops, tmp_path)
    auth = {"Authorization": f"Bearer {w['token']}"}
    assert TestClient(app).post("/v1/reports", json=_package("rag-fin", "dois", "yellow"), headers=auth).status_code == 201
    assert TestClient(app).post("/v1/reports", json=_package("rag-fin", "tres", "red"), headers=auth).status_code == 201
    oid = w["adm"]["org_id"]
    statements = []

    def spy(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", spy)
    try:
        d = c.get(f"/v1/ops/organizations/{oid}?limit=1").json()
    finally:
        event.remove(app.state.engine, "before_cursor_execute", spy)
    assert [r["seq"] for r in d["reports"]] == [3]  # só 1 versão, a mais recente
    assert d["agents"][0]["latest_semaforo"] == "red" and d["agents"][0]["last_report_at"]  # não depende do limit
    assert d["reports"][0]["generated_at"] == "2026-01-02T03:04:05-03:00"
    report_sql = [q for q in statements if "FROM report_version" in q]
    assert any("LIMIT" in q for q in report_sql)  # o corte é feito no banco
    # o resumo inteiro não é carregado: toda menção a summary_json em consultas de report_version fica
    # dentro de JSON_EXTRACT( (SQLite) ou de ->> (Postgres); a coluna crua nunca vai no SELECT
    for q in report_sql:
        rest = re.sub(r"JSON_EXTRACT\(report_version\.summary_json,", "", q)
        rest = re.sub(r"report_version\.summary_json\s*->>", "", rest)
        rest = re.sub(r"%\(summary_json_\d+\)s", "", rest)  # nome do parâmetro de bind do ->> (Postgres)
        assert "summary_json" not in rest, q
    d3 = c.get(f"/v1/ops/organizations/{oid}?limit=3").json()
    assert [r["seq"] for r in d3["reports"]] == [3, 2, 1]
    assert c.get(f"/v1/ops/organizations/{oid}?limit=501").status_code == 422


def test_cli_reset_nao_reativa_operador_inativo_sem_activate(monkeypatch, tmp_path, capsys):
    url = f"sqlite:///{tmp_path / 'ops2.db'}"
    monkeypatch.setenv("AOK_DATABASE_URL", url)
    assert create_operator.main(["--email", "ops@x.test"]) == 0
    app = _make_app(monkeypatch, tmp_path, url=url)
    with Session(app.state.engine) as s:
        s.execute(update(PlatformOperator).values(active=False))
        s.commit()
    capsys.readouterr()
    assert create_operator.main(["--email", "ops@x.test", "--reset-password"]) == 0
    out = capsys.readouterr().out
    pwd = next(ln.strip() for ln in out.splitlines() if ln.startswith("  "))
    assert "continua inativo" in out
    assert TestClient(app).post("/v1/ops/auth/login", json={"email": "ops@x.test", "password": pwd}).status_code == 401
    assert create_operator.main(["--email", "ops@x.test", "--reset-password", "--activate"]) == 0
    pwd2 = next(ln.strip() for ln in capsys.readouterr().out.splitlines() if ln.startswith("  "))
    assert TestClient(app).post("/v1/ops/auth/login", json={"email": "ops@x.test", "password": pwd2}).status_code == 200
    with pytest.raises(SystemExit):  # --activate sozinho não faz sentido
        create_operator.main(["--email", "ops@x.test", "--activate"])
