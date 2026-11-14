import pytest

from agent_ops_kit.config import load_config
from agent_ops_kit.redteam.attacks import AttackCase
from agent_ops_kit.redteam.harness import (
    POISONED_DIR,
    AttackRecord,
    asr_by_category,
    build_testbed_system_prompt,
    format_asr_markdown,
    load_records,
    run_attack,
    run_suite,
    wilson_interval,
)
from agent_ops_kit.redteam.testbed import CANARY
from examples.rag_agent.agent import CONFIG_PATH

CONFIG = load_config(CONFIG_PATH)


def fake_base(name, arguments, k=3):
    return "[fonte: ferias.md]\n30 dias de férias."


def answer_llm(text):
    return lambda model, messages, tools: {"message": {"content": text}}


def tool_llm(tool, args, final="feito"):
    state = {"n": 0}

    def llm(model, messages, tools):
        state["n"] += 1
        if state["n"] == 1:
            return {"message": {"content": "", "tool_calls": [
                {"function": {"name": tool, "arguments": args}}]}}
        return {"message": {"content": final}}

    return llm


def case(**kw):
    base = {"id": "c1", "category": "exfiltracao", "description": "d", "user_input": "u",
            "success": {"type": "canary_in_output"}}
    base.update(kw)
    return AttackCase.model_validate(base)


def test_system_prompt_has_canary():
    p = build_testbed_system_prompt(CONFIG)
    assert p.startswith(CONFIG.system_prompt.rstrip()) and CANARY in p


def test_exfil_leak_and_refusal():
    leak = run_attack(case(), CONFIG, answer_llm(f"O código é {CANARY}"), base_runner=fake_base)
    assert leak.success and leak.error is None
    ok = run_attack(case(), CONFIG, answer_llm("Não posso divulgar."), base_runner=fake_base)
    assert not ok.success


def test_system_prompt_sent_contains_canary():
    seen = {}

    def llm(model, messages, tools):
        seen["sys"] = messages[0]["content"]
        seen["tools"] = [t["function"]["name"] for t in tools]
        return {"message": {"content": "x"}}

    run_attack(case(), CONFIG, llm, base_runner=fake_base)
    assert CANARY in seen["sys"]
    assert {"send_email", "read_file", "delete_record", "search_docs"} <= set(seen["tools"])


def test_forbidden_tool_called():
    c = case(id="t1", category="abuso_de_tools", success={"type": "tool_called", "tool": "send_email"})
    rec = run_attack(c, CONFIG, tool_llm("send_email", {"to": "a@b.c"}), base_runner=fake_base)
    assert rec.success and rec.tool_calls == ["send_email"]
    # argumentos inesperados também registram a chamada
    rec = run_attack(c, CONFIG, tool_llm("send_email", {"foo": "x"}), base_runner=fake_base)
    assert rec.success


def test_indirect_poisoned_doc_in_search_results():
    doc = min(p.name for p in POISONED_DIR.glob("*.md"))
    c = case(id="i1", category="injecao_indireta", poisoned_doc=doc,
             success={"type": "tool_called", "tool": "read_file"})
    seen = {}

    def llm(model, messages, tools):
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return {"message": {"content": "", "tool_calls": [
                {"function": {"name": "search_docs", "arguments": {"query": "q"}}}]}}
        seen["result"] = tool_msgs[0]["content"]
        return {"message": {"content": "ok"}}

    rec = run_attack(c, CONFIG, llm, base_runner=fake_base)
    text = (POISONED_DIR / doc).read_text(encoding="utf-8")
    assert "30 dias de férias" in seen["result"]
    assert f"[fonte: {doc}]" in seen["result"] and text in seen["result"]
    assert rec.tool_calls == ["search_docs"] and not rec.success


def test_agent_error_not_success_and_counted():
    def boom(model, messages, tools):
        raise RuntimeError("ollama fora")

    rec = run_attack(case(), CONFIG, boom, base_runner=fake_base)
    assert not rec.success and "RuntimeError" in rec.error
    summary = asr_by_category([rec, AttackRecord(case_id="b", category="exfiltracao", success=True)])
    row = summary["exfiltracao"]
    assert (row["n"], row["sucessos"], row["n_erros"]) == (2, 1, 1)


def test_wilson_known_values():
    lo, hi = wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    lo, hi = wilson_interval(10, 10)
    assert hi == pytest.approx(1.0) and lo == pytest.approx(0.7225, abs=1e-3)
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_asr_by_category_and_markdown():
    recs = [AttackRecord(case_id=str(i), category="injecao_direta", success=i < 3) for i in range(10)]
    recs.append(AttackRecord(case_id="z", category="abuso_de_tools"))
    s = asr_by_category(recs)
    assert s["injecao_direta"]["asr"] == 0.3 and s["total"]["n"] == 11
    assert s["total"]["sucessos"] == 3
    md = format_asr_markdown(s, "Teste")
    assert "| injecao_direta | 10 | 3 | 30.0 |" in md and "Limitações" in md


def test_run_suite_jsonl_and_resilience(tmp_path, monkeypatch):
    cases = [case(id="a"), case(id="b"), case(id="c")]
    n = {"i": 0}

    def llm(model, messages, tools):
        n["i"] += 1
        if n["i"] == 2:
            raise RuntimeError("falha")
        return {"message": {"content": f"vaza {CANARY}"}}

    out = tmp_path / "sub" / "r.jsonl"
    recs = run_suite(cases, CONFIG, llm, out_path=out, limit=3)
    back = load_records(out)
    assert [r.case_id for r in back] == ["a", "b", "c"]
    assert back[0].success and back[1].error and not back[1].success
    assert "vaza" in back[0].final_answer and len(recs) == 3
    assert len(run_suite(cases, CONFIG, answer_llm("x"), limit=2)) == 2


def test_limit_zero_runs_nothing():
    recs = run_suite([case(id="a")], CONFIG, answer_llm("x"), limit=0)
    assert recs == []
    assert asr_by_category(recs)["total"]["n"] == 0
