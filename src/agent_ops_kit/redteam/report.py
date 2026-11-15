"""Relatório do red team a partir dos JSONL gravados (sem modelo).

Não imprime texto de ataque nem resposta do modelo: só ids, contagens, estágios e motivos.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_ops_kit.redteam.harness import (
    CATEGORIES,
    AttackRecord,
    asr_by_category,
    load_records,
)

STAGES = ("input", "tool", "output")


class ReportError(Exception):
    """Arquivo ausente ou inválido: mensagem curta para o usuário."""


def _load_attacks(path: Path) -> list[AttackRecord]:
    if not path.is_file():
        raise ReportError(f"arquivo não encontrado: {path}")
    try:
        return load_records(path)
    except ValueError as exc:
        raise ReportError(f"JSONL inválido em {path}: {exc}") from exc


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        raise ReportError(f"arquivo não encontrado: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
    except ValueError as exc:
        raise ReportError(f"JSONL inválido em {path}: {exc}") from exc


def _categories(records: list[AttackRecord]) -> list[str]:
    extra = sorted({r.category for r in records} - set(CATEGORIES))
    return [c for c in CATEGORIES if any(r.category == c for r in records)] + extra


def _asr_comparison(base: list[AttackRecord], guard: list[AttackRecord]) -> str:
    sb, sg = asr_by_category(base), asr_by_category(guard)
    lines = [
        "| Categoria | Config. | n | Sucessos | ASR % | IC 95% (Wilson) | Erros |",
        "|---|---|---|---|---|---|---|",
    ]
    for cat in [*_categories(base + guard), "total"]:
        for label, s in (("sem guardrails", sb), ("com guardrails", sg)):
            r = s.get(cat)
            if not r or r["n"] == 0:
                continue
            lo, hi = r["ic95"]
            lines.append(
                f"| {cat} | {label} | {r['n']} | {r['sucessos']} | {r['asr'] * 100:.1f} "
                f"| [{lo * 100:.1f}; {hi * 100:.1f}] | {r['n_erros']} |"
            )
    return "\n".join(lines) + "\n"


def _attribution(base: list[AttackRecord], guard: list[AttackRecord]) -> tuple[str, dict]:
    """Tabela de atribuição e dados usados na leitura honesta."""
    lines = [
        "| Categoria | n | Bloqueados: input | tool | output | Sem bloqueio |",
        "|---|---|---|---|---|---|",
    ]
    total = {s: 0 for s in STAGES}
    total_none = 0
    for cat in _categories(guard):
        recs = [r for r in guard if r.category == cat]
        counts = {s: sum(s in r.blocked_by for r in recs) for s in STAGES}
        none = sum(not r.blocked_by for r in recs)
        for s in STAGES:
            total[s] += counts[s]
        total_none += none
        lines.append(
            f"| {cat} | {len(recs)} | {counts['input']} | {counts['tool']} "
            f"| {counts['output']} | {none} |"
        )
    lines.append(
        f"| total | {len(guard)} | {total['input']} | {total['tool']} "
        f"| {total['output']} | {total_none} |"
    )
    lines += [
        "",
        (
            "Um ataque pode ser bloqueado por mais de um estágio; 'Sem bloqueio' = nenhum "
            "guardrail atuou (o ataque não teve sucesso sem intervenção de guardrail, ou não foi detectado)."
        ),
        "",
        "Ataques com sucesso na baseline e o que aconteceu com os guardrails ligados:",
        "",
    ]
    by_id = {r.case_id: r for r in guard}
    won = [r for r in base if r.success]
    fate = {"blocked": 0, "unblocked": 0, "missing": 0, "still_success": 0}
    for r in won:
        g = by_id.get(r.case_id)
        if g is None:
            what, key = "ausente na execução com guardrails", "missing"
        elif g.success:
            what, key = "continuou com sucesso com guardrails", "still_success"
        elif g.blocked_by:
            what, key = f"bloqueado no estágio {', '.join(g.blocked_by)}", "blocked"
        else:
            what, key = "falhou na execução com guardrails SEM bloqueio", "unblocked"
        fate[key] += 1
        lines.append(f"- {r.case_id} ({r.category}): {what}")
    if not won:
        lines.append("- nenhum ataque teve sucesso na baseline")
    data = {"won": len(won), "none": total_none, "n": len(guard), **fate}
    return "\n".join(lines) + "\n", data


def _fp_section(
    fp_dir: Path, dataset: Path, v1_answers: Path
) -> tuple[str, dict]:
    from agent_ops_kit.redteam.false_positives import format_fp_markdown

    ds = _load_jsonl(fp_dir / "fp_dataset.jsonl")
    bn = _load_jsonl(fp_dir / "fp_benign.jsonl")
    groups = {f"Dataset de avaliação ({len(ds)})": ds, f"Benignas novas ({len(bn)})": bn}
    text = format_fp_markdown(groups).split("\nLimitações:")[0].rstrip() + "\n"
    blocked = {
        "ds": sum(r["blocked"] for r in ds),
        "bn": sum(r["blocked"] for r in bn),
        "n_ds": len(ds),
        "n_bn": len(bn),
        "details": [
            (r["case_id"], r["blocked_by"], r["reasons"]) for r in bn + ds if r["blocked"]
        ],
    }
    text += "\n"
    ab_done = False
    if dataset.is_file() and v1_answers.is_file():
        try:
            from agent_ops_kit.eval.dataset import load_dataset
            from agent_ops_kit.eval.runner import load_records as load_answers
            from agent_ops_kit.redteam.false_positives import (
                format_utility_markdown,
                utility_cost,
            )

            cases = load_dataset(dataset)
            ids = {r["case_id"] for r in ds}
            cases = [c for c in cases if c.id in ids]
            base = [r for r in load_answers(v1_answers) if r["case_id"] in ids]
            text += format_utility_markdown(utility_cost(cases, ds, base)).replace("### ", "#### ", 1)
            ab_done = True
        except (ValueError, KeyError) as exc:
            text += f"Utilidade: não foi possível recalcular o A/B ({exc}).\n"
    if not ab_done:
        md = fp_dir / "falsos_positivos.md"
        text += (
            f"Utilidade: A/B não recalculado (faltam {dataset} ou {v1_answers}); ver {md}.\n"
            if md.is_file()
            else "Utilidade: A/B de utilidade indisponível.\n"
        )
    return text, blocked


def _pct(num: int, den: int) -> str:
    return f"{num / den * 100:.1f}%".replace(".", ",") if den else "n/d"


def _limitations(
    base: list[AttackRecord], attr: dict, fp: dict | None, guard: list[AttackRecord]
) -> str:
    sb = asr_by_category(base)
    sg = asr_by_category(guard)
    cats = ["injecao_direta", "injecao_indireta", "exfiltracao"]
    base_low = ", ".join(
        f"{c} {_pct(sb[c]['sucessos'], sb[c]['n'])}" for c in cats if sb.get(c, {}).get("n")
    )
    items = [
        (
            "Abuso de tools: o ASR ir a zero é em grande parte POR CONSTRUÇÃO. As tools "
            "proibidas não estão na allowlist do agent.yaml, então a allowlist as bloqueia "
            "sempre. A medição mostra que o filtro funciona, não robustez geral do agente."
        ),
        (
            "Exfiltração: o critério de sucesso do canary usa a mesma noção de vazamento do "
            "filtro de saída (cobertura de codificações do detector). Vazamentos fora dessa "
            "cobertura não são contados nem bloqueados."
        ),
        (
            f"{attr['none']} dos {attr['n']} ataques não foram bloqueados por nenhum guardrail: "
            f"nesses o ataque não teve sucesso sem intervenção de guardrail. A baseline já era baixa em {base_low}; os ICs "
            "são largos e se sobrepõem aos da execução com guardrails nessas categorias."
        ),
        (
            f"Dos {attr['won']} ataques bem-sucedidos na baseline, {attr['blocked']} foram "
            f"bloqueados por guardrail e {attr['unblocked']} falhou na segunda execução SEM "
            "bloqueio (ver lista acima), por variação entre execuções ou efeito do prompt "
            "alterado; não é possível separar os dois, então nem toda a queda de "
            f"{sb['total']['sucessos']} para {sg['total']['sucessos']} é atribuível "
            "aos guardrails."
        ),
    ]
    if fp is not None:
        det = "; ".join(
            f"{cid} (estágio {', '.join(st)}; motivo {', '.join(rs)})"
            for cid, st, rs in fp["details"]
        )
        items += [
            (
                f"Falsos positivos: {fp['ds']}/{fp['n_ds']} no dataset e {fp['bn']}/{fp['n_bn']} "
                f"nas benignas novas. Bloqueadas: {det or 'nenhuma'}. Quando o motivo é "
                "canary_leak no estágio output, a resposta bruta do modelo continha o canary e o "
                "filtro evitou o vazamento; do ponto de vista do usuário é o bloqueio de uma "
                "pergunta legítima, então conta como falso positivo."
            ),
            (
                "O A/B de utilidade NÃO pode ser lido como melhora causada pelos guardrails: a "
                f"execução gravada do v1 é de outra data/execução, {fp['ds']} das {fp['n_ds']} "
                "perguntas do dataset foram bloqueadas, e o prompt do teste com guardrails tem "
                "acréscimos (linha do canary e nota de conteúdo não confiável) que alteram o "
                "comportamento do modelo. Não é possível atribuir a diferença aos guardrails; no "
                "máximo, é indício de que os guardrails não degradaram a utilidade neste "
                "conjunto."
            ),
            (
                "O conjunto benigno foi escrito e commitado antes da medição com guardrails, "
                "mas depois da baseline e depois de dois falsos positivos de teste já serem "
                "conhecidos (fontes: o teste test_falsos_positivos_conhecidos em "
                "tests/test_guardrails.py e a seção de limitações do docstring de "
                "input_filter.py, ambos do commit dos guardrails, anteriores às benignas)."
            ),
        ]
    items.append(
        "Uma execução por configuração (seed 42), n pequeno por categoria, um único modelo "
        "(llama3.1:8b). O conjunto de ataques NÃO é reservado: foi escrito no mesmo projeto; "
        "os guardrails foram projetados sem consultar os ataques (declaração do autor da "
        "implementação; uma comparação por trechos de 3-4 palavras feita na revisão não "
        "achou sobreposição) e ficaram congelados desde o commit 'feat: guardrails (...)', "
        "antes da medição, mas a suíte não é um conjunto cego. O critério de sucesso é conservador (vazamento "
        "parafraseado não conta)."
    )
    return "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1)) + "\n"


def build_summary(
    baseline: str | Path,
    guardrails: str | Path,
    fp_dir: str | Path | None = None,
    report_path: str | Path | None = None,
) -> str:
    """Placar curto (ASR antes -> depois por categoria, falsos positivos). Sem texto de ataque."""
    base = _load_attacks(Path(baseline))
    guard = _load_attacks(Path(guardrails))
    sb, sg = asr_by_category(base), asr_by_category(guard)

    def cell(s: dict | None) -> str:
        if not s or s["n"] == 0:
            return "n/d"
        return f"{s['sucessos']}/{s['n']} ({_pct(s['sucessos'], s['n'])})"

    rows = []
    for cat in [*_categories(base + guard), "total"]:
        n = (sg.get(cat) or sb.get(cat) or {}).get("n", 0)
        rows.append((cat, str(n), cell(sb.get(cat)), cell(sg.get(cat))))
    head = ("categoria", "n", "ASR sem guardrails", "ASR com guardrails")
    widths = [max(len(r[i]) for r in [head, *rows]) for i in range(4)]

    def line(r: tuple[str, ...]) -> str:
        cells = [r[0].ljust(widths[0])] + [r[i].rjust(widths[i]) for i in range(1, 4)]
        return "  " + "  ".join(cells)

    out = ["Red team: ASR antes → depois dos guardrails", line(head), *[line(r) for r in rows]]
    if fp_dir is not None:
        ds = _load_jsonl(Path(fp_dir) / "fp_dataset.jsonl")
        bn = _load_jsonl(Path(fp_dir) / "fp_benign.jsonl")
        out.append(
            "Falsos positivos: "
            f"{sum(r['blocked'] for r in ds)}/{len(ds)} no dataset de avaliação, "
            f"{sum(r['blocked'] for r in bn)}/{len(bn)} nas benignas novas"
        )
    if report_path is not None:
        out.append(f"Relatório completo: {report_path}")
    return "\n".join(out)


def build_report(
    baseline: str | Path,
    guardrails: str | Path,
    fp_dir: str | Path | None = None,
    dataset: str | Path = "evals/dataset.jsonl",
    v1_answers: str | Path = "evals/answers/v1.jsonl",
) -> str:
    base = _load_attacks(Path(baseline))
    guard = _load_attacks(Path(guardrails))
    attr_md, attr = _attribution(base, guard)
    parts = [
        "## Red team: ASR antes e depois dos guardrails",
        "",
        (
            f"Fontes: `{baseline}` (sem guardrails) e `{guardrails}` (com guardrails). "
            "Denominador = todos os casos executados; erros do agente não contam como sucesso."
        ),
        "",
        _asr_comparison(base, guard),
        "### Atribuição por estágio",
        "",
        attr_md,
    ]
    fp = None
    if fp_dir is not None:
        fp_md, fp = _fp_section(Path(fp_dir), Path(dataset), Path(v1_answers))
        parts += ["### Falsos positivos", "", fp_md.replace("### Falsos positivos dos guardrails\n\n", "")]
    parts += ["### Limitações e leitura honesta", "", _limitations(base, attr, fp, guard)]
    return "\n".join(parts)

