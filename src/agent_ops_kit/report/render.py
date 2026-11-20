"""Renderiza o dict de build_data em Markdown e HTML estático (CSS inline, sem JS).

Estrutura executiva e de auditoria conforme ABNT NBR 10719:2015 e ABNT NBR 6024:2012.
Todo texto vindo de dados passa por html.escape no HTML e por _t/_cell no Markdown.
"""

from __future__ import annotations

import hashlib
import re
from html import escape

from agent_ops_kit.report import stats as stats_mod
from agent_ops_kit.report.build import GREEN_TEXT

COLOR_LABEL = {"green": "VERDE", "yellow": "AMARELO", "red": "VERMELHO"}
COLOR_CSS = {"green": "#1b7f3b", "yellow": "#b58105", "red": "#b3261e"}

Block = tuple  # ("h1"|"h2"|"h3"|"subtitle"|"p"|"ul"|"table"|"light", ...)

_SECTIONS = (
    "1 INTRODUÇÃO E ESCOPO DA AVALIAÇÃO",
    "2 PARECER EXECUTIVO PARA NEGÓCIOS E GOVERNANÇA",
    "3 ANÁLISE DE QUALIDADE FUNCIONAL E CONTINUIDADE DO SERVIÇO",
    "4 ANÁLISE DE EXPOSIÇÃO A RISCOS OPERACIONAIS E CONTROLES DE PROTEÇÃO",
    "5 RASTREABILIDADE, PRIVACIDADE E LIMITAÇÕES METODOLÓGICAS",
    "6 CONCLUSÃO, ENCAMINHAMENTOS E QUADRO DE CIÊNCIA PARA AUDITORIA",
    "APÊNDICE A — EVIDÊNCIAS TÉCNICAS E CRIPTOGRÁFICAS PARA AUDITORIA",
)

_CATEGORY_RISK = {
    "injecao_direta": (
        "Tentativa direta de desvio de instruções "
        "(comandos explícitos para ignorar regras do sistema)"
    ),
    "injecao_indireta": (
        "Instruções maliciosas embutidas em documentos consultados "
        "(envenenamento de contexto)"
    ),
    "abuso_de_tools": (
        "Acionamento indevido de ferramentas do sistema "
        "(tentativa de execução ou acesso não autorizado)"
    ),
    "exfiltracao": (
        "Tentativa de extração de informação interna de controle "
        "ou dado restrito na resposta"
    ),
    "total": "Consolidado de todas as simulações avaliadas",
}


def _f(x: float, digits: int = 4, signed: bool = False) -> str:
    return f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}"


def _light_text(color: str) -> str:
    return {
        "green": "Sem reprovações ou alertas acionados neste ciclo de verificação.",
        "yellow": "Há pontos de atenção neste ciclo que requerem acompanhamento antes da operação ampla.",
        "red": "Critério impeditivo acionado neste ciclo; liberação bloqueada até tratamento.",
    }[color]


def _doc_code(d: dict) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "-", str(d["agent"]["name"])).strip("-").upper()[:24] or "AGENTE"
    cfg_hash = d.get("hashes", {}).get("config")
    if not cfg_hash:
        seed_text = f"{d['agent']['name']}|{d['agent']['prompt_version']}|{d['agent']['model']}"
        cfg_hash = hashlib.sha256(seed_text.encode("utf-8")).hexdigest()
    return f"REL-AOK-{name}-{str(cfg_hash)[:8].upper()}"


def _fp_totals(rt: dict) -> tuple[int, float]:
    fp = rt["false_positives"]
    blocked = fp["dataset"]["blocked"] + fp["benign"]["blocked"]
    total = rt["n_legit_questions"]
    rate = blocked / total if total else 0.0
    return blocked, rate


def _audit_status_short(au: dict | None) -> str:
    if au is None:
        return "não informada neste pacote"
    if not au["ok"]:
        return f"cadeia inválida (falha na linha {au['first_bad_line'] or '-'})"
    sig = au.get("signature")
    if isinstance(sig, dict) and sig.get("checked"):
        alg = sig.get("algorithm")
        alg_suffix = f" {alg}" if alg else ""
        if sig.get("ok"):
            return f"cadeia íntegra ({au['n_events']} eventos verificados) e assinatura{alg_suffix} válida"
        return f"cadeia íntegra ({au['n_events']} eventos), porém assinatura{alg_suffix} inválida"
    return f"cadeia íntegra ({au['n_events']} eventos verificados)"


def _pretextual_blocks(d: dict, doc_code: str) -> list[Block]:
    ag, ev, rt, au = d["agent"], d["eval"], d["redteam"], d["audit"]
    color = d["semaphore"]["color"]
    asr_b = rt["asr"]["baseline"].get("total") or {"n": 0, "successes": 0, "asr": 0.0}
    asr_g = rt["asr"]["guardrails"].get("total") or {"n": 0, "successes": 0, "asr": 0.0}
    fp_blocked, _ = _fp_totals(rt)
    gate_msg = (
        "com disparo do gate de regressão"
        if ev["regression"]
        else "sem disparo do gate de regressão"
    )
    summary = (
        f"Este parecer apresenta os resultados determinísticos da avaliação do agente {ag['name']} "
        f"(prompt {ag['prompt_version']}, modelo {ag['model']}), abrangendo {ev['n_cases']} casos "
        f"de qualidade funcional ({ev['candidate']} vs {ev['baseline']}), {rt['n_attacks']} "
        f"simulações de manipulação e {rt['n_legit_questions']} consultas legítimas. A classificação "
        f"consolidada foi {COLOR_LABEL[color]}. Na qualidade funcional, a variante candidata obteve "
        f"média {_f(ev['mean_candidate'])} ({_pct(ev['mean_candidate'])}%) contra "
        f"{_f(ev['mean_baseline'])} ({_pct(ev['mean_baseline'])}%) da referência, {gate_msg}. "
        f"Sob simulações de manipulação, {asr_g['successes']} de {asr_g['n']} tentativas tiveram "
        f"êxito com controles ativos frente a {asr_b['successes']} de {asr_b['n']} sem controles, "
        f"com {fp_blocked} de {rt['n_legit_questions']} perguntas legítimas bloqueadas "
        f"(falsos positivos). A trilha de auditoria encontra-se {_audit_status_short(au)}."
    )
    return [
        ("h1", f"RELATÓRIO TÉCNICO E PARECER DE AVALIAÇÃO — AGENTE {ag['name']}"),
        (
            "subtitle",
            (
                "Avaliação de Qualidade Funcional, Exposição a Riscos Operacionais e "
                "Rastreabilidade para Governança e Auditoria"
            ),
        ),
        ("h2", "IDENTIFICAÇÃO E CONTROLE DOCUMENTAL"),
        (
            "table",
            ["Campo", "Identificação"],
            [
                ["Código do documento", doc_code],
                ["Data e hora de emissão", str(d["generated_at"])],
                ["Agente avaliado", str(ag["name"])],
                ["Versão de prompt", str(ag["prompt_version"])],
                ["Modelo avaliado", str(ag["model"])],
                ["Semente de reprodutibilidade", str(ev["seed"])],
                [
                    "Esquema / Regra de classificação",
                    f"v{d['schema_version']} / {d['semaphore']['rules_version']}",
                ],
                ["Estrutura de referência", "ABNT NBR 10719:2015 e ABNT NBR 6024:2012"],
                ["Resultado consolidado", COLOR_LABEL[color]],
            ],
        ),
        ("h2", "RESUMO EXECUTIVO"),
        ("p", summary),
        ("h2", "SUMÁRIO EXECUTIVO DAS SEÇÕES"),
        ("ul", list(_SECTIONS)),
    ]


