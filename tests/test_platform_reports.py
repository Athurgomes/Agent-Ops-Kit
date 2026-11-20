"""POST /v1/reports (fase 2) e cliente `aok check --publish URL`. Sem rede externa."""

import hashlib
import io
import json
import threading
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.models import AgentCredential, ReportVersion
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_ops_kit import cli
from agent_ops_kit.report import publish

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "examples/rag_agent/agent.yaml"
KEY = "chave-de-teste-nao-secreta"
ADMIN = {"Authorization": f"Bearer {KEY}"}
ANCHOR = "a" * 64


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package(agent_id="rag-demo", mean=0.7, color="green", **extra):
    js = {
        "schema_version": 1,
        "agent": {"name": agent_id, "prompt_version": "v2", "model": "llama3.1:8b"},
        "semaphore": {"color": color, "triggered": []},
        "eval": {
            "baseline": "v1",
            "candidate": "v2",
            "n_cases": 50,
            "mean_candidate": mean,
            "seed": 42,
            "regression": False,
            "manifest": {"v2": {"prompt_sha256": "p" * 64, "dataset_sha256": "d" * 64}},
        },
        "redteam": {"asr": {"guardrails": {"total": {"n": 40, "successes": 0}}}},
        "audit": {"ok": True, "n_events": 3, "anchor": ANCHOR},
    }
    files = {
        "relatorio.json": json.dumps(js, ensure_ascii=False),
        "relatorio.md": "# Relatório\n\nçãõ\r\n",
        "relatorio.html": "<h1>Relatório</h1>",
    }
    return {
        "agent_id": agent_id,
        "timestamp": "20260102T030405Z",
        "semaphore": color,
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
        **extra,
    }


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    return TestClient(app), tmp_path / "data"


def _make_agent(client, slug="rag-demo"):
    area = client.post("/v1/admin/areas", json={"name": f"A-{slug}"}, headers=ADMIN).json()
    ag = client.post(
        "/v1/admin/agents", json={"area_id": area["id"], "slug": slug, "name": slug}, headers=ADMIN
    ).json()
    tok = client.post(f"/v1/admin/agents/{ag['id']}/tokens", headers=ADMIN).json()
    return ag, tok["token"], tok["token_id"]


def _post(client, token, body):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/v1/reports", json=body, headers=headers)


def test_publica_duas_vezes_gera_seq_1_e_2(env):
    client, data = env
    _, token, _ = _make_agent(client)
    r1 = _post(client, token, _package(mean=0.7))
    r2 = _post(client, token, _package(mean=0.8))
    assert (r1.status_code, r1.json()["seq"]) == (201, 1)
    assert (r2.status_code, r2.json()["seq"]) == (201, 2)
    with Session(client.app.state.engine) as s:
        rows = s.scalars(select(ReportVersion).order_by(ReportVersion.seq)).all()
        assert [r.seq for r in rows] == [1, 2]
        row = rows[0]
        assert row.sha256 == _sha(_package(mean=0.7)["files"]["relatorio.json"])
        assert (row.status_semaforo, row.audit_verify_ok, row.audit_anchor) == (
            "green",
            True,
            ANCHOR,
        )
        assert (row.model, row.seed, row.n_cases) == ("llama3.1:8b", 42, 50)
        assert (row.prompt_sha256, row.dataset_sha256) == ("p" * 64, "d" * 64)
        assert row.summary_json["eval"]["mean_candidate"] == 0.7
        for path in (row.file_md, row.file_html, row.file_json):
            assert (data / path).is_file()
        # bytes idênticos ao enviado (inclui CRLF e acentos) e pacote.json no formato do motor
        assert (data / row.file_md).read_bytes() == _package()["files"]["relatorio.md"].encode()
        meta = json.loads((data / Path(row.file_json).parent / "pacote.json").read_text("utf-8"))
        assert set(meta) == {"agent_id", "timestamp", "semaphore", "sha256"}
        assert not list(data.rglob("*.tmp"))


