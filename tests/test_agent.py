import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_ops_kit.config import load_config
from agent_ops_kit.tracing import setup_tracing
from examples.rag_agent import tools
from examples.rag_agent.agent import CONFIG_PATH, LIMIT_MESSAGE, run_agent


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    setup_tracing("test", exporter=exporter)
    return exporter


def _tool_msg(name, args):
    return {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": args}}],
        },
        "prompt_eval_count": 10,
        "eval_count": 5,
    }


def _final(text):
    return {
        "message": {"role": "assistant", "content": text},
        "prompt_eval_count": 20,
        "eval_count": 7,
    }


def test_agent_yaml_valido():
    cfg = load_config(CONFIG_PATH)
    assert cfg.model == "llama3.1:8b"
    assert set(cfg.tools) == {"search_docs", "calculator", "current_date"}


def test_loop_chama_tool_e_responde(spans):
    seen = []
    replies = iter([_tool_msg("calculator", {"expression": "2 + 3 * 4"}), _final("O total é 14.")])

    def fake_llm(model, messages, tool_schemas):
        seen.append([m["role"] for m in messages])
        return next(replies)

    assert run_agent("quanto é 2+3*4?", llm=fake_llm) == "O total é 14."
    assert seen[1][-1] == "tool"
    names = [s.name for s in spans.get_finished_spans()]
    assert names.count("agent.run") == 1
    assert len({s.context.trace_id for s in spans.get_finished_spans()}) == 1
    assert names.count("llm.call") == 2
    assert names.count("tool.call") == 1
    llm_span = next(s for s in spans.get_finished_spans() if s.name == "llm.call")
    assert llm_span.attributes["gen_ai.usage.input_tokens"] == 10
    assert llm_span.attributes["gen_ai.usage.output_tokens"] == 5


def test_resultado_da_tool_volta_ao_llm():
    captured = {}
    replies = iter([_tool_msg("calculator", {"expression": "6 * 7"}), _final("ok")])

    def fake_llm(model, messages, tool_schemas):
        captured["messages"] = messages
        return next(replies)

    run_agent("x", llm=fake_llm)
    assert captured["messages"][-1] == {"role": "tool", "tool_name": "calculator", "content": "42"}


def test_limite_de_iteracoes():
    calls = []

    def fake_llm(model, messages, tool_schemas):
        calls.append(1)
        return _tool_msg("current_date", {})

    assert run_agent("x", llm=fake_llm, max_iterations=3) == LIMIT_MESSAGE
    assert len(calls) == 3


def test_tool_desconhecida_nao_quebra():
    replies = iter([_tool_msg("rm_rf", {}), _final("ok")])
    assert run_agent("x", llm=lambda *a: next(replies)) == "ok"


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo oi')",
        "open('x')",
        "().__class__",
        "[1, 2]",
        "'a' * 3",
        "2 ** 100000",
        "import os",
        "x + 1",
        "(lambda: 1)()",
    ],
)
def test_calculator_rejeita_perigosas(expr):
    assert tools.calculator(expr).startswith("erro:")


def test_calculator_aritmetica():
    assert tools.calculator("(1 + 2) * 3 - 4 / 2") == "7.0"
    assert tools.calculator("-5 + 2") == "-3"
    assert tools.calculator("1 / 0").startswith("erro:")


def test_search_docs_deduplica_por_source(monkeypatch, spans):
    hits = [
        {"text": "a1", "source": "a.md", "distance": 0.1},
        {"text": "a2", "source": "a.md", "distance": 0.2},
        {"text": "b1", "source": "b.md", "distance": 0.3},
    ]
    monkeypatch.setattr(tools, "query_index", lambda q, k=3: hits)
    res = tools.search_docs("qualquer")
    assert res == [{"text": "a1", "source": "a.md"}, {"text": "b1", "source": "b.md"}]
    span = next(s for s in spans.get_finished_spans() if s.name == "retrieval.query")
    assert span.attributes["retrieval.results.count"] == 2


def test_run_tool_search_docs_inclui_fonte(monkeypatch):
    monkeypatch.setattr(
        tools, "query_index", lambda q, k=3: [{"text": "30 dias", "source": "01.md", "distance": 0}]
    )
    out = tools.run_tool("search_docs", {"query": "férias"})
    assert "[fonte: 01.md]" in out and "30 dias" in out