def _target_line(d: dict) -> str:
    """Agente auditado (tipo, ref, semente): um texto se todas as execuções coincidem, senão por origem."""
    rows = stats_mod.target_rows(d)
    texts = {stats_mod.target_text(t) for _, t in rows if t}
    if len(texts) == 1 and all(t for _, t in rows):
        return f"Agente auditado: {texts.pop()}."
    if not texts:
        return f"Agente auditado: {_NOT_RECORDED}."
    return "Agente auditado (por origem): " + "; ".join(
        f"{label}: {stats_mod.target_text(t)}" for label, t in rows
    ) + "."


def _not_evaluated_notes(rt: dict) -> list[Block]:
    parts = []
    for name, label in (("baseline", "sem controles"), ("guardrails", "com controles")):
        k = (rt["asr"][name].get("total") or {}).get("not_evaluated", 0)
        if k:
            parts.append(f"{k} {label}")
    if not parts:
        return []
    return [(
        "p",
        "Métrica de ferramenta não avaliada (agente externo sem `tool_calls` declarados): "
        + "; ".join(parts) + ". Esses casos ficam fora de n e do ASR.",
    )]


def _scope_blocks(d: dict) -> list[Block]:
    ag, ev, rt, au = d["agent"], d["eval"], d["redteam"], d["audit"]
    fp = rt["false_positives"]
    dates = sorted({str(m["date"]) for m in ev["manifest"].values()})
    audit_item = (
        "Trilha de auditoria: nenhum log informado neste pacote."
        if au is None
        else f"Trilha de auditoria: {au['n_events']} eventos submetidos à verificação criptográfica."
    )
    return [
        ("h2", _SECTIONS[0]),
        (
            "p",
            (
                "Esta verificação tem por finalidade subsidiar gestores da área de negócio, equipes de "
                "riscos e a auditoria interna antes da aprovação ou manutenção de alterações em "
                "configurações de agentes de IA, apoiando a decisão com métricas reproduzíveis e sem "
                "exposição de diálogos reais ou dados pessoais."
            ),
        ),
        (
            "ul",
            [
                (
                    f"Agente avaliado: {ag['name']} (prompt_version no agent.yaml: "
                    f"{ag['prompt_version']}; modelo: {ag['model']})."
                ),
                _target_line(d),
                (
                    f"Avaliação funcional A/B: {ev['candidate']} comparada à referência "
                    f"{ev['baseline']} em {ev['n_cases']} casos ({ev['runs_per_config']} "
                    f"execução(ões) por configuração); respostas gravadas em {', '.join(dates)}."
                ),
                (
                    f"Simulações de manipulação (red team): {rt['n_attacks']} cenários executados "
                    f"sem controles e com controles ativos ({rt['runs_per_config']} execução(ões) "
                    "por configuração; a data de execução não é registrada nos resultados)."
                ),
                (
                    f"Consultas legítimas (falsos positivos): {rt['n_legit_questions']} perguntas "
                    f"({fp['dataset']['n']} do conjunto de avaliação e {fp['benign']['n']} "
                    "consultas benignas inéditas)."
                ),
                audit_item,
            ],
        ),
    ]


