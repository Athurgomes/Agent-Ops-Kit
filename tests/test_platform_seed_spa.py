"""Portal servido pela API (SPA) e seed de demonstração. Sem rede, sem modelo."""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform import seed_demo
from aok_platform.app import create_app
from aok_platform.models import ReportVersion
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parent.parent


def _dist(tmp_path):
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>portal</title>", encoding="utf-8")
    (d / "assets" / "app-abc.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "segredo.txt").write_text("nao servir", encoding="utf-8")
    return d


def test_spa_servido_com_fallback_e_api_intacta(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_PORTAL_DIR", str(_dist(tmp_path)))
    c = TestClient(create_app("sqlite:///:memory:", data_dir=tmp_path / "data"))
    r = c.get("/")
    assert r.status_code == 200 and "portal" in r.text
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert "portal" in c.get("/app/areas/3").text  # rota do cliente cai no index.html
    js = c.get("/assets/app-abc.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
    assert "nao servir" not in c.get("/..%2fsegredo.txt").text
    assert "nao servir" not in c.get("/%2e%2e/segredo.txt").text
    assert c.get("/v1/areas").status_code == 401  # a API segue valendo
    nope = c.get("/v1/nao-existe")
    assert nope.status_code == 404 and nope.headers["content-type"] == "application/json"
    assert c.get("/docs").status_code == 200


def test_sem_dist_a_api_continua_igual(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_PORTAL_DIR", str(tmp_path / "nao-existe"))
    c = TestClient(create_app("sqlite:///:memory:", data_dir=tmp_path / "data"))
    assert c.get("/").status_code == 404
    assert c.get("/v1/areas").status_code == 401


def test_seed_demo_idempotente_e_detalhe_com_ressalvas(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv("AOK_DATABASE_URL", f"sqlite:///{tmp_path / 'demo.db'}")
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    data = tmp_path / "data"
    pwds = seed_demo.seed(ROOT, data)
    assert set(pwds) == {e for e, _, _ in seed_demo.USERS}
    assert all(len(p) >= 12 for p in pwds.values())

    assert seed_demo.seed(ROOT, data) == {}  # segunda execução: nada novo, nenhuma senha
    c = TestClient(create_app(data_dir=data))
    with Session(c.app.state.engine) as s:
        counts = s.execute(
            select(ReportVersion.agent_id, func.count()).group_by(ReportVersion.agent_id)
        ).all()
    assert len(counts) == 3 and {n for _, n in counts} == {2}

    email = "operacoes@demo.example"
    assert c.post("/v1/auth/login", json={"email": email, "password": pwds[email]}).status_code == 200
    agents = c.get("/v1/areas/2/agents").json()  # Atendimento é sub-área de Operações
    reports = c.get(f"/v1/agents/{agents[0]['id']}/reports").json()
    assert [r["seq"] for r in reports] == [2, 1]
    detail = c.get(f"/v1/reports/{reports[0]['id']}").json()
    assert detail["limitations"] and detail["status_semaforo"] in {"green", "yellow", "red"}
    assert c.get("/v1/areas/3/agents").status_code == 404  # Finanças fora do alcance


def test_seed_demo_recusa_banco_remoto(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_DATABASE_URL", "postgresql+psycopg://u:p@db.exemplo.com/x")
    with pytest.raises(SystemExit, match="local"):
        seed_demo.seed(ROOT, tmp_path)
