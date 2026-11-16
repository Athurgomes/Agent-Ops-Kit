"""Multi-organização: isolamento total entre A e B, org inativa, bootstrap com X-Org-Slug, esquema legado."""

import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.db import ensure_schema
from aok_platform.models import (
    AdminEvent,
    Agent,
    Area,
    DownloadLog,
    Membership,
    Organization,
    ReportVersion,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

KEY = "chave-de-teste-nao-secreta"
PWD = "senha-de-teste-123"


def hdr(slug):
    return {"Authorization": f"Bearer {KEY}", "X-Org-Slug": slug}


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package(slug, tag="x"):
    js = {
        "generated_at": "2026-01-02T03:04:05-03:00",
        "agent": {"name": slug, "model": "m"},
        "semaphore": {"color": "green", "triggered": []},
        "eval": {"baseline": "v1", "candidate": "v2", "n_cases": 5, "tag": tag},
    }
    files = {"relatorio.json": json.dumps(js), "relatorio.md": f"# {tag}\n", "relatorio.html": f"<p>{tag}</p>"}
    return {
        "agent_id": slug,
        "timestamp": "20260102T030405Z",
        "semaphore": "green",
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
    }


def _login(app, email):
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": email, "password": PWD}).status_code == 200
    return c


def _populate(c, app, slug, other_slug_marker):
    """Uma organização completa. O agente `shared` tem o MESMO slug e o MESMO relatório nas duas orgs."""
    h = hdr(slug)
    w = SimpleNamespace(slug=slug, h=h)
    mk = lambda path, body: c.post(path, json=body, headers=h)
    w.area_p = mk("/v1/admin/areas", {"name": f"Area P {slug}"}).json()["id"]
    w.area_c = mk("/v1/admin/areas", {"name": f"Area C {slug}", "parent_id": w.area_p}).json()["id"]
    w.shared = mk("/v1/admin/agents", {"area_id": w.area_p, "slug": "shared", "name": f"Shared {slug}"}).json()["id"]
    w.own_slug = f"own-{slug}"
    w.own = mk("/v1/admin/agents", {"area_id": w.area_c, "slug": w.own_slug, "name": f"Own {slug}"}).json()["id"]
    w.tok_shared = c.post(f"/v1/admin/agents/{w.shared}/tokens", headers=h).json()
    w.tok_own = c.post(f"/v1/admin/agents/{w.own}/tokens", headers=h).json()
    w.admin_email, w.viewer_email = f"admin@{slug}.test", f"viewer@{slug}.test"
    w.admin = mk("/v1/admin/users", {"email": w.admin_email, "password": PWD}).json()["id"]
    w.viewer = mk("/v1/admin/users", {"email": w.viewer_email, "password": PWD}).json()["id"]
    w.m_admin = mk("/v1/admin/memberships", {"user_id": w.admin, "role": "org_admin"}).json()["id"]
    w.m_viewer = mk(
        "/v1/admin/memberships", {"user_id": w.viewer, "role": "area_viewer", "area_id": w.area_p}
    ).json()["id"]
    for key, tok, ag in (("shared", w.tok_shared, "shared"), ("own", w.tok_own, w.own_slug)):
        r = c.post("/v1/reports", json=_package(ag, "same" if key == "shared" else slug),
                   headers={"Authorization": f"Bearer {tok['token']}"})
        assert r.status_code == 201, r.text
        setattr(w, f"sha_{key}", r.json()["sha256"])
    w.admin_c, w.viewer_c = _login(app, w.admin_email), _login(app, w.viewer_email)
    with Session(app.state.engine) as s:
        w.report_shared, w.report_own = (
            s.scalar(select(ReportVersion.id).where(ReportVersion.agent_id == a)) for a in (w.shared, w.own)
        )
        w.org_id = s.scalar(select(Agent.org_id).where(Agent.id == w.shared))
    assert w.viewer_c.get(f"/v1/reports/{w.report_shared}/download?format=md").status_code == 200  # gera download_log
    return w


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    monkeypatch.setattr("aok_platform.auth._SCRYPT", {"n": 2**4, "r": 8, "p": 1})  # só acelera o teste
    data = tmp_path / "data"
    app = create_app("sqlite:///:memory:", data_dir=data)
    with Session(app.state.engine) as s:
        s.add(Organization(name="Bravo", slug="bravo", active=True))
        s.commit()
    c = TestClient(app)
    a = _populate(c, app, "default", "bravo")  # a organização padrão é a A (slug "default")
    b = _populate(c, app, "bravo", "default")
    return SimpleNamespace(app=app, c=c, a=a, b=b, data=data)


def _snapshot(w, org):
    """Tudo o que o admin enxerga de uma org (listagens + eventos): serve para provar que nada mudou."""
    out = {}
    for p in ("areas", "agents", "users", "memberships", f"agents/{org.shared}/tokens", f"agents/{org.own}/tokens"):
        out[p] = w.c.get(f"/v1/admin/{p}", headers=org.h).json()
    out["events"] = org.admin_c.get("/v1/admin/events?limit=500").json()
    out["downloads"] = org.admin_c.get("/v1/admin/downloads").json()
    out["reports"] = org.admin_c.get(f"/v1/agents/{org.shared}/reports").json()
    return out


# ---- bootstrap e X-Org-Slug -----------------------------------------------------------------


def test_bootstrap_com_duas_orgs_exige_cabecalho(world):
    w = world
    only_key = {"Authorization": f"Bearer {KEY}"}
    r = w.c.get("/v1/admin/areas", headers=only_key)
    assert r.status_code == 400 and "X-Org-Slug" in r.json()["detail"]
    assert w.c.post("/v1/admin/areas", json={"name": "z"}, headers=only_key).status_code == 400
    assert w.c.get("/v1/admin/areas", headers=hdr("nao-existe")).status_code == 404
    names = {a["name"] for a in w.c.get("/v1/admin/areas", headers=hdr("bravo")).json()}
    assert names == {"Area P bravo", "Area C bravo"}


def test_bootstrap_nao_le_events_nem_downloads_mesmo_com_cabecalho(world):
    w = world
    for p in ("/v1/admin/events", "/v1/admin/downloads"):
        assert w.c.get(p, headers=hdr("bravo")).status_code == 401


def test_sessao_admin_ignora_cabecalho_de_outra_org(world):
    w = world
    r = w.a.admin_c.get("/v1/admin/areas", headers={"X-Org-Slug": "bravo"})
    assert {a["name"] for a in r.json()} == {"Area P default", "Area C default"}


def test_bootstrap_uma_org_so_funciona_sem_cabecalho(monkeypatch):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    c = TestClient(create_app("sqlite:///:memory:"))
    only_key = {"Authorization": f"Bearer {KEY}"}
    assert c.post("/v1/admin/areas", json={"name": "x"}, headers=only_key).status_code == 201
    assert c.get("/v1/admin/areas", headers=hdr("default")).status_code == 200
    assert c.get("/v1/admin/areas", headers=hdr("outra")).status_code == 404


# ---- slug por organização, e-mail global, mesmo sha em duas orgs -------------------------------


def test_slug_de_agente_unico_so_dentro_da_org(world):
    w = world
    r = w.c.post("/v1/admin/agents", json={"area_id": w.a.area_p, "slug": "shared", "name": "dup"}, headers=w.a.h)
    assert r.status_code == 409 and "bravo" not in r.text.lower()  # não revela outras orgs
    only_b = w.c.post("/v1/admin/agents", json={"area_id": w.b.area_p, "slug": "so-na-b", "name": "n"}, headers=w.b.h)
    assert only_b.status_code == 201
    assert w.c.post("/v1/admin/agents", json={"area_id": w.a.area_p, "slug": "so-na-b", "name": "n"}, headers=w.a.h).status_code == 201


def test_email_e_unico_global(world):
    w = world  # o login é só por e-mail: o mesmo e-mail em duas orgs seria ambíguo
    r = w.c.post("/v1/admin/users", json={"email": w.a.admin_email, "password": PWD}, headers=w.b.h)
    assert r.status_code == 409


def test_mesmo_slug_e_mesmo_sha_em_duas_orgs_sem_colisao(world):
    w = world
    assert w.a.sha_shared == w.b.sha_shared and w.a.report_shared != w.b.report_shared
    fa = w.data / str(w.a.org_id) / "shared" / w.a.sha_shared
    fb = w.data / str(w.b.org_id) / "shared" / w.b.sha_shared
    assert fa != fb and (fa / "relatorio.md").is_file() and (fb / "relatorio.md").is_file()
    for org in (w.a, w.b):
        assert org.viewer_c.get(f"/v1/reports/{org.report_shared}/download?format=html").text == "<p>same</p>"
        assert len(org.admin_c.get(f"/v1/agents/{org.shared}/reports").json()) == 1
    # republicar na mesma org continua sendo 409 (a unicidade é por agente)
    again = w.c.post("/v1/reports", json=_package("shared", "same"), headers={"Authorization": f"Bearer {w.a.tok_shared['token']}"})
    assert again.status_code == 409


# ---- auditoria de escopo: nada de B é lido, listado, baixado, alterado ou revogado por A -----------

ADMIN_WRITES = [  # (método, caminho, corpo) com ids de B; qualquer principal de A deve receber 403/404
    ("PATCH", lambda b: f"/v1/admin/areas/{b.area_p}", lambda b: {"name": "hack"}),
    ("PATCH", lambda b: f"/v1/admin/agents/{b.shared}", lambda b: {"active": False}),
    ("PATCH", lambda b: f"/v1/admin/agents/{b.own}", lambda b: {"name": "hack"}),
    ("PATCH", lambda b: f"/v1/admin/users/{b.viewer}", lambda b: {"active": False}),
    ("PATCH", lambda b: f"/v1/admin/users/{b.viewer}", lambda b: {"password": "outra-senha-longa-1"}),
    ("POST", lambda b: f"/v1/admin/agents/{b.shared}/tokens", None),
    ("GET", lambda b: f"/v1/admin/agents/{b.shared}/tokens", None),
    ("DELETE", lambda b: f"/v1/admin/agents/{b.shared}/tokens/{b.tok_shared['token_id']}", None),
    ("DELETE", lambda b: f"/v1/admin/memberships/{b.m_viewer}", None),
    ("DELETE", lambda b: f"/v1/admin/memberships/{b.m_admin}", None),
    ("POST", lambda b: "/v1/admin/areas", lambda b: {"name": "x", "parent_id": b.area_p}),
    ("POST", lambda b: "/v1/admin/agents", lambda b: {"area_id": b.area_p, "slug": "novo", "name": "n"}),
    ("POST", lambda b: "/v1/admin/memberships", lambda b: {"user_id": b.viewer, "role": "org_admin"}),
    ("POST", lambda b: "/v1/admin/memberships", lambda b: {"user_id": b.viewer, "role": "area_viewer", "area_id": b.area_p}),
]
PORTAL_READS = [
    lambda b: f"/v1/areas/{b.area_p}/agents",
    lambda b: f"/v1/areas/{b.area_c}/agents",
    lambda b: f"/v1/agents/{b.shared}/reports",
    lambda b: f"/v1/reports/{b.report_shared}",
    lambda b: f"/v1/reports/{b.report_own}",
    lambda b: f"/v1/reports/{b.report_shared}/download?format=md",
    lambda b: f"/v1/reports/{b.report_shared}/download?format=html",
    lambda b: f"/v1/reports/{b.report_shared}/download?format=json",
    lambda b: f"/v1/reports/{b.report_own}/download?format=md",
]


@pytest.mark.parametrize("who", ["admin", "viewer", "bootstrap"])
@pytest.mark.parametrize("idx", range(len(ADMIN_WRITES)))
def test_a_nao_altera_nem_le_admin_de_b(world, who, idx):
    w = world
    method, path_fn, body = ADMIN_WRITES[idx]
    client, headers = {"admin": (w.a.admin_c, {}), "viewer": (w.a.viewer_c, {}), "bootstrap": (w.c, w.a.h)}[who]
    before = _snapshot(w, w.b)
    r = client.request(method, path_fn(w.b), json=body(w.b) if body else None, headers=headers)
    assert r.status_code in (403, 404), (method, path_fn(w.b), r.status_code, r.text)
    assert _snapshot(w, w.b) == before  # nada mudou em B (nem eventos)


@pytest.mark.parametrize("who", ["admin", "viewer"])
@pytest.mark.parametrize("idx", range(len(PORTAL_READS)))
def test_a_nao_le_portal_de_b(world, who, idx):
    w = world
    client = w.a.admin_c if who == "admin" else w.a.viewer_c
    r = client.get(PORTAL_READS[idx](w.b))
    assert r.status_code == 404
    assert "bravo" not in r.text.lower() and "same" not in r.text


def test_bootstrap_nao_usa_o_portal(world):
    w = world
    assert w.c.get(f"/v1/reports/{w.b.report_shared}", headers=w.a.h).status_code == 401


@pytest.mark.parametrize("who", ["admin", "viewer", "bootstrap"])
def test_listagens_de_a_nao_contem_nada_de_b(world, who):
    w = world
    client, headers = {"admin": (w.a.admin_c, {}), "viewer": (w.a.viewer_c, {}), "bootstrap": (w.c, w.a.h)}[who]
    paths = ["/v1/areas", f"/v1/areas/{w.a.area_p}/agents", f"/v1/agents/{w.a.shared}/reports", "/v1/me/downloads"]
    if who != "viewer":
        paths += ["/v1/admin/areas", "/v1/admin/agents", "/v1/admin/users", "/v1/admin/memberships"]
    if who == "admin":
        paths += ["/v1/admin/events?limit=500", "/v1/admin/downloads", f"/v1/admin/downloads?agent_id={w.b.shared}",
                  f"/v1/me/downloads?agent_id={w.b.shared}", f"/v1/me/downloads?area_id={w.b.area_p}"]
    for p in paths:
        r = client.get(p, headers=headers if p.startswith("/v1/admin") else {})
        if who == "bootstrap" and not p.startswith("/v1/admin"):
            continue  # bootstrap não usa o portal (coberto acima)
        if r.status_code == 200:
            blob = r.text.lower()
            assert "bravo" not in blob, p
            assert w.b.own_slug not in blob and w.b.admin_email not in blob, p
    ev = w.a.admin_c.get("/v1/admin/events?limit=500").json()
    assert ev and all(e["actor_email"] in (None, w.a.admin_email) for e in ev)


def test_eventos_e_downloads_de_cada_org_ficam_na_propria_org(world):
    w = world
    assert w.b.admin_c.get(f"/v1/admin/downloads?agent_id={w.a.shared}").json() == []
    mine = w.a.admin_c.get("/v1/admin/downloads").json()
    assert mine and all(d["area_id"] == w.a.area_p and d["user_email"] == w.a.viewer_email for d in mine)
    with Session(w.app.state.engine) as s:
        assert s.scalar(select(AdminEvent.id).where(AdminEvent.org_id == w.a.org_id)) is not None
        orgs = {o for o in s.scalars(select(AdminEvent.org_id))}
        assert orgs == {w.a.org_id, w.b.org_id}
        logs = list(s.scalars(select(DownloadLog)))
        assert len(logs) == 2  # um por org, cada um do próprio viewer


def test_membership_cruzada_e_recusada_e_nao_cria_nada(world):
    w = world
    cases = [
        (w.a.h, {"user_id": w.a.viewer, "role": "area_viewer", "area_id": w.b.area_p}),
        (w.b.h, {"user_id": w.a.viewer, "role": "area_viewer", "area_id": w.b.area_p}),
        (w.a.h, {"user_id": w.b.viewer, "role": "area_viewer", "area_id": w.a.area_p}),
        (w.b.h, {"user_id": w.b.viewer, "role": "area_viewer", "area_id": w.a.area_c}),
    ]
    with Session(w.app.state.engine) as s:
        before = s.scalar(select(Membership.id).order_by(Membership.id.desc()))
    for headers, body in cases:
        assert w.c.post("/v1/admin/memberships", json=body, headers=headers).status_code == 404
    assert w.a.admin_c.post("/v1/admin/memberships", json=cases[0][1]).status_code == 404
    with Session(w.app.state.engine) as s:
        assert s.scalar(select(Membership.id).order_by(Membership.id.desc())) == before


def test_usuario_com_membership_cruzada_no_banco_nao_ganha_acesso(world):
    w = world  # defesa em profundidade: mesmo que a linha exista, a consulta filtra por organização
    with Session(w.app.state.engine) as s:
        s.add(Membership(user_id=w.a.viewer, area_id=w.b.area_p, role="area_viewer"))
        s.commit()
    assert w.a.viewer_c.get(f"/v1/areas/{w.b.area_p}/agents").status_code == 404
    assert w.a.viewer_c.get(f"/v1/reports/{w.b.report_shared}").status_code == 404
    assert {a["name"] for a in w.a.viewer_c.get("/v1/areas").json()} == {"Area P default"}


def test_token_de_a_nao_publica_em_agente_de_b(world):
    w = world
    ha = {"Authorization": f"Bearer {w.a.tok_shared['token']}"}
    # slug de um agente que só existe em B: o corpo não confere com o agente do token
    assert w.c.post("/v1/reports", json=_package(w.b.own_slug, "t1"), headers=ha).status_code == 403
    # o slug "shared" existe nas duas orgs: quem decide é o token, então cai no agente de A
    r = w.c.post("/v1/reports", json=_package("shared", "t2"), headers=ha)
    assert r.status_code == 201
    with Session(w.app.state.engine) as s:
        new = s.scalar(select(ReportVersion).where(ReportVersion.sha256 == r.json()["sha256"]))
        assert new.agent_id == w.a.shared and new.file_md.startswith(f"{w.a.org_id}/shared/")
        assert len(list(s.scalars(select(ReportVersion).where(ReportVersion.agent_id == w.b.shared)))) == 1
    # token revogado ou de outro agente não abre nada em B
    assert w.c.post("/v1/reports", json=_package(w.b.own_slug, "t3"), headers={"Authorization": f"Bearer {w.a.tok_own['token']}"}).status_code == 403


# ---- organização inativa -----------------------------------------------------------------------


def _set_active(w, org, value):
    with Session(w.app.state.engine) as s:
        s.execute(update(Organization).where(Organization.id == org.org_id).values(active=value))
        s.commit()


def test_org_inativa_bloqueia_login_sessao_e_token_sem_apagar_nada(world):
    w = world
    with Session(w.app.state.engine) as s:
        counts = {t: len(list(s.scalars(select(t.id)))) for t in (Area, Agent, ReportVersion, DownloadLog)}
    _set_active(w, w.b, False)
    assert w.b.admin_c.get("/v1/auth/me").status_code == 401  # sessão existente
    assert w.b.admin_c.get("/v1/areas").status_code == 401
    assert w.b.admin_c.get("/v1/admin/areas").status_code in (401, 503)
    fresh = TestClient(w.app).post("/v1/auth/login", json={"email": w.b.viewer_email, "password": PWD})
    assert fresh.status_code == 401 and fresh.json()["detail"] == "e-mail ou senha inválidos"  # erro genérico
    tok = {"Authorization": f"Bearer {w.b.tok_own['token']}"}
    assert w.c.post("/v1/reports", json=_package(w.b.own_slug, "novo"), headers=tok).status_code == 401
    assert w.c.get("/v1/admin/areas", headers=w.b.h).status_code == 404  # bootstrap não resolve a org inativa
    assert w.a.admin_c.get("/v1/areas").status_code == 200  # a outra org segue normal
    with Session(w.app.state.engine) as s:
        assert {t: len(list(s.scalars(select(t.id)))) for t in (Area, Agent, ReportVersion, DownloadLog)} == counts
    _set_active(w, w.b, True)  # reativar devolve tudo, inclusive a sessão antiga
    assert w.b.admin_c.get("/v1/auth/me").status_code == 200
    assert _login(w.app, w.b.viewer_email).get("/v1/areas").status_code == 200
    assert w.c.post("/v1/reports", json=_package(w.b.own_slug, "novo"), headers=tok).status_code == 201


# ---- download: caminho novo, caminho antigo e path traversal ---------------------------------------


def test_download_segue_para_caminho_antigo_e_bloqueia_traversal(world):
    w = world
    report = w.a.report_own
    new_dir = w.data / str(w.a.org_id) / w.a.own_slug / w.a.sha_own
    legacy = w.data / w.a.own_slug / w.a.sha_own  # layout antigo: <slug>/<sha256>
    legacy.mkdir(parents=True)
    for name in ("relatorio.md", "relatorio.html", "relatorio.json"):
        (legacy / name).write_bytes((new_dir / name).read_bytes())
    rt = ReportVersion.__table__
    with Session(w.app.state.engine) as s:  # Core update: o ORM bloqueia update de report_version
        s.execute(update(rt).where(rt.c.id == report).values(
            file_md=f"{w.a.own_slug}/{w.a.sha_own}/relatorio.md",
            file_html=f"{w.a.own_slug}/{w.a.sha_own}/relatorio.html",
            file_json="../../fora.json",
        ))
        s.commit()
    (w.data.parent / "fora.json").write_text("segredo", encoding="utf-8")
    assert w.a.admin_c.get(f"/v1/reports/{report}/download?format=md").status_code == 200  # legado
    assert w.a.admin_c.get(f"/v1/reports/{w.a.report_shared}/download?format=md").status_code == 200  # novo
    r = w.a.admin_c.get(f"/v1/reports/{report}/download?format=json")
    assert r.status_code == 404 and "segredo" not in r.text  # traversal barrado
    with Session(w.app.state.engine) as s:
        s.execute(update(rt).where(rt.c.id == report).values(file_json="/etc/passwd"))
        s.commit()
    assert w.a.admin_c.get(f"/v1/reports/{report}/download?format=json").status_code == 404


# ---- esquema legado: colunas novas sem Alembic ------------------------------------------------------


def _legacy_db(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE organization (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL);
        CREATE TABLE area (id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name VARCHAR(200) NOT NULL,
                           parent_id INTEGER);
        CREATE TABLE agent (id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL, slug VARCHAR(64) NOT NULL UNIQUE,
                            name VARCHAR(200) NOT NULL, active BOOLEAN);
        INSERT INTO organization (id, name) VALUES (1, 'Minha Empresa'), (2, 'Minha Empresa');
        INSERT INTO area (id, org_id, name) VALUES (1, 1, 'A'), (2, 2, 'B');
        INSERT INTO agent (id, area_id, slug, name, active) VALUES (1, 1, 'ag-1', 'Ag 1', 1), (2, 2, 'ag-2', 'Ag 2', 1);
        """
    )
    con.commit()
    con.close()


def test_ensure_schema_adiciona_colunas_e_preenche_e_e_idempotente(tmp_path):
    db = tmp_path / "legacy.db"
    _legacy_db(db)
    engine = create_engine(f"sqlite:///{db}")
    ensure_schema(engine)
    ensure_schema(engine)  # idempotente
    with Session(engine) as s:
        orgs = list(s.scalars(select(Organization).order_by(Organization.id)))
        assert [o.slug for o in orgs] == ["minha-empresa", "minha-empresa-2"]  # único, derivado do nome
        assert all(o.active is True and o.created_at is not None for o in orgs)
        agents = {a.slug: a.org_id for a in s.scalars(select(Agent))}
        assert agents == {"ag-1": 1, "ag-2": 2}  # org do agente vem da área
    app = create_app(f"sqlite:///{db}", data_dir=tmp_path / "data")  # a API sobe sobre o banco migrado
    assert app.state.engine is not None
    # slug de organização continua único depois da migração (índice criado)
    con = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO organization (name, slug, active) VALUES ('x', 'minha-empresa', 1)")
    con.close()


def test_create_org_cli_cria_a_segunda_org_e_o_bootstrap_passa_a_exigir_cabecalho(monkeypatch, tmp_path):
    from aok_platform import create_org

    url = f"sqlite:///{tmp_path / 'o.db'}"
    monkeypatch.setenv("AOK_DATABASE_URL", url)
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    with pytest.raises(SystemExit):
        create_org.create_org("Slug Inválido", "x", url)
    create_org.create_org("acme", "Acme", url)
    with pytest.raises(SystemExit):  # slug repetido
        create_org.create_org("acme", "Outra", url)
    c = TestClient(create_app(url, data_dir=tmp_path / "d"))
    assert c.get("/v1/admin/areas", headers={"Authorization": f"Bearer {KEY}"}).status_code == 400
    assert c.get("/v1/admin/areas", headers=hdr("acme")).status_code == 200