def _business_indicator_rows(d: dict) -> list[list[str]]:
    ev, rt, au = d["eval"], d["redteam"], d["audit"]
    asr_b = rt["asr"]["baseline"].get("total") or {"n": 0, "successes": 0, "asr": 0.0}
    asr_g = rt["asr"]["guardrails"].get("total") or {"n": 0, "successes": 0, "asr": 0.0}
    fp_blocked, fp_rate = _fp_totals(rt)

    if ev["regression"]:
        qual_read = (
            "Queda estatisticamente significativa na qualidade das respostas; "
            "impede liberação imediata até correção."
        )
    elif ev["mean_diff"] < 0:
        qual_read = (
            "Leve redução na média sem confirmação estatística; recomenda acompanhamento "
            "em amostra ampliada."
        )
    else:
        qual_read = (
            "Qualidade funcional mantida ou superior à referência, sem evidência de "
            "regressão no conjunto avaliado."
        )

    if asr_g["successes"] == 0:
        rt_read = (
            "Nenhuma simulação testada teve êxito com os controles ativos, "
            "dentro do escopo da suíte atual."
        )
    else:
        rt_read = (
            f"{asr_g['successes']} tentativa(s) superaram os controles ativos; "
            "requer revisão dos filtros antes de ampliar o uso."
        )

    if fp_blocked == 0:
        fp_read = (
            "Nenhum bloqueio indevido observado nas perguntas legítimas testadas; "
            "baixo risco de atrito operacional."
        )
    else:
        fp_read = (
            f"{fp_blocked} consulta(s) legítima(s) barrada(s); pode gerar atrito no atendimento "
            "e requer calibração de filtros."
        )

    if au is None:
        au_ind = "Não informada"
        au_read = (
            "Sem arquivo de auditoria anexado a este pacote; limita a conferência posterior "
            "dos eventos."
        )
    elif not au["ok"]:
        au_ind = f"Cadeia inválida (linha {au['first_bad_line'] or '-'})"
        au_read = (
            "Inconsistência detectada no encadeamento de registros; bloqueia aprovação até "
            "apuração técnica."
        )
    else:
        sig = au.get("signature")
        if isinstance(sig, dict) and sig.get("checked"):
            if sig.get("ok"):
                au_ind = f"Cadeia íntegra e assinada ({sig.get('algorithm')}, {au['n_events']} eventos)"
                au_read = (
                    "Registros encadeados e assinatura da âncora válidos, sujeitos à guarda "
                    "protegida da chave e sem carimbo de tempo RFC 3161."
                )
            else:
                au_ind = f"Assinatura inválida ({au['n_events']} eventos)"
                au_read = (
                    "Assinatura criptográfica da âncora inválida ou incompatível; bloqueia "
                    "aprovação até apuração técnica."
                )
        else:
            au_ind = f"Cadeia íntegra ({au['n_events']} eventos)"
            au_read = (
                "Registros encadeados consistentes com a âncora criptográfica informada, "
                "permitindo verificação de integridade."
            )

    return [
        [
            "Qualidade das respostas ao usuário",
            (
                f"Média {_f(ev['mean_candidate'])} ({_pct(ev['mean_candidate'])}%) vs "
                f"{_f(ev['mean_baseline'])} ({_pct(ev['mean_baseline'])}%); "
                f"diferença {_f(ev['mean_diff'], signed=True)} (p = {_f(ev['p_value'])})"
            ),
            qual_read,
        ],
        [
            "Contenção de tentativas de manipulação e vazamento",
            (
                f"{asr_g['successes']}/{asr_g['n']} com controles ({_pct(asr_g['asr'])}%) vs "
                f"{asr_b['successes']}/{asr_b['n']} sem controles ({_pct(asr_b['asr'])}%)"
            ),
            rt_read,
        ],
        [
            "Impacto em solicitações legítimas de clientes/usuários",
            f"{fp_blocked}/{rt['n_legit_questions']} bloqueadas ({_pct(fp_rate)}%)",
            fp_read,
        ],
        ["Integridade da trilha de auditoria", au_ind, au_read],
    ]


def _fmt(v: object) -> str:
    if v is None:
        return "n/d"
    if isinstance(v, bool):
        return "sim" if v else "não"
    return f"{v:g}" if isinstance(v, float) else str(v)


_RESULT = {True: "Atendida", False: "Não atendida", None: "Não avaliada"}


def _policy_blocks(d: dict) -> list[Block]:
    pol = d.get("policy")
    if not pol:  # relatorio.json antigo, sem política registrada
        return [(
            "p",
            (
                f"Classificação regida pela regra PROVISÓRIA versão {d['semaphore']['rules_version']}; "
                "este relatório não registra a política aplicada."
            ),
        )]
    rows = [
        [
            f"{r['id']} ({'vermelho' if r['severity'] == 'red' else 'amarelo'}): {r['rationale']}",
            f"{r['metric']} {r['op']} {_fmt(r['threshold'])}",
            _fmt(r["observed"]),
            _RESULT[r["passed"]],
        ]
        for r in pol["rules"]
    ]
    return [
        (
            "p",
            (
                f"Classificação regida pela política '{pol['id']}' versão {pol['version']} "
            f"(arquivo {pol['path_relative']}, sha256 {pol['sha256'][:16]}...). A política é "
            "configurável (opção --policy) e os limiares padrão são PROVISÓRIOS: aguardam validação "
            "formal junto à liderança, Riscos e Auditoria Interna. Cada regra é uma condição a "
            "atender; falha em regra vermelha resulta em VERMELHO, falha em regra amarela resulta em "
            "AMARELO, e regra não avaliada (métrica ausente) nunca resulta em verde."
            ),
        ),
        ("table", ["Regra", "Limiar", "Observado", "Resultado"], rows),
    ]


def _executive_verdict_blocks(d: dict) -> list[Block]:
    color = d["semaphore"]["color"]
    triggered = d["semaphore"]["triggered"]
    prev = d["previous"]
    rules = {r["id"]: r for r in (d.get("policy") or {}).get("rules", [])}
    def reason(k: str) -> str:
        r = rules.get(k)
        if r is None:
            return k
        return (
            f"{r['rationale']} Observado: {_fmt(r['observed'])}; critério: "
            f"{r['metric']} {r['op']} {_fmt(r['threshold'])}."
        )

    blocks: list[Block] = [
        ("h2", _SECTIONS[1]),
        ("light", color, f"{COLOR_LABEL[color]}: {_light_text(color)}"),
    ]
    if color == "green":
        blocks.append(("p", GREEN_TEXT))
    if triggered:
        blocks += [
            ("p", "Critérios acionados neste ciclo:"),
            ("ul", [reason(k) for k in triggered]),
        ]
    if d["semaphore"].get("not_evaluated"):
        blocks += [
            ("p", "Ressalva: regra não avaliada, por métrica ausente no relatório (não equivale a aprovação):"),
            ("ul", list(d["semaphore"]["not_evaluated"])),
        ]

    blocks += [
        ("h3", "2.1 Quadro de indicadores traduzidos para decisão de negócio"),
        ("table", ["Dimensão", "Indicador medido", "Leitura para o negócio"], _business_indicator_rows(d)),
        ("h3", "2.2 Critérios de classificação (REGRA PROVISÓRIA)"),
        *_policy_blocks(d),
        ("h3", "2.3 Evolução em relação à versão anterior"),
    ]
    if prev is None:
        blocks.append(
            (
                "p",
                (
                    "Relatório anterior não informado neste ciclo de avaliação; este parecer "
                    "estabelece a referência inicial de acompanhamento."
                ),
            )
        )
    else:
        blocks += [
            ("p", f"Comparação consolidada frente ao relatório emitido em {prev['generated_at']}:"),
            (
                "table",
                ["Métrica", "Antes", "Agora"],
                [[r["metric"], r["before"], r["after"]] for r in prev["rows"]],
            ),
        ]
    return blocks


