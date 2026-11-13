"""Comparação estatística pareada entre duas variantes (bootstrap + teste de permutação)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

EXACT_MAX_N = 16


@dataclass(frozen=True)
class ABResult:
    n: int
    n_dropped: int
    mean_baseline: float
    mean_candidate: float
    mean_diff: float
    ci_low: float
    ci_high: float
    p_value: float
    p_method: str  # "exact" ou "monte_carlo"
    seed: int
    n_resamples: int


def _valid(x: float | None) -> bool:
    return x is not None and not math.isnan(x)


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Percentil q (0-100) com interpolação linear."""
    pos = (len(sorted_vals) - 1) * q / 100
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def paired_ab(
    baseline: dict[str, float | None],
    candidate: dict[str, float | None],
    n_resamples: int = 10_000,
    seed: int = 42,
) -> ABResult:
    """Compara candidate vs baseline nos mesmos case_ids.

    Descarta ids só de um lado ou com score None/NaN (conta em n_dropped).
    IC 95%: bootstrap pareado. p-valor: permutação por inversão de sinal, bilateral.
    """
    if n_resamples < 1:
        raise ValueError("n_resamples deve ser >= 1")
    all_ids = set(baseline) | set(candidate)
    ids = sorted(
        i
        for i in set(baseline) & set(candidate)
        if _valid(baseline[i]) and _valid(candidate[i])
    )
    n = len(ids)
    if n < 2:
        raise ValueError(f"pares válidos insuficientes: {n} (mínimo 2)")

    base = [float(baseline[i]) for i in ids]  # type: ignore[arg-type]
    cand = [float(candidate[i]) for i in ids]  # type: ignore[arg-type]
    diffs = [c - b for b, c in zip(base, cand)]
    mean_diff = sum(diffs) / n

    rng = random.Random(seed)

    # Bootstrap pareado da diferença média.
    boots = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(n_resamples))
    ci_low = _percentile(boots, 2.5)
    ci_high = _percentile(boots, 97.5)

    # Teste de permutação pareado (inversão de sinal), bilateral, em termos da soma.
    obs = abs(sum(diffs))
    tol = 1e-9 * max(1.0, sum(abs(d) for d in diffs))
    if n <= EXACT_MAX_N:
        sums = [0.0]
        for d in diffs:
            sums = [s + d for s in sums] + [s - d for s in sums]
        k = sum(1 for s in sums if abs(s) >= obs - tol)
        p_value = k / len(sums)
        method = "exact"
    else:
        k = 0
        for _ in range(n_resamples):
            s = sum(d if rng.random() < 0.5 else -d for d in diffs)
            if abs(s) >= obs - tol:
                k += 1
        p_value = (k + 1) / (n_resamples + 1)
        method = "monte_carlo"

    return ABResult(
        n=n,
        n_dropped=len(all_ids) - n,
        mean_baseline=sum(base) / n,
        mean_candidate=sum(cand) / n,
        mean_diff=mean_diff,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        p_method=method,
        seed=seed,
        n_resamples=n_resamples,
    )


def format_ab_markdown(
    result: ABResult, baseline_name: str, candidate_name: str, metric_name: str
) -> str:
    """Tabela markdown em português; interpretação fica com o leitor."""
    r = result
    lines = [
        f"### Comparação A/B: {candidate_name} vs {baseline_name} ({metric_name})",
        "",
        "| Item | Valor |",
        "|---|---|",
        f"| Média {baseline_name} | {r.mean_baseline:.4f} |",
        f"| Média {candidate_name} | {r.mean_candidate:.4f} |",
        f"| Diferença média ({candidate_name} - {baseline_name}) | {r.mean_diff:+.4f} |",
        f"| IC 95% da diferença (bootstrap) | [{r.ci_low:+.4f}, {r.ci_high:+.4f}] |",
        f"| p-valor (permutação pareada, bilateral, {r.p_method}) | {r.p_value:.4f} |",
        f"| n (pares usados) | {r.n} |",
        f"| Descartados | {r.n_dropped} |",
        f"| Semente / reamostragens | {r.seed} / {r.n_resamples} |",
        "",
    ]
    if r.p_value < 0.05:
        lines.append("Diferença estatisticamente distinguível de zero a 5%.")
        lines.append("")
    lines.append(
        "Aviso: p-valor não é prova de causalidade, e n pequeno limita o poder do teste."
    )
    return "\n".join(lines) + "\n"
