"""CLI única do agent-ops-kit (`aok`). Cada subcomando é uma função isolada (`cmd_*`)."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

ALPHA = 0.05
DEFAULT_EVAL_REPORT = "reports/eval_report.md"
DEFAULT_REDTEAM_REPORT = "reports/redteam_report.md"
DEFAULT_CONFIG = "examples/rag_agent/agent.yaml"
# Resultados do agente de exemplo: só valem quando NENHUM argumento de red team é informado.
RT_DEFAULTS = (
    "redteam/results/baseline.jsonl", "redteam/results/guardrails.jsonl", "redteam/results",
)

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
    if getattr(args, "runs", 1) != 1:
        tokens += ["--runs", str(args.runs)]
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


def _variance_section(variance: dict[str, dict], variants: list[str]) -> list[str]:
    lines = [
        "## Variância entre execuções",
        "",
        (
            "| Variante | Execuções | Média | Desvio-padrão (execuções) | "
            "Desvio médio por caso | Consistência exata (score / resposta) |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for v in variants:
        s = variance[v]
        consistency = (
            f"{s['exact_score_consistency_rate']:.1%} / "
            f"{s['exact_answer_consistency_rate']:.1%}"
        )
        lines.append(
            f"| {v} | {s['n_runs']} | {s['mean']:.4f} | {s['run_stdev']:.4f} | "
            f"{s['mean_case_stdev']:.4f} | {consistency} |"
        )
    lines.append("")
    for v in variants:
        means = ", ".join(f"{m:.4f}" for m in variance[v]["per_run_means"])
        lines.append(f"- Médias por execução ({v}): [{means}]")
    lines.append("")
    return lines


def _cost_note(model: str, price_table, records: dict[str, list[dict]]) -> str:
    """Rodapé do custo. Sem tokens registrados (agente que não usa o `llm` do kit) o custo é n/d."""
    if any(r.get("input_tokens") is None for recs in records.values() for r in recs):
        return "n/d (tokens não registrados: o agente não recebeu ou não declarou o `llm` do kit)."
    return f"{price_table.note} " + (
        "Modelo fora da tabela: n/d."
        if model not in price_table.prices
        else "Local = 0.0."
        if price_table.prices[model] == (0.0, 0.0)
        else "Preço da tabela informada."
    )


EXTERNAL_VARIANTS_WARNING = (
    "Aviso: o agente é externo (`target`) e usa o próprio prompt; as variantes de prompt "
    "({b} e {c}) do kit não se aplicam. A comparação abaixo não mede diferença de prompt: "
    "a diferença observada vem só da variação do agente."
)


def _eval_summary(
    args, ab, n_cases: int, gate: str | None, path: str, defaulted: bool, n_runs: int = 1,
    external: bool = False,
) -> str:
    """Placar curto do `aok eval --summary`: só números e o caminho do relatório completo."""
    b, c = args.baseline, args.candidate
    runs_part = f", {n_runs} execuções" if n_runs > 1 else ""
    lines = [
        (
            f"Avaliação A/B: {b} (baseline) vs {c} (candidate), {n_cases} casos "
            f"({ab.n} pareados){runs_part}, semente {args.seed}"
        ),
        f"  média {b}: {ab.mean_baseline:.4f}",
        f"  média {c}: {ab.mean_candidate:.4f}",
        f"  diferença ({c} - {b}): {ab.mean_diff:+.4f}",
        f"  IC 95%: [{ab.ci_low:+.4f}; {ab.ci_high:+.4f}]  p-valor: {ab.p_value:.4f} ({ab.p_method})",
    ]
    if external:
        lines.append("  AVISO: agente externo; as variantes de prompt não se aplicam (ver o relatório)")
    if gate:
        lines.append(f"  gate (--fail-on-regression): {gate}")
    lines.append(f"Relatório completo: {path}")
    if defaulted:
        lines.append("(--report não informado: relatório gravado no caminho padrão)")
    return "\n".join(lines)


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

    from agent_ops_kit import provenance
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
    if args.runs < 1:
        raise CliError("--runs deve ser >= 1")
    if args.reuse and args.runs != 1:
        raise CliError(
            "--runs não pode ser usado com --reuse "
            "(com --reuse são usadas todas as execuções já gravadas)"
        )
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
    if not args.reuse and config.target is not None and config.target.type == "http":
        from agent_ops_kit.target_http import http_target_warning

        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
        print(http_target_warning(config.target), file=sys.stderr)
    exec_info: dict | None = None  # capturado uma vez, só quando o modelo roda (sem --reuse)
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
                runs=args.runs,
            )
            if exec_info is None:
                exec_info = {
                    **provenance.execution_info(config.model, _reproducible_command(args)),
                    **provenance.target_info(config),
                }
            entry = runner.manifest_entry(
                v, config, args.dataset, len(records[v]), args.seed, args.prompts_dir,
                answers_path=path, extra=exec_info,
            )
            runner.write_manifest_entry(answers_dir, v, entry)

    scores = {v: runner.score_records(dataset, records[v]) for v in variants}
    variance = {v: runner.summarize_runs(dataset, records[v]) for v in variants}
    has_multirun = any(s["n_runs"] > 1 for s in variance.values())
    try:
        ab = paired_ab(scores[args.baseline], scores[args.candidate], seed=args.seed)
    except ValueError as exc:
        raise CliError(f"não foi possível comparar: {exc}") from exc

    meta_lines = [
        "# Relatório de avaliação A/B",
        "",
        f"- Comando: `{_reproducible_command(args)}`",
        f"- Modelo: {config.model}",
        f"- Semente: {args.seed}",
        f"- Casos: {len(cases)}",
    ]
    if config.target is not None:
        meta_lines += ["", EXTERNAL_VARIANTS_WARNING.format(b=args.baseline, c=args.candidate), ""]
    if has_multirun:
        runs_vals = [variance[v]["n_runs"] for v in variants]
        runs_label = (
            str(runs_vals[0])
            if len(set(runs_vals)) == 1
            else ", ".join(f"{v}: {variance[v]['n_runs']}" for v in variants)
        )
        meta_lines.append(f"- Execuções por configuração: {runs_label}")
    meta_lines += [
        f"- Respostas: {_answers_source(args)}",
        f"- Data: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "## Métrica determinística",
        "",
        format_ab_markdown(ab, args.baseline, args.candidate, "checagens determinísticas"),
    ]
    if has_multirun:
        meta_lines += _variance_section(variance, variants)
    lines = meta_lines + [
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
        f"- Custo ({config.model}): " + _cost_note(config.model, price_table, records),
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
    if args.summary:
        out_path = args.report or DEFAULT_EVAL_REPORT
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(report, encoding="utf-8")
        gate = None
        if args.fail_on_regression:
            gate = "REGRESSÃO detectada (código 1)" if regression else "sem regressão (código 0)"
        n_runs_summary = max((s["n_runs"] for s in variance.values()), default=1)
        print(
            _eval_summary(
                args, ab, len(cases), gate, out_path, defaulted=not args.report,
                n_runs=n_runs_summary, external=config.target is not None,
            )
        )
        return 1 if args.fail_on_regression and regression else 0
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
        if args.config:
            argv += ["--config", args.config]
        if args.attacks_dir:
            argv += ["--attacks-dir", args.attacks_dir]
        if args.blind_attacks_dir:
            argv += ["--blind-attacks-dir", args.blind_attacks_dir]
        if args.blind_only:
            argv += ["--blind-only"]
        if args.universal:
            argv += ["--universal"]
        if args.evidence_root:
            argv += ["--evidence-root", args.evidence_root]
        return harness.main(argv)

    from agent_ops_kit.redteam.report import ReportError, build_report, build_summary

    try:
        text = build_report(args.baseline, args.guardrails, args.fp_dir, args.dataset, args.v1_answers)
        if args.summary:
            out_path = args.output or DEFAULT_REDTEAM_REPORT
            summary = build_summary(args.baseline, args.guardrails, args.fp_dir, out_path)
    except ReportError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.summary:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
        print(summary)
        if not args.output:
            print("(--output não informado: relatório gravado no caminho padrão)")
        return 0
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


def _resolve_hmac_env(env_name: str | None) -> str | None:
    if not env_name:
        return None
    val = os.environ.get(env_name)
    if not val:
        raise ValueError(f"variável de ambiente {env_name} ausente ou vazia")
    return val


def cmd_audit(args: argparse.Namespace) -> int:
    """`aok audit verify|report|anchor|keygen|sign` sobre um log de auditoria."""
    from agent_ops_kit import audit, audit_sign

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.audit_cmd == "keygen":
        try:
            info = audit_sign.generate_ed25519_keypair(
                args.private_out, args.public_out, overwrite=args.overwrite
            )
        except (FileExistsError, ValueError, OSError) as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        print(f"Par Ed25519 gerado ({info['algorithm']})")
        print(f"Fingerprint: {info['key_fingerprint']}")
        print(f"Chave privada: {info['private_path']}")
        print(f"Chave pública: {info['public_path']}")
        return 0

    if args.audit_cmd == "sign":
        try:
            hmac_key = _resolve_hmac_env(args.hmac_key_env)
            receipt = audit_sign.sign_anchor(
                args.log,
                private_key_path=args.private_key,
                hmac_key=hmac_key,
                out_path=args.out,
            )
        except audit.AuditChainError as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 1
        except (FileNotFoundError, ValueError, OSError) as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        print(
            f"Âncora assinada ({receipt['algorithm']}, {receipt['n_events']} eventos, "
            f"fingerprint {receipt['key_fingerprint']}) -> {args.out}"
        )
        return 0

    if args.audit_cmd == "verify":
        if args.public_key and args.hmac_key_env:
            print("erro: informe apenas --public-key ou --hmac-key-env", file=sys.stderr)
            return 2
        if (args.public_key or args.hmac_key_env) and not args.signature:
            print("erro: --public-key/--hmac-key-env exige --signature", file=sys.stderr)
            return 2
        if args.signature and not (args.public_key or args.hmac_key_env):
            print("erro: --signature exige --public-key ou --hmac-key-env", file=sys.stderr)
            return 2
        try:
            hmac_key = _resolve_hmac_env(args.hmac_key_env) if args.signature else None
            res = audit.verify(args.log, args.anchor, args.expected_n)
        except (FileNotFoundError, ValueError) as exc:
            print(f"erro: {exc}", file=sys.stderr)
            return 2
        print(_chain_text(res))
        if not res.ok:
            return 1
        if args.signature:
            sres = audit_sign.verify_signature(
                args.log,
                args.signature,
                public_key_path=args.public_key,
                hmac_key=hmac_key,
            )
            if sres.ok:
                print(
                    f"Assinatura válida ({sres.algorithm}, fingerprint {sres.key_fingerprint}, "
                    f"{sres.n_events} eventos)"
                )
                return 0
            print(f"Assinatura INVÁLIDA: {sres.reason}")
            return 1
        return 0

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


def _write_package(args: argparse.Namespace) -> dict:
    """Gera relatorio.{json,md,html} em args.out (compartilhado por `report build` e `check`)."""
    import json

    from agent_ops_kit import audit_sign
    from agent_ops_kit.redteam.report import ReportError
    from agent_ops_kit.report import build, render

    if args.audit_public_key and args.audit_hmac_key_env:
        raise ReportError("informe apenas --audit-public-key ou --audit-hmac-key-env")
    if (args.audit_signature or args.audit_public_key or args.audit_hmac_key_env) and not args.audit:
        raise ReportError("--audit-signature exige --audit")
    if (args.audit_public_key or args.audit_hmac_key_env) and not args.audit_signature:
        raise ReportError("--audit-public-key/--audit-hmac-key-env exige --audit-signature")
    if args.audit_signature and not (args.audit_public_key or args.audit_hmac_key_env):
        raise ReportError("--audit-signature exige --audit-public-key ou --audit-hmac-key-env")
    try:
        hmac_key = _resolve_hmac_env(args.audit_hmac_key_env)
    except ValueError as exc:
        raise ReportError(str(exc)) from exc

    given = [args.redteam_baseline, args.redteam_guardrails, args.fp_dir]
    if all(g is None for g in given):
        args.redteam_baseline, args.redteam_guardrails, args.fp_dir = RT_DEFAULTS
    elif any(g is None for g in given):
        raise ReportError(
            "informe --redteam-baseline, --redteam-guardrails e --fp-dir juntos (ou nenhum, para "
            "usar os resultados do agente de exemplo); misturar execuções de agentes diferentes "
            "não é permitido. Com target externo, o kit não aplica guardrails: passe o mesmo "
            "JSONL nos dois primeiros"
        )
    cwd = os.getcwd()  # o runner importa examples.rag_agent, na raiz do repositório
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    data = build.build_data(
        config=args.config,
        dataset=args.dataset,
        prompts_dir=args.prompts_dir,
        answers_dir=args.answers_dir,
        baseline=args.baseline,
        candidate=args.candidate,
        seed=args.seed,
        redteam_baseline=args.redteam_baseline,
        redteam_guardrails=args.redteam_guardrails,
        fp_dir=args.fp_dir,
        audit_path=args.audit,
        audit_signature=args.audit_signature,
        audit_public_key=args.audit_public_key,
        audit_hmac_key=hmac_key,
        previous=args.previous,
        policy=args.policy,
        coverage_map=args.coverage_map,
        evidence_root=args.evidence_root,
        command="aok " + shlex.join(getattr(args, "argv", None) or sys.argv[1:]),
    )
    blocks = render.build_blocks(data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    title = f"Relatório de teste do agente {data['agent']['name']}"
    json_bytes = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    sig_path = out / "relatorio.json.sig"
    try:
        key_pem = audit_sign.signing_key_from_env()
        receipt = audit_sign.sign_bytes(json_bytes, key_pem) if key_pem else None
    except ValueError as exc:
        raise ReportError(str(exc)) from None
    (out / "relatorio.json").write_bytes(json_bytes)
    if receipt:
        sig_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    else:
        sig_path.unlink(missing_ok=True)  # um .sig antigo não vale para o json novo
    (out / "relatorio.md").write_text(render.to_markdown(blocks), encoding="utf-8")
    (out / "relatorio.html").write_text(render.to_html(blocks, title), encoding="utf-8")
    return data


def cmd_report_verify(args: argparse.Namespace) -> int:
    """`aok report verify`: confere offline um pacote contra os arquivos de evidência (exit 0/1/2)."""
    import json

    from agent_ops_kit.report import verify

    try:
        hmac_key = _resolve_hmac_env(args.audit_hmac_key_env)
        result = verify.verify_package(
            args.package, args.repo_root, hmac_key, args.public_key, args.require_signature,
            args.evidence_root,
        )
    except (verify.PackageError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(verify.format_table(result))
    return 0 if result["ok"] else 1


def cmd_report(args: argparse.Namespace) -> int:
    """`aok report build|verify`: pacote relatorio.{json,md,html} e sua verificação offline."""
    from agent_ops_kit.redteam.report import ReportError
    from agent_ops_kit.report import render

    if args.report_cmd == "verify":
        return cmd_report_verify(args)
    try:
        data = _write_package(args)
    except (ReportError, OSError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    label = render.COLOR_LABEL[data["semaphore"]["color"]]
    print(f"Pacote gravado em {Path(args.out).as_posix()}/ (relatorio.md, relatorio.html, relatorio.json)")
    print(f"Semáforo (regras provisórias): {label}")
    if (Path(args.out) / "relatorio.json.sig").is_file():
        print("Assinado: relatorio.json.sig (Ed25519)")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """`aok check`: gera o pacote (sem modelo) e, com --publish, publica em pasta local versionada."""
    from agent_ops_kit.redteam.report import ReportError
    from agent_ops_kit.report import publish, render

    for stream in (sys.stdout, sys.stderr):  # avisos e erros também saem com acento correto no Windows
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    config_given = args.config is not None
    if not config_given:
        args.config = DEFAULT_CONFIG
    try:
        agent_id = args.agent_id
        if args.publish:
            if agent_id is None and not config_given:
                raise publish.PublishError("--publish exige --agent-id ou --config")
            if agent_id is not None:
                publish.validate_agent_id(agent_id)
        remote = bool(args.publish) and publish.is_url(args.publish)
        if remote and agent_id is None:
            from agent_ops_kit.config import load_config

            plat = load_config(args.config).platform
            agent_id = plat.agent_id if plat else None
        data = _write_package(args)
        if args.publish:
            if agent_id is None:
                agent_id = data["agent"]["name"]
            if remote:
                seq, color = publish.publish_remote(args.out, args.publish, agent_id)
            else:
                dest, color = publish.publish(args.out, args.publish, agent_id)
    except (ReportError, publish.PublishError, OSError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    print(f"Pacote gravado em {Path(args.out).as_posix()}/ (relatorio.md, relatorio.html, relatorio.json)")
    print(f"Semáforo (regras provisórias): {render.COLOR_LABEL[data['semaphore']['color']]}")
    if args.publish and remote:
        print(f"Publicado na plataforma como versão {seq} (semáforo: {color})")
    elif args.publish:
        print(f"Publicado em {dest.as_posix()} (semáforo: {color})")
    return 0


def cmd_reproduce(args: argparse.Namespace) -> int:
    """`aok reproduce PACOTE`: reexecuta o pacote e compara com o declarado (exit 0 = reexecutou;
    os vereditos estão no reproducao.json; 2 = recusa ou erro). Roda na raiz do repositório."""
    from agent_ops_kit import reproduce

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        res = reproduce.reproduce(
            args.package, only=args.only, out=args.out, repo_root=".",
            evidence_root=args.evidence_root, audit_log=args.audit_log,
            signing_key=args.signing_key, public_key=args.public_key,
            hmac_key=_resolve_hmac_env(args.audit_hmac_key_env), limit=args.limit,
            command=reproduce.command_from_argv(args.argv),
            log=lambda msg: print(msg, flush=True),
        )
    except (reproduce.ReproduceError, ValueError, OSError) as exc:
        print(f"erro: {reproduce.scrub(str(exc), {'cwd': Path.cwd()})}", file=sys.stderr)
        return 2
    d = res["data"]
    counts = ", ".join(f"{k} {v}" for k, v in d["verdict_counts"].items())
    print(f"Reexecução gravada em {res['out'].as_posix()}/ (reproducao.json, reproducao.md)")
    print(f"Ambiente: {d['environment']['status']}" + (" (reexecução parcial)" if d["parameters"]["partial"] else ""))
    print(f"Vereditos: {counts}")
    print("Descrição, não aprovação: veja reproducao.md.")
    print(f"Log de auditoria: {res['audit_log'].as_posix()} (evento reproduction, seq {res['audit_seq']})")
    if res["signature"]:
        print(f"Âncora assinada: {res['signature'].as_posix()}")
    elif res["stale_signature"]:
        print("AVISO: há uma assinatura anterior ao lado do log; ela não cobre o novo evento (reassine).")
    return 0


NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_TEMPLATE_TEXT_SUFFIXES = {".py", ".md", ".yaml"}


def _copy_template(src, dst: Path, name: str) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir(), key=lambda i: i.name):
        if item.name == "__pycache__":
            continue
        target = dst / (".gitignore" if item.name == "gitignore" else item.name)
        if item.is_dir():
            _copy_template(item, target, name)
            continue
        if Path(item.name).suffix in _TEMPLATE_TEXT_SUFFIXES:
            text = item.read_text(encoding="utf-8").replace("__NAME__", name)
            target.write_text(text, encoding="utf-8", newline="\n")
        else:
            target.write_bytes(item.read_bytes())


def cmd_new(args: argparse.Namespace) -> int:
    """`aok new <nome> [--dir DESTINO]`: gera um agente RAG já instrumentado a partir do template."""
    from importlib.resources import files

    name = args.name
    if not NAME_RE.fullmatch(name):
        print(
            "erro: nome inválido; use letras minúsculas, dígitos, hífen ou sublinhado "
            "(até 64 caracteres, começando por letra ou dígito)",
            file=sys.stderr,
        )
        return 2
    dest = Path(args.dir or ".") / name
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        print(f"erro: {dest} já existe e não está vazia; nada foi sobrescrito", file=sys.stderr)
        return 2
    _copy_template(files("agent_ops_kit") / "templates" / "agent", dest, name)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    shown = dest.as_posix()
    print(f"Agente '{name}' criado em {shown}")
    print("  agent.yaml (guardrails e auditoria ligados), corpus/ (3 documentos fictícios), run.py")
    print("Próximos passos:")
    print(f"  cd {shown}")
    print('  python run.py "Quantos dias de férias a Aurora Papéis concede?"')
    print(f"  aok audit verify {shown}/audit/{name}.jsonl")
    print("  Jaeger: docker compose up -d (ver README.md do agente)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aok", description="agent-ops-kit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new", help="gera um agente RAG já instrumentado (tracing, auditoria, guardrails)")
    p.add_argument("name", help="nome do agente (minúsculas, dígitos, - e _)")
    p.add_argument("--dir", default=None, help="pasta onde criar o agente (padrão: pasta atual)")
    p.set_defaults(func=cmd_new)

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
    p.add_argument(
        "--runs",
        type=int,
        default=1,
        help="execuções por caso para medir variância entre execuções (padrão: 1)",
    )
    p.add_argument("--prices", default=None, help="YAML de preços {modelo: {input, output}} por 1M tokens")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--report", default=None, help="grava o relatório markdown neste caminho")
    p.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="código 1 se diferença média < 0 e p-valor < 0.05 (métrica determinística)",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help=f"imprime só um placar curto; o relatório completo vai para --report "
        f"(padrão: {DEFAULT_EVAL_REPORT})",
    )
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("redteam", help="suíte de red team: roda ataques ou gera o relatório")
    rsub = p.add_subparsers(dest="redteam_cmd", required=True)
    r = rsub.add_parser("run", help="roda a suíte (usa o modelo local)")
    r.add_argument("--guardrails", default="none", help='"none", "all" ou lista separada por vírgulas')
    r.add_argument("--out", default=None, help="JSONL de saída (obrigatório com --guardrails)")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--seed", type=int, default=42)
    r.add_argument("--config", default=None, help="agent.yaml do agente a auditar (padrão: exemplo)")
    r.add_argument("--attacks-dir", default=None)
    r.add_argument(
        "--blind-attacks-dir",
        default=None,
        help="diretório externo com *.jsonl da suíte cega (ou use AOK_BLIND_ATTACKS_DIR)",
    )
    r.add_argument(
        "--blind-only",
        action="store_true",
        help="executa apenas a suíte cega (requer --blind-attacks-dir ou AOK_BLIND_ATTACKS_DIR)",
    )
    r.add_argument(
        "--universal",
        action="store_true",
        help="gera e executa a bateria universal v1 parametrizada pelo --config",
    )
    r.add_argument(
        "--evidence-root", default=None,
        help="raiz das evidências fora do repositório (caminhos gravados como @evidence/...)",
    )
    r = rsub.add_parser("report", help="relatório markdown a partir dos JSONL gravados (sem modelo)")
    r.add_argument("--baseline", required=True, help="JSONL sem guardrails")
    r.add_argument("--guardrails", required=True, help="JSONL com guardrails")
    r.add_argument("--fp-dir", default=None, help="pasta com fp_dataset.jsonl e fp_benign.jsonl")
    r.add_argument("--dataset", default="evals/dataset.jsonl")
    r.add_argument("--v1-answers", default="evals/answers/v1.jsonl")
    r.add_argument("--output", default=None, help="grava o markdown neste caminho")
    r.add_argument(
        "--summary",
        action="store_true",
        help=f"imprime só a tabela compacta; o relatório completo vai para --output "
        f"(padrão: {DEFAULT_REDTEAM_REPORT})",
    )
    p.set_defaults(func=cmd_redteam)

    p = sub.add_parser("audit", help="log de auditoria: verifica a cadeia, gera relatório, âncora e assinatura")
    asub = p.add_subparsers(dest="audit_cmd", required=True)
    a = asub.add_parser("verify", help="recalcula a cadeia de hashes (código 1 se quebrada)")
    a.add_argument("log")
    a.add_argument("--anchor", default=None, help="último hash esperado (guardado fora do arquivo)")
    a.add_argument("--expected-n", type=int, default=None, help="número de eventos esperado")
    a.add_argument("--signature", default=None, help="recibo JSON da assinatura da âncora")
    vg = a.add_mutually_exclusive_group()
    vg.add_argument("--public-key", default=None, help="chave pública Ed25519 em PEM")
    vg.add_argument("--hmac-key-env", default=None, help="variável de ambiente com a chave HMAC")
    a = asub.add_parser("report", help="relatório markdown do log")
    a.add_argument("log")
    a.add_argument("--output", default=None, help="grava o markdown neste caminho")
    a.add_argument("--title", default="Relatório de auditoria")
    a = asub.add_parser("anchor", help="imprime o último hash (para guardar fora do arquivo)")
    a.add_argument("log")
    a = asub.add_parser("keygen", help="gera par de chaves Ed25519 em PEM (PKCS8) para assinar âncoras")
    a.add_argument("--private-out", required=True, help="caminho de saída da chave privada PEM")
    a.add_argument("--public-out", required=True, help="caminho de saída da chave pública PEM")
    a.add_argument("--overwrite", action="store_true", help="permite sobrescrever arquivos existentes")
    a = asub.add_parser("sign", help="assina a âncora do log e grava recibo JSON")
    a.add_argument("log")
    a.add_argument("--out", required=True, help="caminho de saída do recibo de assinatura (.sig.json)")
    sg = a.add_mutually_exclusive_group(required=True)
    sg.add_argument("--private-key", default=None, help="chave privada Ed25519 em PEM")
    sg.add_argument("--hmac-key-env", default=None, help="variável de ambiente com a chave HMAC")
    p.set_defaults(func=cmd_audit)

    def add_package_args(r, config_default):
        r.add_argument("--baseline", default="v1", help="variante de referência do eval")
        r.add_argument("--candidate", default="v2", help="variante candidata do eval")
        r.add_argument("--dataset", default="evals/dataset.jsonl")
        r.add_argument("--prompts-dir", default="evals/prompts")
        r.add_argument("--config", default=config_default)
        r.add_argument("--answers-dir", default="evals/answers", help="pasta com as respostas e o manifest.json")
        r.add_argument("--seed", type=int, default=42)
        r.add_argument(
            "--redteam-baseline", default=None,
            help=f"JSONL do red team sem guardrails (padrão do repositório: {RT_DEFAULTS[0]}; "
            "os três argumentos de red team vão juntos ou nenhum)",
        )
        r.add_argument(
            "--redteam-guardrails", default=None,
            help=f"JSONL do red team com guardrails (padrão do repositório: {RT_DEFAULTS[1]})",
        )
        r.add_argument(
            "--fp-dir", default=None,
            help=f"pasta com fp_dataset.jsonl e fp_benign.jsonl (padrão do repositório: {RT_DEFAULTS[2]})",
        )
        r.add_argument(
            "--evidence-root", default=None,
            help="raiz das evidências fora do repositório (caminhos gravados como @evidence/...)",
        )
        r.add_argument("--audit", default=None, help="log de auditoria (só o resultado da cadeia e a âncora entram)")
        r.add_argument("--audit-signature", default=None, help="recibo JSON da assinatura da âncora de auditoria")
        r.add_argument("--audit-public-key", default=None, help="chave pública Ed25519 em PEM para verificar a assinatura")
        r.add_argument("--audit-hmac-key-env", default=None, help="variável de ambiente com a chave HMAC para verificar a assinatura")
        r.add_argument("--policy", default=None, help="política de classificação YAML (padrão: policies/default.yaml)")
        r.add_argument("--coverage-map", default=None, help="mapa de cobertura OWASP YAML (padrão: policies/coverage/owasp_llm_2025.yaml)")
        r.add_argument("--previous", default=None, help="relatorio.json anterior, para comparar")
        r.add_argument("--out", default="reports/pacote", help="pasta de saída")

    p = sub.add_parser("report", help="pacote de relatório para a liderança (sem modelo)")
    rsub = p.add_subparsers(dest="report_cmd", required=True)
    r = rsub.add_parser("build", help="gera relatorio.md, relatorio.html e relatorio.json")
    add_package_args(r, DEFAULT_CONFIG)
    r = rsub.add_parser("verify", help="confere offline um pacote contra os arquivos de evidência")
    r.add_argument("package", help="pasta do pacote (com relatorio.json)")
    r.add_argument("--repo-root", default=".", help="raiz a que os caminhos do pacote se referem")
    r.add_argument("--json", action="store_true", help="saída em JSON")
    r.add_argument("--audit-hmac-key-env", default=None, help="variável de ambiente com a chave HMAC da assinatura de auditoria")
    r.add_argument("--public-key", default=None, help="chave pública Ed25519 (PEM) para conferir relatorio.json.sig")
    r.add_argument("--require-signature", action="store_true", help="falha se o pacote não tiver relatorio.json.sig")
    r.add_argument("--evidence-root", default=None, help="raiz das evidências fora do repositório (@evidence/...)")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser(
        "reproduce",
        help="reexecuta um pacote de relatório já emitido e compara com o declarado (usa o modelo)",
    )
    p.add_argument("package", help="pasta do pacote (com relatorio.json) ou o próprio relatorio.json")
    p.add_argument("--only", choices=("all", "eval", "redteam"), default="all", help="o que reexecutar")
    p.add_argument("--out", default=None, help="pasta nova de saída (padrão: <pacote>_reproducao ao lado)")
    p.add_argument("--evidence-root", default=None, help="raiz das evidências fora do repositório (@evidence/...)")
    p.add_argument("--audit-log", default=None, help="log de auditoria existente a que acrescentar o evento (padrão: novo, em <out>/audit)")
    p.add_argument("--signing-key", default=None, help="chave privada Ed25519 (PEM) para assinar a âncora do log (padrão: AOK_SIGNING_KEY_FILE/PEM)")
    p.add_argument("--public-key", default=None, help="chave pública Ed25519 (PEM) para conferir relatorio.json.sig")
    p.add_argument("--audit-hmac-key-env", default=None, help="variável de ambiente com a chave HMAC da assinatura de auditoria do pacote")
    p.add_argument("--limit", type=int, default=None, help="reexecuta só os N primeiros casos (teste rápido; reexecução parcial)")
    p.set_defaults(func=cmd_reproduce)

    p = sub.add_parser("check", help="gera o pacote a partir dos resultados gravados e, opcional, publica")
    add_package_args(p, None)
    p.add_argument("--publish", default=None, metavar="ROOT|URL", help="publica em ROOT/<agent-id>/<timestamp UTC>/ (pasta local) ou envia à plataforma (http/https; token em AOK_PLATFORM_TOKEN)")
    p.add_argument("--agent-id", default=None, help="[a-z0-9-], 1 a 64 (padrão: name do --config)")
    p.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.argv = list(sys.argv[1:] if argv is None else argv)  # comando registrado na proveniência
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
