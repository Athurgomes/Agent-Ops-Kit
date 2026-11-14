import json
from pathlib import Path

import pytest

from agent_ops_kit.metrics import (
    MetricsCollector,
    PriceTable,
    estimate_cost,
    latency_summary,
    percentile,
    summarize_records,
)

ROOT = Path(__file__).resolve().parents[1]
# preços FICTÍCIOS, só para testar a conta; não representam nenhum provedor
FAKE = {"fake-model": {"input": 2.0, "output": 10.0}}


def test_percentile_known_values():
    values = list(range(1, 101))
    assert percentile(values, 50) == pytest.approx(50.5)
    assert percentile(values, 95) == pytest.approx(95.05)
    assert percentile(values, 0) == 1
    assert percentile(values, 100) == 100
    assert percentile([7], 95) == 7


def test_percentile_empty_and_invalid():
    assert percentile([], 50) is None
    with pytest.raises(ValueError):
        percentile([1, 2], 101)


def test_latency_summary():
    s = latency_summary([1.0, 2.0, 3.0])
    assert s == {"p50": 2.0, "p95": pytest.approx(2.9), "mean": 2.0, "n": 3}
    assert latency_summary([]) == {"p50": None, "p95": None, "mean": None, "n": 0}


def test_cost_with_configured_table():
    table = PriceTable.from_dict(FAKE)
    # 500k entrada * 2 + 100k saída * 10 por 1M tokens = 1.0 + 1.0
    assert estimate_cost("fake-model", 500_000, 100_000, table) == pytest.approx(2.0)


def test_cost_unknown_model_is_none():
    assert estimate_cost("fake-model", 10, 10, PriceTable.default()) is None


def test_default_local_model_is_free():
    assert estimate_cost("llama3.1:8b", 1000, 1000) == 0.0
    assert "estimado" in PriceTable.default().note


def test_from_dict_invalid():
    with pytest.raises(ValueError):
        PriceTable.from_dict({"m": {"input": 1}})


def test_from_yaml(tmp_path):
    p = tmp_path / "prices.yaml"
    p.write_text("fake-model:\n  input: 2.0\n  output: 10.0\n", encoding="utf-8")
    table = PriceTable.from_yaml(p)
    assert table.cost("fake-model", 1_000_000, 1_000_000) == pytest.approx(12.0)


def test_collector_summary():
    c = MetricsCollector(PriceTable.from_dict(FAKE))
    c.record_llm("fake-model", 1.0, 1000, 100)
    c.record_llm("fake-model", 3.0, 3000, 300)
    c.record_tool("search", True, 0.1)
    c.record_tool("search", False, 0.2)
    c.record_tool("search", True, 0.1)
    c.record_tool("search", True, 0.1)
    s = c.summary()
    assert s["llm_calls"] == 2
    assert s["llm_latency_p50_s"] == pytest.approx(2.0)
    assert s["avg_input_tokens"] == 2000
    assert s["avg_output_tokens"] == 200
    assert s["tool_calls"] == 4
    assert s["tool_error_rate"] == 0.25
    assert s["estimated_cost"] == pytest.approx((4000 * 2 + 400 * 10) / 1e6)


def test_collector_empty_and_no_state_shared():
    s = MetricsCollector().summary()
    assert s["llm_calls"] == 0
    assert s["tool_error_rate"] is None
    assert s["llm_latency_p50_s"] is None
    assert s["estimated_cost"] is None
    a, b = MetricsCollector(), MetricsCollector()
    a.record_llm("m", 1.0, 1, 1)
    assert b.summary()["llm_calls"] == 0


def test_collector_cost_none_for_unknown_model():
    c = MetricsCollector(PriceTable.from_dict(FAKE))
    c.record_llm("other", 1.0, 10, 10)
    assert c.summary()["estimated_cost"] is None


def test_summarize_records_synthetic():
    recs = [
        {"latency_s": 1.0, "input_tokens": 100, "output_tokens": 10, "error": None},
        {"latency_s": 3.0, "input_tokens": 300, "output_tokens": 30, "error": "boom"},
    ]
    s = summarize_records(recs, "fake-model", PriceTable.from_dict(FAKE))
    assert s["llm_calls"] == 2
    assert s["agent_error_rate"] == 0.5
    assert s["tool_error_rate"] is None
    assert s["avg_input_tokens"] == 200
    assert s["estimated_cost"] == pytest.approx((400 * 2 + 40 * 10) / 1e6)


def test_summarize_records_with_tool_data():
    recs = [{"latency_s": 1.0, "input_tokens": 1, "output_tokens": 1, "tools": [{"ok": True}, {"ok": False}]}]
    assert summarize_records(recs, "llama3.1:8b")["tool_error_rate"] == 0.5


@pytest.mark.parametrize("variant", ["v1", "v2"])
def test_summarize_real_answers(variant):
    path = ROOT / "evals" / "answers" / f"{variant}.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    s = summarize_records(records, "llama3.1:8b")
    assert s["llm_calls"] == 50
    assert s["llm_latency_p50_s"] <= s["llm_latency_p95_s"]
    assert s["tool_error_rate"] is None
    assert s["estimated_cost"] == 0.0