def _has_multirun(ev: dict) -> bool:
    variance = ev.get("variance") or {}
    return bool(variance) and (
        ev["runs_per_config"] > 1 or any(v.get("n_runs", 1) > 1 for v in variance.values())
    )


def _functional_quality_blocks(ev: dict) -> list[Block]:
    diff_pp = ev["mean_diff"] * 100
    if ev["regression"]:
        continuity = (
            f"O gate automático de regressão disparou (diferença negativa com p < {ev['alpha']}), "
            "indicando perda mensurável de aderência funcional na variante avaliada e risco à "
            "consistência do atendimento."
        )
    elif ev["mean_diff"] < 0:
        continuity = (
            f"O gate automático de regressão não disparou (p >= {ev['alpha']}), porém a média "
            "apresentou leve recuo pontual; recomenda-se observar a estabilidade em ciclos "
            "seguintes antes de consolidar a mudança."
        )
    else:
        continuity = (
            "O gate automático de regressão não disparou e a variante avaliada manteve ou superou "
            "o nível funcional da referência, preservando a consistência e a continuidade do "
            "serviço nos critérios verificados."
        )

    blocks: list[Block] = [
        ("h2", _SECTIONS[2]),
        (
            "p",
            (
                f"Na comparação pareada entre a configuração candidata ({ev['candidate']}) e a "
                f"referência ({ev['baseline']}), medida pelo indicador '{ev['metric']}', a candidata "
                f"obteve média {_f(ev['mean_candidate'])} (equivalente a {_pct(ev['mean_candidate'])}%) "
                f"frente a {_f(ev['mean_baseline'])} ({_pct(ev['mean_baseline'])}%) da referência. "
                f"A diferença observada foi de {_f(ev['mean_diff'], signed=True)} "
                f"({diff_pp:+.1f} pontos percentuais), com intervalo de confiança de 95% via "
                f"bootstrap entre [{_f(ev['ci95_low'], signed=True)}; "
                f"{_f(ev['ci95_high'], signed=True)}] e p = {_f(ev['p_value'])} "
                f"({ev['p_method']}, {ev['n_pairs']} pares analisados e {ev['n_dropped']} descartados)."
            ),
        ),
        ("p", continuity),
    ]
    if _has_multirun(ev):
        variance = ev["variance"]
        parts = []
        for v in (ev["baseline"], ev["candidate"]):
            vs = variance.get(v)
            if vs:
                parts.append(
                    f"{v}: média {_f(vs['mean'])} em {vs['n_runs']} execuções "
                    f"(desvio-padrão entre execuções {_f(vs['run_stdev'])}, "
                    f"desvio médio por caso {_f(vs['mean_case_stdev'])}, "
                    f"consistência exata de score {_pct(vs['exact_score_consistency_rate'])}% "
                    f"e de resposta {_pct(vs['exact_answer_consistency_rate'])}%)"
                )
        if parts:
            blocks.append(("p", "Variância entre execuções: " + "; ".join(parts) + "."))
    return blocks


def _mcnemar_blocks(mc: dict | None) -> list[Block]:
    """Teste de McNemar exato (baseline vs guardrails, pareado por ataque)."""
    if not mc:
        return [("p", f"Teste de McNemar (baseline vs guardrails): {_NOT_RECORDED} neste relatório.")]
    if not mc["applicable"]:
        return [("p", f"Teste de McNemar (baseline vs guardrails): não aplicável. {mc['reason']}.")]
    ex = mc["excluded"]
    return [
        (
            "p",
            (
                "Teste de McNemar exato (binomial bilateral), pareado por ataque. b = sucesso só "
                "sem guardrails; c = sucesso só com guardrails."
            ),
        ),
        (
            "table",
            ["Pares (n)", "b", "c", "p exato", "Excluídos (erro / sem par)"],
            [[
                str(mc["n_paired"]), str(mc["b"]), str(mc["c"]), f"{mc['p_value']:.4f}",
                f"{ex['total']} ({ex['errors']} / {ex['unpaired']})",
            ]],
        ),
    ]


def _risk_analysis_blocks(rt: dict) -> list[Block]:
    asr_b = rt["asr"]["baseline"].get("total") or {"n": 0, "successes": 0, "asr": 0.0}
    asr_g = rt["asr"]["guardrails"].get("total") or {"n": 0, "successes": 0, "asr": 0.0}
    fp = rt["false_positives"]
    fp_blocked, fp_rate = _fp_totals(rt)

    cats = list(dict.fromkeys([*rt["asr"]["guardrails"].keys(), *rt["asr"]["baseline"].keys()]))
    risk_rows: list[list[str]] = []
    for cat in cats:
        if cat == "total":
            continue
        rb = rt["asr"]["baseline"].get(cat)
        rg = rt["asr"]["guardrails"].get(cat)
        risk_rows.append(
            [
                cat,
                _CATEGORY_RISK.get(cat, "Cenário específico avaliado na suíte de manipulação"),
                f"{rb['successes']}/{rb['n']} ({_pct(rb['asr'])}%)" if rb else "n/d",
                f"{rg['successes']}/{rg['n']} ({_pct(rg['asr'])}%)" if rg else "n/d",
            ]
        )

    blocks: list[Block] = [
        ("h2", _SECTIONS[3]),
        (
            "p",
            (
                f"Sem os controles de proteção ativos, {asr_b['successes']} de {asr_b['n']} "
                f"simulações de ataque obtiveram êxito ({_pct(asr_b['asr'])}%). Com as camadas de "
                f"proteção ligadas, {asr_g['successes']} de {asr_g['n']} ataques obtiveram êxito "
                f"({_pct(asr_g['asr'])}%). Conforme detalhado na Seção 5, a redução observada reflete "
                "o conjunto de restrições arquiteturais do agente (como lista de ferramentas permitidas) "
                "somado aos filtros de entrada e saída, não devendo ser atribuída isoladamente a um "
                "único controle."
            ),
        ),
    ]
    if risk_rows:
        blocks.append(
            (
                "table",
                ["Categoria", "Exposição ao risco de negócio", "Sem controles", "Com controles"],
                risk_rows,
            )
        )
    blocks += _not_evaluated_notes(rt)
    blocks += _mcnemar_blocks(rt.get("mcnemar"))
    blocks.append(
        (
            "p",
            (
                f"Quanto ao impacto sobre demandas válidas de usuários (falsos positivos), "
                f"{fp_blocked} de {rt['n_legit_questions']} consultas legítimas foram bloqueadas "
                f"({_pct(fp_rate)}%): {fp['dataset']['blocked']}/{fp['dataset']['n']} no conjunto de "
                f"avaliação ({_pct(fp['dataset']['rate'])}%) e {fp['benign']['blocked']}/"
                f"{fp['benign']['n']} nas perguntas benignas inéditas ({_pct(fp['benign']['rate'])}%). "
                "Bloqueios indevidos elevam o atrito no atendimento e demandam ajuste fino dos filtros "
                "preventivos."
            ),
        )
    )
    return blocks


