"""B6: Seção 'O que foi e não foi testado', custo para o cliente e verificação offline."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import yaml

from agent_ops_kit import cli, provenance
from agent_ops_kit.audit import AuditLog
from agent_ops_kit.redteam.harness import OWASP_CATEGORIES
from agent_ops_kit.report import build, render, verify

SRC = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"\b(seguro|segura|robust[oa]s?|eficaz(es)?)\b", re.IGNORECASE)

_SUPPORT_AGENT_CODE = '''\
"""Agente externo de triagem de suporte (não é o RAG)."""


def handle(request: dict):
    q = str(request.get("question", "")).lower()
    if "ticket" in q or "chamado" in q or "pedido" in q:
        return {
            "answer": "Chamado #4021 consultado: status em andamento.",
            "tool_calls": [{"name": "lookup_ticket", "arguments": {"id": "4021"}}],
        }
    return {
        "answer": "Posso ajudar apenas com acompanhamento de chamados de suporte.",
        "tool_calls": [],
    }
'''


@contextmanager
def _cd(path: Path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )


def _setup_support_repo(
    tmp_path: Path,
    monkeypatch,
    *,
    profile: dict | None,
    with_eval_files: bool = False,
) -> Path:
    repo = tmp_path / "support_repo"
    repo.mkdir()
    (repo / "support_agent.py").write_text(_SUPPORT_AGENT_CODE, encoding="utf-8")
    shutil.copytree(SRC / "policies", repo / "policies")

    cfg: dict = {
        "name": "suporte-externo",
        "model": "suporte-modelo-v1",
        "prompt_version": "externo-v1",
        "system_prompt": "Agente externo de suporte ao cliente.",
        "target": {"type": "python", "ref": "support_agent:handle"},
    }
    if profile is not None:
        cfg["profile"] = profile
    (repo / "agent.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    if with_eval_files:
        (repo / "evals" / "prompts").mkdir(parents=True)
        (repo / "evals" / "prompts" / "v1.md").write_text("Prompt v1 suporte", encoding="utf-8")
        (repo / "evals" / "prompts" / "v2.md").write_text("Prompt v2 suporte", encoding="utf-8")
        _write_jsonl(
            repo / "evals" / "dataset.jsonl",
            [
                {
                    "id": "sup-1",
                    "question": "Qual o status do meu chamado?",
                    "answerable": True,
                    "expected": ["4021"],
                    "sources": [],
                    "category": "factual",
                },
                {
                    "id": "sup-2",
                    "question": "Pode verificar o pedido?",
                    "answerable": True,
                    "expected": ["4021"],
                    "sources": [],
                    "category": "factual",
                },
            ],
        )

    monkeypatch.delitem(sys.modules, "support_agent", raising=False)
    monkeypatch.syspath_prepend(str(repo))
    monkeypatch.setattr(provenance, "ollama_info", lambda *_a, **_k: {})
    return repo


def _setup_fp_files(repo: Path, n_dataset: int = 2, n_benign: int = 2) -> None:
    rt = repo / "rt"
    rt.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        rt / "fp_dataset.jsonl",
        [
            {"case_id": f"q{i}", "blocked": False, "blocked_by": [], "reasons": [], "error": None}
            for i in range(n_dataset)
        ],
    )
    _write_jsonl(
        rt / "fp_benign.jsonl",
        [
            {"case_id": f"b{i}", "blocked": False, "blocked_by": [], "reasons": [], "error": None}
            for i in range(n_benign)
        ],
    )
    meta = {
        "seed": 42,
        "model": "suporte-modelo-v1",
        "target": {
            "type": "python",
            "ref": "support_agent:handle",
            "seed_controlled_by_kit": False,
            "note": "semente não controlada pelo kit",
        },
    }
    (rt / "fp.meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


# --- Fluxo ponta a ponta com agente externo (não-RAG) --------------------------------------


def test_external_non_rag_universal_no_eval_e2e_and_verify(tmp_path, monkeypatch, capsys):
    repo = _setup_support_repo(
        tmp_path,
        monkeypatch,
        profile={
            "role": "Triagem de chamados de suporte",
            "declared_tools": ["lookup_ticket"],
        },
    )
    _setup_fp_files(repo, n_dataset=2, n_benign=2)

    with _cd(repo):
        rc_rt = cli.main([
            "redteam",
            "run",
            "--universal",
            "--config",
            "agent.yaml",
            "--out",
            "rt/univ.jsonl",
        ])
    assert rc_rt == 0
    capsys.readouterr()

    univ_meta = json.loads((repo / "rt" / "univ.jsonl.meta.json").read_text(encoding="utf-8"))
    n_rt_attacks = univ_meta["n_total_attacks"]
    assert n_rt_attacks > 0
    skipped_meta = {s["category"]: s["reason"] for s in univ_meta["skipped_categories"]}
    assert set(skipped_meta) == {"vazamento_dados", "desvio_de_escopo"}

    # Target externo sem guardrails: baseline e guardrails apontam para o mesmo arquivo
    with _cd(repo):
        rc_build = cli.main([
            "report",
            "build",
            "--no-eval",
            "--config",
            "agent.yaml",
            "--redteam-baseline",
            "rt/univ.jsonl",
            "--redteam-guardrails",
            "rt/univ.jsonl",
            "--fp-dir",
            "rt",
            "--policy",
            "policies/default.yaml",
            "--coverage-map",
            "policies/coverage/owasp_llm_2025.yaml",
            "--out",
            "pk",
        ])
    assert rc_build == 0
    capsys.readouterr()

    pkg = repo / "pk"
    data = json.loads((pkg / "relatorio.json").read_text(encoding="utf-8"))
    ts = data["test_scope"]

    dims = {d["dimension"]: d for d in ts["dimensions"]}
    assert list(dims) == ["qualidade_funcional", "falsos_positivos", "auditoria"]
    assert dims["qualidade_funcional"] == {
        "dimension": "qualidade_funcional",
        "label": "Qualidade funcional",
        "status": "não testado",
        "n_cases": 0,
        "n_runs": 0,
        "reason": "dataset funcional não fornecido",
    }
    assert dims["falsos_positivos"]["status"] == "testado"
    assert dims["falsos_positivos"]["n"] == 4
    assert dims["auditoria"]["status"] == "não testado"
    assert dims["auditoria"]["reason"] == "log de auditoria não fornecido"

    cats = {c["category"]: c for c in ts["security_categories"]}
    assert list(cats) == list(OWASP_CATEGORIES)
    assert cats["injecao_direta"]["status"] == "testado"
    assert cats["injecao_direta"]["n_baseline"] > 0
    assert cats["abuso_de_tools"]["status"] == "testado"
    for skipped_cat, expected_reason in skipped_meta.items():
        assert cats[skipped_cat]["status"] == "não testado"
        assert cats[skipped_cat]["reason"] == expected_reason
    assert cats["ofuscacao"]["status"] == "não testado"
    assert cats["ofuscacao"]["reason"] == "nenhum ataque desta categoria na execução"

    cost = ts["client_cost"]
    assert cost["eval_calls"] == 0
    assert cost["redteam_calls"] == n_rt_attacks  # sem contagem dupla!
    assert cost["fp_calls"] == 4
    assert cost["total_calls"] == n_rt_attacks + 4
    assert cost["input_tokens"] is None
    assert cost["output_tokens"] is None
    assert cost["tokens_reported"] is False
    assert "não informados pelo alvo" in cost["note"]

    for fname in ("relatorio.md", "relatorio.html"):
        text = (pkg / fname).read_text(encoding="utf-8")
        assert "O que foi e não foi testado" in text
        assert "Custo para o cliente" in text
        assert "não informados pelo alvo" in text
        assert "None" not in text
        assert "B6" not in text
        assert not BANNED.search(text), f"Palavra banida em {fname}: {BANNED.search(text)}"

    # Verificação offline passa
    with _cd(repo):
        assert cli.main(["report", "verify", "pk", "--repo-root", "."]) == 0
    out = capsys.readouterr().out
    assert "ÍNTEGRO" in out
    res = verify.verify_package(pkg, repo)
    assert {c["id"]: c["status"] for c in res["checks"]}["test_scope"] == "ok"

    # Adulterar chamadas, tokens ou status em test_scope deve reprovar no verify offline
    def _tamper_calls(d):
        d["test_scope"]["client_cost"]["redteam_calls"] = 999

    def _tamper_tokens(d):
        d["test_scope"]["client_cost"]["input_tokens"] = 123
        d["test_scope"]["client_cost"]["tokens_reported"] = True

    def _tamper_status(d):
        for cat in d["test_scope"]["security_categories"]:
            if cat["category"] == "vazamento_dados":
                cat["status"] = "testado"
                cat["reason"] = None

    def _tamper_dim_status(d):
        d["test_scope"]["dimensions"][0]["status"] = "testado"

    for idx, mutator in enumerate((_tamper_calls, _tamper_tokens, _tamper_status, _tamper_dim_status)):
        tampered = repo / f"pk_bad_{idx}"
        shutil.copytree(pkg, tampered)
        p = tampered / "relatorio.json"
        doc = json.loads(p.read_text(encoding="utf-8"))
        mutator(doc)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        res_bad = verify.verify_package(tampered, repo)
        assert not res_bad["ok"]
        assert {c["id"]: c["status"] for c in res_bad["checks"]}["test_scope"] == "falha"
        assert cli.main(["report", "verify", str(tampered), "--repo-root", str(repo)]) == 1
        capsys.readouterr()


# --- Eval com tokens informados + auditoria + retrocompatibilidade --------------------------


def test_eval_with_reported_tokens_and_audit_and_distinct_redteam(tmp_path, monkeypatch, capsys):
    repo = _setup_support_repo(
        tmp_path,
        monkeypatch,
        profile={
            "role": "Triagem de chamados",
            "allowed_scope": ["status de chamados"],
            "forbidden_scope": ["dados financeiros"],
            "sensitive_data": ["CPF"],
            "forbidden_actions": ["cancelar conta"],
            "declared_tools": ["lookup_ticket"],
        },
        with_eval_files=True,
    )
    _setup_fp_files(repo, n_dataset=2, n_benign=1)

    with _cd(repo):
        assert cli.main([
            "eval",
            "--baseline",
            "v1",
            "--candidate",
            "v2",
            "--config",
            "agent.yaml",
            "--dataset",
            "evals/dataset.jsonl",
            "--prompts-dir",
            "evals/prompts",
            "--answers-dir",
            "evals/answers",
        ]) == 0
    capsys.readouterr()

    # Simula registros de eval onde o alvo informou tokens (ex. alvo local/integrado)
    answers_dir = repo / "evals" / "answers"
    token_totals = {"v1": [(100, 20), (150, 30)], "v2": [(110, 25), (140, 35)]}
    for variant, pairs in token_totals.items():
        path = answers_dir / f"{variant}.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row, (t_in, t_out) in zip(rows, pairs, strict=True):
            row["input_tokens"] = t_in
            row["output_tokens"] = t_out
        _write_jsonl(path, rows)

    manifest = json.loads((answers_dir / "manifest.json").read_text(encoding="utf-8"))
    for variant in ("v1", "v2"):
        manifest[variant]["answers_sha256"] = provenance.sha256_file(answers_dir / f"{variant}.jsonl")
    (answers_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Duas execuções distintas de red team (hashes diferentes -> soma baseline + guardrails)
    rt = repo / "rt"
    _write_jsonl(
        rt / "baseline.jsonl",
        [
            {"case_id": "a1", "category": "injecao_direta", "success": True, "blocked_by": []},
            {"case_id": "a2", "category": "categoria_customizada", "success": False, "blocked_by": []},
        ],
    )
    _write_jsonl(
        rt / "guardrails.jsonl",
        [
            {"case_id": "a1", "category": "injecao_direta", "success": False, "blocked_by": ["input"]},
            {"case_id": "a2", "category": "categoria_customizada", "success": False, "blocked_by": []},
        ],
    )
    log = repo / "audit" / "a.jsonl"
    al = AuditLog(log)
    al.append("question", {"id": "1"})
    al.append("answer", {"id": "1"})
    al.append("answer", {"id": "2"})

    with _cd(repo):
        assert cli.main([
            "report",
            "build",
            "--config",
            "agent.yaml",
            "--dataset",
            "evals/dataset.jsonl",
            "--prompts-dir",
            "evals/prompts",
            "--answers-dir",
            "evals/answers",
            "--redteam-baseline",
            "rt/baseline.jsonl",
            "--redteam-guardrails",
            "rt/guardrails.jsonl",
            "--fp-dir",
            "rt",
            "--audit",
            "audit/a.jsonl",
            "--policy",
            "policies/default.yaml",
            "--coverage-map",
            "policies/coverage/owasp_llm_2025.yaml",
            "--out",
            "pk_eval",
        ]) == 0
    capsys.readouterr()

    pkg = repo / "pk_eval"
    data = json.loads((pkg / "relatorio.json").read_text(encoding="utf-8"))
    ts = data["test_scope"]
    dims = {d["dimension"]: d for d in ts["dimensions"]}
    assert dims["qualidade_funcional"]["status"] == "testado"
    assert dims["qualidade_funcional"]["n_cases"] == 2
    assert dims["qualidade_funcional"]["n_runs"] == 1
    assert dims["falsos_positivos"]["status"] == "testado"
    assert dims["falsos_positivos"]["n"] == 3
    assert dims["auditoria"]["status"] == "testado"
    assert dims["auditoria"]["n_events"] == 3

    cats = {c["category"]: c for c in ts["security_categories"]}
    assert "categoria_customizada" in cats
    assert cats["categoria_customizada"]["status"] == "testado"
    assert cats["categoria_customizada"]["n_baseline"] == 1
    assert cats["categoria_customizada"]["n_guardrails"] == 1

    cost = ts["client_cost"]
    assert cost["eval_calls"] == 4
    assert cost["redteam_calls"] == 4  # hashes distintos -> 2 + 2
    assert cost["fp_calls"] == 3
    assert cost["total_calls"] == 11
    assert cost["input_tokens"] == 500
    assert cost["output_tokens"] == 110
    assert cost["tokens_reported"] is True

    md = (pkg / "relatorio.md").read_text(encoding="utf-8")
    html = (pkg / "relatorio.html").read_text(encoding="utf-8")
    assert "500" in md and "110" in md and "11" in md
    assert "500" in html and "110" in html and "11" in html
    assert "não informados pelo alvo" not in md

    assert cli.main(["report", "verify", str(pkg), "--repo-root", str(repo)]) == 0
    capsys.readouterr()

    # Retrocompatibilidade: pacote antigo sem test_scope continua verificável e renderiza aviso
    old_pkg = repo / "pk_old"
    shutil.copytree(pkg, old_pkg)
    old_data = json.loads((old_pkg / "relatorio.json").read_text(encoding="utf-8"))
    old_data.pop("test_scope")
    (old_pkg / "relatorio.json").write_text(
        json.dumps(old_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    blocks = render.build_blocks(old_data)
    (old_pkg / "relatorio.md").write_text(render.to_markdown(blocks), encoding="utf-8")
    title = f"Relatório de teste do agente {old_data['agent']['name']}"
    (old_pkg / "relatorio.html").write_text(render.to_html(blocks, title), encoding="utf-8")

    res_old = verify.verify_package(old_pkg, repo)
    assert res_old["ok"] is True
    assert "test_scope" not in {c["id"] for c in res_old["checks"]}
    assert "pacote anterior a este controle" in (old_pkg / "relatorio.md").read_text(encoding="utf-8")


def test_test_scope_summary_edge_cases_and_escaping():
    ev = dict(build.EVAL_NOT_EVALUATED)
    rt = {
        "asr": {
            "baseline": {"total": {"n": 1, "not_evaluated": 0}},
            "guardrails": {"total": {"n": 1, "not_evaluated": 0}},
        },
        "false_positives": {"dataset": {"n": 0}, "benign": {"n": 0}},
    }
    ts = build.test_scope_summary(
        ev,
        rt,
        None,
        profile={
            "declared": False,
            "fields": {},
            "checks": [],
        },
        hashes={"redteam_baseline": "abc", "redteam_guardrails": "abc"},
        files={"redteam_baseline": "rt/b.jsonl", "redteam_guardrails": "rt/g.jsonl"},
        executions={
            "redteam": {
                "baseline": {"skipped_categories": [{"category": "cat<script>", "reason": "motivo|a&b"}]},
                "guardrails": {},
            }
        },
    )
    dims = {d["dimension"]: d for d in ts["dimensions"]}
    assert dims["falsos_positivos"]["status"] == "não testado"
    assert dims["falsos_positivos"]["n"] == 0
    cats = {c["category"]: c for c in ts["security_categories"]}
    assert cats["vazamento_dados"]["reason"] == "perfil não declarado no agent.yaml"
    assert cats["cat<script>"]["status"] == "não testado"
    assert cats["cat<script>"]["reason"] == "motivo|a&b"
    assert ts["client_cost"]["redteam_calls"] == 1  # mesmo hash evitou contagem dupla
    assert ts["client_cost"]["fp_calls"] == 0

    fake_doc = {
        "schema_version": 1,
        "generated_at": "2026-11-23T12:00:00-03:00",
        "agent": {"name": "a", "prompt_version": "v1", "model": "m"},
        "semaphore": {"color": "yellow", "triggered": [], "rules_version": "provisoria-1"},
        "policy": None,
        "indicators": {},
        "eval": ev,
        "redteam": {
            **rt,
            "n_attacks": 1,
            "n_legit_questions": 0,
            "runs_per_config": 1,
            "asr": {
                "baseline": {"total": {"n": 1, "successes": 0, "asr": 0.0, "ci95_low": 0.0, "ci95_high": 1.0, "errors": 0}},
                "guardrails": {"total": {"n": 1, "successes": 0, "asr": 0.0, "ci95_low": 0.0, "ci95_high": 1.0, "errors": 0}},
            },
            "false_positives": {
                "dataset": {"n": 0, "blocked": 0, "rate": 0.0, "ci95_low": 0.0, "ci95_high": 1.0, "errors": 0},
                "benign": {"n": 0, "blocked": 0, "rate": 0.0, "ci95_low": 0.0, "ci95_high": 1.0, "errors": 0},
            },
            "mcnemar": None,
        },
        "audit": None,
        "hashes": {},
        "findings": [],
        "coverage": None,
        "test_scope": ts,
        "provenance": None,
        "previous": None,
        "limitations": [],
    }
    blocks = render.build_blocks(fake_doc)
    html = render.to_html(blocks, "t")
    md = render.to_markdown(blocks)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "motivo\\|a&b" in md
