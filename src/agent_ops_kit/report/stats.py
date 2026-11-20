"""Estatística do relatório: McNemar exato e ressalvas geradas a partir dos dados (sem modelo).

Tudo é determinístico: a mesma entrada gera os mesmos números e o mesmo texto, na mesma ordem.
Fórmulas em docs/decisoes.md (ADR-025).
"""

from __future__ import annotations

import math
from collections import Counter

ALPHA = 0.05
Z_ALPHA = 1.959964  # bilateral, alfa = 5%
Z_POWER = 0.841621  # poder = 80%
SMALL_N = 30  # abaixo disso, a medição é marcada como "n pequeno"
WIDE_CI = 0.20  # largura do IC 95% (escala 0 a 1) a partir da qual o IC é marcado como largo

_NA = "não registrado"


# ---- McNemar exato ----

def mcnemar_exact_p(b: int, c: int) -> float:
    """p-valor exato bilateral: 2 * P(X <= min(b, c)), X ~ Binomial(b + c, 0,5), limitado a 1."""
    m = b + c
    if m == 0:
        return 1.0
    tail = sum(math.comb(m, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**m)  # divisão de inteiros: sem estouro de float


def _keyed(records: list) -> dict[tuple[str, int], object]:
    """Chave (attack_id, ocorrência): execuções repetidas do mesmo ataque se pareiam em ordem."""
    seen: Counter[str] = Counter()
    out: dict[tuple[str, int], object] = {}
    for r in records:
        out[(r.case_id, seen[r.case_id])] = r
        seen[r.case_id] += 1
    return out


def mcnemar_block(baseline: list | None, guardrails: list | None) -> dict:
    """Compara o sucesso do ataque sem e com guardrails, pareado por attack_id.

    b = sucesso só na baseline; c = sucesso só com guardrails. Pares com erro de execução em
    qualquer lado, ou presentes em só um lado, são excluídos e contados.
    """
    base_fields = ("n_paired", "b", "c", "both", "neither", "p_value", "excluded")
    if baseline is None or guardrails is None:
        missing = "baseline" if baseline is None else "guardrails"
        return {
            "applicable": False,
            "reason": f"há só uma configuração do red team (falta {missing}); sem par para comparar",
            **dict.fromkeys(base_fields),
        }
    kb, kg = _keyed(baseline), _keyed(guardrails)
    unpaired = len(set(kb) ^ set(kg))
    errors = b = c = both = neither = 0
    for key in sorted(set(kb) & set(kg)):
        rb, rg = kb[key], kg[key]
        if rb.error is not None or rg.error is not None:
            errors += 1
        elif rb.success and rg.success:
            both += 1
        elif rb.success:
            b += 1
        elif rg.success:
            c += 1
        else:
            neither += 1
    n = b + c + both + neither
    excluded = {"errors": errors, "unpaired": unpaired, "total": errors + unpaired}
    out = {
        "applicable": n > 0, "reason": None, "n_paired": n, "b": b, "c": c, "both": both,
        "neither": neither, "p_value": mcnemar_exact_p(b, c), "excluded": excluded,
    }
    if n == 0:
        out.update(reason="nenhum par válido (todos excluídos por erro ou sem par)", p_value=None)
    return out


# ---- efeito mínimo detectável (MDE) ----

def mde_proportion(n: int) -> float | None:
    """MDE da diferença entre duas proporções, n por grupo, alfa 5% bilateral, poder 80%.

    (z_alfa + z_poder) * sqrt(2 * p(1 - p) / n) com p = 0,5 (pior caso, conservador).
    """
    return None if n <= 0 else (Z_ALPHA + Z_POWER) * math.sqrt(0.5 / n)


def mde_from_ci(low: float, high: float) -> float:
    """MDE de uma diferença de médias a partir da meia-largura do IC 95%: (z_alfa+z_poder)/z_alfa * h."""
    return (Z_ALPHA + Z_POWER) / Z_ALPHA * (high - low) / 2


def _ceil(x: float, digits: int) -> float:
    return math.ceil(round(x * 10**digits, 9)) / 10**digits  # arredonda para cima: nunca favorece


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ---- medições e ressalvas ----

def measurements(data: dict) -> list[dict]:
    """Lista ordenada de medições: nome, n, IC 95%, MDE (None quando não calculável)."""
    ev, rt = data["eval"], data["redteam"]
    rows = [{
        "name": f"Eval: diferença média ({ev['candidate']} - {ev['baseline']})",
        "n": ev["n_pairs"], "low": ev["ci95_low"], "high": ev["ci95_high"], "kind": "mean",
        "mde": mde_from_ci(ev["ci95_low"], ev["ci95_high"]),
    }]
    sources = (
        ("ASR sem guardrails", (rt["asr"]["baseline"] or {}).get("total"), "ci95_low", "ci95_high"),
        ("ASR com guardrails", (rt["asr"]["guardrails"] or {}).get("total"), "ci95_low", "ci95_high"),
        ("Falsos positivos (dataset de avaliação)", rt["false_positives"]["dataset"], "ci95_low", "ci95_high"),
        ("Falsos positivos (perguntas benignas)", rt["false_positives"]["benign"], "ci95_low", "ci95_high"),
    )
    for name, r, lo, hi in sources:
        if r:
            rows.append({
                "name": name, "n": r["n"], "low": r[lo], "high": r[hi], "kind": "proportion",
                "mde": mde_proportion(r["n"]),
            })
    return rows


def _measurement_line(m: dict) -> str:
    if m["kind"] == "mean":
        ci = f"[{m['low']:+.4f}; {m['high']:+.4f}]"
        mde = f"{_ceil(m['mde'], 4):.4f} (na escala 0 a 1 da nota)"
    else:
        ci = f"[{_pct(m['low'])}; {_pct(m['high'])}]"
        mde = "n/d" if m["mde"] is None else f"{_ceil(m['mde'] * 100, 1):.1f} pontos percentuais"
    return (
        f"{m['name']}: n = {m['n']}, IC 95% {ci}, efeito mínimo detectável aproximado de {mde} "
        "(poder 80%, alfa 5%; fórmula na ADR-025)."
    )


def _commit_rows(data: dict) -> list[tuple[str, str | None, bool | None]]:
    ex = (data.get("provenance") or {}).get("executions") or {}
    rows: list[tuple[str, str | None, bool | None]] = []
    for v, run in (ex.get("eval") or {}).items():
        rows.append((f"eval {v}", *_commit(run)))
    for key, label in (("baseline", "red team baseline"), ("guardrails", "red team guardrails"),
                       ("false_positives", "falsos positivos")):
        if key in (ex.get("redteam") or {}):
            rows.append((label, *_commit(ex["redteam"][key])))
    return rows


def _commit(run: dict | None) -> tuple[str | None, bool | None]:
    run = run or {}
    return run.get("git_commit"), run.get("git_dirty")


def _short(commit: str) -> str:
    return commit[:12]


def _suite_caveat(rt: dict) -> str:
    n, k = rt.get("n_attacks"), rt.get("n_blind_attacks")
    if k is None:
        return (
            "Não há registro de suíte cega neste relatório: a suíte de ataques deve ser tratada "
            "como pública e conhecida pelo autor das defesas, sem valor de teste cego."
        )
    if k == 0:
        return (
            "A suíte de ataques é pública (versionada no repositório), foi escrita no mesmo "
            "projeto das defesas e é conhecida pelo autor: não funciona como teste cego."
        )
    if k >= n:
        return f"Todos os {n} ataques vêm de suíte cega (sem metadado sobre quem a conhece)."
    return (
        f"Só {k} de {n} ataques vêm de suíte cega; os outros {n - k} são públicos e conhecidos "
        "pelo autor das defesas, sem valor de teste cego."
    )


def statistical_caveats(data: dict) -> list[str]:
    """Ressalvas estatísticas derivadas dos dados. Ordem fixa: medições, avisos, suíte, proveniência."""
    ev, rt = data["eval"], data["redteam"]
    ms = measurements(data)
    out = [_measurement_line(m) for m in ms]

    small = [f"{m['name']} (n = {m['n']})" for m in ms if m["n"] < SMALL_N]
    if small:
        out.append(f"n pequeno (menos de {SMALL_N}): " + "; ".join(small) + ".")
    wide = [m["name"] for m in ms if m["high"] - m["low"] > WIDE_CI]
    if wide:
        out.append(
            f"IC largo (largura do IC 95% acima de {WIDE_CI:.2f} na escala 0 a 1): "
            + "; ".join(wide) + "."
        )
    if ev["p_value"] >= ALPHA:
        out.append(
            f"Eval: p = {ev['p_value']:.4f}, não significativo (alfa {ALPHA}); sem evidência de "
            "diferença entre as variantes, o que não prova equivalência."
        )
    mc = rt.get("mcnemar")
    if not mc:
        out.append("McNemar (baseline vs guardrails) não registrado neste relatório.")
    elif not mc["applicable"]:
        out.append(f"McNemar não aplicável: {mc['reason']}.")
    else:
        if mc["p_value"] >= ALPHA:
            out.append(
                f"McNemar: p = {mc['p_value']:.4f}, não significativo (alfa {ALPHA}); sem evidência "
                "de diferença no sucesso dos ataques com e sem guardrails (b = "
                f"{mc['b']}, c = {mc['c']}), o que não prova equivalência."
            )
        if mc["excluded"]["total"]:
            ex = mc["excluded"]
            out.append(
                f"McNemar: {ex['total']} ataque(s) excluído(s) da comparação pareada ({ex['errors']} "
                f"com erro de execução, {ex['unpaired']} sem par); o teste usa {mc['n_paired']} pares."
            )
    out.append(_suite_caveat(rt))

    rows = _commit_rows(data)
    commits = {c for _, c, _ in rows if c}
    if len(commits) > 1:
        out.append(
            "Execuções em commits diferentes: "
            + "; ".join(f"{label} em {_short(c)}" for label, c, _ in rows if c)
            + ". Os resultados não vêm de uma única versão do código."
        )
    dirty = [label for label, _, d in rows if d is True]
    if dirty:
        out.append(
            "Execuções com árvore git com alterações não commitadas: " + "; ".join(dirty)
            + ". O commit registrado não reproduz exatamente o código executado."
        )
    missing = [label for label, c, _ in rows if not c]
    if missing:
        out.append(
            "Commit " + _NA + " nas execuções: " + "; ".join(missing)
            + ". Não é possível confirmar a versão do código usada."
        )
    if (data.get("provenance") or {}).get("git_dirty") is True:
        out.append("O relatório foi gerado com a árvore git com alterações não commitadas.")
    return out