def _audit_signature_summary(au: dict | None) -> str | None:
    if not isinstance(au, dict):
        return None
    sig = au.get("signature")
    if not (isinstance(sig, dict) and sig.get("checked")):
        return "Assinatura da âncora de auditoria: não informada (cadeia de hashes sem assinatura)."
    status = "válida" if sig.get("ok") else "inválida"
    alg = sig.get("algorithm") or "-"
    fp = sig.get("key_fingerprint") or "-"
    signed_at = sig.get("signed_at_utc") or "-"
    msg = (
        f"Assinatura da âncora de auditoria: {status} (algoritmo: {alg}, "
        f"key_fingerprint: {fp}, carimbo no recibo: {signed_at})."
    )
    if not sig.get("ok") and sig.get("reason"):
        msg += f" Motivo: {sig['reason']}."
    return msg


def _audit_signature_limitation(sig: dict | None) -> str:
    if not (isinstance(sig, dict) and sig.get("checked")):
        return (
            "A âncora criptográfica (sem assinatura) só garante detecção de alteração quando "
            "guardada fora do arquivo de auditoria."
        )
    alg = sig.get("algorithm")
    if alg == "ed25519":
        return (
            "Assinatura Ed25519 cobre integridade autenticada e não-repúdio sujeito à custódia "
            "protegida da chave privada; não inclui carimbo de tempo externo confiável "
            "(RFC 3161 TSA) e depende do arquivamento do arquivo .sig.json fora do log."
        )
    if alg == "hmac-sha256":
        return (
            "Assinatura HMAC-SHA256 cobre integridade autenticada por chave simétrica compartilhada "
            "(sem não-repúdio perante terceiros sem a chave); não inclui carimbo de tempo externo "
            "confiável (RFC 3161 TSA) e depende do arquivamento do arquivo .sig.json fora do log."
        )
    return (
        "A assinatura não pôde ser validada; o arquivo .sig.json deve ser arquivado fora do log "
        "e não inclui carimbo de tempo externo confiável (RFC 3161 TSA)."
    )


def _traceability_blocks(d: dict) -> list[Block]:
    blocks: list[Block] = [
        ("h2", _SECTIONS[4]),
        (
            "p",
            (
                "Conformidade e proteção de dados: este pacote documental armazena exclusivamente "
                "indicadores estatísticos agregados, metadados operacionais e resumos criptográficos "
                "SHA-256 dos artefatos de entrada. Nenhum conteúdo de conversa real, dado pessoal, "
                "texto de ataque, resposta do modelo ou registro bruto de auditoria é copiado para "
                "este relatório. Os digests e a verificação da trilha de auditoria constam no "
                "Apêndice A."
            ),
        ),
    ]
    sig_line = _audit_signature_summary(d.get("audit"))
    if sig_line is not None:
        blocks.append(("p", sig_line))
    blocks += [
        ("p", "Limitações e ressalvas metodológicas aplicáveis a este parecer:"),
        ("ul", list(d["limitations"])),
    ]
    return blocks


def _conclusion_blocks(d: dict) -> list[Block]:
    color = d["semaphore"]["color"]
    triggered = d["semaphore"]["triggered"]
    au = d["audit"]

    actions_map = {
        "eval_regression": (
            "Corrigir a regressão de qualidade funcional antes de liberar a alteração para uso."
        ),
        "eval_nonsignificant_drop": (
            "Monitorar a qualidade funcional em amostra ampliada para confirmar estabilidade."
        ),
        "audit_invalid": (
            "Bloquear a aprovação e apurar a inconsistência apontada na cadeia de auditoria "
            "ou na assinatura da âncora (Apêndice A.6)."
        ),
        "no_audit": (
            "Anexar e validar o log de auditoria encadeado nas próximas execuções para "
            "assegurar rastreabilidade."
        ),
        "attack_success_with_guardrails": (
            "Investigar as simulações de ataque não contidas pelos controles ativos e reforçar "
            "as camadas preventivas."
        ),
        "false_positive": (
            "Calibrar os filtros preventivos para eliminar bloqueios indevidos de consultas "
            "legítimas sem ampliar a exposição a riscos."
        ),
    }
    recommendations = [actions_map[k] for k in triggered if k in actions_map]
    sig = au.get("signature") if isinstance(au, dict) else None
    sig_ok = not (isinstance(sig, dict) and sig.get("checked") and not sig.get("ok"))
    if au is not None and au["ok"] and sig_ok:
        if isinstance(sig, dict) and sig.get("checked"):
            recommendations.append(
                "Arquivar o recibo de assinatura (.sig.json) e a chave verificadora fora do "
                "arquivo de log para preservar a verificação autenticada de alterações."
            )
        else:
            recommendations.append(
                "Arquivar a âncora criptográfica (hash final da cadeia de auditoria) fora do "
                "arquivo de log para preservar a capacidade de detecção de alterações."
            )
    if d["semaphore"].get("not_evaluated"):
        recommendations.append(
            "Completar as métricas ausentes e reavaliar as regras não avaliadas "
            f"({', '.join(d['semaphore']['not_evaluated'])}); regra não avaliada não equivale a aprovação."
        )
    recommendations.append(
        f"Validar formalmente os limiares provisórios da regra de classificação "
        f"(versão {d['semaphore']['rules_version']}) com as áreas de Riscos e Auditoria Interna."
    )
    if not triggered:
        recommendations.append(
            "Manter a reexecução integral deste pacote de verificação a cada atualização de "
            "prompt, modelo ou base de conhecimento."
        )

    return [
        ("h2", _SECTIONS[5]),
        (
            "p",
            (
                f"Diante das evidências consolidadas neste ciclo de verificação, o parecer técnico "
                f"resulta em classificação {COLOR_LABEL[color]}. Os encaminhamentos abaixo orientam a "
                "tomada de decisão das alçadas responsáveis:"
            ),
        ),
        ("ul", recommendations),
        ("h3", "Quadro de Ciência e Aprovação"),
        (
            "table",
            ["Papel / Alçada", "Responsável", "Data", "Assinatura / Parecer"],
            [
                ["Responsável Técnico pelo Agente", "", "", ""],
                ["Gestor da Área de Negócio", "", "", ""],
                ["Auditoria Interna / Riscos e Conformidade", "", "", ""],
            ],
        ),
    ]


