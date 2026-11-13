"""Métricas de operação: latência, tokens, erro de tool e custo estimado (só biblioteca padrão).

- O custo é ESTIMADO e configurável: a tabela padrão só traz modelos locais do Ollama (preço 0.0).
  Para outros modelos, informe a sua própria tabela (`PriceTable.from_dict` ou `from_yaml`).
- Modelo ausente da tabela: `cost()` devolve None (custo desconhecido), nunca um valor inventado.
- Sem estado global: cada `MetricsCollector` guarda só as suas próprias chamadas.
- Limitação: nos registros do runner, latência e tokens são por CASO (soma das chamadas de LLM do
  caso), não por chamada. Em `summarize_records`, `llm_calls` é o nº de casos e `llm_latency_*` e
  `avg_*_tokens` valem por caso. Só o `MetricsCollector` mede por chamada de LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PRICE_NOTE = (
    "Custo estimado e configurável: preço por 1 milhão de tokens (entrada e saída) por modelo. "
    "O padrão traz só modelos locais do Ollama, a 0.0."
)

# Modelos locais do Ollama (sem custo por token). Não há preços de provedores pagos aqui.
LOCAL_MODELS = ("llama3.1:8b", "qwen2.5:0.5b", "nomic-embed-text")


def percentile(values: list[float], p: float) -> float | None:
    """Percentil por interpolação linear (p em 0-100). Lista vazia -> None."""
    if not 0 <= p <= 100:
        raise ValueError("p deve estar entre 0 e 100")
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * p / 100
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def latency_summary(values: list[float]) -> dict:
    """p50, p95, média e n das latências (None nos três primeiros se a lista for vazia)."""
    mean = sum(values) / len(values) if values else None
    return {"p50": percentile(values, 50), "p95": percentile(values, 95), "mean": mean, "n": len(values)}


@dataclass
class PriceTable:
    """Preço (por 1 milhão de tokens) de entrada e saída por modelo: {modelo: (in, out)}."""

    prices: dict[str, tuple[float, float]] = field(default_factory=dict)
    note: str = PRICE_NOTE

    @classmethod
    def from_dict(cls, data: dict) -> PriceTable:
        """Formato: {modelo: {"input": preço, "output": preço}}."""
        prices = {}
        for model, p in data.items():
            try:
                prices[str(model)] = (float(p["input"]), float(p["output"]))
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"preço inválido para o modelo {model!r}: use input e output") from e
        return cls(prices)

    @classmethod
    def from_yaml(cls, path: str | Path) -> PriceTable:
        import yaml

        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise TypeError("o YAML de preços deve ser um mapa modelo -> {input, output}")
        return cls.from_dict(data)

    @classmethod
    def default(cls) -> PriceTable:
        return cls({m: (0.0, 0.0) for m in LOCAL_MODELS})

    def cost(self, model: str, input_tokens: int, output_tokens: int) -> float | None:
        """Custo estimado em dinheiro; None se o modelo não está na tabela."""
        if model not in self.prices:
            return None
        p_in, p_out = self.prices[model]
        return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


def estimate_cost(model: str, input_tokens: int, output_tokens: int, table: PriceTable | None = None) -> float | None:
    """Custo estimado de uma chamada; usa a tabela padrão (modelos locais) se `table` for None."""
    return (table or PriceTable.default()).cost(model, input_tokens, output_tokens)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _summary(
    latencies: list[float],
    in_tokens: list[int],
    out_tokens: list[int],
    tool_ok: list[bool],
    cost: float | None,
) -> dict:
    lat = latency_summary(latencies)
    return {
        "llm_calls": len(latencies),
        "llm_latency_p50_s": lat["p50"],
        "llm_latency_p95_s": lat["p95"],
        "avg_input_tokens": _mean(in_tokens),
        "avg_output_tokens": _mean(out_tokens),
        "tool_calls": len(tool_ok),
        "tool_error_rate": (tool_ok.count(False) / len(tool_ok)) if tool_ok else None,
        "estimated_cost": cost,
    }


class MetricsCollector:
    """Acumula chamadas de LLM e de tool; `summary()` devolve o resumo."""

    def __init__(self, price_table: PriceTable | None = None) -> None:
        self.price_table = price_table
        self.llm_calls: list[dict] = []
        self.tool_calls: list[dict] = []

    def record_llm(self, model: str, latency_s: float, input_tokens: int, output_tokens: int) -> None:
        self.llm_calls.append(
            {"model": model, "latency_s": latency_s, "input_tokens": input_tokens, "output_tokens": output_tokens}
        )

    def record_tool(self, name: str, ok: bool, latency_s: float) -> None:
        self.tool_calls.append({"name": name, "ok": ok, "latency_s": latency_s})

    def summary(self) -> dict:
        cost = None
        if self.price_table and self.llm_calls:
            costs = [self.price_table.cost(c["model"], c["input_tokens"], c["output_tokens"]) for c in self.llm_calls]
            cost = None if None in costs else sum(costs)
        return _summary(
            [c["latency_s"] for c in self.llm_calls],
            [c["input_tokens"] for c in self.llm_calls],
            [c["output_tokens"] for c in self.llm_calls],
            [c["ok"] for c in self.tool_calls],
            cost,
        )


def summarize_records(records: list[dict], model: str, price_table: PriceTable | None = None) -> dict:
    """Resumo a partir dos registros do runner (um por caso).

    Atenção: latência e tokens são por CASO, não por chamada de LLM. Aqui `llm_calls` é o nº de
    casos (não de chamadas) e `llm_latency_*`, `avg_input_tokens` e `avg_output_tokens` valem por caso.

    Mesmo formato do `MetricsCollector.summary()`, mais `agent_error_rate` (casos com `error`).
    A taxa de erro de tool só existe se os registros trouxerem `tools: [{"ok": bool}, ...]`;
    caso contrário é None. Sem `price_table`, o custo usa a tabela padrão (modelos locais).
    """
    table = price_table or PriceTable.default()
    ok_flags = [bool(t.get("ok")) for r in records for t in r.get("tools", [])]
    in_tokens = [r.get("input_tokens", 0) for r in records]
    out_tokens = [r.get("output_tokens", 0) for r in records]
    cost = table.cost(model, sum(in_tokens), sum(out_tokens)) if records else None
    out = _summary([r["latency_s"] for r in records], in_tokens, out_tokens, ok_flags, cost)
    out["agent_error_rate"] = (sum(1 for r in records if r.get("error")) / len(records)) if records else None
    return out
