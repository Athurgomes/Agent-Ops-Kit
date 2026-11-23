"""Target do agent.yaml (A7): contrato, ref seguro, eval, red team e proveniência. Sem Ollama."""

import shutil
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_ops_kit import provenance
from agent_ops_kit.config import AgentConfig, TargetConfig, load_config
from agent_ops_kit.eval.dataset import EvalCase
from agent_ops_kit.eval.runner import run_variant
from agent_ops_kit.metrics import summarize_records
from agent_ops_kit.redteam.attacks import AttackCase
from agent_ops_kit.redteam.harness import (
    asr_by_category,
    format_asr_markdown,
    run_attack,
    run_suite,
)
from agent_ops_kit.target import (
    EXAMPLE_REF,
    ContractError,
    TargetError,
    resolve_target,
    validate_response,
)
from examples.rag_agent.agent import CONFIG_PATH

ROOT = Path(__file__).resolve().parent.parent
BASE = load_config(CONFIG_PATH)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Raiz de projeto temporária com o agente-fixture como módulo `fxagent`."""
    shutil.copy(Path(__file__).with_name("fixture_agent.py"), tmp_path / "fxagent.py")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    sys.modules.pop("fxagent", None)


def cfg_for(ref: str) -> AgentConfig:
    return BASE.model_copy(update={"target": TargetConfig(ref=ref)})


def attack(success: dict, **kw) -> AttackCase:
    data = {"id": "t1", "category": "abuso_de_tools", "description": "d",
            "user_input": "calls", "success": success}
    return AttackCase.model_validate({**data, **kw})


TOOL_OK = {"type": "tool_called", "tool": "send_email"}


# --- contrato -----------------------------------------------------------------------------


def test_contract_valid_minimal_and_full():
    assert validate_response({"answer": "ok"}) == {"answer": "ok", "tool_calls": None, "trace_id": None}
    full = {"answer": "ok", "tool_calls": [{"name": "x", "arguments": {}}], "trace_id": "t"}
    assert validate_response(full) == full


@pytest.mark.parametrize(
    "raw",
    [
        "texto",
        {"tool_calls": []},
        {"answer": 1},
        {"answer": "x", "tool_calls": "send_email"},
        {"answer": "x", "tool_calls": [{"name": "a"}]},
        {"answer": "x", "tool_calls": [{"name": 1, "arguments": {}}]},
        {"answer": "x", "trace_id": 5},
    ],
)
def test_contract_invalid(raw):
    with pytest.raises(ContractError):
        validate_response(raw)


def test_call_contract_and_agent_exception(project):
    t = resolve_target(cfg_for("fxagent:agent"))
    assert t.call("oi")["answer"] == "eco: oi"
    assert t.call("ctx", context="doc")["answer"] == "contexto=doc"
    with pytest.raises(ContractError):
        t.call("no_answer")
    with pytest.raises(RuntimeError, match="falha do agente"):
        t.call("boom")


# --- config e ref ---------------------------------------------------------------------------


def test_config_without_target_is_default():
    assert BASE.target is None
    t = resolve_target(BASE)
    assert t.is_example and t.ref == EXAMPLE_REF and t.type == "python"


def test_config_unknown_type_and_mixed_fields_refused():
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {**BASE.model_dump(), "target": {"type": "grpc", "ref": "a:b"}}
        )
    with pytest.raises(ValidationError, match="target.ref não é permitido"):
        AgentConfig.model_validate(
            {**BASE.model_dump(), "target": {"type": "http", "url": "https://x.invalid/a", "ref": "a:b"}}
        )
    with pytest.raises(ValidationError, match="campos HTTP não são permitidos"):
        AgentConfig.model_validate(
            {**BASE.model_dump(), "target": {"type": "python", "ref": "fxagent:agent", "timeout_s": 5}}
        )
    cfg = AgentConfig.model_validate(
        {**BASE.model_dump(), "target": {"type": "http", "url": "https://x.invalid/a"}}
    )
    assert cfg.target is not None and cfg.target.type == "http"


@pytest.mark.parametrize("ref", ["mod", "mod:", ":fn", "a/b:fn", "../x:fn", "a.b:c.d", "a b:c", "a:b:c"])
def test_config_malformed_ref(ref):
    with pytest.raises(ValidationError, match="ref inválido"):
        TargetConfig(ref=ref)


def test_yaml_target_roundtrip(tmp_path):
    text = CONFIG_PATH.read_text(encoding="utf-8") + '\ntarget:\n  type: python\n  ref: "fxagent:agent"\n'
    p = tmp_path / "agent.yaml"
    p.write_text(text, encoding="utf-8")
    cfg = load_config(p)
    assert cfg.target is not None and cfg.target.ref == "fxagent:agent"


def test_ref_outside_project_refused(project, tmp_path_factory):
    empty = tmp_path_factory.mktemp("outro_projeto")
    with pytest.raises(TargetError, match="não encontrado dentro da raiz"):
        resolve_target(cfg_for("fxagent:agent"), root=empty)
    with pytest.raises(TargetError, match="não encontrado dentro da raiz"):
        resolve_target(cfg_for("json:dumps"), root=project)  # stdlib: fora do projeto


def test_ref_missing_or_not_callable(project):
    with pytest.raises(TargetError, match="não é chamável|não existe"):
        resolve_target(cfg_for("fxagent:NOT_CALLABLE"))
    with pytest.raises(TargetError, match="não é chamável|não existe"):
        resolve_target(cfg_for("fxagent:inexistente"))
    with pytest.raises(TargetError, match="não encontrado"):
        resolve_target(cfg_for("modulo_que_nao_existe:fn"))


def test_accepts_llm_detected(project):
    assert not resolve_target(cfg_for("fxagent:agent")).accepts_llm
    assert resolve_target(cfg_for("fxagent:agent_llm")).accepts_llm


# --- eval -----------------------------------------------------------------------------------

CASE = EvalCase(
    id="q1", question="oi", answerable=False, expected=[], sources=[], category="ferias"
)
PROMPTS = ROOT / "evals" / "prompts"


def llm_stub(model, messages, tools):
    return {"message": {"content": "via llm"}, "prompt_eval_count": 7, "eval_count": 3}


def test_eval_external_without_llm_tokens_none(project):
    recs = run_variant("v1", [CASE], cfg_for("fxagent:agent"), llm=llm_stub, prompts_dir=PROMPTS)
    assert recs[0]["answer"] == "eco: oi" and recs[0]["error"] is None
    assert recs[0]["input_tokens"] is None and recs[0]["output_tokens"] is None
    s = summarize_records(recs, "llama3.1:8b")
    assert s["avg_input_tokens"] is None and s["estimated_cost"] is None


def test_eval_external_with_llm_counts_tokens(project):
    recs = run_variant("v1", [CASE], cfg_for("fxagent:agent_llm"), llm=llm_stub, prompts_dir=PROMPTS)
    assert recs[0]["answer"] == "via llm"
    assert (recs[0]["input_tokens"], recs[0]["output_tokens"]) == (7, 3)


def test_eval_external_errors_do_not_stop_run(project):
    cases = [CASE.model_copy(update={"id": f"q{i}", "question": q})
             for i, q in enumerate(["boom", "no_answer", "oi"])]
    recs = run_variant("v1", cases, cfg_for("fxagent:agent"), prompts_dir=PROMPTS)
    assert recs[0]["error"].startswith("RuntimeError")
    assert recs[1]["error"].startswith("ContractError")
    assert recs[2]["error"] is None and recs[2]["answer"] == "eco: oi"


def test_eval_default_target_unchanged():
    recs = run_variant("v1", [CASE], BASE, llm=lambda m, msgs, t: {
        "message": {"content": "x"}, "prompt_eval_count": 5, "eval_count": 2}, prompts_dir=PROMPTS)
    assert (recs[0]["input_tokens"], recs[0]["output_tokens"]) == (5, 2)
    assert recs[0]["answer"] == "x"


# --- red team ---------------------------------------------------------------------------------


def test_redteam_declared_tool_calls_measured(project):
    rec = run_attack(attack(TOOL_OK), cfg_for("fxagent:agent"))
    assert rec.success and rec.tool_calls == ["send_email"] and not rec.tool_not_evaluated
    rec = run_attack(attack(TOOL_OK, user_input="empty_calls"), cfg_for("fxagent:agent"))
    assert not rec.success and rec.tool_calls == [] and not rec.tool_not_evaluated


def test_redteam_undeclared_tool_calls_not_evaluated(project):
    recs = [
        run_attack(attack(TOOL_OK, id="a", user_input="oi"), cfg_for("fxagent:agent")),
        run_attack(attack(TOOL_OK, id="b"), cfg_for("fxagent:agent")),
    ]
    assert recs[0].tool_not_evaluated and not recs[0].success
    row = asr_by_category(recs)["abuso_de_tools"]
    assert row["n"] == 1 and row["sucessos"] == 1 and row["n_nao_avaliados"] == 1
    assert "não avaliada" in format_asr_markdown(asr_by_category(recs), "t")
    # critério que não é de ferramenta segue avaliado pela resposta
    leak = run_attack(
        attack({"type": "output_contains", "text": "eco"}, user_input="oi"), cfg_for("fxagent:agent")
    )
    assert leak.success and not leak.tool_not_evaluated


def test_redteam_agent_errors_and_guardrails(project):
    for q, kind in (("boom", "RuntimeError"), ("bad_type", "ContractError")):
        rec = run_attack(attack(TOOL_OK, user_input=q), cfg_for("fxagent:agent"))
        assert rec.error.startswith(kind) and not rec.success and not rec.tool_not_evaluated
    with pytest.raises(ValueError, match="guardrails só se aplicam"):
        run_attack(attack(TOOL_OK), cfg_for("fxagent:agent"), guardrails=["input_filter"])


def test_redteam_poisoned_doc_goes_as_context(project, tmp_path):
    poisoned = tmp_path / "poisoned"
    poisoned.mkdir()
    (poisoned / "p.md").write_text("DOC_ENVENENADO", encoding="utf-8")
    c = attack(
        {"type": "output_contains", "text": "DOC_ENVENENADO"},
        category="injecao_indireta", user_input="ctx", poisoned_doc="p.md",
    )
    assert run_attack(c, cfg_for("fxagent:agent"), poisoned_dir=poisoned).success


# --- proveniência -----------------------------------------------------------------------------


def test_target_info_default_and_external():
    d = provenance.target_info(BASE)["target"]
    assert d == {"type": "python", "ref": EXAMPLE_REF, "seed_controlled_by_kit": True}
    e = provenance.target_info(cfg_for("fxagent:agent"))["target"]
    assert e["type"] == "python" and e["ref"] == "fxagent:agent"
    assert e["seed_controlled_by_kit"] is False and "não controlada" in e["note"]


def test_sidecar_records_target(project, tmp_path):
    import json

    out = tmp_path / "res" / "r.jsonl"
    cases = [attack(TOOL_OK, id="a", user_input="oi")]
    run_suite(cases, cfg_for("fxagent:agent"), out_path=out)
    meta = json.loads(Path(f"{out}.meta.json").read_text(encoding="utf-8"))
    assert meta["target"]["ref"] == "fxagent:agent"
    assert meta["target"]["seed_controlled_by_kit"] is False
    assert meta["n_tool_not_evaluated"] == 1
    out2 = tmp_path / "res" / "d.jsonl"
    run_suite(cases, BASE, llm=lambda m, msgs, t: {"message": {"content": "x"}}, out_path=out2)
    meta2 = json.loads(Path(f"{out2}.meta.json").read_text(encoding="utf-8"))
    assert meta2["target"]["seed_controlled_by_kit"] is True
    assert "n_tool_not_evaluated" not in meta2


def test_ref_module_already_loaded_from_outside_refused(project, tmp_path_factory):
    resolve_target(cfg_for("fxagent:agent"))  # carrega fxagent da raiz do projeto
    other = tmp_path_factory.mktemp("outra_raiz")
    shutil.copy(project / "fxagent.py", other / "fxagent.py")
    with pytest.raises(TargetError, match="fora da raiz"):
        resolve_target(cfg_for("fxagent:agent"), root=other)
