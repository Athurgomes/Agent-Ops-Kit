"""Renderiza o dict de build_data em Markdown e HTML estático (CSS inline, sem JS).

Todo texto vindo de dados passa por html.escape no HTML e por _cell nas tabelas do Markdown.
"""

from __future__ import annotations

from html import escape

from agent_ops_kit.report.build import GREEN_TEXT, RED_RULES, YELLOW_RULES

COLOR_LABEL = {"green": "VERDE", "yellow": "AMARELO", "red": "VERMELHO"}
COLOR_CSS = {"green": "#1b7f3b", "yellow": "#b58105", "red": "#b3261e"}

Block = tuple  # ("h1"|"h2"|"h3"|"p"|"ul"|"table"|"light", ...)


def _f(x: float, digits: int = 4, signed: bool = False) -> str:
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}"


def _light_text(color: str) -> str:
    return {
        "green": "Nada reprovou neste teste.",
        "yellow": "Há pontos de atenção neste teste.",
        "red": "Algo reprovou neste teste.",
    }[color]


def build_blocks(d: dict) -> list[Block]:
    ev, rt, au, ag = d["eval"], d["redteam"], d["audit"], d["agent"]
    color = d["semaphore"]["color"]
    asr_b, asr_g = rt["asr"]["baseline"]["total"], rt["asr"]["guardrails"]["total"]
    fp = rt["false_positives"]
    fp_blocked = fp["dataset"]["blocked"] + fp["benign"]["blocked"]
    man = ev["manifest"]
    dates = sorted({str(m["date"]) for m in man.values()})

    b: list[Block] = [
        ("h1", f"Relatório de teste do agente {ag['name']}"),
        ("p", f"Gerado em {d['generated_at']}."),
        ("h2", "1. O que foi testado e quando"),
        (
            "ul",
            [
                (
                    f"Agente: {ag['name']} (prompt_version do agent.yaml: "
                    f"{ag['prompt_version']}). Modelo: {ag['model']}."
                ),
                (
                    f"Avaliação de qualidade: {ev['candidate']} comparada com {ev['baseline']} "
                    f"em {ev['n_cases']} casos; respostas gravadas em {', '.join(dates)}."
                ),
                (
                    f"Red team: {rt['n_attacks']} ataques, sem e com guardrails. A data da "
                    "execução não é registrada nos resultados."
                ),
                f"Falsos positivos: {rt['n_legit_questions']} perguntas legítimas.",
                "Auditoria: "
                + (
                    "nenhum log informado."
                    if au is None
                    else f"{au['n_events']} eventos verificados."
                ),
            ],
        ),
        ("h2", "2. Resultado"),
        ("light", color, f"{COLOR_LABEL[color]}: {_light_text(color)}"),
    ]
    if color == "green":
        b.append(("p", GREEN_TEXT))
    triggered = d["semaphore"]["triggered"]
    if triggered:
        rules = {**RED_RULES, **YELLOW_RULES}
        b += [("p", "Motivos:"), ("ul", [rules[k] for k in triggered])]
    b += [
        (
            "p",
            (
                f"{asr_g['successes']} de {asr_g['n']} ataques tiveram sucesso com guardrails e "
                f"{asr_b['successes']} de {asr_b['n']} sem guardrails, neste teste, com as "
                "ressalvas da seção Limitações."
            ),
        ),
        (
            "p",
            (
                f"Falsos positivos: {fp_blocked} de {rt['n_legit_questions']} perguntas "
                "legítimas foram bloqueadas."
            ),
        ),
        (
            "p",
            f"Qualidade ({ev['metric']}): média {_f(ev['mean_candidate'])} em {ev['candidate']} "
            f"contra {_f(ev['mean_baseline'])} em {ev['baseline']}; diferença "
            f"{_f(ev['mean_diff'], signed=True)} (IC 95% [{_f(ev['ci95_low'], signed=True)}; "
            f"{_f(ev['ci95_high'], signed=True)}], p = {_f(ev['p_value'])}). Gate de regressão: "
            + ("disparou." if ev["regression"] else "não disparou."),
        ),
    ]
    if au is not None:
        b.append(
            (
                "p",
                (
                    f"Auditoria: cadeia íntegra ({au['n_events']} eventos)."
                    if au["ok"]
                    else f"Auditoria: cadeia inválida ({au['reason']})."
                ),
            )
        )
    b += [
        ("h3", "Regra do semáforo (PROVISÓRIA)"),
        (
            "p",
            "Regras provisórias, ainda sem validação. Vermelho se: "
            + "; ".join(RED_RULES.values())
            + ". Amarelo, se não houver vermelho e: "
            + "; ".join(YELLOW_RULES.values())
            + ". Verde nos demais casos.",
        ),
    ]
    prev = d["previous"]
    b.append(("h2", "3. O que mudou desde a versão anterior"))
    if prev is None:
        b.append(("p", "Relatório anterior não informado."))
    else:
        b += [
            ("p", f"Comparação com o relatório gerado em {prev['generated_at']}."),
            ("table", ["Métrica", "Antes", "Agora"], [[r["metric"], r["before"], r["after"]] for r in prev["rows"]]),
        ]
    b += [("h2", "4. Limitações"), ("ul", list(d["limitations"]))]

    b.append(("h1", "Anexo técnico"))
    b += [
        ("h2", "A. Eval A/B"),
        (
            "table",
            ["Item", "Valor"],
            [
                [f"Média {ev['baseline']}", _f(ev["mean_baseline"])],
                [f"Média {ev['candidate']}", _f(ev["mean_candidate"])],
                [f"Diferença ({ev['candidate']} - {ev['baseline']})", _f(ev["mean_diff"], signed=True)],
                ["IC 95% (bootstrap)", f"[{_f(ev['ci95_low'], signed=True)}; {_f(ev['ci95_high'], signed=True)}]"],
                [f"p-valor (permutação pareada, {ev['p_method']})", _f(ev["p_value"])],
                ["Pares usados / descartados", f"{ev['n_pairs']} / {ev['n_dropped']}"],
                ["Semente / reamostragens", f"{ev['seed']} / {ev['n_resamples']}"],
                [f"Gate (diferença menor que 0 e p menor que {ev['alpha']})", "disparou" if ev["regression"] else "não disparou"],
                ["Execuções por configuração", str(ev["runs_per_config"])],
            ],
        ),
        ("h2", "B. ASR por categoria (IC 95% de Wilson)"),
    ]
    rows = []
    for cat in rt["asr"]["guardrails"]:
        for label, key in (("sem guardrails", "baseline"), ("com guardrails", "guardrails")):
            r = rt["asr"][key].get(cat)
            if r:
                rows.append(
                    [cat, label, str(r["n"]), str(r["successes"]), _pct(r["asr"]),
                     f"[{_pct(r['ci95_low'])}; {_pct(r['ci95_high'])}]", str(r["errors"])]
                )
    b.append(("table", ["Categoria", "Config.", "n", "Sucessos", "ASR %", "IC 95%", "Erros"], rows))
    b += [
        ("h2", "C. Falsos positivos"),
        (
            "table",
            ["Conjunto", "n", "Bloqueadas", "Taxa %", "IC 95% (Wilson)", "Erros"],
            [
                [name, str(r["n"]), str(r["blocked"]), _pct(r["rate"]),
                 f"[{_pct(r['ci95_low'])}; {_pct(r['ci95_high'])}]", str(r["errors"])]
                for name, r in (("Dataset de avaliação", fp["dataset"]), ("Benignas novas", fp["benign"]))
            ],
        ),
        ("h2", "D. Manifesto das respostas do eval"),
        (
            "table",
            ["Variante", "Modelo", "Semente", "Casos", "Data", "sha256 do prompt", "sha256 do dataset"],
            [
                [v, str(m["model"]), str(m["seed"]), str(m["n_cases"]), str(m["date"]),
                 str(m["prompt_sha256"]), str(m["dataset_sha256"])]
                for v, m in man.items()
            ],
        ),
        ("h2", "E. Hashes dos arquivos de entrada (sha256)"),
        ("table", ["Entrada", "sha256"], [[k, v] for k, v in d["hashes"].items()]),
        ("h2", "F. Auditoria"),
    ]
    if au is None:
        b.append(("p", "Nenhum log de auditoria informado."))
    else:
        b.append(
            (
                "table",
                ["Item", "Valor"],
                [
                    ["Cadeia", "íntegra" if au["ok"] else "inválida"],
                    ["Eventos", str(au["n_events"])],
                    ["Hash âncora (último hash)", str(au["anchor"])],
                    ["Primeira linha com problema", str(au["first_bad_line"] or "-")],
                    ["Motivo", str(au["reason"] or "-")],
                ],
            )
        )
        b.append(("p", "A âncora só protege se for guardada fora do arquivo de auditoria."))
    return b