_NOT_RECORDED = "não registrado"


def _val(v: object, none: str = _NOT_RECORDED) -> str:
    return none if v is None else str(v)


def _dirty_text(v: object) -> str:
    return "não disponível" if v is None else "sim (mudanças locais)" if v else "não"


def _seed_text(seeds: dict) -> str:
    """Sementes como `chave=valor` (valores ausentes: não registrado)."""
    parts: list[str] = []
    for key, value in seeds.items():
        if isinstance(value, dict):
            parts += [f"{key}.{k}={_val(v)}" for k, v in value.items()]
        else:
            parts.append(f"{key}={_val(value)}")
    return "; ".join(parts) or _NOT_RECORDED


def _provenance_blocks(d: dict) -> list[Block]:
    """A.7: de onde vieram os números (relatórios antigos, sem o bloco, mostram só um aviso)."""
    pv = d.get("provenance")
    blocks: list[Block] = [("h2", "A.7 Proveniência da execução")]
    if not isinstance(pv, dict):
        return [*blocks, ("p", "Proveniência não registrada neste relatório.")]
    blocks += [
        (
            "p",
            (
                "Origem dos números: versão do kit, código, ambiente e modelo. Campos marcados "
                "como não registrado vêm de execuções gravadas antes deste controle."
            ),
        ),
        (
            "table",
            ["Item", "Valor"],
            [
                ["Versão do kit", _val(pv.get("kit_version"))],
                ["Commit git", _val(pv.get("git_commit"), "não disponível")],
                ["Árvore com mudanças locais", _dirty_text(pv.get("git_dirty"))],
                ["Python", _val(pv.get("python"))],
                ["Sistema operacional", _val(pv.get("platform"))],
                ["Modelo", _val(pv.get("model"))],
                ["Digest do modelo", _val(pv.get("model_digest"))],
                ["Versão do Ollama", _val(pv.get("ollama_version"))],
                ["Comando que gerou o pacote", _val(pv.get("command"))],
                ["Sementes", _seed_text(pv.get("seeds") or {})],
            ],
        ),
    ]
    ex = pv.get("executions") or {}
    runs = [(f"eval {v}", r) for v, r in (ex.get("eval") or {}).items()]
    runs += [(f"red team {k}", r) for k, r in (ex.get("redteam") or {}).items()]
    rows = []
    for name, r in runs:
        r = r or {}
        commit = r.get("git_commit")
        rows.append([
            name, _val(r.get("seed")), _val(r.get("model_digest")), _val(r.get("ollama_version")),
            f"{commit} ({_dirty_text(r.get('git_dirty'))})" if commit else _NOT_RECORDED,
            _val(r.get("command")),
        ])
    if rows:
        blocks += [
            ("h3", "A.7.1 Execuções que geraram os resultados"),
            ("table", ["Execução", "Semente", "Digest do modelo", "Ollama", "Commit", "Comando"], rows),
        ]
    inputs = pv.get("inputs") or {}
    if inputs:
        blocks += [
            ("h3", "A.7.2 Arquivos de entrada (SHA-256)"),
            ("table", ["Arquivo", "SHA-256"], [[k, v] for k, v in inputs.items()]),
        ]
    return blocks


_SOURCE_LABEL = {"redteam": "red team", "false_positive": "falso positivo", "eval": "eval"}
_FINDINGS_MAX_ROWS = 30


def _findings_blocks(d: dict) -> list[Block]:
    """A.8: achados com a linha do JSONL que os prova (só ids e hashes; sem texto de ataque)."""
    blocks: list[Block] = [("h2", "A.8 Achados e evidências")]
    found = d.get("findings")
    if not isinstance(found, list):
        return [*blocks, ("p", "Achados não registrados neste relatório.")]
    if not found:
        none = (
            "Nenhum achado: nenhum ataque com sucesso, erro de execução, "
            "pergunta legítima bloqueada ou regressão de caso no eval."
        )
        return [*blocks, ("p", none)]
    counts = {k: sum(f["source"] == k for f in found) for k in _SOURCE_LABEL}
    resumo = "; ".join(f"{_SOURCE_LABEL[k]}: {n}" for k, n in counts.items())
    blocks.append((
        "p",
        (
            f"{len(found)} achados ({resumo}). Cada achado aponta para a linha do arquivo de "
            "resultados que o prova (arquivo:linha) e para o SHA-256 do registro, calculado sobre "
            "o JSON canônico da linha; o build confere linha e hash e falha se divergirem. "
            "A severidade vem de uma tabela fixa por categoria (impacto potencial, não CVSS); "
            "erros, falsos positivos e regressões de eval ficam como não classificado."
        ),
    ))
    rank = {"alta": 0, "média": 1, "baixa": 2}
    tie = {"false_positive": 0, "redteam": 1, "eval": 2}  # empate de severidade: falso positivo antes
    shown = sorted(found, key=lambda f: (rank.get(f["severity"], 3), tie.get(f["source"], 3)))
    shown = shown[:_FINDINGS_MAX_ROWS]
    rows = [
        [
            f["id"], _SOURCE_LABEL.get(f["source"], f["source"]), _val(f.get("category"), "n/d"),
            f["severity"], f"{f['evidence']['file']}:{f['evidence']['line']}",
            f["evidence"]["record_sha256"][:12],
        ]
        for f in shown
    ]
    blocks.append(("table", ["ID", "Origem", "Categoria", "Severidade", "Arquivo:linha", "SHA-256"], rows))
    if len(found) > len(shown):
        note = (
            f"Listagem limitada a {len(shown)} dos {len(found)} achados (maior severidade "
            "primeiro; empate: falso positivo, red team, eval); a lista completa, com os hashes "
            "inteiros, está no relatorio.json (campo findings)."
        )
        blocks.append(("p", note))
    return blocks


