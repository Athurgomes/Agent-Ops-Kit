"""`aok reproduce` (A9): reexecuta uma auditoria a partir de um pacote de relatório já emitido e
compara o resultado reexecutado com o declarado.

O relatório do `report build` é autodeclarado; o `report verify` só confere que ele é coerente com
os arquivos de evidência. Aqui o auditor reexecuta o eval e o red team (com e sem guardrails) com os
MESMOS parâmetros gravados na proveniência (agente, semente, dataset/suíte, modelo) e compara.

Fluxo: (1) `report verify` offline; pacote que falha é recusado. (2) Os arquivos de entrada têm de
existir e ter o mesmo sha256 gravado; senão recusa (nunca reexecuta dados diferentes). (3) Diferenças
de ambiente (versão do kit, modelo, digest, versão do Ollama) são registradas antes de rodar.
(4) Reexecuta em pasta nova, sem `--reuse`. (5) Compara e grava `reproducao.json`/`reproducao.md`.
(6) Registra o evento `reproduction` no log de auditoria encadeado (e assina a âncora com chave).

Vereditos por item, regras fixas, sem arredondar a favor (o resultado descreve, não aprova):
- `reproduzido`: reexecutado == original (igualdade exata do número).
- `dentro da variância`: só se o relatório declara variância entre execuções para a métrica
  (desvio-padrão das médias por execução, com 2 ou mais execuções) e |diferença| < esse desvio
  (na diferença de médias, raiz da soma dos quadrados dos desvios das duas variantes). Sem
  variância declarada, ou em reexecução parcial (`--limit`), esse veredito NÃO é usado.
- `divergente`: qualquer outra diferença.
- `não reproduzível`: não deu para rodar (motivo registrado).
A sobreposição dos ICs é registrada (`ci_overlap`) mas não muda o veredito.

Segurança: o agente do pacote (`target.ref` do agent.yaml) é código Python que SERÁ EXECUTADO; só roda
se o `pacote.modulo:funcao` resolver dentro da raiz do repositório atual (`resolve_target`), e só se o
agent.yaml tiver o mesmo sha256 do pacote. Não reproduza pacotes de origem não confiável sem revisar
esse código. Caminhos do relatório com `..`, absolutos ou que resolvam (links simbólicos) para fora da
raiz são recusados; `--out` precisa ser pasta nova ou vazia, fora do pacote original.

Limite: o Ollama pode não ser determinístico mesmo com temperatura 0 e semente fixa.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_ops_kit import audit, audit_sign, provenance
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.checks import run_checks
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.eval.prompts import load_prompt
from agent_ops_kit.redteam import false_positives as fp_mod
from agent_ops_kit.redteam import harness
from agent_ops_kit.redteam.attacks import load_attacks
from agent_ops_kit.report import build, verify
from agent_ops_kit.target import resolve_target

SCHEMA_VERSION = 1
REPRO_JSON = "reproducao.json"
REPRO_MD = "reproducao.md"
SCOPES = ("all", "eval", "redteam")

SAME, WITHIN, DIVERGENT, NOT_REPRODUCIBLE = (
    "reproduzido", "dentro da variância", "divergente", "não reproduzível",
)
VERDICTS = (SAME, WITHIN, DIVERGENT, NOT_REPRODUCIBLE)
RERUN, NOT_REQUESTED, NOT_STATUS = "reexecutado", "não solicitado", "não reproduzível"
ENV_SAME, ENV_DIFFERENT, ENV_UNCONFIRMED = "igual", "diferente", "não confirmado"

# Campos que, se diferirem, marcam "ambiente diferente"; os demais são só informativos.
_RELEVANT_ENV = ("kit_version", "model", "model_digest", "ollama_version", "generation_limits")
_INFO_ENV = ("git_commit", "python", "platform")

RULES = (
    "reproduzido: o número reexecutado é exatamente igual ao original.",
    (
        "dentro da variância: só quando o relatório declara variância entre execuções para a "
        "métrica (desvio-padrão das médias por execução, com 2 ou mais execuções) e a diferença "
        "absoluta é menor que esse desvio; na diferença de médias vale a raiz da soma dos "
        "quadrados dos desvios das duas variantes. Sem variância declarada, ou em reexecução "
        "parcial, esse veredito não é usado."
    ),
    "divergente: qualquer outra diferença.",
    "não reproduzível: não foi possível rodar (o motivo está registrado).",
    "A sobreposição dos intervalos de confiança é informada, mas não altera o veredito.",
)
NOTES = (
    "Este resultado descreve a reexecução; não é aprovação nem reprovação do agente.",
    (
        "O Ollama pode não ser determinístico mesmo com temperatura 0 e semente fixa (GPU ou CPU, "
        "versão do runtime, lotes). Em 21/11/2026, na reexecução do kit, o eval de 50 casos "
        "reproduziu exato e o de 200 casos divergiu 0,02 na média da v1."
    ),
    (
        "Uma reexecução idêntica não prova que o agente é seguro; uma divergente não prova erro "
        "do relatório. Só mostra se o procedimento declarado dá o mesmo resultado neste ambiente."
    ),
    "Resultados do red team aparecem só agregados; nenhum texto de ataque ou resposta é gravado aqui.",
    "O juiz (LLM-as-judge) não faz parte do pacote e não é reexecutado.",
)


class ReproduceError(Exception):
    """Recusa ou erro de uso: a reprodução não é feita (exit 2). Mensagem em português."""


class _NotReproducible(Exception):
    """Uma parte (eval, red team, falsos positivos) não pode ser reexecutada; a demais seguem."""


# --- esquema fechado do reproducao.json -------------------------------------------------------


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCmp(_Closed):
    case_id: str
    occurrence: int
    original_sha256: str | None
    rerun_sha256: str | None
    identical: bool
    original_outcome: float | bool | None
    rerun_outcome: float | bool | None


class AnswerGroup(_Closed):
    name: str
    n_cases: int
    n_identical: int
    identical_rate: float | None
    n_errors_original: int
    n_errors_rerun: int
    cases: list[CaseCmp]


class Part(_Closed):
    id: str
    status: str
    reason: str | None
    limit: int | None
    runs: int | None
    seeds: dict[str, int]
    groups: list[AnswerGroup]


class Item(_Closed):
    id: str
    description: str
    original: float | None
    rerun: float | None
    difference: float | None
    tolerance: float | None
    tolerance_source: str | None
    ci_overlap: bool | None
    verdict: str
    reason: str | None


class EnvDiff(_Closed):
    field: str
    original: str | None
    current: str | None


class Environment(_Closed):
    status: str
    original: dict[str, str | None]
    current: dict[str, str | None]
    differences: list[EnvDiff]
    informational: list[EnvDiff]
    not_recorded: list[str]


class Original(_Closed):
    report_sha256: str
    schema_version: int
    agent: str
    model: str | None


class Parameters(_Closed):
    scope: str
    limit_requested: int | None
    partial: bool
    command: str


class Verification(_Closed):
    ok: bool
    ok_count: int
    fail_count: int
    not_verifiable_count: int


class Reproduction(_Closed):
    schema_version: int
    kind: str
    generated_at: str
    original: Original
    parameters: Parameters
    verification: Verification
    environment: Environment
    parts: list[Part]
    items: list[Item]
    verdict_counts: dict[str, int]
    differences: list[str]
    artifacts: dict[str, str]
    rules: list[str]
    notes: list[str]


def validate(data: dict) -> Reproduction:
    """Valida o `reproducao.json` contra o esquema fechado (campo extra ou ausente é erro)."""
    return Reproduction.model_validate(data)


# --- utilidades -------------------------------------------------------------------------------

# Unidade ou UNC com barras invertidas (as pastas podem ter espaço) ou com barras comuns.
_WIN_PATH = re.compile(
    r"(?:(?<![\w])[A-Za-z]:\\|\\\\)(?:[^\\/:*?\"<>|\r\n]+\\)*[^\s\\/:*?\"<>|,;)']*"
    r"|(?<![\w])[A-Za-z]:/[^\s'\",;)]*"
)
_POSIX_PATH = re.compile(r"(?<![\w.:/-])/(?:[\w.@+~-]+/)+[\w.@+~-]*")


def scrub(text: str, roots: dict[str, Path | None] | None = None) -> str:
    """Remove caminhos pessoais: raízes conhecidas viram `<nome>`; qualquer caminho absoluto
    (inclusive estilo Windows em Linux) vira `<externo>/nome`."""
    ordered = sorted((roots or {}).items(), key=lambda kv: -len(str(kv[1] or "")))
    for label, root in ordered:
        if root is None:
            continue
        resolved = Path(root).resolve()
        for variant in {str(resolved), resolved.as_posix(), str(root), Path(root).as_posix()}:
            if len(variant) > 3:
                text = text.replace(variant, f"<{label}>")

    def repl(m: re.Match) -> str:
        return "<externo>/" + re.split(r"[\\/]", m.group(0).rstrip("\\/"))[-1]

    return _POSIX_PATH.sub(repl, _WIN_PATH.sub(repl, text))


def _scrub_all(obj: object, roots: dict[str, Path | None]) -> object:
    if isinstance(obj, str):
        return scrub(obj, roots)
    if isinstance(obj, list):
        return [_scrub_all(x, roots) for x in obj]
    if isinstance(obj, dict):
        return {k: _scrub_all(v, roots) for k, v in obj.items()}
    return obj


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


@dataclass
class _Ctx:
    data: dict
    repo_root: Path
    evidence_root: Path | None
    out: Path
    cfg: object
    llm: object
    scope: str
    limit: int | None
    exec_info: dict
    log: Callable[[str], None]
    partial: bool = False
    files: dict = field(default_factory=dict)

    def res(self, key: object, what: str) -> Path:
        """Chave do pacote (`caminho` ou `@evidence/...`) como caminho real; ausente = recusa."""
        if not isinstance(key, str) or not key:
            raise ReproduceError(f"o pacote não informa o caminho de {what}; não dá para reproduzir")
        p = Path(key)
        if p.anchor or ".." in p.parts:
            raise ReproduceError(f"caminho fora da raiz em {what}: {key}")
        if key.startswith(provenance.EVIDENCE_PREFIX):
            if self.evidence_root is None:
                raise ReproduceError(
                    f"{what} está na raiz de evidências ({key}): informe --evidence-root"
                )
            base, full = self.evidence_root, self.evidence_root / key[len(provenance.EVIDENCE_PREFIX):]
        else:
            base, full = self.repo_root, self.repo_root / p
        if full.exists() and not full.resolve().is_relative_to(base.resolve()):
            raise ReproduceError(f"{what} resolve para fora da raiz (link simbólico?): {key}")
        if not full.exists():
            raise ReproduceError(
                f"{what} não encontrado ({key}): sem o mesmo arquivo não há como reproduzir"
            )
        return full

    def same_sha(self, actual: str, expected: object, what: str, key: str) -> None:
        if actual != expected:
            raise ReproduceError(
                f"{what} ({key}) tem sha256 diferente do gravado no pacote: não reexecuto dados "
                "diferentes como se fossem os mesmos"
            )

    def effective_n(self, n_original: int) -> int:
        """Casos a reexecutar: os da execução original, ou menos se `--limit` pedir (parcial)."""
        eff = n_original if self.limit is None else min(n_original, self.limit)
        if eff < n_original:
            self.partial = True
        return eff


# --- comparação -------------------------------------------------------------------------------


def _answer_text(rec: dict, key: str) -> str:
    return f"[erro] {rec['error']}" if rec.get("error") else str(rec.get(key, ""))


def _index(recs: list[dict]) -> dict[tuple[str, int], dict]:
    seen: dict[str, int] = {}
    out: dict[tuple[str, int], dict] = {}
    for r in recs:
        n = seen.get(r["case_id"], 0)
        seen[r["case_id"]] = n + 1
        out[(r["case_id"], n)] = r
    return out


def _group(
    name: str, orig: list[dict], new: list[dict], key: str, outcome: Callable[[dict], float | bool]
) -> AnswerGroup:
    """Compara, por caso, o sha256 da resposta gravada com o da reexecutada (sem guardar texto)."""
    ids = {r["case_id"] for r in new}
    o, n = _index([r for r in orig if r["case_id"] in ids]), _index(new)
    cases = []
    for k in sorted(set(o) | set(n)):
        ro, rn = o.get(k), n.get(k)
        so = _sha_text(_answer_text(ro, key)) if ro else None
        sn = _sha_text(_answer_text(rn, key)) if rn else None
        cases.append(CaseCmp(
            case_id=k[0], occurrence=k[1], original_sha256=so, rerun_sha256=sn,
            identical=so is not None and so == sn,
            original_outcome=outcome(ro) if ro else None, rerun_outcome=outcome(rn) if rn else None,
        ))
    same = sum(c.identical for c in cases)
    return AnswerGroup(
        name=name, n_cases=len(cases), n_identical=same,
        identical_rate=same / len(cases) if cases else None,
        n_errors_original=sum(bool(r.get("error")) for r in orig if r["case_id"] in ids),
        n_errors_rerun=sum(bool(r.get("error")) for r in new), cases=cases,
    )


def _overlap(a: tuple[float, float] | None, b: tuple[float, float] | None) -> bool | None:
    if a is None or b is None:
        return None
    return max(a[0], b[0]) <= min(a[1], b[1])


def make_item(
    item_id: str, description: str, original: float | None, rerun: float | None, *,
    tolerance: float | None = None, tolerance_source: str | None = None,
    ci: tuple[tuple[float, float], tuple[float, float]] | None = None, partial: bool = False,
    reason: str | None = None,
) -> Item:
    """Veredito de um item pelas regras fixas (ver o docstring do módulo)."""
    if original is None or rerun is None:
        return Item(
            id=item_id, description=description, original=original, rerun=rerun, difference=None,
            tolerance=None, tolerance_source=None, ci_overlap=None, verdict=NOT_REPRODUCIBLE,
            reason=reason or "valor não disponível",
        )
    diff = rerun - original
    why = None
    if original == rerun:
        verdict = SAME
    elif tolerance is not None and tolerance > 0 and not partial and abs(diff) < tolerance:
        verdict = WITHIN
    else:
        verdict = DIVERGENT
        if partial:
            why = "reexecução parcial: a variância declarada é do conjunto completo e não se aplica"
        elif tolerance is None:
            why = "o relatório não declara variância para esta métrica"
        elif tolerance == 0:
            why = "a variância declarada é zero"
        else:
            why = "a diferença é maior ou igual à variância declarada"
    return Item(
        id=item_id, description=description, original=original, rerun=rerun, difference=diff,
        tolerance=tolerance, tolerance_source=tolerance_source,
        ci_overlap=_overlap(*ci) if ci else None, verdict=verdict, reason=why,
    )


def _failed_part(part_id: str, reason: str, scope_label: str) -> tuple[Part, list[Item]]:
    part = Part(id=part_id, status=NOT_STATUS, reason=reason, limit=None, runs=None, seeds={}, groups=[])
    item = Item(
        id=part_id, description=scope_label, original=None, rerun=None, difference=None,
        tolerance=None, tolerance_source=None, ci_overlap=None, verdict=NOT_REPRODUCIBLE, reason=reason,
    )
    return part, [item]


def _answers_item(group: AnswerGroup, item_id: str, what: str) -> Item:
    return make_item(
        item_id, f"{what}: taxa de respostas idênticas às gravadas (referência 1,0)",
        1.0 if group.n_cases else None, group.identical_rate,
        reason="nenhum caso comparado",
    )


# --- eval -------------------------------------------------------------------------------------


def _prompts_dir(ctx: _Ctx, variants: list[str], manifest: dict) -> Path:
    inputs = ctx.data["provenance"]["inputs"]
    dirs = []
    for v in variants:
        found = None
        for key in sorted(inputs):
            if key == f"{v}.md" or key.endswith(f"/{v}.md"):
                path = ctx.res(key, f"prompt {v}")
                if runner.sha256_text(load_prompt(v, path.parent)) == manifest[v].get("prompt_sha256"):
                    found = path.parent
                    break
        if found is None:
            raise ReproduceError(
                f"o prompt {v} não foi encontrado com o mesmo sha256 do manifesto do eval: "
                "não reexecuto prompts diferentes"
            )
        dirs.append(found)
    if dirs[0] != dirs[1]:
        raise _NotReproducible("os prompts das duas variantes estão em pastas diferentes")
    return dirs[0]


def _run_eval(ctx: _Ctx) -> tuple[Part, list[Item]]:
    ev = ctx.data["eval"]
    b, c = ev["baseline"], ev["candidate"]
    files = ctx.files
    dataset_path = ctx.res(files.get("eval_dataset"), "dataset do eval")
    ctx.same_sha(
        runner.dataset_hash(dataset_path), ctx.data["hashes"].get("eval_dataset"),
        "dataset do eval", files["eval_dataset"],
    )
    manifest = json.loads(ctx.res(files.get("eval_manifest"), "manifesto do eval").read_text(encoding="utf-8"))
    dataset = load_dataset(dataset_path)
    if len(dataset) != ev["n_dataset"]:
        raise ReproduceError("o dataset do eval tem outro número de casos que o do relatório")
    prompts_dir = _prompts_dir(ctx, [b, c], manifest)
    seeds = {v: manifest[v].get("seed") for v in (b, c)}
    if any(isinstance(s, bool) or not isinstance(s, int) for s in seeds.values()):
        raise _NotReproducible("semente de geração do eval não registrada no manifesto")
    runs = ev["runs_per_config"]
    limit = ctx.effective_n(ev["n_cases"])
    orig = {v: runner.load_records(ctx.res(files.get(f"eval_answers_{v}"), f"respostas de {v}")) for v in (b, c)}

    rerun = {}
    for v in (b, c):
        ctx.log(f"eval: reexecutando {v} (semente {seeds[v]}, {runs} execução(ões), "
                f"{limit} casos)")
        rerun[v] = runner.run_variant(
            v, dataset, ctx.cfg, llm=ctx.llm, out_path=ctx.out / "eval" / "answers" / f"{v}.jsonl",
            limit=limit, seed=seeds[v], prompts_dir=prompts_dir, runs=runs,
        )
    orig_f = {v: [r for r in orig[v] if r["case_id"] in {x["case_id"] for x in rerun[v]}] for v in (b, c)}
    try:
        sec_new, _ = build.eval_numbers(dataset, rerun, b, c, ev["seed"])
        sec_old, _ = build.eval_numbers(dataset, orig_f, b, c, ev["seed"])
    except (ValueError, KeyError, build.ReportError) as exc:
        raise _NotReproducible(f"não foi possível calcular os números do eval: {exc}") from exc

    by_id = {x.id: x for x in dataset}

    def score(r: dict) -> float:
        return run_checks(by_id[r["case_id"]], runner.final_answer(r["answer"])).score

    sd: dict[str, float | None] = {}
    for v in (b, c):
        var = (ev.get("variance") or {}).get(v) or {}
        sd[v] = var.get("run_stdev") if (var.get("n_runs") or 0) >= 2 else None
    src = "desvio-padrão entre execuções declarado em eval.variance.{}.run_stdev"
    tau_diff = math.sqrt(sd[b] ** 2 + sd[c] ** 2) if None not in sd.values() else None
    ci = ((sec_old["ci95_low"], sec_old["ci95_high"]), (sec_new["ci95_low"], sec_new["ci95_high"]))
    items = [
        make_item(f"eval.mean.{v}", f"eval: média das checagens determinísticas da variante {v}",
                  sec_old[key], sec_new[key], tolerance=sd[v],
                  tolerance_source=src.format(v) if sd[v] is not None else None, partial=ctx.partial)
        for v, key in ((b, "mean_baseline"), (c, "mean_candidate"))
    ] + [
        make_item("eval.mean_diff", f"eval: diferença de médias ({c} - {b})",
                  sec_old["mean_diff"], sec_new["mean_diff"], tolerance=tau_diff,
                  tolerance_source=(
                      "raiz da soma dos quadrados dos desvios declarados das duas variantes"
                      if tau_diff is not None else None),
                  ci=ci, partial=ctx.partial),
        make_item("eval.p_value", "eval: p-valor da permutação pareada",
                  sec_old["p_value"], sec_new["p_value"], partial=ctx.partial),
    ]
    groups = [_group(f"eval:{v}", orig_f[v], rerun[v], "answer", score) for v in (b, c)]
    items += [_answers_item(g, f"eval.answers.{v}", f"eval {v}") for g, v in zip(groups, (b, c), strict=True)]
    part = Part(
        id="eval", status=RERUN, reason=None, limit=limit, runs=runs,
        seeds={"bootstrap": ev["seed"], **{f"geracao_{v}": s for v, s in seeds.items()}},
        groups=groups,
    )
    return part, items


# --- red team e falsos positivos --------------------------------------------------------------


def _check_target(ctx: _Ctx, meta: dict, role: str) -> None:
    mine = provenance.target_info(ctx.cfg)["target"]
    rec = meta.get("target")
    if isinstance(rec, dict) and (rec.get("type"), rec.get("ref")) != (mine["type"], mine["ref"]):
        raise _NotReproducible(
            f"o agente do red team ({role}) não é o do agent.yaml do pacote "
            f"({rec.get('ref')} vs {mine['ref']})"
        )
    if meta.get("model") != ctx.cfg.model:
        raise _NotReproducible(f"o modelo do red team ({role}) difere do agent.yaml do pacote")


def _asr(recs: list[dict]) -> dict:
    return harness.asr_by_category([harness.AttackRecord(**r) for r in recs])["total"]


def _run_redteam(ctx: _Ctx) -> tuple[Part, list[Item]]:
    files = ctx.files
    metas: dict[str, dict] = {}
    for role in ("baseline", "guardrails"):
        key = files.get(f"redteam_{role}_meta")
        if not key:
            raise _NotReproducible(
                f"sidecar de proveniência do red team ({role}) ausente: o pacote é anterior à "
                "ADR-022 e não registra semente nem suíte"
            )
        metas[role] = json.loads(ctx.res(key, f"sidecar do red team ({role})").read_text(encoding="utf-8"))
    orig = {role: [r.model_dump() for r in harness.load_records(
        ctx.res(files.get(f"redteam_{role}"), f"resultado do red team ({role})"))] for role in metas}
    plan = {}
    for role, meta in metas.items():
        if meta.get("blind_suite_used"):
            raise _NotReproducible("a execução usou a suíte cega (sigilo): não é reexecutável aqui")
        _check_target(ctx, meta, role)
        seed = meta.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise _NotReproducible(f"semente do red team ({role}) não registrada")
        names = meta.get("guardrails") or []
        if names and getattr(ctx.cfg, "target", None) is not None:
            raise _NotReproducible("guardrails do kit não se aplicam a agente externo")
        akey, pkey = meta.get("attacks_dir"), meta.get("poisoned_dir")
        adir, pdir = ctx.res(akey, f"suíte de ataques ({role})"), ctx.res(pkey, f"corpus envenenado ({role})")
        ctx.same_sha(provenance.sha256_dir(adir), meta.get("attacks_sha256"), f"suíte de ataques ({role})", akey)
        ctx.same_sha(provenance.sha256_dir(pdir, "*.md"), meta.get("poisoned_sha256"),
                     f"corpus envenenado ({role})", pkey)
        cases = load_attacks(adir, pdir)
        if len(orig[role]) > len(cases):
            raise _NotReproducible(f"a suíte tem menos casos ({len(cases)}) que o resultado gravado")
        plan[role] = (cases, names, seed, pdir, ctx.effective_n(len(orig[role])))

    new: dict[str, list[dict]] = {}
    for role, (cases, names, seed, pdir, limit) in plan.items():
        ctx.log(f"red team: reexecutando {role} (semente {seed}, {limit} ataques)")
        recs = harness.run_suite(
            cases, ctx.cfg, llm=ctx.llm, out_path=ctx.out / "redteam" / f"{role}.jsonl", limit=limit,
            seed=seed, guardrails=names or None, poisoned_dir=pdir, meta=dict(ctx.exec_info),
        )
        new[role] = [r.model_dump() for r in recs]
    items, groups = [], []
    for role in ("baseline", "guardrails"):
        ids = {r["case_id"] for r in new[role]}
        old_rows = [r for r in orig[role] if r["case_id"] in ids]
        o, n = _asr(old_rows), _asr(new[role])
        items.append(make_item(
            f"redteam.{role}.asr", f"red team ({role}): taxa de sucesso dos ataques (ASR) total",
            o["asr"], n["asr"], ci=(tuple(o["ic95"]), tuple(n["ic95"])), partial=ctx.partial))
        g = _group(f"redteam:{role}", old_rows, new[role], "final_answer", lambda r: bool(r["success"]))
        groups.append(g)
        items.append(_answers_item(g, f"redteam.{role}.answers", f"red team ({role})"))
    part = Part(
        id="redteam", status=RERUN, reason=None,
        limit=min(p[4] for p in plan.values()), runs=1,
        seeds={f"geracao_{r}": p[2] for r, p in plan.items()}, groups=groups,
    )
    return part, items


def _run_fp(ctx: _Ctx) -> tuple[Part, list[Item]]:
    files = ctx.files
    key = files.get("fp_meta")
    if not key:
        raise _NotReproducible("sidecar dos falsos positivos (fp.meta.json) ausente no pacote")
    meta = json.loads(ctx.res(key, "sidecar dos falsos positivos").read_text(encoding="utf-8"))
    seed, names = meta.get("seed"), meta.get("guardrails") or []
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise _NotReproducible("semente dos falsos positivos não registrada")
    if names and getattr(ctx.cfg, "target", None) is not None:
        raise _NotReproducible("guardrails do kit não se aplicam a agente externo")
    sets = {}
    for name, mk, fk in (("dataset", "dataset_path", "fp_dataset"), ("benign", "benign_path", "fp_benign")):
        path = ctx.res(meta.get(mk), f"conjunto de falsos positivos ({name})")
        ctx.same_sha(provenance.sha256_file(path), meta.get(f"{name}_sha256"),
                     f"conjunto de falsos positivos ({name})", meta[mk])
        recs = _read_jsonl(ctx.res(files.get(fk), f"resultado de falsos positivos ({name})"))
        cases = load_dataset(path)
        if len(recs) > len(cases):
            raise _NotReproducible(f"o conjunto {name} tem menos casos que o resultado gravado")
        sets[name] = (cases, recs, ctx.effective_n(len(recs)))
    cfg = ctx.cfg
    if getattr(cfg, "target", None) is None:  # o exemplo usa o prompt v1 (como o fp_mod.main)
        pdir = ctx.repo_root / "evals" / "prompts"
        try:
            cfg = cfg.model_copy(update={"system_prompt": load_prompt("v1", pdir), "prompt_version": "v1"})
        except FileNotFoundError as exc:
            raise _NotReproducible("prompt v1 não encontrado em evals/prompts") from exc
    items, groups, limits = [], [], []
    for name, (cases, recs, limit) in sets.items():
        sel = cases[:limit]
        ctx.log(f"falsos positivos: reexecutando {name} ({len(sel)} perguntas)")
        new = fp_mod.run_benign(
            sel, cfg, names, llm=ctx.llm, out_path=ctx.out / "redteam" / f"fp_{name}.jsonl", seed=seed,
        )
        ids = {r["case_id"] for r in new}
        old_rows = [r for r in recs if r["case_id"] in ids]
        o, n = fp_mod.fp_rate(old_rows), fp_mod.fp_rate(new)
        items.append(make_item(
            f"false_positives.{name}.rate", f"falsos positivos ({name}): taxa de perguntas bloqueadas",
            o["taxa"], n["taxa"], ci=(tuple(o["ic95"]), tuple(n["ic95"])), partial=ctx.partial))
        g = _group(f"fp:{name}", old_rows, new, "answer", lambda r: bool(r["blocked"]))
        groups.append(g)
        items.append(_answers_item(g, f"false_positives.{name}.answers", f"falsos positivos ({name})"))
        limits.append(limit)
    part = Part(
        id="false_positives", status=RERUN, reason=None,
        limit=min(limits), runs=1,
        seeds={"geracao": seed}, groups=groups,
    )
    return part, items


# --- ambiente ---------------------------------------------------------------------------------


def _orig_env(data: dict, scope: str) -> dict[str, str | None]:
    ex = data["provenance"]["executions"]
    runs: list[dict | None] = []
    if scope in ("all", "eval"):
        runs += list((ex.get("eval") or {}).values())
    if scope in ("all", "redteam"):
        rt = ex.get("redteam") or {}
        runs += [rt.get("baseline"), rt.get("guardrails"), rt.get("false_positives")]
    out: dict[str, str | None] = {}
    for fld in ("kit_version", "git_commit", "python", "platform", "ollama_version", "model_digest"):
        vals = sorted({str(r[fld]) for r in runs if r and r.get(fld) is not None})
        out[fld] = " | ".join(vals) or None
    limits = sorted({json.dumps(r["generation_limits"], sort_keys=True)
                     for r in runs if r and r.get("generation_limits") is not None})
    out["generation_limits"] = " | ".join(limits) or None
    out["model"] = data["provenance"].get("model")
    return out


def _current_env(exec_info: dict, model: str) -> dict[str, str | None]:
    def s(v: object) -> str | None:
        return None if v is None else str(v)

    return {
        "kit_version": s(exec_info.get("kit_version")), "git_commit": s(exec_info.get("git_commit")),
        "python": s(exec_info.get("python")), "platform": s(exec_info.get("platform")),
        "ollama_version": s(exec_info.get("ollama_version")),
        "model_digest": s(exec_info.get("model_digest")),
        "generation_limits": json.dumps(exec_info.get("generation_limits"), sort_keys=True),
        "model": model,
    }


def compare_environment(original: dict[str, str | None], current: dict[str, str | None]) -> Environment:
    diffs, info, unknown = [], [], []
    for fld in _RELEVANT_ENV:
        if original.get(fld) is None:
            unknown.append(fld)
        elif original[fld] != current.get(fld):
            diffs.append(EnvDiff(field=fld, original=original[fld], current=current.get(fld)))
    for fld in _INFO_ENV:
        if original.get(fld) != current.get(fld):
            info.append(EnvDiff(field=fld, original=original.get(fld), current=current.get(fld)))
    status = ENV_DIFFERENT if diffs else ENV_UNCONFIRMED if unknown else ENV_SAME
    return Environment(
        status=status, original=original, current=current, differences=diffs, informational=info,
        not_recorded=unknown,
    )


# --- orquestração -----------------------------------------------------------------------------


def _default_out(package: Path) -> Path:
    base = package.resolve()
    cand = base.parent / f"{base.name}_reproducao"
    n = 2
    while cand.exists():
        cand = base.parent / f"{base.name}_reproducao_{n}"
        n += 1
    return cand


def _package_dir(path: str | Path) -> Path:
    p = Path(path)
    return p.parent if p.name == verify.PACKAGE_FILE else p


def _describe_diffs(items: list[Item], env: Environment, parts: list[Part]) -> list[str]:
    out = [f"ambiente: {d.field}: original {d.original}, atual {d.current}" for d in env.differences]
    for it in items:
        if it.verdict in (DIVERGENT, WITHIN):
            out.append(
                f"{it.id}: original {it.original:.6g}, reexecutado {it.rerun:.6g} ({it.verdict})"
            )
        elif it.verdict == NOT_REPRODUCIBLE:
            out.append(f"{it.id}: não reproduzível: {it.reason}")
    return out


def reproduce(
    package: str | Path,
    *,
    only: str = "all",
    out: str | Path | None = None,
    repo_root: str | Path = ".",
    evidence_root: str | Path | None = None,
    audit_log: str | Path | None = None,
    signing_key: str | Path | None = None,
    public_key: str | Path | None = None,
    hmac_key: str | None = None,
    limit: int | None = None,
    command: str = "aok reproduce",
    llm: object | None = None,
    fetch: Callable[[str], dict] | None = None,
    log: Callable[[str], None] = lambda _m: None,
) -> dict:
    """Reexecuta o pacote e grava `reproducao.{json,md}` e o evento no log de auditoria.

    `llm` e `fetch` só existem para teste (None = Ollama real). Levanta `ReproduceError` ao recusar.
    """
    if only not in SCOPES:
        raise ReproduceError(f"--only deve ser um de {', '.join(SCOPES)}")
    if limit is not None and limit < 1:
        raise ReproduceError("--limit deve ser >= 1")
    pkg = _package_dir(package)
    root = Path(repo_root)
    if root.resolve() != Path.cwd().resolve():
        raise ReproduceError(
            "rode a partir da raiz do repositório do pacote (o agente e o eval são importados do "
            "diretório atual); --repo-root deve ser o diretório atual"
        )
    ev_root = Path(evidence_root) if evidence_root is not None else None
    try:
        data = verify.load_package(pkg)
        report_bytes = (pkg / verify.PACKAGE_FILE).read_bytes()
        vres = verify.verify_package(pkg, root, hmac_key, public_key, False, ev_root)
    except verify.PackageError as exc:
        raise ReproduceError(f"pacote recusado: {exc}") from exc
    if not vres["ok"]:
        bad = [f"[{c['status']}] {c['label']}: {c['detail']}" for c in vres["checks"] if c["status"] != "ok"]
        raise ReproduceError(
            "o pacote não passou na verificação offline (report verify); recuso reproduzir um "
            "pacote que nem confere com os próprios arquivos:\n  " + "\n  ".join(bad)
        )
    if audit_log is not None and pkg.resolve() in Path(audit_log).resolve().parents:
        raise ReproduceError("--audit-log não pode ficar dentro do pacote original (o pacote não é alterado)")
    out_dir = Path(out) if out is not None else _default_out(pkg)
    if out_dir.resolve() == pkg.resolve() or pkg.resolve() in out_dir.resolve().parents:
        raise ReproduceError("--out não pode ser o próprio pacote nem uma pasta dentro dele")
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ReproduceError(f"{out_dir.name} já existe e não está vazia; nada foi sobrescrito")
    key_pem = None
    try:
        key_pem = Path(signing_key).read_bytes() if signing_key else audit_sign.signing_key_from_env()
        if key_pem:
            audit_sign.sign_bytes(b"", key_pem)  # valida a chave antes de rodar
    except (OSError, ValueError) as exc:
        raise ReproduceError(f"chave de assinatura inválida ou ilegível: {exc}") from exc

    files = data["provenance"].get("files")
    if not isinstance(files, dict) or not files:
        raise ReproduceError("o pacote não referencia seus arquivos (provenance.files): não dá para reproduzir")
    cfg_path = _res_cfg(files, root, ev_root)
    cfg = load_config(str(cfg_path))
    if provenance.sha256_file(cfg_path) != data["hashes"].get("config"):
        raise ReproduceError(
            "agent.yaml tem sha256 diferente do gravado no pacote: não reexecuto outro agente"
        )
    try:
        resolve_target(cfg)
    except Exception as exc:  # import do agente pode falhar de várias formas
        raise ReproduceError(
            "o agente do pacote não é reprodutível por este ambiente: "
            f"{scrub(str(exc), {'raiz': root})}"
        ) from exc

    exec_info = provenance.execution_info(cfg.model, command, fetch=fetch, cwd=root)
    env = compare_environment(_orig_env(data, only), _current_env(exec_info, cfg.model))
    log(f"ambiente: {env.status}")
    for d in env.differences:
        log(f"  diferença de ambiente: {d.field}: original {d.original}, atual {d.current}")
    out_dir.mkdir(parents=True, exist_ok=True)

    ctx = _Ctx(
        data=data, repo_root=root, evidence_root=ev_root, out=out_dir, cfg=cfg, llm=llm, scope=only,
        limit=limit, exec_info=exec_info, log=log, files=files,
    )
    parts: list[Part] = []
    items: list[Item] = []
    steps = []
    if only in ("all", "eval"):
        steps.append(("eval", "eval", _run_eval))
    if only in ("all", "redteam"):
        steps += [("redteam", "red team", _run_redteam), ("false_positives", "falsos positivos", _run_fp)]
    for pid, label, fn in steps:
        try:
            p, its = fn(ctx)
        except _NotReproducible as exc:
            p, its = _failed_part(pid, scrub(str(exc), {"raiz": root}), label)
        parts.append(p)
        items += its
    for pid, label in (("eval", "eval"), ("redteam", "red team"), ("false_positives", "falsos positivos")):
        if pid not in {p.id for p in parts}:
            parts.append(Part(id=pid, status=NOT_REQUESTED, reason=f"fora do escopo ({only})",
                              limit=None, runs=None, seeds={}, groups=[]))
    parts.sort(key=lambda p: ("eval", "redteam", "false_positives").index(p.id))

    artifacts = {
        p.relative_to(out_dir).as_posix(): provenance.sha256_file(p)
        for p in sorted(out_dir.rglob("*")) if p.is_file()
    }
    summary = vres["summary"]
    counts = {v: sum(i.verdict == v for i in items) for v in VERDICTS}
    roots = {"raiz": root, "evidencias": ev_root, "pacote": pkg, "saida": out_dir, "cwd": Path.cwd(),
             "home": Path.home()}
    repro = Reproduction(
        schema_version=SCHEMA_VERSION, kind="reproducao",
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        original=Original(
            report_sha256=_sha_bytes(report_bytes), schema_version=data["schema_version"],
            agent=data["agent"]["name"], model=data["agent"].get("model"),
        ),
        parameters=Parameters(
            scope=only, limit_requested=limit, partial=ctx.partial,
            command=provenance.sanitize_command(command, root),
        ),
        verification=Verification(
            ok=True, ok_count=summary["ok"], fail_count=summary["falha"],
            not_verifiable_count=summary["nao_verificavel"],
        ),
        environment=env, parts=parts, items=items, verdict_counts=counts,
        differences=_describe_diffs(items, env, parts), artifacts=artifacts,
        rules=list(RULES), notes=list(NOTES),
    )
    dump = _scrub_all(repro.model_dump(), roots)
    validate(dump)  # o que sai respeita o esquema fechado, mesmo depois do saneamento
    json_bytes = (json.dumps(dump, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (out_dir / REPRO_JSON).write_bytes(json_bytes)
    (out_dir / REPRO_MD).write_text(render_markdown(dump), encoding="utf-8", newline="\n")

    log_path = Path(audit_log) if audit_log is not None else out_dir / "audit" / "reproducao.jsonl"
    try:
        entry = audit.AuditLog(log_path).append("reproduction", {
            "schema_version": SCHEMA_VERSION,
            "original_report_sha256": repro.original.report_sha256,
            "reproducao_json_sha256": _sha_bytes(json_bytes),
            "environment_status": env.status,
            "partial": ctx.partial,
            "verdict_counts": counts,
            "verdicts": {i.id: i.verdict for i in items},
        })
    except audit.AuditChainError as exc:
        raise ReproduceError(f"log de auditoria recusado: {exc}") from exc
    sig_path = None
    if key_pem:
        sig_path = log_path.with_suffix(".sig.json")
        audit_sign.sign_anchor(log_path, private_key_pem=key_pem, out_path=sig_path)
    return {
        "out": out_dir, "json": out_dir / REPRO_JSON, "md": out_dir / REPRO_MD, "data": dump,
        "audit_log": log_path, "audit_seq": entry["seq"], "signature": sig_path,
        "stale_signature": audit_log is not None and not key_pem and log_path.with_suffix(".sig.json").exists(),
    }


def _res_cfg(files: dict, root: Path, ev_root: Path | None) -> Path:
    key = files.get("config")
    if not isinstance(key, str):
        raise ReproduceError("o pacote não referencia o agent.yaml (provenance.files.config)")
    if key.startswith(provenance.EVIDENCE_PREFIX):
        if ev_root is None:
            raise ReproduceError(f"agent.yaml está na raiz de evidências ({key}): informe --evidence-root")
        p = ev_root / key[len(provenance.EVIDENCE_PREFIX):]
    else:
        p = root / key
    if not p.is_file():
        raise ReproduceError(f"agent.yaml não encontrado ({key}): sem o agente não há como reproduzir")
    return p


# --- markdown ---------------------------------------------------------------------------------


def _num(x: float | None) -> str:
    return "n/d" if x is None else f"{x:.4f}"


def render_markdown(d: dict) -> str:
    """reproducao.md: função pura do reproducao.json (mesma entrada, mesmo texto)."""
    o, p, e = d["original"], d["parameters"], d["environment"]
    lines = [
        "# Reexecução da auditoria", "",
        (
            "Resultado da reexecução de um pacote de relatório já emitido. Descreve o que "
            "aconteceu; não aprova nem reprova o agente."
        ),
        "",
        "## Pacote original", "",
        f"- sha256 do relatorio.json: `{o['report_sha256']}`",
        f"- Agente: {o['agent']} (modelo {o['model'] or 'não registrado'})",
        (
            "- Verificação offline antes de reexecutar (report verify): "
            f"{d['verification']['ok_count']} ok, {d['verification']['fail_count']} falha(s), "
            f"{d['verification']['not_verifiable_count']} não verificável(is)"
        ),
        f"- Escopo: {p['scope']}"
        + (f"; limite pedido: {p['limit_requested']}" if p["limit_requested"] else ""),
        f"- Comando: `{p['command']}`",
    ]
    if p["partial"]:
        lines += ["", (
            "**Reexecução parcial** (`--limit`): só os primeiros casos foram reexecutados; "
            "os números não são comparáveis com os agregados do relatório inteiro."
        )]
    lines += ["", "## Ambiente", "", f"Situação: **ambiente {e['status']}**."
              if e["status"] == ENV_DIFFERENT else f"Situação: ambiente {e['status']}.", ""]
    lines += ["| Campo | Original | Atual |", "|---|---|---|"]
    for k in (*_RELEVANT_ENV, *_INFO_ENV):
        lines.append(f"| {k} | {e['original'].get(k) or 'não registrado'} | {e['current'].get(k) or 'não registrado'} |")
    if e["not_recorded"]:
        lines += ["", "Não registrados no original (não dá para confirmar): " + ", ".join(e["not_recorded"]) + "."]
    lines += ["", "## Partes", "", "| Parte | Situação | Limite | Execuções | Sementes | Motivo |", "|---|---|---|---|---|---|"]
    for pt in d["parts"]:
        seeds = ", ".join(f"{k} {v}" for k, v in pt["seeds"].items()) or "-"
        lines.append(
            f"| {pt['id']} | {pt['status']} | {pt['limit'] if pt['limit'] is not None else 'todos'} "
            f"| {pt['runs'] if pt['runs'] is not None else '-'} | {seeds} | {pt['reason'] or '-'} |"
        )
    lines += ["", "## Vereditos por item", ""]
    if d["items"]:
        lines += ["| Item | Original | Reexecução | Diferença | Variância declarada | ICs se sobrepõem | Veredito |",
                  "|---|---|---|---|---|---|---|"]
        for it in d["items"]:
            ci = "-" if it["ci_overlap"] is None else "sim" if it["ci_overlap"] else "não"
            verdict = it["verdict"] + (f" ({it['reason']})" if it["reason"] else "")
            lines.append(
                f"| {it['id']} | {_num(it['original'])} | {_num(it['rerun'])} | {_num(it['difference'])} "
                f"| {_num(it['tolerance'])} | {ci} | {verdict} |"
            )
        c = d["verdict_counts"]
        lines += ["", "Contagem: " + ", ".join(f"{v} {c[v]}" for v in VERDICTS) + "."]
    else:
        lines.append("Nenhum item reexecutado.")
    lines += ["", "## Respostas por caso (sha256, sem texto)", ""]
    groups = [(pt["id"], g) for pt in d["parts"] for g in pt["groups"]]
    if groups:
        lines += ["| Grupo | Casos | Idênticas | Taxa | Erros original | Erros reexecução |", "|---|---|---|---|---|---|"]
        for _, g in groups:
            lines.append(
                f"| {g['name']} | {g['n_cases']} | {g['n_identical']} | {_num(g['identical_rate'])} "
                f"| {g['n_errors_original']} | {g['n_errors_rerun']} |"
            )
    else:
        lines.append("Nenhuma resposta comparada.")
    lines += ["", "## Diferenças registradas", ""]
    lines += [f"- {x}" for x in d["differences"]] or ["- nenhuma"]
    lines += ["", "## Regras de veredito", ""] + [f"- {x}" for x in d["rules"]]
    lines += ["", "## Notas", ""] + [f"- {x}" for x in d["notes"]] + [""]
    return "\n".join(lines)


def command_from_argv(argv: list[str]) -> str:
    return "aok " + shlex.join(argv)


__all__ = [
    "ReproduceError", "Reproduction", "command_from_argv", "compare_environment", "make_item",
    "render_markdown", "reproduce", "validate",
]
