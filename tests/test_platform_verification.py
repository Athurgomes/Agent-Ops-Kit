"""Verificação de relatórios com reproducao.json (B9 / A5) com agente externo não-RAG."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

pytest.importorskip("alembic")
pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from aok_platform.app import create_app
from aok_platform.db import make_engine
from aok_platform.migrate import alembic_config, run_migrations
from aok_platform.models import AdminEvent, Base, DownloadLog, ReportVersion
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session
from test_platform_reports import ADMIN, KEY, _make_agent, _package, _post

from agent_ops_kit import cli, provenance, reproduce
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.redteam import false_positives as fp
from agent_ops_kit.redteam import harness
from agent_ops_kit.redteam.attacks import load_attacks
from agent_ops_kit.report import publish

ROOT = Path(__file__).resolve().parent.parent
VIEWER_PWD = "leitor-teste-12345"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fake_fetch(path: str) -> dict:
    if path == "/api/version":
        return {"version": "0.9.9"}
    return {"models": [{"name": "llama3.1:8b", "digest": "ext-digest-1"}]}


def _make_llm(mode: str = "oracle"):
    by_q = {c.question: c for c in load_dataset(ROOT / "evals" / "dataset.jsonl")}

    def llm(model, messages, tools=None):
        q = messages[-1]["content"]
        if mode == "blank":
            text = "resposta divergente"
        else:
            case = by_q.get(q)
            text = case.expected[0] if case and case.expected else "atendimento externo ok"
        return {"message": {"content": text}, "prompt_eval_count": 2, "eval_count": 2}

    return llm


@pytest.fixture(scope="module")
def external_package(tmp_path_factory):
    """Gera pacote + reproducao.json real usando agente externo não-RAG (target python)."""
    repo = tmp_path_factory.mktemp("ext_repo")
    (repo / "ext_billing_agent.py").write_text(
        "def support_bot(request, llm=None):\n"
        "    resp = llm('external-model', [{'role': 'user', 'content': request['question']}], [])\n"
        "    return {'answer': resp['message']['content']}\n",
        encoding="utf-8",
    )
    shutil.copytree(ROOT / "evals" / "prompts", repo / "evals" / "prompts")
    shutil.copy(ROOT / "evals" / "dataset.jsonl", repo / "evals" / "dataset.jsonl")
    shutil.copytree(ROOT / "policies", repo / "policies")
    shutil.copytree(ROOT / "redteam" / "attacks", repo / "redteam" / "attacks")
    shutil.copytree(ROOT / "redteam" / "poisoned_corpus", repo / "redteam" / "poisoned_corpus")
    (repo / "redteam" / "benign").mkdir()
    shutil.copy(ROOT / "redteam" / "benign" / "benign.jsonl", repo / "redteam" / "benign" / "benign.jsonl")

    cfg_data = {
        "name": "ext-billing-bot",
        "model": "llama3.1:8b",
        "system_prompt": "Assistente externo de cobrança.",
        "prompt_version": "v1",
        "target": {"type": "python", "ref": "ext_billing_agent:support_bot"},
    }
    (repo / "agent.yaml").write_text(yaml.safe_dump(cfg_data, allow_unicode=True), encoding="utf-8")

    old_cwd = os.getcwd()
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    sys.modules.pop("ext_billing_agent", None)
    try:
        cfg = load_config("agent.yaml")
        dataset = load_dataset("evals/dataset.jsonl")
        llm = _make_llm("oracle")
        info = {
            **provenance.execution_info(cfg.model, "aok eval", fetch=_fake_fetch),
            **provenance.target_info(cfg),
        }
        for v in ("v1", "v2"):
            recs = runner.run_variant(
                v,
                dataset,
                cfg,
                llm=llm,
                out_path=f"evals/answers/{v}.jsonl",
                limit=4,
                seed=42,
                prompts_dir="evals/prompts",
            )
            entry = runner.manifest_entry(
                v,
                cfg,
                "evals/dataset.jsonl",
                len(recs),
                42,
                "evals/prompts",
                answers_path=f"evals/answers/{v}.jsonl",
                extra=info,
            )
            runner.write_manifest_entry("evals/answers", v, entry)

        adir, pdir = Path("redteam/attacks"), Path("redteam/poisoned_corpus")
        meta = {
            **provenance.execution_info(cfg.model, "aok redteam run", fetch=_fake_fetch),
            "attacks_dir": provenance.rel_path(adir),
            "attacks_sha256": provenance.sha256_dir(adir),
            "poisoned_dir": provenance.rel_path(pdir),
            "poisoned_sha256": provenance.sha256_dir(pdir, "*.md"),
        }
        cases = load_attacks(adir, pdir)
        for name in ("baseline", "guardrails"):
            harness.run_suite(
                cases, cfg, llm=llm, out_path=f"rt/{name}.jsonl", limit=6, seed=42, poisoned_dir=pdir, meta=dict(meta)
            )
        benign = fp.load_benign("redteam/benign/benign.jsonl")
        fp.run_benign(dataset[:2], cfg, [], llm=llm, out_path="rt/fp_dataset.jsonl", seed=42)
        fp.run_benign(benign[:2], cfg, [], llm=llm, out_path="rt/fp_benign.jsonl", seed=42)
        fp.write_fp_meta(
            "rt", cfg.model, 42, [], "evals/dataset.jsonl", "redteam/benign/benign.jsonl", "fp", extra={**info}
        )
        # Pacote paralelo sem sidecars de red team para gerar veredito real `não reproduzível`
        shutil.copytree("rt", "rt_no_meta", ignore=shutil.ignore_patterns("*.meta.json"))

        common = [
            "--config", "agent.yaml",
            "--policy", "policies/default.yaml",
            "--coverage-map", "policies/coverage/owasp_llm_2025.yaml",
        ]
        assert cli.main([
            "report", "build", "--out", "pk", "--redteam-baseline", "rt/baseline.jsonl",
            "--redteam-guardrails", "rt/guardrails.jsonl", "--fp-dir", "rt", *common,
        ]) == 0
        assert cli.main([
            "report", "build", "--out", "pk_nometa", "--redteam-baseline", "rt_no_meta/baseline.jsonl",
            "--redteam-guardrails", "rt_no_meta/guardrails.jsonl", "--fp-dir", "rt_no_meta", *common,
        ]) == 0

        res_ok = reproduce.reproduce("pk", llm=llm, fetch=_fake_fetch, out="repro_ok")
        res_div = reproduce.reproduce("pk", llm=_make_llm("blank"), fetch=_fake_fetch, out="repro_div")
        res_nr = reproduce.reproduce("pk_nometa", only="redteam", llm=llm, fetch=_fake_fetch, out="repro_nr")
        yield {
            "repo": repo,
            "pk": repo / "pk",
            "repro_ok": res_ok["json"].read_text(encoding="utf-8"),
            "repro_div": res_div["json"].read_text(encoding="utf-8"),
            "repro_nr": res_nr["json"].read_text(encoding="utf-8"),
        }
    finally:
        if str(repo) in sys.path:
            sys.path.remove(str(repo))
        sys.modules.pop("ext_billing_agent", None)
        os.chdir(old_cwd)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    return TestClient(app), tmp_path / "data"


def _viewer_client(app, admin_client, area_id: int) -> TestClient:
    u = admin_client.post(
        "/v1/admin/users",
        json={"email": "leitor@x.io", "password": VIEWER_PWD},
        headers=ADMIN,
    ).json()
    admin_client.post(
        "/v1/admin/memberships",
        json={"user_id": u["id"], "role": "area_viewer", "area_id": area_id},
        headers=ADMIN,
    )
    viewer = TestClient(app)
    assert viewer.post(
        "/v1/auth/login", json={"email": "leitor@x.io", "password": VIEWER_PWD}
    ).status_code == 200
    return viewer


def _pkg_from_dir(pkg_dir: Path, agent_id: str, **extra) -> dict:
    files = {name: (pkg_dir / name).read_text(encoding="utf-8") for name in publish.FILES}
    js = json.loads(files["relatorio.json"])
    return {
        "agent_id": agent_id,
        "timestamp": "20260102T030405Z",
        "semaphore": js["semaphore"]["color"],
        "sha256": {k: _sha(v) for k, v in files.items()},
        "files": files,
        **extra,
    }


def test_padrao_sem_e_com_reproducao_externa_e_download(env, external_package):
    client, data = env
    ag, token, _ = _make_agent(client, "ext-billing-bot")
    viewer = _viewer_client(client.app, client, ag["area_id"])

    # 1) Padrão (require_verification=False) sem reproducao_json: 201, verified=False, download -> 404
    r_plain = _post(client, token, _package("ext-billing-bot"))
    assert r_plain.status_code == 201
    assert r_plain.json()["verified"] is False
    assert r_plain.json()["verification_status"] is None
    assert r_plain.json()["has_reproducao"] is False

    rep_plain = viewer.get(f"/v1/agents/{ag['id']}/reports").json()[0]
    assert (rep_plain["verified"], rep_plain["verification_status"], rep_plain["has_reproducao"]) == (
        False, None, False
    )
    assert viewer.get(f"/v1/reports/{rep_plain['id']}/download?format=reproducao").status_code == 404
    with Session(client.app.state.engine) as s:
        assert s.scalars(select(DownloadLog)).all() == []

    # 2) Publica pacote do agente externo não-RAG com reproducao.json real -> 201, verified=True
    repro_text = external_package["repro_ok"]
    body = _pkg_from_dir(external_package["pk"], "ext-billing-bot", reproducao_json=repro_text)
    r_ver = _post(client, token, body)
    assert r_ver.status_code == 201
    assert r_ver.json()["verified"] is True
    assert r_ver.json()["verification_status"] == "reproduzido"
    assert r_ver.json()["has_reproducao"] is True

    items = viewer.get(f"/v1/agents/{ag['id']}/reports").json()
    rep_ver = items[0]
    assert (rep_ver["verified"], rep_ver["verification_status"], rep_ver["has_reproducao"]) == (
        True, "reproduzido", True
    )
    det = viewer.get(f"/v1/reports/{rep_ver['id']}").json()
    assert (det["verified"], det["verification_status"], det["has_reproducao"]) == (
        True, "reproduzido", True
    )

    dl = viewer.get(f"/v1/reports/{rep_ver['id']}/download?format=reproducao")
    assert dl.status_code == 200
    assert dl.text == repro_text
    assert dl.headers["content-disposition"] == 'attachment; filename="ext-billing-bot-2.reproducao.json"'
    with Session(client.app.state.engine) as s:
        row = s.scalar(select(ReportVersion).where(ReportVersion.id == rep_ver["id"]))
        assert row.file_reproducao is not None
        assert (data / row.file_reproducao).read_text(encoding="utf-8") == repro_text
        logs = s.scalars(select(DownloadLog)).all()
        assert len(logs) == 1 and logs[0].format == "reproducao"

    # 3) Path traversal em file_reproducao é bloqueado com 404 sem gravar download
    secret = data.parent / "segredo.json"
    secret.write_text('{"segredo": true}', encoding="utf-8")
    with client.app.state.engine.begin() as conn:
        conn.execute(
            text("UPDATE report_version SET file_reproducao = '../segredo.json' WHERE id = :id"),
            {"id": rep_ver["id"]},
        )
    assert viewer.get(f"/v1/reports/{rep_ver['id']}/download?format=reproducao").status_code == 404
    with Session(client.app.state.engine) as s:
        assert len(s.scalars(select(DownloadLog)).all()) == 1


def test_padrao_aceita_divergente_e_dentro_da_variancia(env, external_package):
    client, _ = env
    _, token, _ = _make_agent(client, "ext-billing-bot")

    # Divergente real com require_verification=False -> 201, verified=False, status='divergente'
    body_div = _pkg_from_dir(
        external_package["pk"], "ext-billing-bot", reproducao_json=external_package["repro_div"]
    )
    r_div = _post(client, token, body_div)
    assert r_div.status_code == 201
    assert (r_div.json()["verified"], r_div.json()["verification_status"], r_div.json()["has_reproducao"]) == (
        False, "divergente", True
    )

    # Dentro da variância -> 201, verified=True, status='dentro da variância'
    pkg2 = _package("ext-billing-bot", mean=0.95)
    repro_within = json.loads(external_package["repro_ok"])
    repro_within["original"]["report_sha256"] = pkg2["sha256"]["relatorio.json"]
    repro_within["items"][0]["verdict"] = reproduce.WITHIN
    repro_within["verdict_counts"] = {
        v: sum(i["verdict"] == v for i in repro_within["items"]) for v in reproduce.VERDICTS
    }
    pkg2["reproducao_json"] = json.dumps(repro_within)
    r_within = _post(client, token, pkg2)
    assert r_within.status_code == 201
    assert (r_within.json()["verified"], r_within.json()["verification_status"]) == (
        True, "dentro da variância"
    )


def test_require_verification_recusas_e_aceite(env, external_package):
    client, _ = env
    ag, token, _ = _make_agent(client, "ext-billing-bot")
    r_patch = client.patch(
        f"/v1/admin/agents/{ag['id']}", json={"require_verification": True}, headers=ADMIN
    )
    assert r_patch.status_code == 200 and r_patch.json()["require_verification"] is True

    # 1) Ausente -> 422
    r_miss = _post(client, token, _package("ext-billing-bot"))
    assert r_miss.status_code == 422 and "reproducao.json" in r_miss.json()["detail"]

    # 2) Outro pacote / hash divergente -> 422
    other_pkg = _package("ext-billing-bot", mean=0.55)
    other_pkg["reproducao_json"] = external_package["repro_ok"]
    r_hash = _post(client, token, other_pkg)
    assert r_hash.status_code == 422 and "sha256" in r_hash.json()["detail"]

    # 3) Veredito divergente -> 422
    body_div = _pkg_from_dir(
        external_package["pk"], "ext-billing-bot", reproducao_json=external_package["repro_div"]
    )
    r_div = _post(client, token, body_div)
    assert r_div.status_code == 422 and "divergente" in r_div.json()["detail"]

    # 4) Veredito não reproduzível -> 422
    repro_nr = json.loads(external_package["repro_nr"])
    assert repro_nr["verdict_counts"][reproduce.NOT_REPRODUCIBLE] > 0
    # Usa um pacote novo compatível com pk_nometa via _pkg_from_dir
    nometa_dir = external_package["repo"] / "pk_nometa"
    body_nr = _pkg_from_dir(nometa_dir, "ext-billing-bot", reproducao_json=external_package["repro_nr"])
    r_nr = _post(client, token, body_nr)
    assert r_nr.status_code == 422 and "não reproduzível" in r_nr.json()["detail"]

    # 5) JSON inválido / esquema adulterado -> 422
    for bad in ("{invalido", "[]", json.dumps({"schema_version": 1})):
        bad_pkg = _package("ext-billing-bot")
        bad_pkg["reproducao_json"] = bad
        assert _post(client, token, bad_pkg).status_code == 422

    # 6) Válido -> 201, verified=True
    body_ok = _pkg_from_dir(
        external_package["pk"], "ext-billing-bot", reproducao_json=external_package["repro_ok"]
    )
    r_ok = _post(client, token, body_ok)
    assert r_ok.status_code == 201 and r_ok.json()["verified"] is True


def test_admin_agent_require_verification_e_admin_event(env):
    client, _ = env
    area = client.post("/v1/admin/areas", json={"name": "Verif"}, headers=ADMIN).json()
    created = client.post(
        "/v1/admin/agents",
        json={"area_id": area["id"], "slug": "bot-v", "name": "Bot V", "require_verification": True},
        headers=ADMIN,
    )
    assert created.status_code == 201 and created.json()["require_verification"] is True

    listed = client.get("/v1/admin/agents", headers=ADMIN).json()
    assert listed[0]["require_verification"] is True

    p1 = client.patch(
        f"/v1/admin/agents/{created.json()['id']}", json={"require_verification": False}, headers=ADMIN
    )
    assert p1.status_code == 200 and p1.json()["require_verification"] is False
    p2 = client.patch(
        f"/v1/admin/agents/{created.json()['id']}", json={"require_verification": True}, headers=ADMIN
    )
    assert p2.status_code == 200 and p2.json()["require_verification"] is True

    with Session(client.app.state.engine) as s:
        actions = list(
            s.scalars(
                select(AdminEvent.action)
                .where(
                    AdminEvent.target_type == "agent",
                    AdminEvent.target_id == created.json()["id"],
                )
                .order_by(AdminEvent.id)
            )
        )
        assert actions == ["agent.create", "agent.require_verification", "agent.require_verification"]


def test_cli_publish_remote_e_check_com_reproducao(env, monkeypatch, tmp_path, external_package):
    client, _ = env
    ag, token, _ = _make_agent(client, "ext-billing-bot")
    client.patch(f"/v1/admin/agents/{ag['id']}", json={"require_verification": True}, headers=ADMIN)
    sent_bodies = []

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()

    class _Opener:
        def open(self, req, timeout=None):
            sent_bodies.append(json.loads(req.data))
            r = client.post(
                "/v1/reports",
                content=req.data,
                headers={
                    "Authorization": req.get_header("Authorization"),
                    "Content-Type": "application/json",
                },
            )
            if r.status_code >= 400:
                raise urllib.error.HTTPError(req.full_url, r.status_code, "x", {}, io.BytesIO(r.content))
            return _Resp(r.content)

    monkeypatch.setattr(publish.urllib.request, "build_opener", lambda *a: _Opener())

    pk = tmp_path / "pk"
    shutil.copytree(external_package["pk"], pk)

    # 1) publish_remote sem reproducao.json não envia campo extra e servidor recusa (422)
    with pytest.raises(publish.PublishError, match="reproducao.json"):
        publish.publish_remote(pk, "http://plataforma.local", "ext-billing-bot", token)
    assert "reproducao_json" not in sent_bodies[-1]

    # 2) --reproducao inexistente falha cedo (exit 2)
    monkeypatch.setenv("AOK_PLATFORM_TOKEN", token)
    assert cli.main([
        "check", "--out", str(pk), "--config", str(external_package["repo"] / "agent.yaml"),
        "--publish", "http://plataforma.local", "--agent-id", "ext-billing-bot",
        "--reproducao", str(tmp_path / "nao_existe.json"),
    ]) == 2

    # 3) Via `aok check --publish URL --reproducao <arquivo>` (mantendo relatorio.json original)
    repro_path = external_package["repo"] / "repro_ok" / "reproducao.json"
    monkeypatch.setattr(
        cli, "_write_package", lambda _args: json.loads((pk / "relatorio.json").read_text(encoding="utf-8"))
    )
    rc = cli.main([
        "check", "--out", str(pk), "--config", str(external_package["repo"] / "agent.yaml"),
        "--publish", "http://plataforma.local", "--agent-id", "ext-billing-bot",
        "--reproducao", str(repro_path),
    ])
    assert rc == 0 and "reproducao_json" in sent_bodies[-1]

    # 4) publish_remote detecta reproducao.json quando presente dentro da pasta do pacote
    shutil.copyfile(repro_path, pk / publish.REPRO_FILE)
    with pytest.raises(publish.PublishError, match="já foi publicado"):  # 409 prova que passou na validação!
        publish.publish_remote(pk, "http://plataforma.local", "ext-billing-bot", token)


def test_migracao_0004_upgrade_idempotente_e_downgrade_para_0003(tmp_path):
    url = f"sqlite:///{tmp_path / 'verif.db'}"
    engine = make_engine(url)
    try:
        run_migrations(engine, revision="0003_report_signature")
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO organization (id, name, slug, active, created_at) "
                "VALUES (1, 'Org', 'org', 1, '2026-01-01')"
            ))
            conn.execute(text("INSERT INTO area (id, org_id, name) VALUES (1, 1, 'Area')"))
            conn.execute(text(
                "INSERT INTO agent (id, org_id, area_id, slug, name, active, require_signature) "
                "VALUES (1, 1, 1, 'ag', 'Ag', 1, 0)"
            ))

        run_migrations(engine)
        run_migrations(engine)  # idempotente
        with engine.connect() as conn:
            revs = [r[0] for r in conn.execute(text("SELECT version_num FROM alembic_version"))]
            assert revs == ["0004_report_verification"]
            assert conn.execute(text("SELECT require_verification FROM agent")).scalar() in (0, False)
            mc = MigrationContext.configure(
                conn, opts={"compare_type": True, "render_as_batch": True}
            )
            assert compare_metadata(mc, Base.metadata) == []

        cfg = alembic_config(url)
        with engine.connect() as conn:
            cfg.attributes["connection"] = conn
            command.downgrade(cfg, "0003_report_signature")

        insp = inspect(engine)
        assert "require_verification" not in {c["name"] for c in insp.get_columns("agent")}
        assert {"verified", "verification_status", "file_reproducao"}.isdisjoint(
            {c["name"] for c in insp.get_columns("report_version")}
        )
        fmt_col = next(c for c in insp.get_columns("download_log") if c["name"] == "format")
        assert fmt_col["type"].length == 4
    finally:
        engine.dispose()
