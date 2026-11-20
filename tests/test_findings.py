import copy
import json
from pathlib import Path

import pytest

from agent_ops_kit import cli, provenance
from agent_ops_kit.redteam.report import ReportError
from agent_ops_kit.report import build, findings, render

ROOT = Path(__file__).resolve().parent.parent
SECRET = "TEXTO-DE-ATAQUE-SECRETO"


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _atk(cid, cat, success=False, error=None, **extra):
    return {
        "case_id": cid, "category": cat, "success": success, "error": error, "blocked_by": [],
        "final_answer": SECRET, "raw_answer": SECRET, **extra,
    }


def _fp(cid, blocked=False):
    return {
        "case_id": cid, "blocked": blocked, "blocked_by": ["output"] if blocked else [],
        "reasons": ["canary_leak"] if blocked else [], "answer": SECRET, "raw_answer": SECRET,
        "score": 1.0, "error": None,
    }


@pytest.fixture
def rt(tmp_path):
    d = tmp_path / "rt"
    d.mkdir()
    _write(d / "baseline.jsonl", [
        _atk("a1", "exfiltracao", True, trace_id="t-1"), _atk("a2", "injecao_direta"),
        _atk("a3", "exaustao_recursos", error="timeout"),
    ])
    _write(d / "guardrails.jsonl", [
        _atk("a1", "exfiltracao"), _atk("a2", "injecao_direta", True), _atk("a3", "x_nova", True),
    ])
    _write(d / "fp_dataset.jsonl", [_fp("q1"), _fp("q2", True)])
    _write(d / "fp_benign.jsonl", [_fp("b1"), _fp("b2", True)])
    return d


def _collect(rt, eval_ctx=None):
    return findings.collect(
        redteam={"baseline": rt / "baseline.jsonl", "guardrails": rt / "guardrails.jsonl"},
        false_positives={"dataset": rt / "fp_dataset.jsonl", "benign": rt / "fp_benign.jsonl"},
        eval_ctx=eval_ctx,
    )


def test_findings_from_sample_jsonl(rt):
    found, _ = _collect(rt)
    by_id = {f["id"]: f for f in found}
    assert set(by_id) == {
        "RT-a1-baseline", "RT-ERR-a3-baseline", "RT-a2-guardrails", "RT-a3-guardrails",
        "FP-q2-dataset", "FP-b2-benign",
    }
    a1 = by_id["RT-a1-baseline"]
    assert (a1["source"], a1["config"], a1["attack_id"], a1["category"]) == (
        "redteam", "baseline", "a1", "exfiltracao")
    assert a1["severity"] == "alta"
    assert by_id["RT-a2-guardrails"]["severity"] == "média"
    assert by_id["RT-a3-guardrails"]["severity"] == findings.NOT_CLASSIFIED  # fora da tabela
    assert by_id["RT-ERR-a3-baseline"]["severity"] == findings.NOT_CLASSIFIED
    assert by_id["FP-q2-dataset"]["source"] == "false_positive"
    assert by_id["FP-q2-dataset"]["reasons"] == ["canary_leak"]
    ev = a1["evidence"]
    assert ev["trace_id"] == "t-1" and ev["run_id"] is None
    assert ev["file"].endswith("baseline.jsonl") and ev["line"] == 1
    assert by_id["RT-a2-guardrails"]["evidence"]["line"] == 2
    assert by_id["FP-b2-benign"]["evidence"]["line"] == 2


def test_line_and_hashes_match(rt):
    found, paths = _collect(rt)
    findings.verify(found, paths)
    for f in found:
        ev = f["evidence"]
        path = paths[ev["file"]]
        line = path.read_text(encoding="utf-8").splitlines()[ev["line"] - 1]
        assert findings.record_sha256(json.loads(line)) == ev["record_sha256"]
        assert provenance.sha256_file(path) == ev["file_sha256"]


def test_repeated_runs_get_distinct_ids(tmp_path):
    p = _write(tmp_path / "g.jsonl", [_atk("a1", "exfiltracao", True), _atk("a1", "exfiltracao", True)])
    q = _write(tmp_path / "f.jsonl", [_fp("q1")])
    found, _ = findings.collect(redteam={"guardrails": p}, false_positives={"dataset": q})
    assert [f["id"] for f in found] == ["RT-a1-guardrails-r1", "RT-a1-guardrails-r2"]


def test_divergence_is_error(rt):
    found, paths = _collect(rt)
    path = rt / "baseline.jsonl"  # arquivo alterado depois da coleta
    path.write_text(path.read_text(encoding="utf-8").replace("exfiltracao", "exfiltracaX"), encoding="utf-8")
    with pytest.raises(ReportError, match="mudou"):
        findings.verify(found, paths)


def test_wrong_line_or_record_hash_is_error(rt):
    found, paths = _collect(rt)
    bad = copy.deepcopy(found)
    bad[0]["evidence"]["line"] += 1
    with pytest.raises(ReportError, match="não confere|outro caso"):
        findings.verify(bad, paths)
    bad = copy.deepcopy(found)
    bad[0]["evidence"]["record_sha256"] = "0" * 64
    with pytest.raises(ReportError, match="não confere"):
        findings.verify(bad, paths)
    bad = copy.deepcopy(found)
    bad[0]["evidence"]["line"] = 999
    with pytest.raises(ReportError, match="não confere"):
        findings.verify(bad, paths)


def test_order_is_stable_and_independent_of_input_order(rt):
    a, _ = _collect(rt)
    assert a == _collect(rt)[0]
    rank = {"redteam": 0, "false_positive": 1, "eval": 2}
    keys = [(rank[f["source"]], f["config"], f["id"]) for f in a]
    assert keys == sorted(keys)
    found, _ = findings.collect(
        redteam={"guardrails": rt / "guardrails.jsonl", "baseline": rt / "baseline.jsonl"},
        false_positives={"benign": rt / "fp_benign.jsonl", "dataset": rt / "fp_dataset.jsonl"},
    )
    assert found == a


def test_eval_regressions_by_case(tmp_path):
    b = _write(tmp_path / "v1.jsonl", [{"case_id": "q1", "answer": SECRET}, {"case_id": "q2", "answer": "x"}])
    c = _write(tmp_path / "v2.jsonl", [{"case_id": "q1", "answer": SECRET}, {"case_id": "q2", "answer": "y"}])
    ctx = {
        "baseline": "v1", "candidate": "v2", "baseline_path": b, "candidate_path": c,
        "scores_baseline": {"q1": 1.0, "q2": 0.5}, "scores_candidate": {"q1": 0.5, "q2": 0.75},
        "categories": {"q1": "factual"},
    }
    found, paths = findings.collect(redteam={}, false_positives={}, eval_ctx=ctx)
    assert [f["id"] for f in found] == ["EV-q1-v2"]
    f = found[0]
    assert (f["source"], f["category"], f["baseline_score"], f["candidate_score"]) == (
        "eval", "factual", 1.0, 0.5)
    assert f["evidence"]["file"] != f["baseline_evidence"]["file"]
    findings.verify(found, paths)
    assert SECRET not in json.dumps(found)


def _argv(out, rt):
    return [
        "report", "build", "--out", str(out),
        "--dataset", str(ROOT / "evals/dataset.jsonl"),
        "--prompts-dir", str(ROOT / "evals/prompts"),
        "--config", str(ROOT / "examples/rag_agent/agent.yaml"),
        "--answers-dir", str(ROOT / "evals/answers"),
        "--redteam-baseline", str(rt / "baseline.jsonl"),
        "--redteam-guardrails", str(rt / "guardrails.jsonl"),
        "--fp-dir", str(rt),
    ]


def test_build_has_findings_without_attack_text(rt, tmp_path):
    out = tmp_path / "pk"
    assert cli.main(_argv(out, rt)) == 0
    data = json.loads((out / "relatorio.json").read_text(encoding="utf-8"))
    assert {"RT-a1-baseline", "FP-q2-dataset"} <= {f["id"] for f in data["findings"]}
    for name in ("relatorio.json", "relatorio.md", "relatorio.html"):
        assert SECRET not in (out / name).read_text(encoding="utf-8")
    md = (out / "relatorio.md").read_text(encoding="utf-8")
    assert "A.8 Achados e evidências" in md and "RT-a1-baseline" in md
    for f in data["findings"]:
        assert f["evidence"]["record_sha256"][:12] in md


def test_build_exit_2_when_evidence_does_not_match(rt, tmp_path, monkeypatch):
    real = findings.collect

    def tampered(**kw):
        found, paths = real(**kw)
        found[0]["evidence"]["record_sha256"] = "0" * 64
        return found, paths

    monkeypatch.setattr(findings, "collect", tampered)
    assert cli.main(_argv(tmp_path / "pk", rt)) == 2
    assert not (tmp_path / "pk" / "relatorio.json").exists()


def _many(n):
    ev = {"file": "r/g.jsonl", "line": 1, "record_sha256": "a" * 64, "file_sha256": "b" * 64}
    return [
        {"id": f"RT-a{i:03d}-guardrails", "source": "redteam", "category": "exfiltracao",
         "severity": "baixa" if i else "alta", "evidence": ev}
        for i in range(n)
    ]


def test_render_limits_long_list():
    text = render.to_markdown(render._findings_blocks({"findings": _many(45)}))
    assert "RT-a000-guardrails" in text  # maior severidade primeiro
    assert "RT-a044-guardrails" not in text
    assert "limitada a 30 dos 45" in text
    assert "r/g.jsonl:1" in text and "a" * 12 in text and "a" * 13 not in text


def test_render_old_report_and_empty():
    assert "não registrados" in render.to_markdown(render._findings_blocks({}))
    assert "Nenhum achado" in render.to_markdown(render._findings_blocks({"findings": []}))


def test_build_data_findings_are_deterministic(rt):
    kw = {
        "config": str(ROOT / "examples/rag_agent/agent.yaml"),
        "dataset": str(ROOT / "evals/dataset.jsonl"),
        "prompts_dir": str(ROOT / "evals/prompts"), "answers_dir": str(ROOT / "evals/answers"),
        "baseline": "v1", "candidate": "v2", "seed": 42,
        "redteam_baseline": str(rt / "baseline.jsonl"),
        "redteam_guardrails": str(rt / "guardrails.jsonl"), "fp_dir": str(rt),
    }
    assert build.build_data(**kw)["findings"] == build.build_data(**kw)["findings"]
