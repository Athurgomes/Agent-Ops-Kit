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
    if args.no_verify:
        tokens.append("--no-verify")
    if args.judge:
        tokens.append("--judge")
    if args.limit is not None:
        tokens += ["--limit", str(args.limit)]
    if args.prices:
        tokens += ["--prices", args.prices]
    tokens += ["--seed", str(args.seed)]
    if args.report:
        tokens += ["--report", args.report]
    if args.fail_on_regression:
        tokens.append("--fail-on-regression")
    return shlex.join(tokens)


def _answers_source(args: argparse.Namespace) -> str:
    if not args.reuse:
        return "geradas nesta execução"
    if args.no_verify:
        return "gravadas (--reuse), manifesto NÃO verificado (--no-verify)"
    return "gravadas (--reuse), manifesto verificado"


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


OPS_NOTES = (
    "Valores por caso (soma das chamadas de LLM do caso), não por chamada.",
    (
        "A latência depende do hardware e da carga do modelo (a 1ª execução inclui a carga a frio). "
        "Com `--reuse`, a latência vem das respostas gravadas (não é medida no CI)."
    ),
)


def _fmt(value: float | None, digits: int = 2) -> str:
    return "n/d" if value is None else f"{value:.{digits}f}"


def _ops_table(summaries: dict[str, dict], variants: list[str]) -> str:
    rows = [
        ("Casos", lambda s: str(s["llm_calls"])),
        ("Latência por caso, p50 (s)", lambda s: _fmt(s["llm_latency_p50_s"])),
        ("Latência por caso, p95 (s)", lambda s: _fmt(s["llm_latency_p95_s"])),
        ("Tokens de entrada, média por caso", lambda s: _fmt(s["avg_input_tokens"])),
        ("Tokens de saída, média por caso", lambda s: _fmt(s["avg_output_tokens"])),
        ("Taxa de erro do agente", lambda s: _fmt(s["agent_error_rate"], 4)),
        ("Taxa de erro de tool", lambda s: "n/d (o runner não registra tools por caso)"),
        ("Custo estimado", lambda s: _fmt(s["estimated_cost"], 4)),
    ]
    lines = ["| Métrica | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(summaries[v]) for v in variants) + " |")
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
    import yaml

    from agent_ops_kit.config import load_config
    from agent_ops_kit.eval import judge as judge_mod
    from agent_ops_kit.eval import runner
    from agent_ops_kit.eval.ab import format_ab_markdown, paired_ab
    from agent_ops_kit.eval.dataset import load_dataset
    from agent_ops_kit.eval.prompts import load_prompt
    from agent_ops_kit.metrics import PriceTable, summarize_records

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

    price_table = None
    if args.prices:
        if not Path(args.prices).is_file():
            raise CliError(f"tabela de preços não encontrada: {args.prices}")
        try:
            price_table = PriceTable.from_yaml(args.prices)
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            raise CliError(f"tabela de preços inválida: {exc}") from exc
    price_table = price_table or PriceTable.default()

    dataset = load_dataset(args.dataset)
    config = load_config(args.config)
    cases = dataset[: args.limit] if args.limit is not None else dataset
    case_ids = {c.id for c in cases}

    if args.reuse and not args.no_verify:
        try:
            runner.verify_manifest(answers_dir, variants, config, args.dataset, args.prompts_dir)
        except runner.ManifestError as exc:
            raise CliError(str(exc)) from exc

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
            entry = runner.manifest_entry(
                v, config, args.dataset, len(records[v]), args.seed, args.prompts_dir
            )
            runner.write_manifest_entry(answers_dir, v, entry)

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
        f"- Respostas: {_answers_source(args)}",
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
        "## Métricas operacionais",
        "",
        _ops_table(
            {v: summarize_records(records[v], config.model, price_table) for v in variants},
            variants,
        ),
        *[f"- {n}" for n in OPS_NOTES],
        f"- Custo ({config.model}): {price_table.note} "
        + (
            "Modelo fora da tabela: n/d."
            if config.model not in price_table.prices
            else "Local = 0.0."
            if price_table.prices[config.model] == (0.0, 0.0)
            else "Preço da tabela informada."
        ),
        "",
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


def cmd_redteam(args: argparse.Namespace) -> int:
    """`aok redteam run|report`. Deve rodar na raiz do repositório (como o eval)."""
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    if args.redteam_cmd == "run":
        from agent_ops_kit.redteam import harness

        argv: list[str] = []
        if args.guardrails not in (None, "none"):
            argv += ["--guardrails", args.guardrails]
        if args.out:
            argv += ["--out", args.out]
        if args.limit is not None:
            argv += ["--limit", str(args.limit)]
        argv += ["--seed", str(args.seed)]
        if args.attacks_dir:
            argv += ["--attacks-dir", args.attacks_dir]
        return harness.main(argv)

    from agent_ops_kit.redteam.report import ReportError, build_report

    try:
        text = build_report(args.baseline, args.guardrails, args.fp_dir, args.dataset, args.v1_answers)
    except ReportError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


def _chain_text(res) -> str:
    if res.ok:
        return f"Cadeia íntegra ({res.n_lines} eventos)"
    where = f"na linha {res.first_bad_line}" if res.first_bad_line else "(âncora)"
    return f"Cadeia QUEBRADA {where}: {res.reason}"


def cmd_audit(args: argparse.Namespace) -> int:
    """`aok audit verify|report|anchor` sobre um log de auditoria."""
    from agent_ops_kit import audit

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.audit_cmd == "verify":
        try:
            res = audit.verify(args.log, args.anchor, args.expected_n)
        except FileNotFoundError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        print(_chain_text(res))
        return 0 if res.ok else 1

    if args.audit_cmd == "anchor":
        try:
            print(audit.anchor(args.log))
        except FileNotFoundError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        except audit.AuditChainError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 1
        return 0

    try:
        text = audit.report(args.log, title=args.title)
        res = audit.verify(args.log)
    except FileNotFoundError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Relatório gravado em {args.output}")
    else:
        print(text)
    print(_chain_text(res))
    return 0


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
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="com --reuse, não confere o manifesto (prompt, dataset, modelo) das respostas",
    )
    p.add_argument("--judge", action="store_true", help="avalia também com o juiz (usa o modelo)")
    p.add_argument("--limit", type=int, default=None, help="usa só os N primeiros casos")
    p.add_argument("--prices", default=None, help="YAML de preços {modelo: {input, output}} por 1M tokens")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--report", default=None, help="grava o relatório markdown neste caminho")
    p.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="código 1 se diferença média < 0 e p-valor < 0.05 (métrica determinística)",
    )
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("redteam", help="suíte de red team: roda ataques ou gera o relatório")
    rsub = p.add_subparsers(dest="redteam_cmd", required=True)
    r = rsub.add_parser("run", help="roda a suíte (usa o modelo local)")
    r.add_argument("--guardrails", default="none", help='"none", "all" ou lista separada por vírgulas')
    r.add_argument("--out", default=None, help="JSONL de saída (obrigatório com --guardrails)")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--attacks-dir", default=None)
    r = rsub.add_parser("report", help="relatório markdown a partir dos JSONL gravados (sem modelo)")
    r.add_argument("--baseline", required=True, help="JSONL sem guardrails")
    r.add_argument("--guardrails", required=True, help="JSONL com guardrails")
    r.add_argument("--fp-dir", default=None, help="pasta com fp_dataset.jsonl e fp_benign.jsonl")
    r.add_argument("--dataset", default="evals/dataset.jsonl")
    r.add_argument("--v1-answers", default="evals/answers/v1.jsonl")
    r.add_argument("--output", default=None, help="grava o markdown neste caminho")
    p.set_defaults(func=cmd_redteam)

    p = sub.add_parser("audit", help="log de auditoria: verifica a cadeia, gera relatório, âncora")
    asub = p.add_subparsers(dest="audit_cmd", required=True)
    a = asub.add_parser("verify", help="recalcula a cadeia de hashes (código 1 se quebrada)")
    a.add_argument("log")
    a.add_argument("--anchor", default=None, help="último hash esperado (guardado fora do arquivo)")
    a.add_argument("--expected-n", type=int, default=None, help="número de eventos esperado")
    a = asub.add_parser("report", help="relatório markdown do log")
    a.add_argument("log")
    a.add_argument("--output", default=None, help="grava o markdown neste caminho")
    a.add_argument("--title", default="Relatório de auditoria")
    a = asub.add_parser("anchor", help="imprime o último hash (para guardar fora do arquivo)")
    a.add_argument("log")
    p.set_defaults(func=cmd_audit)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