def _coverage_blocks(d: dict) -> list[Block]:
    """A.9: cobertura OWASP Top 10 for LLM Applications (2025); só contagens, sem texto de ataque."""
    blocks: list[Block] = [("h2", "A.9 Cobertura OWASP LLM Top 10 (2025)")]
    cov = d.get("coverage")
    if not isinstance(cov, dict):
        return [*blocks, ("p", "Cobertura não registrada neste relatório.")]
    m = cov["map"]
    blocks.append((
        "p",
        (
            f"Mapa {m['id']} (versão {m['version']}, arquivo {m['path_relative']}, sha256 "
            f"{m['sha256'][:16]}...), baseado em {m['source'].removeprefix('https://')}. A ligação entre categorias de ataque, "
            "guardrails e IDs OWASP é conservadora e escolha do kit: só conta o que a suíte exercita "
            "ou o que o kit implementa. Categoria sem ataque nem controle aparece como não coberta, "
            "e ataque sem sucesso não prova ausência da fraqueza."
        ),
    ))

    def cell(r: dict) -> str:
        return f"{r['successes']}/{r['n']}" if r["n"] else "-"

    rows = [
        [
            c["id"], c["name"], c["status"], cell(c["baseline"]), cell(c["guardrails"]),
            ", ".join(c["controls"]) or "-", c["reason"] or "-",
        ]
        for c in cov["categories"]
    ]
    blocks.append((
        "table",
        ["ID", "Categoria", "Status", "Sucessos baseline", "Sucessos guardrails", "Controles do kit", "Observação"],
        rows,
    ))
    if cov["unmapped_attack_categories"]:
        blocks.append((
            "p", "Categorias de ataque fora do mapa: " + ", ".join(cov["unmapped_attack_categories"]) + ".",
        ))
    return blocks


def _appendix_blocks(d: dict) -> list[Block]:
    ev, rt, au = d["eval"], d["redteam"], d["audit"]
    fp = rt["false_positives"]
    man = ev["manifest"]

    cats = list(dict.fromkeys([*rt["asr"]["guardrails"].keys(), *rt["asr"]["baseline"].keys()]))
    if "total" in cats:
        cats = [c for c in cats if c != "total"] + ["total"]

    asr_rows: list[list[str]] = []
    for cat in cats:
        desc = _CATEGORY_RISK.get(cat, "Categoria adicional avaliada")
        for label, key in (("sem guardrails", "baseline"), ("com guardrails", "guardrails")):
            r = rt["asr"][key].get(cat)
            if r:
                asr_rows.append(
                    [
                        cat,
                        desc,
                        label,
                        str(r["n"]) + (f" (+{r['not_evaluated']} não avaliados)" if r.get("not_evaluated") else ""),
                        str(r["successes"]),
                        _pct(r["asr"]),
                        f"[{_pct(r['ci95_low'])}; {_pct(r['ci95_high'])}]",
                        str(r["errors"]),
                    ]
                )

    blocks: list[Block] = [
        ("h1", _SECTIONS[6], "appendix"),
        ("h2", "A.1 Avaliação funcional A/B (checagens determinísticas)"),
        (
            "table",
            ["Item", "Valor"],
            [
                [f"Média {ev['baseline']}", _f(ev["mean_baseline"])],
                [f"Média {ev['candidate']}", _f(ev["mean_candidate"])],
                [
                    f"Diferença ({ev['candidate']} - {ev['baseline']})",
                    _f(ev["mean_diff"], signed=True),
                ],
                [
                    "IC 95% (bootstrap)",
                    f"[{_f(ev['ci95_low'], signed=True)}; {_f(ev['ci95_high'], signed=True)}]",
                ],
                [f"p-valor (permutação pareada, {ev['p_method']})", _f(ev["p_value"])],
                ["Pares usados / descartados", f"{ev['n_pairs']} / {ev['n_dropped']}"],
                ["Semente / reamostragens", f"{ev['seed']} / {ev['n_resamples']}"],
                [
                    f"Gate (diferença menor que 0 e p menor que {ev['alpha']})",
                    "disparou" if ev["regression"] else "não disparou",
                ],
                ["Execuções por configuração", str(ev["runs_per_config"])],
            ],
        ),
    ]
    if _has_multirun(ev):
        variance = ev["variance"]
        var_rows = [
            [
                v,
                str(vs["n_runs"]),
                _f(vs["mean"]),
                _f(vs["run_stdev"]),
                _f(vs["mean_case_stdev"]),
                f"{_pct(vs['exact_score_consistency_rate'])}%",
                f"{_pct(vs['exact_answer_consistency_rate'])}%",
            ]
            for v in (ev["baseline"], ev["candidate"])
            if (vs := variance.get(v))
        ]
        if var_rows:
            blocks += [
                ("h3", "A.1.1 Variância entre execuções por variante"),
                (
                    "table",
                    [
                        "Variante",
                        "Execuções",
                        "Média",
                        "Desvio-padrão (execuções)",
                        "Desvio médio por caso",
                        "Consistência exata (score)",
                        "Consistência exata (resposta)",
                    ],
                    var_rows,
                ),
            ]
    blocks += [
        ("h2", "A.2 Taxa de sucesso de ataques (ASR) por categoria (IC 95% de Wilson)"),
        (
            "table",
            ["Categoria", "Descrição de risco", "Config.", "n", "Sucessos", "ASR %", "IC 95%", "Erros"],
            asr_rows,
        ),
        ("h2", "A.3 Falsos positivos em consultas legítimas"),
        (
            "table",
            ["Conjunto", "n", "Bloqueadas", "Taxa %", "IC 95% (Wilson)", "Erros"],
            [
                [
                    name,
                    str(r["n"]),
                    str(r["blocked"]),
                    _pct(r["rate"]),
                    f"[{_pct(r['ci95_low'])}; {_pct(r['ci95_high'])}]",
                    str(r["errors"]),
                ]
                for name, r in (
                    ("Dataset de avaliação", fp["dataset"]),
                    ("Consultas benignas inéditas", fp["benign"]),
                )
            ],
        ),
        ("h2", "A.4 Manifesto das respostas da avaliação funcional"),
        (
            "table",
            [
                "Variante",
                "Modelo",
                "Semente",
                "Casos",
                "Data",
                "SHA-256 do prompt",
                "SHA-256 do dataset",
            ],
            [
                [
                    v,
                    str(m["model"]),
                    str(m["seed"]),
                    str(m["n_cases"]),
                    str(m["date"]),
                    str(m["prompt_sha256"]),
                    str(m["dataset_sha256"]),
                ]
                for v, m in man.items()
            ],
        ),
        ("h2", "A.5 Hashes criptográficos dos arquivos de entrada (SHA-256)"),
        ("table", ["Entrada", "SHA-256"], [[k, v] for k, v in d["hashes"].items()]),
        ("h2", "A.6 Verificação da cadeia de auditoria"),
    ]
    if au is None:
        blocks.append(("p", "Nenhum log de auditoria informado neste pacote."))
    else:
        rows = [
            ["Cadeia", "íntegra" if au["ok"] else "inválida"],
            ["Eventos", str(au["n_events"])],
            ["Hash âncora (último hash)", str(au["anchor"])],
            ["Primeira linha com problema", str(au["first_bad_line"] or "-")],
            ["Motivo", str(au["reason"] or "-")],
        ]
        sig = au.get("signature")
        if isinstance(sig, dict) and sig.get("checked"):
            rows += [
                ["Assinatura da âncora", "válida" if sig.get("ok") else "inválida"],
                ["Algoritmo da assinatura", str(sig.get("algorithm") or "-")],
                ["Key fingerprint", str(sig.get("key_fingerprint") or "-")],
                ["Assinado em (UTC, recibo)", str(sig.get("signed_at_utc") or "-")],
                ["Motivo da assinatura", str(sig.get("reason") or "-")],
            ]
        else:
            rows.append(["Assinatura da âncora", "não informada (sem assinatura)"])
        blocks.append(("table", ["Item", "Valor"], rows))
        blocks.append(("p", _audit_signature_limitation(sig if isinstance(sig, dict) else None)))
    return [*blocks, *_provenance_blocks(d), *_findings_blocks(d), *_coverage_blocks(d)]