def _t(text: str) -> str:
    """Neutraliza HTML cru no Markdown (dados nunca viram tag)."""
    return str(text).replace("<", "&lt;").replace(">", "&gt;")


def _cell(text: str) -> str:
    return _t(text).replace("|", "\\|").replace("\n", " ")


def to_markdown(blocks: list[Block]) -> str:
    out: list[str] = []
    for blk in blocks:
        kind = blk[0]
        if kind in ("h1", "h2", "h3"):
            out.append(f"{'#' * int(kind[1])} {_t(blk[1])}")
        elif kind == "p":
            out.append(_t(blk[1]))
        elif kind == "light":
            out.append(f"**{_t(blk[2])}**")
        elif kind == "ul":
            out.append("\n".join(f"- {_t(t)}" for t in blk[1]))
        elif kind == "table":
            head, rows = blk[1], blk[2]
            lines = ["| " + " | ".join(map(_cell, head)) + " |", "|" + "---|" * len(head)]
            lines += ["| " + " | ".join(map(_cell, r)) + " |" for r in rows]
            out.append("\n".join(lines))
    return "\n\n".join(out) + "\n"


_CSS = (
    "body{font-family:Arial,Helvetica,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;"
    "color:#222;line-height:1.5}h1{border-bottom:2px solid #ddd;padding-bottom:.3rem}"
    "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}"
    "th,td{border:1px solid #ccc;padding:.3rem .5rem;text-align:left;vertical-align:top;"
    "word-break:break-word}th{background:#f3f3f3}"
    ".light{color:#fff;padding:1rem;border-radius:6px;font-size:1.3rem;font-weight:bold}"
    "@media print{h1{page-break-before:always}h1:first-of-type{page-break-before:avoid}}"
)


def to_html(blocks: list[Block], title: str) -> str:
    body: list[str] = []
    for blk in blocks:
        kind = blk[0]
        if kind in ("h1", "h2", "h3"):
            body.append(f"<{kind}>{escape(blk[1])}</{kind}>")
        elif kind == "p":
            body.append(f"<p>{escape(blk[1])}</p>")
        elif kind == "light":
            body.append(
                f'<div class="light" style="background:{COLOR_CSS[blk[1]]}">{escape(blk[2])}</div>'
            )
        elif kind == "ul":
            body.append("<ul>" + "".join(f"<li>{escape(t)}</li>" for t in blk[1]) + "</ul>")
        elif kind == "table":
            head = "".join(f"<th>{escape(str(h))}</th>" for h in blk[1])
            rows = "".join(
                "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in r) + "</tr>" for r in blk[2]
            )
            body.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
    return (
        '<!DOCTYPE html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )
