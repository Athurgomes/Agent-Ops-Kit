"""A7: falsos positivos com target, e bloco do agente auditado e casos não avaliados no relatório.

Sem Ollama: o agente-fixture não usa o modelo; o resto são arquivos sintéticos.
"""

import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from agent_ops_kit import cli, provenance
from agent_ops_kit.config import TargetConfig, load_config
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.redteam import false_positives as fp
from agent_ops_kit.report import render, verify
from examples.rag_agent.agent import CONFIG_PATH

SRC = Path(__file__).resolve().parent.parent
BASE = load_config(CONFIG_PATH)
EXAMPLE = provenance.target_info(BASE)["target"]
EXTERNAL = {"type": "python", "ref": "fxagent:agent", "seed_controlled_by_kit": False,
            "note": "semente não controlada pelo kit"}
OTHER = {**EXTERNAL, "ref": "outro:agente"}


@contextmanager
def _cd(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


# --- falsos positivos com target ------------------------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    shutil.copy(Path(__file__).with_name("fixture_agent.py"), tmp_path / "fxagent.py")
    shutil.copytree(SRC / "evals" / "prompts", tmp_path / "evals" / "prompts")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    sys.modules.pop("fxagent", None)


def _ext_cfg():
    return BASE.model_copy(update={"target": TargetConfig(ref="fxagent:agent")})


def test_run_benign_with_external_target(project):
    cases = load_dataset(fp.BENIGN_PATH)[:2]
    recs = fp.run_benign(cases, _ext_cfg(), [], out_path=project / "o.jsonl")
    assert [r["blocked"] for r in recs] == [False, False]
    assert recs[0]["answer"] == f"eco: {cases[0].question}" and recs[0]["error"] is None


def test_run_benign_external_with_guardrails_is_clear_error(project):
    with pytest.raises(ValueError, match="guardrails só se aplicam ao agente de exemplo"):
        fp.run_benign(load_dataset(fp.BENIGN_PATH)[:1], _ext_cfg(), ["input_filter"])


def _write_cfg(root: Path) -> Path:
    data = json.loads(BASE.model_dump_json())
    data["target"] = {"type": "python", "ref": "fxagent:agent"}
    path = root / "agent.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_fp_main_external_records_target_in_meta(project, monkeypatch):
    monkeypatch.setattr(provenance, "ollama_info", lambda *_a, **_k: {})
    out = project / "fp"
    args = ["--out-dir", str(out), "--config", str(_write_cfg(project)), "--limit", "2",
            "--dataset", str(SRC / "evals" / "dataset.jsonl"),
            "--benign", str(fp.BENIGN_PATH), "--v1-answers", str(SRC / "evals" / "answers" / "v1.jsonl")]
    assert fp.main(args) == 0
    meta = json.loads((out / "fp.meta.json").read_text(encoding="utf-8"))
    assert meta["target"]["ref"] == "fxagent:agent" and meta["target"]["seed_controlled_by_kit"] is False
    assert meta["guardrails"] == []
    with pytest.raises(SystemExit) as exc:
        fp.main([*args, "--guardrails", "all"])
    assert exc.value.code == 2


def test_fp_main_without_target_records_example(project, monkeypatch):
    monkeypatch.setattr(provenance, "ollama_info", lambda *_a, **_k: {})
    called = []
    monkeypatch.setattr(fp, "run_benign", lambda cases, cfg, names, **kw: called.append(names) or [])
    monkeypatch.setattr(fp, "utility_cost", lambda *a, **k: None)
    monkeypatch.setattr(fp, "format_utility_markdown", lambda *_: "")
    out = project / "fp"
    out.mkdir()
    for n in ("fp_dataset.jsonl", "fp_benign.jsonl"):
        (out / n).write_text("", encoding="utf-8")
    fp.main(["--out-dir", str(out), "--limit", "1", "--dataset", str(SRC / "evals" / "dataset.jsonl"),
             "--v1-answers", str(SRC / "evals" / "answers" / "v1.jsonl")])
    assert called[0] == list(fp.parse_guardrails("all"))  # sem target: guardrails "all", como antes
    meta = json.loads((out / "fp.meta.json").read_text(encoding="utf-8"))
    assert meta["target"]["ref"] == EXAMPLE["ref"] and meta["target"]["seed_controlled_by_kit"] is True


# --- relatório: agente auditado e não avaliados ---------------------------------------------


def _write(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _attack(cid, success=False, **kw):
    return {"case_id": cid, "category": "abuso_de_tools", "success": success, "blocked_by": [], **kw}


def _fprow(cid):
    return {"case_id": cid, "blocked": False, "blocked_by": [], "reasons": [], "score": 1.0, "error": None}


def _make_repo(tmp_path, *, base_target=None, guard_target=None, fp_target=None,
               not_eval=0, recorded_not_eval=None):
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(SRC / "evals", root / "evals")
    shutil.copytree(SRC / "examples" / "rag_agent", root / "examples" / "rag_agent",
                    ignore=shutil.ignore_patterns("__pycache__", "chroma*"))
    shutil.copytree(SRC / "policies", root / "policies")
    rt = root / "rt"
    rt.mkdir()
    flagged = [_attack(f"n{i}", tool_not_evaluated=True) for i in range(not_eval)]
    _write(rt / "baseline.jsonl", [_attack("a1", True), _attack("a2"), *flagged])
    _write(rt / "guardrails.jsonl", [_attack("a1"), _attack("a2"), *flagged])
    _write(rt / "fp_dataset.jsonl", [_fprow("q1")])
    _write(rt / "fp_benign.jsonl", [_fprow("b1")])
    for name, target in (("baseline", base_target), ("guardrails", guard_target)):
        meta = {"seed": 42, "model": "m"}
        if target:
            meta["target"] = target
        if recorded_not_eval is not None:
            meta["n_tool_not_evaluated"] = recorded_not_eval
        (rt / f"{name}.jsonl.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if fp_target:
        (rt / "fp.meta.json").write_text(json.dumps({"seed": 42, "target": fp_target}), encoding="utf-8")
    return root


def _build(root, name="pk"):
    with _cd(root):
        rc = cli.main([
            "report", "build", "--out", name, "--redteam-baseline", "rt/baseline.jsonl",
            "--redteam-guardrails", "rt/guardrails.jsonl", "--fp-dir", "rt",
            "--policy", "policies/default.yaml", "--coverage-map", "policies/coverage/owasp_llm_2025.yaml",
        ])
    return rc, json.loads((root / name / "relatorio.json").read_text(encoding="utf-8")) if rc == 0 else None


def _md(data):
    return render.to_markdown(render.build_blocks(data))


def _checks(root, name="pk"):
    res = verify.verify_package(root / name, root)
    return {c["id"]: c["status"] for c in res["checks"]}


def test_old_package_says_not_recorded(tmp_path):
    root = _make_repo(tmp_path)
    rc, data = _build(root)
    assert rc == 0 and "Agente auditado: não registrado." in _md(data)
    assert not any("mesmo agente" in x or "Semente não controlada" in x for x in data["limitations"])
    assert set(_checks(root).values()) == {"ok"}


def test_example_target_shows_reference_agent(tmp_path):
    root = _make_repo(tmp_path, base_target=EXAMPLE, guard_target=EXAMPLE, fp_target=EXAMPLE)
    _, data = _build(root)
    md = _md(data)
    assert "agente de referência do kit" in md and "semente controlada pelo kit: sim" in md
    assert not any("Semente não controlada" in x for x in data["limitations"])


def test_external_target_has_seed_caveat(tmp_path):
    root = _make_repo(tmp_path, base_target=EXTERNAL, guard_target=EXTERNAL, fp_target=EXTERNAL)
    _, data = _build(root)
    md = _md(data)
    assert "ref fxagent:agent, semente controlada pelo kit: não" in md
    assert any(x.startswith("Semente não controlada pelo kit") for x in data["limitations"])
    assert not any("não apontam para o mesmo agente" in x for x in data["limitations"])
    assert set(_checks(root).values()) == {"ok"}


def test_baseline_and_guardrails_from_different_agents_are_refused(tmp_path, capsys):
    root = _make_repo(tmp_path, base_target=EXAMPLE, guard_target=EXTERNAL, fp_target=OTHER)
    rc, _ = _build(root)
    assert rc == 2 and "agentes diferentes" in capsys.readouterr().err


def test_partial_redteam_args_are_refused_and_defaults_only_when_none(tmp_path, capsys):
    root = _make_repo(tmp_path)
    with _cd(root):
        rc = cli.main(["report", "build", "--out", "pk", "--redteam-baseline", "rt/baseline.jsonl"])
    assert rc == 2 and "juntos" in capsys.readouterr().err


def test_divergent_targets_add_caveat_and_verify_reproduces_it(tmp_path):
    root = _make_repo(tmp_path, base_target=EXAMPLE, guard_target=EXAMPLE, fp_target=OTHER)
    _, data = _build(root)
    cav = [x for x in data["limitations"] if "não apontam para o mesmo agente" in x]
    assert len(cav) == 1 and "falsos positivos" in cav[0] and "outro:agente" in cav[0]
    assert "Agente auditado (por origem)" in _md(data)
    assert set(_checks(root).values()) == {"ok"}
    # a ressalva é checada pelo verify: apagá-la do json falha
    p = root / "pk" / "relatorio.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["limitations"] = [x for x in d["limitations"] if "mesmo agente" not in x]
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _checks(root)["limitations"] == "falha"


def test_not_evaluated_shown_caveat_and_verified(tmp_path):
    root = _make_repo(tmp_path, base_target=EXTERNAL, guard_target=EXTERNAL, not_eval=3, recorded_not_eval=3)
    _, data = _build(root)
    tot = data["redteam"]["asr"]["guardrails"]["total"]
    assert tot["not_evaluated"] == 3 and tot["n"] == 2  # fora de n
    assert data["redteam"]["asr"]["baseline"]["total"]["not_evaluated"] == 3
    assert any("Métrica de ferramenta não avaliada" in x and "reduz n" in x for x in data["limitations"])
    assert "(+3 não avaliados)" in _md(data) and "3 sem controles; 3 com controles" in _md(data)
    assert set(_checks(root).values()) == {"ok"}
    p = root / "pk" / "relatorio.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["redteam"]["asr"]["guardrails"]["total"]["not_evaluated"] = 0
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _checks(root)["asr"] == "falha"


def test_zero_not_evaluated_adds_nothing(tmp_path):
    root = _make_repo(tmp_path)
    _, data = _build(root)
    assert "not_evaluated" not in data["redteam"]["asr"]["guardrails"]["total"]
    assert not any("não avaliada" in x for x in data["limitations"])


def test_sidecar_count_mismatch_fails_build(tmp_path):
    root = _make_repo(tmp_path, not_eval=2, recorded_not_eval=5)
    rc, _ = _build(root)
    assert rc != 0


def test_partially_registered_target_adds_caveat_and_verify_reproduces_it(tmp_path):
    root = _make_repo(tmp_path, base_target=EXAMPLE, guard_target=EXAMPLE)  # FP sem target
    _, data = _build(root)
    cav = [x for x in data["limitations"] if x.startswith("Agente não registrado em parte")]
    assert len(cav) == 1 and "falsos positivos" in cav[0] and "eval" in cav[0]
    assert set(_checks(root).values()) == {"ok"}
    p = root / "pk" / "relatorio.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["limitations"] = [x for x in d["limitations"] if "em parte das execuções" not in x]
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    assert _checks(root)["limitations"] == "falha"


# --- evidências fora do repositório (--evidence-root, ADR-030) ----------------------------


def _external_evidence(tmp_path, root):
    """Move o red team do repositório sintético para uma pasta externa (fora do cwd do build)."""
    ext = tmp_path / "ext"
    shutil.copytree(root / "rt", ext / "rt")
    shutil.rmtree(root / "rt")
    return ext


def _build_ext(root, ext, extra=()):
    with _cd(root):
        return cli.main([
            "report", "build", "--out", "pk", "--redteam-baseline", str(ext / "rt/baseline.jsonl"),
            "--redteam-guardrails", str(ext / "rt/guardrails.jsonl"), "--fp-dir", str(ext / "rt"),
            "--policy", "policies/default.yaml", "--coverage-map",
            "policies/coverage/owasp_llm_2025.yaml", *extra,
        ])


def test_evidence_outside_repo_is_verifiable_with_evidence_root(tmp_path):
    root = _make_repo(tmp_path, base_target=EXTERNAL, guard_target=EXTERNAL, fp_target=EXTERNAL)
    ext = _external_evidence(tmp_path, root)
    assert _build_ext(root, ext, ["--evidence-root", str(ext)]) == 0
    data = json.loads((root / "pk" / "relatorio.json").read_text(encoding="utf-8"))
    text = json.dumps(data)
    assert str(ext).replace("\\", "/") not in text and data["provenance"]["evidence_root"] == "@evidence"
    assert data["provenance"]["files"]["redteam_baseline"] == "@evidence/rt/baseline.jsonl"
    res = verify.verify_package(root / "pk", root, evidence_root=ext)
    assert {c["id"]: c["status"] for c in res["checks"]} == {c["id"]: "ok" for c in res["checks"]}
    # sem --evidence-root o verify diz o que falta, sem adivinhar
    res = verify.verify_package(root / "pk", root)
    assert not res["ok"] and any("--evidence-root" in c["detail"] for c in res["checks"])


def test_outside_evidence_without_root_is_not_resolvable_but_stays_inside_package_rules(tmp_path):
    root = _make_repo(tmp_path, base_target=EXTERNAL, guard_target=EXTERNAL, fp_target=EXTERNAL)
    ext = _external_evidence(tmp_path, root)
    assert _build_ext(root, ext) == 0  # legado: chave só com o nome do arquivo
    data = json.loads((root / "pk" / "relatorio.json").read_text(encoding="utf-8"))
    assert "evidence_root" not in data["provenance"]
    assert not verify.verify_package(root / "pk", root)["ok"]


def test_rel_path_and_resolve_key_roundtrip(tmp_path):
    ext, repo = tmp_path / "ext", tmp_path / "repo"
    (ext / "a").mkdir(parents=True)
    repo.mkdir()
    f = ext / "a" / "x.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    key = provenance.rel_path(f, repo, ext)
    assert key == "@evidence/a/x.jsonl"
    assert provenance.resolve_key(key, ext) == ext / "a" / "x.jsonl"
    assert provenance.rel_path(f, repo) == "x.jsonl"  # sem raiz: só o nome (legado)
    with pytest.raises(ValueError):
        provenance.resolve_key(key, None)