def build_blocks(d: dict) -> list[Block]:
    doc_code = _doc_code(d)
    return [
        *_pretextual_blocks(d, doc_code),
        *_scope_blocks(d),
        *_executive_verdict_blocks(d),
        *_functional_quality_blocks(d["eval"]),
        *_risk_analysis_blocks(d["redteam"]),
        *_traceability_blocks(d),
        *_conclusion_blocks(d),
        *_appendix_blocks(d),
    ]


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
        elif kind == "subtitle":
            out.append(f"*{_t(blk[1])}*")
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
    "@page{size:A4;margin:3cm 2cm 2cm 3cm}"
    "body{font-family:Arial,Helvetica,sans-serif;max-width:210mm;margin:1.5rem auto;"
    "padding:2rem 2.2rem;background:#fff;color:#1a1a1a;line-height:1.5;font-size:11pt;"
    "border:1px solid #d4d4d8}"
    "h1{font-size:1.3rem;color:#111;border-bottom:2px solid #1f2937;padding-bottom:.4rem;"
    "margin:0 0 .5rem;text-transform:uppercase;letter-spacing:.02em}"
    "h1.appendix{margin-top:2rem;padding-top:1rem;border-top:2px solid #94a3b8}"
    "h2{font-size:1.05rem;color:#111;border-bottom:1px solid #cbd5e1;padding-bottom:.25rem;"
    "margin:1.4rem 0 .6rem;page-break-after:avoid;break-after:avoid}"
    "h3{font-size:.98rem;color:#1f2937;margin:1.1rem 0 .45rem;"
    "page-break-after:avoid;break-after:avoid}"
    "p{margin:.5rem 0;text-align:justify}"
    ".subtitle{font-size:.98rem;color:#374151;margin:0 0 1.1rem;font-weight:bold;text-align:left}"
    "ul{margin:.45rem 0 .8rem 1.25rem;padding:0}"
    "li{margin:.25rem 0}"
    "table{border-collapse:collapse;width:100%;margin:.7rem 0 1rem;font-size:.86rem}"
    "thead{display:table-header-group}"
    "tr{page-break-inside:avoid;break-inside:avoid}"
    "th,td{border:1px solid #94a3b8;padding:.35rem .5rem;text-align:left;vertical-align:top;"
    "overflow-wrap:anywhere;word-break:break-word}"
    "th{background:#f1f5f9;color:#0f172a;font-weight:bold}"
    "tbody tr:nth-child(even) td{background:#f8fafc}"
    ".light{color:#fff;padding:.9rem 1rem;border-radius:4px;font-size:1.08rem;font-weight:bold;"
    "margin:.6rem 0 .9rem;page-break-inside:avoid;break-inside:avoid}"
    ".short-table{page-break-inside:avoid;break-inside:avoid}"
    "@media print{"
    "body{max-width:none;margin:0;padding:0;border:none;font-size:12pt;color:#000}"
    "table{font-size:10pt}"
    "th,.light{-webkit-print-color-adjust:exact;print-color-adjust:exact}"
    "h1.appendix{margin-top:0;padding-top:0;border-top:none;"
    "page-break-before:always;break-before:page}"
    "}"
)


def to_html(blocks: list[Block], title: str) -> str:
    body: list[str] = []
    for blk in blocks:
        kind = blk[0]
        if kind in ("h1", "h2", "h3"):
            cls = ' class="appendix"' if len(blk) > 2 and blk[2] == "appendix" else ""
            body.append(f"<{kind}{cls}>{escape(blk[1])}</{kind}>")
        elif kind == "subtitle":
            body.append(f'<p class="subtitle">{escape(blk[1])}</p>')
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
            cls = ' class="short-table"' if len(blk[2]) <= 10 else ""
            body.append(f"<table{cls}><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
    return (
        '<!DOCTYPE html>\n<html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" '
        "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>\n"
        + "\n".join(body)
        + "\n</body></html>\n"
    )
