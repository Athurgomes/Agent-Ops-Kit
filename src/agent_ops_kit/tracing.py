"""Tracing com OpenTelemetry (convenções semânticas GenAI)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span

DEFAULT_ENDPOINT = "http://localhost:4317"
MAX_QUERY_CHARS = 200

_provider: TracerProvider | None = None


def setup_tracing(
    service_name: str,
    endpoint: str | None = None,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Configura o tracer do kit. Com `exporter` injetado (testes) não usa OTLP."""
    global _provider
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        url = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or DEFAULT_ENDPOINT
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=url)))
    _provider = provider
    return provider


def _tracer() -> trace.Tracer:
    if _provider is not None:
        return _provider.get_tracer("agent_ops_kit")
    return trace.get_tracer("agent_ops_kit")


@contextmanager
def agent_run(name: str, **attributes: str | float | bool) -> Iterator[Span]:
    """Span raiz `agent.run`: agrupa llm.call/tool.call/retrieval.query em um único trace."""
    with _tracer().start_as_current_span("agent.run") as span:
        span.set_attribute("gen_ai.agent.name", name)
        span.set_attributes(attributes)
        yield span


@contextmanager
def llm_call(model: str, **attributes: str | float | bool) -> Iterator[Span]:
    """Span `llm.call`. Use `set_tokens(span, in, out)` após a resposta."""
    with _tracer().start_as_current_span("llm.call") as span:
        span.set_attribute("gen_ai.request.model", model)
        span.set_attributes(attributes)
        yield span


@contextmanager
def tool_call(name: str, **attributes: str | float | bool) -> Iterator[Span]:
    """Span `tool.call`."""
    with _tracer().start_as_current_span("tool.call") as span:
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attributes(attributes)
        yield span


@contextmanager
def retrieval_query(query: str, **attributes: str | float | bool) -> Iterator[Span]:
    """Span `retrieval.query`. O texto só é gravado se for curto e de uma linha."""
    with _tracer().start_as_current_span("retrieval.query") as span:
        if len(query) <= MAX_QUERY_CHARS and "\n" not in query:
            span.set_attribute("retrieval.query", query)
        span.set_attributes(attributes)
        yield span


def set_tokens(span: Span, input_tokens: int, output_tokens: int) -> None:
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)


def set_results_count(span: Span, count: int) -> None:
    span.set_attribute("retrieval.results.count", count)
