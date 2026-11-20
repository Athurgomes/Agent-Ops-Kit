"""Proveniência do relatório: campos, adulteração, compatibilidade e git ausente (sem Ollama)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_ops_kit import provenance
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.redteam import false_positives, harness
from agent_ops_kit.redteam.report import ReportError
from agent_ops_kit.report import build, render

ROOT = Path(__file__).resolve().parent.parent
EXEC = {
    "kit_version": "9.9.9", "git_commit": "abc123", "git_dirty": False, "python": "3.11.0",
    "platform": "TestOS", "ollama_version": "0.1.2", "model_digest": "sha256:deadbeef",
    "command": "aok eval --baseline v1 --candidate v2",
}
ATTACK = {
    "id": "a1", "category": "exfiltracao", "description": "d", "user_input": "u",
    "success": {"type": "canary_in_output"},
}


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _attack(cid, success=False):
    return {"case_id": cid, "category": "exfiltracao", "success": success, "blocked_by": []}


def _fp(cid):
    return {"case_id": cid, "blocked": False, "blocked_by": [], "reasons": [], "answer": "x",
            "raw_answer": "x", "score": 1.0, "error": None}


@pytest.fixture
def work(tmp_path, monkeypatch):
    """Diretório de trabalho com cópia do eval gravado e resultados de red team sintéticos."""
    monkeypatch.chdir(tmp_path)
    shutil.copytree(ROOT / "evals" / "prompts", "prompts")
    shutil.copytree(ROOT / "evals" / "answers", "answers")
    shutil.copy(ROOT / "evals" / "dataset.jsonl", "dataset.jsonl")
    shutil.copy(ROOT / "examples" / "rag_agent" / "agent.yaml", "agent.yaml")
    _jsonl(Path("suite/attacks.jsonl"), [ATTACK])
    Path("poisoned").mkdir()
    Path("poisoned/p1.md").write_text("documento envenenado\n", encoding="utf-8")
    _jsonl(Path("rt/baseline.jsonl"), [_attack("a1", True)])
    _jsonl(Path("rt/guardrails.jsonl"), [_attack("a1")])
    _jsonl(Path("rt/fp_dataset.jsonl"), [_fp("q1")])
    _jsonl(Path("rt/fp_benign.jsonl"), [_fp("b1")])
    _jsonl(Path("benign.jsonl"), [{"id": "b1"}])
    return tmp_path


def _args(**kw):
    base = {
        "config": "agent.yaml", "dataset": "dataset.jsonl", "prompts_dir": "prompts",
        "answers_dir": "answers", "baseline": "v1", "candidate": "v2", "seed": 42,
        "redteam_baseline": "rt/baseline.jsonl", "redteam_guardrails": "rt/guardrails.jsonl",
        "fp_dir": "rt", "command": "aok report build",
    }
    return {**base, **kw}


def _with_new_manifest(extra=EXEC):
    cfg = load_config("agent.yaml")
    for v in ("v1", "v2"):
        entry = runner.manifest_entry(
            v, cfg, "dataset.jsonl", 50, 42, "prompts", answers_path=f"answers/{v}.jsonl", extra=extra
        )
        runner.write_manifest_entry("answers", v, entry)


def _with_sidecars():
    for name, guard in (("baseline", None), ("guardrails", ["input_filter"])):
        recs = harness.load_records(f"rt/{name}.jsonl")
        extra = {
            **EXEC, "attacks_dir": "suite", "attacks_sha256": provenance.sha256_dir("suite"),
            "poisoned_dir": "poisoned", "poisoned_sha256": provenance.sha256_dir("poisoned", "*.md"),
        }
        harness._write_meta(f"rt/{name}.jsonl", recs, None, guard, "llama3.1:8b", 42, extra)
    false_positives.write_fp_meta(
        "rt", "llama3.1:8b", 42, ["input_filter"], "dataset.jsonl", "benign.jsonl", "cmd", EXEC
    )


def _flip_byte(path):
    p = Path(path)
    p.write_text(p.read_text(encoding="utf-8") + "x", encoding="utf-8")


def test_provenance_fields_present(work):
    _with_new_manifest()
    _with_sidecars()
    prov = build.build_data(**_args())["provenance"]
    for key in ("kit_version", "git_commit", "git_dirty", "python", "platform", "model",
                "model_digest", "ollama_version", "command", "seeds", "executions", "inputs"):
        assert key in prov
    assert prov["model"] == "llama3.1:8b"
    assert prov["model_digest"] == "sha256:deadbeef" and prov["ollama_version"] == "0.1.2"
    assert prov["command"] == "aok report build"
    assert prov["seeds"]["eval_ab_bootstrap"] == 42
    assert prov["seeds"]["eval_generation"] == {"v1": 42, "v2": 42}
    assert prov["seeds"]["redteam"] == {"baseline": 42, "guardrails": 42}
    assert prov["executions"]["eval"]["v1"]["answers_sha256"] == provenance.sha256_file("answers/v1.jsonl")
    assert prov["executions"]["redteam"]["guardrails"]["guardrails_enabled"] is True
    assert prov["executions"]["redteam"]["baseline"]["guardrails_enabled"] is False
    inputs = prov["inputs"]
    for key in ("agent.yaml", "dataset.jsonl", "prompts/v1.md", "prompts/v2.md", "answers/v1.jsonl",
                "suite/attacks.jsonl", "poisoned/p1.md", "rt/baseline.jsonl", "benign.jsonl"):
        assert len(inputs[key]) == 64
    assert not any(k.startswith(("/", "C:")) for k in inputs)


def test_render_has_provenance_section(work):
    _with_new_manifest()
    _with_sidecars()
    data = build.build_data(**_args())
    text = render.to_markdown(render.build_blocks(data))
    assert "A.7 Proveniência da execução" in text and "sha256:deadbeef" in text
    assert "suite/attacks.jsonl" in text


@pytest.mark.parametrize("target", ["answers/v2.jsonl", "prompts/v1.md", "suite/attacks.jsonl",
                                    "poisoned/p1.md", "rt/guardrails.jsonl", "rt/fp_benign.jsonl", "benign.jsonl"])
def test_tampering_fails_build(work, target):
    _with_new_manifest()
    _with_sidecars()
    build.build_data(**_args())  # sem adulteração passa
    _flip_byte(target)
    with pytest.raises(ReportError):
        build.build_data(**_args())


def test_old_manifest_and_no_sidecar_still_build(work):
    prov = build.build_data(**_args())["provenance"]
    assert prov["model_digest"] is None and prov["ollama_version"] is None
    assert prov["executions"]["eval"]["v1"]["answers_sha256"] is None
    assert prov["executions"]["redteam"]["baseline"] is None
    assert prov["executions"]["redteam"]["false_positives"] is None
    assert prov["seeds"]["redteam"] == {"baseline": None, "guardrails": None}
    text = render.to_markdown(render.build_blocks({"provenance": prov, **_minimal(work)}))
    assert "não registrado" in text


def _minimal(work):
    data = build.build_data(**_args())
    return {k: v for k, v in data.items() if k != "provenance"}


@pytest.mark.parametrize(
    ("folder", "dataset"),
    [("answers", "dataset.jsonl"), ("answers_multirun", "dataset.jsonl"),
     ("answers_audit_200", "dataset_audit_200.jsonl")],
)
def test_versioned_manifests_still_verify(folder, dataset):
    cfg = load_config(ROOT / "examples" / "rag_agent" / "agent.yaml")
    runner.verify_manifest(
        ROOT / "evals" / folder, ["v1", "v2"], cfg, ROOT / "evals" / dataset, ROOT / "evals" / "prompts"
    )


def test_manifest_answers_sha_mismatch_raises(work):
    _with_new_manifest()
    cfg = load_config("agent.yaml")
    runner.verify_manifest("answers", ["v1", "v2"], cfg, "dataset.jsonl", "prompts")
    _flip_byte("answers/v1.jsonl")
    with pytest.raises(runner.ManifestError, match="sha256 diverge"):
        runner.verify_manifest("answers", ["v1", "v2"], cfg, "dataset.jsonl", "prompts")


def test_no_git_does_not_break(work, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert provenance.git_info() == (None, None)
    prov = build.build_data(**_args())["provenance"]
    assert prov["git_commit"] is None and prov["git_dirty"] is None
    text = render.to_markdown(render.build_blocks({**_minimal(work), "provenance": prov}))
    assert "não disponível" in text


def test_git_timeout_is_null(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired("git", 5)

    monkeypatch.setattr(subprocess, "run", slow)
    assert provenance.git_info() == (None, None)


def test_ollama_info_with_fake_client_and_failure():
    def fetch(path):
        if path == "/api/version":
            return {"version": "0.5.1"}
        return {"models": [{"name": "other:1b", "digest": "x"},
                           {"name": "llama3.1:8b", "digest": "sha256:abc"}]}

    assert provenance.ollama_info("llama3.1:8b", fetch) == {
        "ollama_version": "0.5.1", "model_digest": "sha256:abc"}

    def down(path):
        raise ConnectionRefusedError("sem ollama")

    assert provenance.ollama_info("llama3.1:8b", down) == {
        "ollama_version": None, "model_digest": None}


def test_run_suite_always_writes_sidecar(tmp_path):
    case = harness.AttackCase.model_validate(ATTACK)
    cfg = load_config(ROOT / "examples" / "rag_agent" / "agent.yaml")
    out = tmp_path / "r.jsonl"
    llm = lambda m, msgs, t: {"message": {"content": "ok"}}
    harness.run_suite([case], cfg, llm, out_path=out, seed=7, meta={"command": "cmd"})
    meta = json.loads(Path(f"{out}.meta.json").read_text(encoding="utf-8"))
    assert meta["blind_suite_used"] is False and meta["guardrails_enabled"] is False
    assert meta["model"] == cfg.model and meta["seed"] == 7 and meta["command"] == "cmd"
    assert meta["results_sha256"] == provenance.sha256_file(out)


def test_command_paths_are_relative_or_external(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inside = tmp_path / "evals" / "dataset.jsonl"
    outside = Path(tmp_path.anchor) / "Users" / "fulano" / "segredo" / "saida.json"
    cmd = provenance.sanitize_command(
        ["aok", "report", "build", "--dataset", str(inside), f"--out={outside}", str(outside),
         "examples/rag_agent/agent.yaml", "--seed", "42"]
    )
    assert "evals/dataset.jsonl" in cmd and str(tmp_path) not in cmd
    assert "--out=<externo>/saida.json" in cmd and "<externo>/saida.json" in cmd
    assert "fulano" not in cmd and "segredo" not in cmd
    assert "examples/rag_agent/agent.yaml" in cmd and "--seed 42" in cmd
    assert provenance.sanitize_command(cmd) == cmd  # idempotente
    win = provenance.sanitize_command(["aok", "--out", r"C:\Users\fulano\x\pk.json"])
    assert "fulano" not in win and "<externo>/pk.json" in win


def test_command_secrets_are_redacted():
    cmd = provenance.sanitize_command(
        "aok check --token abc123 --key=xyz789 --password hunter2 --api-key k1 "
        "AOK_PLATFORM_TOKEN=tok999 --audit-hmac-key-env MINHA_VAR --publish https://u:pw@host/x"
    )
    for secret in ("abc123", "xyz789", "hunter2", "k1", "tok999", "pw@"):
        assert secret not in cmd
    assert cmd.count("<redacted>") >= 6
    assert "MINHA_VAR" in cmd  # nome de variável não é segredo


def test_build_sanitizes_command_and_old_sidecar_command(work):
    _with_new_manifest(extra={**EXEC, "command": "aok eval --token segredo123 --out D:/pessoal/x"})
    prov = build.build_data(**_args(command="aok report build --token s3 --out D:/pessoal/pk"))[
        "provenance"
    ]
    blob = json.dumps(prov)
    assert "segredo123" not in blob and "s3" not in prov["command"] and "pessoal" not in blob
