"""Fase 3 da plataforma: login, usuários, acesso por área, download e histórico. Sem rede."""

import hashlib
import json
from datetime import timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.auth import hash_password, verify_password
from aok_platform.models import DownloadLog, UserSession, utcnow
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

KEY = "chave-de-teste-nao-secreta"
ADMIN = {"Authorization": f"Bearer {KEY}"}
PWD = "senha-de-teste-123"
GEN = "2026-01-02T03:04:05-03:00"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package(slug, mean=0.7):
    js = {
        "generated_at": GEN,
        "agent": {"name": slug, "model": "llama3.1:8b"},
        "semaphore": {"color": "green", "triggered": []},
        "eval": {"baseline": "v1", "candidate": "v2", "n_cases": 50, "mean_candidate": mean},
        "audit": {"ok": True, "anchor": "a" * 64},
    }
    files = {
        "relatorio.json": json.dumps(js),
        "relatorio.md": f"# Relatório {slug}\n",
        "relatorio.html": f"<h1>{slug}</h1>",
    }
    return {
        "agent_id": slug,
        "timestamp": "20260102T030405Z",
        "semaphore": "green",
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
    }


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Áreas: Compliance(A) > Caixa(A1); Dados(B). Um agente e um relatório em cada."""
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")  # o TestClient usa http
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    c = TestClient(app)
    ids = {}
    for name, parent in (("A", None), ("A1", "A"), ("B", None)):
        body = {"name": name, "parent_id": ids.get(parent)}
        ids[name] = c.post("/v1/admin/areas", json=body, headers=ADMIN).json()["id"]
    reports = {}
    for name in ("A", "A1", "B"):
        slug = f"ag-{name.lower()}"
        ag = c.post(
            "/v1/admin/agents",
            json={"area_id": ids[name], "slug": slug, "name": f"Agente {name}"},
            headers=ADMIN,
        ).json()
        tok = c.post(f"/v1/admin/agents/{ag['id']}/tokens", headers=ADMIN).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        assert c.post("/v1/reports", json=_package(slug), headers=h).status_code == 201
        ids[f"ag_{name}"] = ag["id"]
        ids[f"tok_{name}"] = tok
        reports[name] = len(reports) + 1  # id da versão
    return app, c, ids, reports


def _user(c, email, area_id=None, role="area_viewer", password=PWD):
    u = c.post("/v1/admin/users", json={"email": email, "password": password}, headers=ADMIN)
    assert u.status_code == 201, u.text
    body = {"user_id": u.json()["id"], "role": role}
    if area_id is not None:
        body["area_id"] = area_id
    assert c.post("/v1/admin/memberships", json=body, headers=ADMIN).status_code == 201
    return u.json()["id"]


def _login(app, email, password=PWD):
    client = TestClient(app)  # cookie jar próprio por usuário
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return client


# ---- senha e login -------------------------------------------------------------------------


def test_hash_de_senha_tem_sal_e_confere():
    a, b = hash_password(PWD), hash_password(PWD)
    assert a != b and a.startswith("scrypt$") and PWD not in a
    assert verify_password(PWD, a) and not verify_password("outra-senha-123", a)
    assert not verify_password(PWD, "lixo")


def test_login_ok_cookie_e_me(env):
    app, c, ids, _ = env
    _user(c, "Ana@Exemplo.com", ids["A"])
    client = TestClient(app)
    r = client.post("/v1/auth/login", json={"email": " ana@exemplo.COM ", "password": PWD})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=28800" in cookie
    assert "secure" not in cookie.replace("samesite", "")  # AOK_COOKIE_SECURE=false neste teste
    me = client.get("/v1/auth/me").json()
    assert me["email"] == "ana@exemplo.com" and me["is_org_admin"] is False
    assert me["memberships"] == [{"area_id": ids["A"], "role": "area_viewer"}]
    assert PWD not in r.text and "password" not in r.text
    with Session(app.state.engine) as s:  # o token não fica em claro no banco
        assert client.cookies.get("aok_session") != s.scalar(select(UserSession.token_hash))


def test_cookie_secure_por_padrao(env, monkeypatch):
    app, c, ids, _ = env
    monkeypatch.delenv("AOK_COOKIE_SECURE")
    _user(c, "ana@exemplo.com", ids["A"])
    r = TestClient(app).post("/v1/auth/login", json={"email": "ana@exemplo.com", "password": PWD})
    assert "; secure" in r.headers["set-cookie"].lower()


def test_login_erro_generico(env):
    app, c, ids, _ = env
    uid = _user(c, "ana@exemplo.com", ids["A"])
    _user(c, "off@exemplo.com", ids["A"])
    c.patch("/v1/admin/users/2", json={"active": False}, headers=ADMIN)
    client = TestClient(app)
    respostas = {
        (r.status_code, r.text)
        for r in (
            client.post(
                "/v1/auth/login", json={"email": "ana@exemplo.com", "password": "errada-errada"}
            ),
            client.post(
                "/v1/auth/login", json={"email": "nao@existe.com", "password": "errada-errada"}
            ),
            client.post("/v1/auth/login", json={"email": "off@exemplo.com", "password": PWD}),
        )
    }
    assert len(respostas) == 1 and next(iter(respostas))[0] == 401
    assert uid == 1


def test_throttle_5_falhas_bloqueia_5_minutos(env):
    app, c, ids, _ = env
    _user(c, "ana@exemplo.com", ids["A"])
    now = [1000.0]
    app.state.throttle.clock = lambda: now[0]
    client = TestClient(app)
    bad = {"email": "ana@exemplo.com", "password": "errada-errada"}
    for _ in range(5):
        assert client.post("/v1/auth/login", json=bad).status_code == 401
    r = client.post("/v1/auth/login", json={"email": "ana@exemplo.com", "password": PWD})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0  # nem a senha certa passa
    now[0] += 301
    assert (
        client.post(
            "/v1/auth/login", json={"email": "ana@exemplo.com", "password": PWD}
        ).status_code
        == 200
    )


def test_throttle_vale_para_email_inexistente_sem_revelar(env):
    app, _, _, _ = env
    client = TestClient(app)
    codes = [
        client.post(
            "/v1/auth/login", json={"email": "x@y.com", "password": "errada-errada"}
        ).status_code
        for _ in range(6)
    ]
    assert codes == [401] * 5 + [429]


def test_usuario_validacoes_e_senha_nunca_volta(env):
    _, c, _, _ = env
    r = c.post("/v1/admin/users", json={"email": "a@b.com", "password": "curta"}, headers=ADMIN)
    assert r.status_code == 422
    assert (
        c.post(
            "/v1/admin/users", json={"email": "sem-arroba", "password": PWD}, headers=ADMIN
        ).status_code
        == 422
    )
    ok = c.post("/v1/admin/users", json={"email": "a@b.com", "password": PWD}, headers=ADMIN)
    assert ok.status_code == 201 and "password" not in ok.text and "scrypt" not in ok.text
    dup = c.post("/v1/admin/users", json={"email": "A@B.com", "password": PWD}, headers=ADMIN)
    assert dup.status_code == 409
    up = c.patch("/v1/admin/users/1", json={"password": "nova-senha-123456"}, headers=ADMIN)
    assert up.status_code == 200 and "scrypt" not in up.text and "password" not in up.text
    assert (
        c.patch("/v1/admin/users/1", json={"password": "curta"}, headers=ADMIN).status_code == 422
    )
    assert c.patch("/v1/admin/users/99", json={"active": False}, headers=ADMIN).status_code == 404


def test_memberships_regras(env):
    _, c, ids, _ = env
    uid = _user(c, "ana@exemplo.com", ids["A"])
    post = lambda body: c.post("/v1/admin/memberships", json=body, headers=ADMIN)
    assert post({"user_id": uid, "role": "area_viewer", "area_id": ids["A"]}).status_code == 409
    assert post({"user_id": uid, "role": "area_viewer"}).status_code == 422
    assert post({"user_id": uid, "role": "org_admin", "area_id": ids["A"]}).status_code == 422
    assert post({"user_id": uid, "role": "area_viewer", "area_id": 999}).status_code == 404
    assert post({"user_id": 999, "role": "org_admin"}).status_code == 404
    assert post({"user_id": uid, "role": "dono"}).status_code == 422
    assert post({"user_id": uid, "role": "org_admin"}).status_code == 201
    assert post({"user_id": uid, "role": "org_admin"}).status_code == 409
    assert c.delete("/v1/admin/memberships/1", headers=ADMIN).status_code == 204
    assert c.delete("/v1/admin/memberships/1", headers=ADMIN).status_code == 404


# ---- acesso por área -----------------------------------------------------------------------


def test_usuario_da_area_a_nao_ve_area_b(env):
    app, c, ids, rep = env
    _user(c, "ana@exemplo.com", ids["A1"])  # só a sub-área
    _user(c, "bia@exemplo.com", ids["B"])
    ana = _login(app, "ana@exemplo.com")
    assert ana.get(f"/v1/areas/{ids['B']}/agents").status_code == 404
    assert ana.get(f"/v1/agents/{ids['ag_B']}/reports").status_code == 404
    assert ana.get(f"/v1/reports/{rep['B']}").status_code == 404
    assert ana.get(f"/v1/reports/{rep['B']}/download?format=md").status_code == 404
    assert ana.get("/v1/areas/999/agents").status_code == 404  # inexistente = fora do alcance
    assert ana.get(f"/v1/reports/{rep['A1']}").status_code == 200
    with Session(app.state.engine) as s:
        assert s.scalars(select(DownloadLog)).first() is None  # 404 não grava log


def test_heranca_para_sub_areas_e_nunca_para_cima(env):
    app, c, ids, rep = env
    _user(c, "ana@exemplo.com", ids["A"])
    _user(c, "caio@exemplo.com", ids["A1"])
    ana, caio = _login(app, "ana@exemplo.com"), _login(app, "caio@exemplo.com")
    tree = ana.get("/v1/areas").json()
    assert [n["name"] for n in tree] == ["A"] and [n["name"] for n in tree[0]["children"]] == ["A1"]
    assert ana.get(f"/v1/areas/{ids['A1']}/agents").json()[0]["slug"] == "ag-a1"
    assert ana.get(f"/v1/reports/{rep['A1']}").status_code == 200
    # quem só tem a sub-área não enxerga a de cima e a sub-área vira raiz (pai não é revelado)
    tree = caio.get("/v1/areas").json()
    assert len(tree) == 1 and tree[0]["name"] == "A1" and tree[0]["parent_id"] is None
    assert caio.get(f"/v1/areas/{ids['A']}/agents").status_code == 404
    assert caio.get(f"/v1/reports/{rep['A']}").status_code == 404


def test_org_admin_ve_tudo_e_gerencia_por_sessao(env):
    app, c, ids, rep = env
    _user(c, "root@exemplo.com", role="org_admin")
    _user(c, "ana@exemplo.com", ids["A"])
    root, ana = _login(app, "root@exemplo.com"), _login(app, "ana@exemplo.com")
    assert root.get("/v1/auth/me").json()["is_org_admin"] is True
    assert {n["name"] for n in root.get("/v1/areas").json()} == {"A", "B"}
    assert root.get(f"/v1/reports/{rep['B']}").status_code == 200
    # admin por sessão (sem a chave de bootstrap) cria usuário; viewer não
    body = {"email": "novo@exemplo.com", "password": PWD}
    assert root.post("/v1/admin/users", json=body).status_code == 201
    assert ana.post("/v1/admin/users", json={**body, "email": "x@exemplo.com"}).status_code == 403
    assert TestClient(app).post("/v1/admin/users", json=body).status_code == 401


def test_leitura_lista_versoes_mais_recente_primeiro_com_datas(env):
    app, c, ids, rep = env
    h = {"Authorization": f"Bearer {ids['tok_A']}"}
    assert c.post("/v1/reports", json=_package("ag-a", mean=0.9), headers=h).status_code == 201
    _user(c, "ana@exemplo.com", ids["A"])
    ana = _login(app, "ana@exemplo.com")
    lst = ana.get(f"/v1/agents/{ids['ag_A']}/reports").json()
    assert [x["seq"] for x in lst] == [2, 1]
    assert (
        lst[0]["generated_at"] == GEN
        and lst[0]["published_at"]
        and lst[0]["status_semaforo"] == "green"
    )
    det = ana.get(f"/v1/reports/{rep['A']}").json()
    assert det["agent_slug"] == "ag-a" and det["summary"]["eval"]["n_cases"] == 50
    assert det["audit_verify_ok"] is True and det["generated_at"] == GEN
    assert "file_md" not in det  # caminho interno não vaza


def test_token_de_agente_nao_le(env):
    app, _, ids, rep = env
    h = {"Authorization": f"Bearer {ids['tok_A']}"}
    client = TestClient(app)
    for path in (
        "/v1/areas",
        f"/v1/areas/{ids['A']}/agents",
        f"/v1/agents/{ids['ag_A']}/reports",
        f"/v1/reports/{rep['A']}",
        f"/v1/reports/{rep['A']}/download?format=md",
        "/v1/me/downloads",
        "/v1/admin/downloads",
        "/v1/auth/me",
    ):
        assert client.get(path, headers=h).status_code == 401, path


# ---- download e histórico ------------------------------------------------------------------


def test_download_grava_log_e_historico_mostra_as_duas_datas(env):
    app, c, ids, rep = env
    _user(c, "ana@exemplo.com", ids["A"])
    ana = _login(app, "ana@exemplo.com")
    antes = utcnow()
    md = ana.get(f"/v1/reports/{rep['A']}/download?format=md")
    assert md.status_code == 200 and md.text == "# Relatório ag-a\n"
    assert md.headers["content-disposition"] == 'attachment; filename="ag-a-1.md"'
    assert md.headers["x-content-type-options"] == "nosniff"
    html = ana.get(f"/v1/reports/{rep['A']}/download?format=html")
    assert "default-src 'none'" in html.headers["content-security-policy"]
    assert html.headers["content-disposition"].startswith("attachment")
    assert html.headers["x-content-type-options"] == "nosniff"
    js = ana.get(f"/v1/reports/{rep['A']}/download?format=json")
    assert json.loads(js.text)["generated_at"] == GEN
    assert "content-security-policy" not in md.headers
    assert ana.get(f"/v1/reports/{rep['A']}/download?format=pdf").status_code == 422
    assert ana.get(f"/v1/reports/{rep['A']}/download").status_code == 422

    with Session(app.state.engine) as s:
        logs = list(s.scalars(select(DownloadLog).order_by(DownloadLog.id)))
        assert [x.format for x in logs] == ["md", "html", "json"]
        assert all(x.user_id == 1 and x.report_version_id == rep["A"] for x in logs)
        assert all(antes - timedelta(seconds=1) <= x.downloaded_at <= utcnow() for x in logs)

    hist = ana.get("/v1/me/downloads").json()
    assert [h["format"] for h in hist] == ["json", "html", "md"]  # mais recente primeiro
    item = hist[0]
    assert item["generated_at"] == GEN and item["downloaded_at"] and item["downloaded_at"] != GEN
    assert item["agent_slug"] == "ag-a" and item["area_name"] == "A" and item["seq"] == 1
    assert "user_email" in item and item["user_email"] is None
    # filtros
    assert len(ana.get(f"/v1/me/downloads?agent_id={ids['ag_A']}").json()) == 3
    assert ana.get(f"/v1/me/downloads?agent_id={ids['ag_B']}").json() == []
    assert len(ana.get(f"/v1/me/downloads?area_id={ids['A']}").json()) == 3
    assert ana.get(f"/v1/me/downloads?area_id={ids['A1']}").json() == []
    assert len(ana.get("/v1/me/downloads?limit=1").json()) == 1


def test_download_de_arquivo_ausente_nao_grava_log(env, tmp_path):
    app, c, ids, rep = env
    _user(c, "ana@exemplo.com", ids["A"])
    ana = _login(app, "ana@exemplo.com")
    folder = tmp_path / "data" / "1" / "ag-a"  # layout novo: <org_id>/<slug>/<sha256>
    folder.joinpath(next(folder.iterdir()).name, "relatorio.md").unlink()
    assert ana.get(f"/v1/reports/{rep['A']}/download?format=md").status_code == 404
    with Session(app.state.engine) as s:
        assert s.scalars(select(DownloadLog)).first() is None


def test_historico_nao_vaza_entre_usuarios_e_admin_ve_todos(env):
    app, c, ids, rep = env
    _user(c, "ana@exemplo.com", ids["A"])
    _user(c, "bia@exemplo.com", ids["B"])
    _user(c, "root@exemplo.com", role="org_admin")
    ana, bia, root = (_login(app, e + "@exemplo.com") for e in ("ana", "bia", "root"))
    ana.get(f"/v1/reports/{rep['A']}/download?format=md")
    bia.get(f"/v1/reports/{rep['B']}/download?format=json")
    assert [h["agent_slug"] for h in ana.get("/v1/me/downloads").json()] == ["ag-a"]
    assert [h["agent_slug"] for h in bia.get("/v1/me/downloads").json()] == ["ag-b"]
    assert root.get("/v1/me/downloads").json() == []  # o admin também só vê os próprios aqui
    # nem por filtro: user_id não é parâmetro, e area_id de outro só devolve o que é dele
    assert ana.get(f"/v1/me/downloads?area_id={ids['B']}").json() == []
    assert ana.get("/v1/me/downloads?user_id=2").json() == [ana.get("/v1/me/downloads").json()[0]]
    # rota admin: só org_admin por sessão, com e-mail
    assert ana.get("/v1/admin/downloads").status_code == 403
    assert c.get("/v1/admin/downloads", headers=ADMIN).status_code == 401  # chave não lê trilha
    todos = root.get("/v1/admin/downloads").json()
    assert {(t["user_email"], t["agent_slug"]) for t in todos} == {
        ("ana@exemplo.com", "ag-a"),
        ("bia@exemplo.com", "ag-b"),
    }
    assert all(t["generated_at"] == GEN and t["downloaded_at"] for t in todos)
    assert [
        t["user_email"] for t in root.get(f"/v1/admin/downloads?area_id={ids['B']}").json()
    ] == ["bia@exemplo.com"]


# ---- sessão: expiração, revogação, logout --------------------------------------------------


def test_sessao_expirada_falha(env):
    app, c, ids, _ = env
    _user(c, "ana@exemplo.com", ids["A"])
    ana = _login(app, "ana@exemplo.com")
    assert ana.get("/v1/auth/me").status_code == 200
    with Session(app.state.engine) as s:
        row = s.scalars(select(UserSession)).one()
        assert row.expires_at - row.created_at == timedelta(hours=8)
        row.expires_at = utcnow() - timedelta(seconds=1)
        s.commit()
    assert ana.get("/v1/auth/me").status_code == 401
    assert ana.get("/v1/areas").status_code == 401


def test_sessao_revogada_e_logout(env):
    app, c, ids, _ = env
    _user(c, "ana@exemplo.com", ids["A"])
    ana = _login(app, "ana@exemplo.com")
    token = ana.cookies.get("aok_session")
    assert ana.post("/v1/auth/logout").status_code == 204
    assert ana.get("/v1/auth/me").status_code == 401  # cookie apagado
    ana.cookies.set("aok_session", token)  # reaproveitar o token antigo também falha
    assert ana.get("/v1/auth/me").status_code == 401
    with Session(app.state.engine) as s:
        assert s.scalars(select(UserSession)).one().revoked_at is not None
    assert TestClient(app).post("/v1/auth/logout").status_code == 204  # sem sessão: idempotente


def test_desativar_ou_trocar_senha_encerra_sessoes(env):
    app, c, ids, _ = env
    uid = _user(c, "ana@exemplo.com", ids["A"])
    ana = _login(app, "ana@exemplo.com")
    c.patch(f"/v1/admin/users/{uid}", json={"password": "outra-senha-12345"}, headers=ADMIN)
    assert ana.get("/v1/auth/me").status_code == 401
    ana2 = _login(app, "ana@exemplo.com", "outra-senha-12345")
    c.patch(f"/v1/admin/users/{uid}", json={"active": False}, headers=ADMIN)
    assert ana2.get("/v1/auth/me").status_code == 401
    r = TestClient(app).post(
        "/v1/auth/login", json={"email": "ana@exemplo.com", "password": "outra-senha-12345"}
    )
    assert r.status_code == 401
