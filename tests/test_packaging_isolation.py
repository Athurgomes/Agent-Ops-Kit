"""Testes de isolamento de empacotamento: core da CLI e pacotes sem `examples`."""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

ISOLATED_MODULES = (
    "agent_ops_kit.cli",
    "agent_ops_kit.eval.runner",
    "agent_ops_kit.redteam.harness",
    "agent_ops_kit.redteam.false_positives",
    "agent_ops_kit.report.build",
)

BLOCKED_EXAMPLES = (
    "examples",
    "examples.rag_agent",
    "examples.rag_agent.agent",
    "examples.rag_agent.tools",
    "examples.rag_agent.indexer",
)


@pytest.fixture
def isolated_without_examples(monkeypatch):
    """Block `examples.*` and clear cached `agent_ops_kit.*` modules safely."""
    existing_examples = {
        name for name in sys.modules if name == "examples" or name.startswith("examples.")
    }
    for name in sorted(existing_examples | set(BLOCKED_EXAMPLES)):
        monkeypatch.setitem(sys.modules, name, None)
    for name in [n for n in sys.modules if n == "agent_ops_kit" or n.startswith("agent_ops_kit.")]:
        monkeypatch.delitem(sys.modules, name)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "agent_ops_kit" or name.startswith("agent_ops_kit."):
                sys.modules.pop(name, None)


@pytest.mark.parametrize("module_name", ISOLATED_MODULES)
def test_core_modules_import_without_examples(isolated_without_examples, module_name):
    mod = importlib.import_module(module_name)
    assert mod is not None
    assert sys.modules["examples"] is None


def test_cli_eval_reuse_summary_without_examples(
    isolated_without_examples, monkeypatch, tmp_path, capsys
):
    cli = importlib.import_module("agent_ops_kit.cli")
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(cli, "DEFAULT_EVAL_REPORT", str(tmp_path / "eval_report.md"))
    rc = cli.main(["eval", "--baseline", "v1", "--candidate", "v2", "--reuse", "--summary"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "v1 (baseline) vs v2 (candidate)" in out
    assert (tmp_path / "eval_report.md").is_file()


def test_forbidden_schemas_populated_without_examples(isolated_without_examples):
    harness = importlib.import_module("agent_ops_kit.redteam.harness")
    assert harness.MAX_ITERATIONS == 5
    names = [s["function"]["name"] for s in harness.FORBIDDEN_SCHEMAS]
    assert names == ["send_email", "read_file", "delete_record"]
    for schema in harness.FORBIDDEN_SCHEMAS:
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert set(fn["parameters"]["required"]) == set(fn["parameters"]["properties"])


def test_live_agent_helpers_fail_clearly_without_examples(isolated_without_examples, tmp_path):
    config_mod = importlib.import_module("agent_ops_kit.config")
    dataset_mod = importlib.import_module("agent_ops_kit.eval.dataset")
    runner = importlib.import_module("agent_ops_kit.eval.runner")
    attacks = importlib.import_module("agent_ops_kit.redteam.attacks")
    harness = importlib.import_module("agent_ops_kit.redteam.harness")
    false_positives = importlib.import_module("agent_ops_kit.redteam.false_positives")

    cfg = config_mod.load_config(ROOT / "examples" / "rag_agent" / "agent.yaml")
    eval_case = dataset_mod.EvalCase(
        id="q1",
        question="oi",
        expected=["oi"],
        sources=["a.md"],
        answerable=True,
        category="ferias",
    )
    attack_case = attacks.AttackCase.model_validate(
        {
            "id": "a1",
            "category": "exfiltracao",
            "description": "d",
            "user_input": "u",
            "success": {"type": "canary_in_output"},
        }
    )

    with pytest.raises(ImportError, match="examples.rag_agent"):
        runner.run_variant("v1", [eval_case], cfg, prompts_dir=ROOT / "evals" / "prompts")
    with pytest.raises(ImportError, match="examples.rag_agent"):
        harness.run_attack(attack_case, cfg)
    with pytest.raises(ImportError, match="examples.rag_agent"):
        harness.main(["--limit", "0"])
    with pytest.raises(ImportError, match="examples.rag_agent"):
        false_positives.run_benign([eval_case], cfg, ["input_filter"])
    with pytest.raises(ImportError, match="examples.rag_agent"):
        false_positives.main(["--out-dir", str(tmp_path)])


def test_pyproject_httpx_in_dev_extra_only():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = pyproject["project"]["optional-dependencies"]
    assert "httpx" in extras["dev"]
    assert "httpx" not in extras["platform"]
