"""Falsos positivos dos guardrails: perguntas legítimas bloqueadas.

Roda cada pergunta com os guardrails ligados (mesma configuração do red team: prompt do
testbed com canary, tools reais do agente, sem classificador LLM). Bloqueado = qualquer
estágio (entrada, tool ou saída). A taxa de FP é reportada separadamente para o dataset de
avaliação e para o conjunto benigno. Para o dataset também compara o score das checagens
determinísticas com a execução gravada (custo de utilidade).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_ops_kit.config import AgentConfig, load_config
from agent_ops_kit.eval.ab import ABResult, format_ab_markdown, paired_ab
from agent_ops_kit.eval.checks import run_checks
from agent_ops_kit.eval.dataset import EvalCase, load_dataset
from agent_ops_kit.eval.prompts import load_prompt
from agent_ops_kit.eval.runner import final_answer, load_records, score_records
from agent_ops_kit.redteam.harness import (
    REDTEAM_DIR,
    build_guardrails,
    build_testbed_system_prompt,
    make_seeded_llm,
    parse_guardrails,
    wilson_interval,
)
from examples.rag_agent.agent import CONFIG_PATH, LLMFn, run_agent
from examples.rag_agent.tools import TOOL_SCHEMAS

BENIGN_PATH = REDTEAM_DIR / "benign" / "benign.jsonl"


def load_benign(path: str | Path = BENIGN_PATH) -> list[EvalCase]:
    return load_dataset(path)


def run_benign(
    cases: list[EvalCase],
    config: AgentConfig,
    guardrails_cfg: list[str],
    llm: LLMFn | None = None,
    out_path: str | Path | None = None,
    seed: int = 42,
) -> list[dict]:
    """Um registro por pergunta: case_id, blocked, blocked_by, reasons, answer (entregue),
    raw_answer (antes do filtro de saída), score (checagens determinísticas), error."""
    llm = llm or make_seeded_llm(seed)
    tb_config = config.model_copy(update={"system_prompt": build_testbed_system_prompt(config)})
    tools = [TOOL_SCHEMAS[t] for t in config.tools]
    records: list[dict] = []
    out = None
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        out = open(out_path, "w", encoding="utf-8")  # noqa: SIM115 - fechado no finally
    try:
        for case in cases:
            events: list[dict] = []
            answer, error = "", None
            try:
                answer = run_agent(
                    case.question, tb_config, llm, tools=tools,
                    guardrails=build_guardrails(tb_config, guardrails_cfg), events=events,
                )
            except Exception as e:  # noqa: BLE001 - erro do agente não conta como bloqueio
                error = f"{type(e).__name__}: {e}"
            raw = next((e["raw_answer"] for e in events if "raw_answer" in e), answer)
            rec = {
                "case_id": case.id,
                "blocked": bool(events),
                "blocked_by": sorted({e["stage"] for e in events}),
                "reasons": [r for e in events for r in e["reasons"]],
                "answer": answer,
                "raw_answer": raw,
                "score": run_checks(case, final_answer(answer)).score,
                "error": error,
            }
            records.append(rec)
            if out:
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
    finally:
        if out:
            out.close()
    return records


def fp_rate(records: list[dict]) -> dict:
    n = len(records)
    blocked = sum(r["blocked"] for r in records)
    lo, hi = wilson_interval(blocked, n)
    return {
        "n": n, "bloqueadas": blocked, "taxa": blocked / n if n else 0.0, "ic95": [lo, hi],
        "n_erros": sum(r["error"] is not None for r in records),
    }


def format_fp_markdown(groups: dict[str, list[dict]]) -> str:
    lines = [
        "### Falsos positivos dos guardrails", "",
        "| Conjunto | n | Bloqueadas | Taxa de FP % | IC 95% (Wilson) | Erros |",
        "|---|---|---|---|---|---|",
    ]
    for name, recs in groups.items():
        r = fp_rate(recs)
        lo, hi = r["ic95"]
        lines.append(
            f"| {name} | {r['n']} | {r['bloqueadas']} | {r['taxa'] * 100:.1f} "
            f"| [{lo * 100:.1f}; {hi * 100:.1f}] | {r['n_erros']} |"
        )
    lines += ["", "Perguntas bloqueadas:", ""]
    any_blocked = False
    for name, recs in groups.items():
        for rec in recs:
            if rec["blocked"]:
                any_blocked = True
                lines.append(
                    f"- {name} / {rec['case_id']}: estágio(s) {', '.join(rec['blocked_by'])}; "
                    f"motivos: {', '.join(rec['reasons'])}"
                )
    if not any_blocked:
        lines.append("- nenhuma")
    lines += [
        "", "Limitações:",
        "- n pequeno: os intervalos de confiança são largos.",
        "- Uma única execução com seed fixa; o conjunto benigno foi escrito antes da medição.",
        "- Bloqueio por qualquer estágio (entrada, tool ou saída); erros do agente não contam.",
        "",
    ]
    return "\n".join(lines)


def utility_cost(
    dataset: list[EvalCase], records: list[dict], baseline_records: list[dict]
) -> ABResult:
    """Score médio das checagens determinísticas com guardrails vs execução gravada."""
    base = score_records(dataset, baseline_records)
    cand = {r["case_id"]: r["score"] for r in records}
    return paired_ab(base, cand)


def format_utility_markdown(result: ABResult) -> str:
    text = format_ab_markdown(
        result, "v1 gravada", "v1 com guardrails", "score médio das checagens determinísticas"
    )
    return text + (
        "\nAviso: a baseline gravada (evals/answers/v1.jsonl) é de outra execução. A execução "
        "com guardrails usa o prompt v1 acrescido da linha do canary e da nota de conteúdo "
        "não confiável, e uma resposta bloqueada é pontuada como a mensagem de recusa.\n"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mede falsos positivos dos guardrails.")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--guardrails", default="all", help='"all" ou lista separada por vírgulas')
    ap.add_argument("--dataset", default="evals/dataset.jsonl")
    ap.add_argument("--benign", default=str(BENIGN_PATH))
    ap.add_argument("--v1-answers", default="evals/answers/v1.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    try:
        names = parse_guardrails(args.guardrails)
    except ValueError as e:
        ap.error(str(e))
    out_dir = Path(args.out_dir)
    config = load_config(CONFIG_PATH)
    cfg = config.model_copy(update={"system_prompt": load_prompt("v1"), "prompt_version": "v1"})
    dataset = load_dataset(args.dataset)[: args.limit]
    benign = load_benign(args.benign)[: args.limit]
    rec_ds = run_benign(dataset, cfg, names, out_path=out_dir / "fp_dataset.jsonl", seed=args.seed)
    rec_bn = run_benign(benign, cfg, names, out_path=out_dir / "fp_benign.jsonl", seed=args.seed)
    groups = {
        f"Dataset de avaliação ({len(rec_ds)})": rec_ds,
        f"Benignas novas ({len(rec_bn)})": rec_bn,
    }
    ids = {c.id for c in dataset}
    base = [r for r in load_records(args.v1_answers) if r["case_id"] in ids]
    parts = [
        format_fp_markdown(groups),
        format_utility_markdown(utility_cost(dataset, rec_ds, base)),
    ]
    text = "\n".join(parts)
    (out_dir / "falsos_positivos.md").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
