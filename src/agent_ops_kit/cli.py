"""CLI única do agent-ops-kit (`aok`). Cada subcomando é uma função isolada (`cmd_*`)."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

ALPHA = 0.05

JUDGE_WARNING = (
    "Aviso sobre o juiz: o juiz é o mesmo modelo de 8B que gera as respostas (viés de "
    "autopreferência e ruído); as notas são ordinais (1 a 5), não intervalares; a rubrica não "
    "foi calibrada contra humanos. Use como complemento das checagens determinísticas, não "
    "como substituto."
)

CHECK_NAMES = (
    "contains_expected",
    "cites_correct_source",
    "valid_format",
    "refuses_when_unanswerable",
)


class CliError(Exception):
    """Erro de uso (arquivo ou variante inexistente): mensagem curta para o usuário."""


def _reproducible_command(args: argparse.Namespace) -> str:
    tokens = ["aok", "eval", "--baseline", args.baseline, "--candidate", args.candidate]
    tokens += ["--dataset", args.dataset, "--prompts-dir", args.prompts_dir]
    tokens += ["--config", args.config, "--answers-dir", args.answers_dir]
    if args.reuse:
        tokens.append("--reuse")
    if args.judge:
        tokens.append("--judge")
    if args.limit is not None:
        tokens += ["--limit", str(args.limit)]
    tokens += ["--seed", str(args.seed)]
    if args.report:
        tokens += ["--report", args.report]
    if args.fail_on_regression:
        tokens.append("--fail-on-regression")
    return shlex.join(tokens)


def _check_rates(cases, records) -> dict[str, tuple[int, int]]:
    """{checagem: (aprovados, aplicáveis)} sobre a resposta final de cada registro."""
    from agent_ops_kit.eval.checks import run_checks
    from agent_ops_kit.eval.runner import final_answer

    by_id = {c.id: c for c in cases}
    counts = {name: [0, 0] for name in CHECK_NAMES}
    for r in records:
        result = run_checks(by_id[r["case_id"]], final_answer(r["answer"]))
        for name in CHECK_NAMES:
            value = getattr(result, name)
            if value is not None:
                counts[name][1] += 1
                counts[name][0] += int(value)
    return {k: (v[0], v[1]) for k, v in counts.items()}


def _rates_table(rates: dict[str, dict[str, tuple[int, int]]], variants: list[str]) -> str:
    lines = ["| Checagem | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for name in CHECK_NAMES:
        cells = []
        for v in variants:
            ok, total = rates[v][name]
            cells.append(f"{ok}/{total} ({ok / total:.1%})" if total else "n/a")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def cmd_eval(args: argparse.Namespace) -> int:
    """Compara duas variantes de prompt (A/B pareado). Deve rodar na raiz do repositório."""
    # O runner importa `examples.rag_agent`, que fica na raiz do repo (fora de src/): o comando
    # precisa rodar da raiz, e o cwd entra no sys.path para o import funcionar.
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        return _run_eval(args)
    except CliError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2


def _run_eval(args: argparse.Namespace) -> int:
    from agent_ops_kit.config import load_config
    from agent_ops_kit.eval import judge as judge_mod
    from agent_ops_kit.eval import runner
    from agent_ops_kit.eval.ab import format_ab_markdown, paired_ab
    from agent_ops_kit.eval.dataset import load_dataset
    from agent_ops_kit.eval.prompts import load_prompt

    variants = [args.baseline, args.candidate]
    if args.baseline == args.candidate:
        raise CliError("--baseline e --candidate devem ser variantes diferentes")
    if args.limit is not None and args.limit < 1:
        raise CliError("--limit deve ser >= 1")
    answers_dir = Path(args.answers_dir)

    if not Path(args.dataset).is_file():
        raise CliError(f"dataset não encontrado: {args.dataset}")
    if not Path(args.config).is_file():
        raise CliError(f"config não encontrada: {args.config}")
    for v in variants:
        if args.reuse:
            if not (answers_dir / f"{v}.jsonl").is_file():
                raise CliError(
                    f"respostas gravadas não encontradas: {answers_dir / f'{v}.jsonl'} "
                    "(rode sem --reuse para gerá-las)"
                )
        else:
            try:
                load_prompt(v, args.prompts_dir)
            except (FileNotFoundError, ValueError) as exc:
                raise CliError(str(exc)) from exc

    dataset = load_dataset(args.dataset)
    config = load_config(args.config)
    cases = dataset[: args.limit] if args.limit is not None else dataset
    case_ids = {c.id for c in cases}

    records: dict[str, list[dict]] = {}
    for v in variants:
        path = answers_dir / f"{v}.jsonl"
        if args.reuse:
            records[v] = [r for r in runner.load_records(path) if r["case_id"] in case_ids]
        else:
            records[v] = runner.run_variant(
                v,
                dataset,
                config,
                out_path=path,
                limit=args.limit,
                seed=args.seed,
                prompts_dir=args.prompts_dir,
            )

    scores = {v: runner.score_records(dataset, records[v]) for v in variants}
    try:
        ab = paired_ab(scores[args.baseline], scores[args.candidate], seed=args.seed)
    except ValueError as exc:
        raise CliError(f"não foi possível comparar: {exc}") from exc

    lines = [
        "# Relatório de avaliação A/B",
        "",
        f"- Comando: `{_reproducible_command(args)}`",
        f"- Modelo: {config.model}",
        f"- Semente: {args.seed}",
        f"- Casos: {len(cases)}",
        f"- Respostas: {'gravadas (--reuse)' if args.reuse else 'geradas nesta execução'}",
        f"- Data: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "## Métrica determinística",
        "",
        format_ab_markdown(ab, args.baseline, args.candidate, "checagens determinísticas"),
        "## Taxa de aprovação por checagem",
        "",
        "Aprovados/aplicáveis (a checagem não se aplica a todos os casos).",
        "",
        _rates_table({v: _check_rates(cases, records[v]) for v in variants}, variants),
    ]

    if args.judge:
        llm = judge_mod.make_ollama_judge_llm(config.model, args.seed)
        judged = {v: judge_mod.judge_records(dataset, records[v], llm=llm) for v in variants}
        judge_scores = {v: {cid: r.score for cid, r in judged[v].items()} for v in variants}
        try:
            jab = paired_ab(
                judge_scores[args.baseline], judge_scores[args.candidate], seed=args.seed
            )
        except ValueError as exc:
            raise CliError(f"não foi possível comparar as notas do juiz: {exc}") from exc
        lines += [
            "## Juiz (LLM-as-judge)",
            "",
            JUDGE_WARNING,
            "",
            format_ab_markdown(jab, args.baseline, args.candidate, "nota do juiz, 1 a 5"),
        ]
        judge_errors = {v: sum(r.error is not None for r in judged[v].values()) for v in variants}
    else:
        judge_errors = {}

    lines += [
        "## Erros",
        "",
        "| Variante | Erros do agente | Erros do juiz |",
        "|---|---|---|",
    ]
    for v in variants:
        agent_err = sum(r.get("error") is not None for r in records[v])
        judge_err = judge_errors[v] if args.judge else "n/a"
        lines.append(f"| {v} | {agent_err} | {judge_err} |")
    lines.append("")

    regression = ab.mean_diff < 0 and ab.p_value < ALPHA
    if args.fail_on_regression:
        rule = (
            f"Regra do gate (--fail-on-regression): falha (código 1) se a diferença média "
            f"da métrica determinística for < 0 e p-valor < {ALPHA}. Observado: diferença "
            f"{ab.mean_diff:+.4f}, p-valor {ab.p_value:.4f}. "
            f"Resultado: {'regressão detectada, código 1' if regression else 'sem regressão, código 0'}."
        )
        lines += ["## Gate de regressão", "", rule, ""]

    report = "\n".join(lines)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report, encoding="utf-8")
    return 1 if args.fail_on_regression and regression else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aok", description="agent-ops-kit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("eval", help="compara duas variantes de prompt (A/B pareado)")
    p.add_argument("--baseline", required=True, help="variante de referência (ex.: v1)")
    p.add_argument("--candidate", required=True, help="variante candidata (ex.: v2)")
    p.add_argument("--dataset", default="evals/dataset.jsonl")
    p.add_argument("--prompts-dir", default="evals/prompts")
    p.add_argument("--config", default="examples/rag_agent/agent.yaml")
    p.add_argument("--answers-dir", default="evals/answers")
    p.add_argument("--reuse", action="store_true", help="relê as respostas gravadas, sem modelo")
    p.add_argument("--judge", action="store_true", help="avalia também com o juiz (usa o modelo)")
    p.add_argument("--limit", type=int, default=None, help="usa só os N primeiros casos")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--report", default=None, help="grava o relatório markdown neste caminho")
    p.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="código 1 se diferença média < 0 e p-valor < 0.05 (métrica determinística)",
    )
    p.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
