import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agent_ops_kit.tracing import (
    llm_call,
    retrieval_query,
    set_results_count,
    set_tokens,
    setup_tracing,
    tool_call,
)


@pytest.fixture
def exporter():
    exp = InMemorySpanExporter()
    setup_tracing("test-agent", exporter=exp)
    return exp


def test_span_names(exporter):
    with llm_call("llama3"):
        pass
    with tool_call("calculator"):
        pass
    with retrieval_query("o que é X?"):
        pass
    names = [s.name for s in exporter.get_finished_spans()]
    assert names == ["llm.call", "tool.call", "retrieval.query"]


def test_llm_attributes_and_tokens_set_later(exporter):
    with llm_call("llama3", temperature=0.2) as span:
        set_tokens(span, 12, 34)
    attrs = exporter.get_finished_spans()[0].attributes
    assert attrs["gen_ai.request.model"] == "llama3"
    assert attrs["gen_ai.usage.input_tokens"] == 12
    assert attrs["gen_ai.usage.output_tokens"] == 34
    assert attrs["temperature"] == 0.2


def test_tool_attributes(exporter):
    with tool_call("current_date"):
        pass
    assert exporter.get_finished_spans()[0].attributes["gen_ai.tool.name"] == "current_date"


def test_retrieval_attributes(exporter):
    with retrieval_query("política de férias") as span:
        set_results_count(span, 3)
    attrs = exporter.get_finished_spans()[0].attributes
    assert attrs["retrieval.query"] == "política de férias"
    assert attrs["retrieval.results.count"] == 3


def test_retrieval_skips_complex_query(exporter):
    with retrieval_query("linha 1\nlinha 2"):
        pass
    with retrieval_query("x" * 500):
        pass
    for span in exporter.get_finished_spans():
        assert "retrieval.query" not in span.attributes


def test_error_marks_status_and_propagates(exporter):
    with pytest.raises(ValueError, match="boom"), tool_call("calculator"):
        raise ValueError("boom")
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert any(e.name == "exception" for e in span.events)


def test_nested_spans_share_trace(exporter):
    with llm_call("llama3"), tool_call("calculator"):
        pass
    tool, llm = exporter.get_finished_spans()
    assert tool.parent.span_id == llm.context.span_id
    assert tool.context.trace_id == llm.context.trace_id