def test_seq_e_independente_por_agente(env):
    client, _ = env
    _, t1, _ = _make_agent(client, "ag-um")
    _, t2, _ = _make_agent(client, "ag-dois")
    assert _post(client, t1, _package("ag-um")).json()["seq"] == 1
    assert _post(client, t2, _package("ag-dois")).json()["seq"] == 1


def test_token_de_outro_agente_nao_publica_no_alvo(env):
    client, _ = env
    _make_agent(client, "alvo")
    _, outro, _ = _make_agent(client, "outro")
    assert _post(client, outro, _package("alvo")).status_code == 403
    with Session(client.app.state.engine) as s:
        assert s.scalars(select(ReportVersion)).all() == []


def test_agent_id_divergente_403(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    assert _post(client, token, _package("outro-agente")).status_code == 403


@pytest.mark.parametrize("token", [None, "token-inexistente"])
def test_sem_token_ou_desconhecido_401(env, token):
    client, _ = env
    _make_agent(client)
    assert _post(client, token, _package()).status_code == 401


def test_token_revogado_401(env):
    client, _ = env
    ag, token, token_id = _make_agent(client)
    assert _post(client, token, _package()).status_code == 201
    client.delete(f"/v1/admin/agents/{ag['id']}/tokens/{token_id}", headers=ADMIN)
    assert _post(client, token, _package(mean=0.9)).status_code == 401


def test_agente_inativo_403_e_last_used_at(env):
    client, _ = env
    ag, token, _ = _make_agent(client)
    with Session(client.app.state.engine) as s:
        assert s.scalar(select(AgentCredential.last_used_at)) is None
    assert _post(client, token, _package()).status_code == 201
    with Session(client.app.state.engine) as s:
        assert s.scalar(select(AgentCredential.last_used_at)) is not None
    client.patch(f"/v1/admin/agents/{ag['id']}", json={"active": False}, headers=ADMIN)
    assert _post(client, token, _package(mean=0.9)).status_code == 403


def test_token_nao_le(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    h = {"Authorization": f"Bearer {token}"}
    _post(client, token, _package())
    for path in ("/v1/reports", "/v1/reports/1", "/v1/agents/1/reports", "/v1/reports/1/download"):
        assert client.get(path, headers=h).status_code in (401, 405)  # fase 3: leitura exige sessão
    # e as rotas admin recusam o token do agente
    assert client.post("/v1/admin/areas", json={"name": "x"}, headers=h).status_code == 401


def test_campo_extra_recusado(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    body = _package()
    body["audit_log"] = [{"event": "question", "payload": {"text": "SEGREDO"}}]
    r = _post(client, token, body)
    assert r.status_code == 422 and "SEGREDO" not in r.text
    body = _package()
    body["files"]["auditoria.jsonl"] = "x"
    assert _post(client, token, body).status_code == 422
    body = _package()
    body["sha256"]["auditoria.jsonl"] = "0" * 64
    assert _post(client, token, body).status_code == 422


def test_sha256_divergente_422(env):
    client, data = env
    _, token, _ = _make_agent(client)
    body = _package()
    body["files"]["relatorio.md"] += "adulterado"
    r = _post(client, token, body)
    assert r.status_code == 422 and "relatorio.md" in r.json()["detail"]
    with Session(client.app.state.engine) as s:
        assert s.scalars(select(ReportVersion)).all() == []
    assert not data.exists() or not list(data.rglob("*.*"))


def test_semaforo_divergente_do_json_422(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    body = _package(color="green")
    body["semaphore"] = "red"
    assert _post(client, token, body).status_code == 422


def test_relatorio_json_invalido_422(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    body = _package()
    body["files"]["relatorio.json"] = "nao e json"
    body["sha256"]["relatorio.json"] = _sha("nao e json")
    assert _post(client, token, body).status_code == 422


def test_duplicado_409_nao_consome_seq(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    assert _post(client, token, _package()).status_code == 201
    assert _post(client, token, _package()).status_code == 409
    assert _post(client, token, _package(mean=0.5)).json()["seq"] == 2


def test_write_atomic_concorrente_sem_colisao_tmp(tmp_path):
    from aok_platform.reports import _write_atomic

    target = tmp_path / "relatorio.md"
    n_threads = 8
    rounds = 10
    barrier = threading.Barrier(n_threads)
    payloads = {
        (tid, rnd): f"# Relatorio {tid}-{rnd}\n".encode() * 64
        for tid in range(n_threads)
        for rnd in range(rounds)
    }

    def worker(tid: int) -> None:
        for rnd in range(rounds):
            barrier.wait(timeout=5)
            _write_atomic(target, payloads[(tid, rnd)])

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(worker, tid) for tid in range(n_threads)]
        for fut in futures:
            fut.result()

    assert target.read_bytes() in set(payloads.values())
    assert [p.name for p in tmp_path.iterdir()] == ["relatorio.md"]
    assert not list(tmp_path.glob("*.tmp"))

    bad_target = tmp_path / "pasta_existente"
    bad_target.mkdir()
    with pytest.raises(OSError):
        _write_atomic(bad_target, b"conteudo")
    assert not list(tmp_path.glob("*.tmp"))


def test_publicacao_concorrente_mesmo_pacote_201_e_409(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    db_path = tmp_path / "reports.db"
    data_dir = tmp_path / "data"
    app = create_app(f"sqlite:///{db_path}", data_dir=data_dir)
    try:
        with TestClient(app) as setup_client:
            _, token, _ = _make_agent(setup_client)
        pkg = _package()
        barrier = threading.Barrier(2)

        def publish_once() -> int:
            with TestClient(app) as client:
                barrier.wait(timeout=5)
                return _post(client, token, pkg).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(publish_once) for _ in range(2)]
            statuses = [fut.result() for fut in futures]

        assert sorted(statuses) == [201, 409]
        with Session(app.state.engine) as s:
            rows = s.scalars(select(ReportVersion)).all()
            assert len(rows) == 1
            row = rows[0]
            assert row.seq == 1
            folder = data_dir / Path(row.file_json).parent
            for name in ("relatorio.md", "relatorio.html", "relatorio.json"):
                assert (folder / name).read_bytes() == pkg["files"][name].encode("utf-8")
            meta = json.loads((folder / "pacote.json").read_text("utf-8"))
            assert meta == {
                "agent_id": "rag-demo",
                "timestamp": pkg["timestamp"],
                "semaphore": pkg["semaphore"],
                "sha256": pkg["sha256"],
            }
            assert not list(data_dir.rglob("*.tmp"))
    finally:
        app.state.engine.dispose()


def test_corpo_acima_de_1_mib_413(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    body = _package()
    body["files"]["relatorio.html"] = "x" * (1024 * 1024)
    body["sha256"]["relatorio.html"] = _sha(body["files"]["relatorio.html"])
    assert _post(client, token, body).status_code == 413


def test_report_version_imutavel_pela_orm(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    _post(client, token, _package())
    with Session(client.app.state.engine) as s:
        row = s.scalar(select(ReportVersion))
        row.status_semaforo = "red"
        with pytest.raises(RuntimeError):
            s.commit()
        s.rollback()
        s.delete(s.scalar(select(ReportVersion)))
        with pytest.raises(RuntimeError):
            s.commit()


# ---- cliente: aok check --publish URL -------------------------------------------------------


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _attack(cid, cat, success=False):
    return {
        "case_id": cid,
        "category": cat,
        "success": success,
        "blocked_by": [],
        "final_answer": "x",
        "raw_answer": "x",
    }


def _fp(cid):
    return {
        "case_id": cid,
        "blocked": False,
        "blocked_by": [],
        "reasons": [],
        "answer": "x",
        "raw_answer": "x",
        "score": 1.0,
        "error": None,
    }


@pytest.fixture
def check_argv(tmp_path):
    rt = tmp_path / "rt"
    rt.mkdir()
    _write(rt / "baseline.jsonl", [_attack("a1", "injecao_direta", True)])
    _write(rt / "guardrails.jsonl", [_attack("a1", "injecao_direta")])
    _write(rt / "fp_dataset.jsonl", [_fp("q1")])
    _write(rt / "fp_benign.jsonl", [_fp("b1")])
    return [
        "check",
        "--out",
        str(tmp_path / "pk"),
        "--dataset",
        str(ROOT / "evals/dataset.jsonl"),
        "--prompts-dir",
        str(ROOT / "evals/prompts"),
        "--answers-dir",
        str(ROOT / "evals/answers"),
        "--redteam-baseline",
        str(rt / "baseline.jsonl"),
        "--redteam-guardrails",
        str(rt / "guardrails.jsonl"),
        "--fp-dir",
        str(rt),
        "--config",
        str(CONFIG),
    ]


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _bridge(monkeypatch, client, seen):
    """Troca o opener do urllib por uma ponte para o TestClient (sem socket)."""

    class Opener:
        def open(self, req, timeout=None):
            seen.update(url=req.full_url, timeout=timeout, auth=req.get_header("Authorization"))
            r = client.post(
                "/v1/reports",
                content=req.data,
                headers={
                    "Authorization": req.get_header("Authorization"),
                    "Content-Type": "application/json",
                },
            )
            if r.status_code >= 400:
                raise urllib.error.HTTPError(
                    req.full_url, r.status_code, "x", {}, io.BytesIO(r.content)
                )
            return _Resp(r.content)

    monkeypatch.setattr(publish.urllib.request, "build_opener", lambda *a: Opener())


def test_cli_publica_na_plataforma_e_repete_409(env, monkeypatch, check_argv, capsys):
    client, _ = env
    _, token, _ = _make_agent(client, "rag-agent")
    seen = {}
    _bridge(monkeypatch, client, seen)
    monkeypatch.setenv("AOK_PLATFORM_TOKEN", token)
    argv = [*check_argv, "--publish", "http://plataforma.local/", "--agent-id", "rag-agent"]
    assert cli.main(argv) == 0
    out = capsys.readouterr()
    assert "versão 1" in out.out and token not in out.out + out.err
    assert seen["url"] == "http://plataforma.local/v1/reports" and seen["timeout"] > 0
    # mesmo pacote de novo: o servidor responde 409 e o CLI explica em português.
    # Reaproveita os arquivos já gravados (generated_at tem precisão de segundos: regerar
    # o pacote na virada do segundo mudaria o sha256 e tornaria o teste instável).
    pkg_json = Path(argv[argv.index("--out") + 1]) / "relatorio.json"
    monkeypatch.setattr(
        cli, "_write_package", lambda args: json.loads(pkg_json.read_text(encoding="utf-8"))
    )
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert "já foi publicado" in err and token not in err


def test_cli_usa_platform_agent_id_do_config(env, monkeypatch, check_argv, tmp_path, capsys):
    client, _ = env
    _, token, _ = _make_agent(client, "do-config")
    _bridge(monkeypatch, client, {})
    monkeypatch.setenv("AOK_PLATFORM_TOKEN", token)
    cfg = tmp_path / "agent.yaml"
    cfg.write_text(
        CONFIG.read_text(encoding="utf-8") + "\nplatform:\n  agent_id: do-config\n",
        encoding="utf-8",
    )
    argv = [*check_argv[:-1], str(cfg), "--publish", "https://plataforma.local"]
    assert cli.main(argv) == 0
    assert "versão 1" in capsys.readouterr().out


def test_cli_sem_token_no_ambiente(monkeypatch, check_argv, capsys):
    monkeypatch.delenv("AOK_PLATFORM_TOKEN", raising=False)
    assert cli.main([*check_argv, "--publish", "http://x.local", "--agent-id", "ag"]) == 2
    assert "AOK_PLATFORM_TOKEN" in capsys.readouterr().err


def test_cli_token_errado_401_sem_vazar_token(env, monkeypatch, check_argv, capsys):
    client, _ = env
    _make_agent(client, "ag")
    _bridge(monkeypatch, client, {})
    monkeypatch.setenv("AOK_PLATFORM_TOKEN", "TOKEN-SECRETO-ERRADO")
    assert cli.main([*check_argv, "--publish", "http://x.local", "--agent-id", "ag"]) == 2
    out = capsys.readouterr()
    assert "token recusado" in out.err and "TOKEN-SECRETO-ERRADO" not in out.out + out.err


def test_cli_servidor_inacessivel_mensagem_em_portugues(monkeypatch, check_argv, capsys):
    monkeypatch.setenv("AOK_PLATFORM_TOKEN", "t")
    argv = [*check_argv, "--publish", "http://127.0.0.1:9", "--agent-id", "ag"]
    assert cli.main(argv) == 2
    assert "não foi possível falar com a plataforma" in capsys.readouterr().err


def test_publish_remote_contra_servidor_http_real_nao_segue_redirect(tmp_path):
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append((self.path, self.headers.get("Authorization")))
            self.rfile.read(int(self.headers["Content-Length"]))  # consome o corpo inteiro
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/roubo")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pk = tmp_path / "pk"
    pk.mkdir()
    pkg = _package()
    for name, text in pkg["files"].items():
        (pk / name).write_text(text, encoding="utf-8", newline="")
    try:
        with pytest.raises(publish.PublishError) as exc:
            publish.publish_remote(pk, f"http://127.0.0.1:{srv.server_port}", "rag-demo", "tok")
    finally:
        srv.shutdown()
    assert hits == [("/v1/reports", "Bearer tok")]  # um único POST, sem seguir o redirect
    assert "HTTP 302" in str(exc.value) and "Bearer" not in str(exc.value)


def test_config_platform_agent_id_valida_e_extra_forbid(tmp_path):
    from agent_ops_kit.config import load_config

    base = CONFIG.read_text(encoding="utf-8")
    assert load_config(CONFIG).platform is None
    ok = tmp_path / "ok.yaml"
    ok.write_text(base + "\nplatform:\n  agent_id: meu-agente-1\n", encoding="utf-8")
    assert load_config(ok).platform.agent_id == "meu-agente-1"
    for extra in ("platform:\n  agent_id: Maiusculo\n", "platform:\n  agent_id: a\n  url: x\n"):
        bad = tmp_path / "bad.yaml"
        bad.write_text(base + "\n" + extra, encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(bad)


@pytest.mark.parametrize("content", ["nao e json", "{}", '{"semaphore": null}'])
def test_publish_remote_relatorio_json_sem_semaforo(tmp_path, content):
    for name in publish.FILES:
        (tmp_path / name).write_text(content if name.endswith(".json") else "x", encoding="utf-8")
    with pytest.raises(publish.PublishError, match="semáforo"):
        publish.publish_remote(tmp_path, "http://x.local", "ag", "tok")


def test_dockerignore_exclui_env_em_subpastas():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {"**/.env", "**/.env.*", "**/*.db", "**/aok_data"} <= set(lines)


def test_aceita_relatorio_com_e_sem_politica(env):
    """Relatório antigo (sem `policy`) e novo (com `policy`/`indicators`) são aceitos."""
    client, _ = env
    _, token, _ = _make_agent(client)
    assert _post(client, token, _package(mean=0.7)).status_code == 201  # sem policy
    pkg = _package(mean=0.8)
    js = json.loads(pkg["files"]["relatorio.json"])
    js["semaphore"].update(not_evaluated=[], caveats=[], rules_version="provisoria-1")
    js["policy"] = {
        "id": "default", "version": "provisoria-1", "sha256": "a" * 64,
        "path_relative": "policies/default.yaml", "rules": [],
    }
    js["indicators"] = {"audit_informed": True}
    pkg["files"]["relatorio.json"] = json.dumps(js, ensure_ascii=False)
    pkg["sha256"]["relatorio.json"] = _sha(pkg["files"]["relatorio.json"])
    assert _post(client, token, pkg).status_code == 201
