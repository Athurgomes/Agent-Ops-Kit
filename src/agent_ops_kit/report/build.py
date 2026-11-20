"""Monta os dados do relatório (relatorio.json) a partir dos resultados gravados. Sem modelo.

O JSON tem esquema fixo: só agregados, hashes e metadados. Nunca copia texto de ataque, resposta
do modelo, rubrica do juiz nem conteúdo de eventos de auditoria.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

from agent_ops_kit import audit, audit_sign, provenance
from agent_ops_kit.cli import ALPHA
from agent_ops_kit.config import load_config
from agent_ops_kit.eval import runner
from agent_ops_kit.eval.ab import paired_ab
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.redteam.false_positives import fp_rate
from agent_ops_kit.redteam.harness import asr_by_category
from agent_ops_kit.redteam.report import ReportError, _load_attacks, _load_jsonl
from agent_ops_kit.report import coverage as coverage_mod
from agent_ops_kit.report import findings as findings_mod
from agent_ops_kit.report import policy as policy_mod
from agent_ops_kit.report import stats as stats_mod

SCHEMA_VERSION = 1

# As regras do semáforo vivem em policies/default.yaml (ou na política dada por --policy).
GREEN_TEXT = (
    "Verde não significa seguro: indica que nada reprovou neste teste, com este escopo "
    "e estas limitações."
)

_MANIFEST_KEYS = ("prompt_sha256", "dataset_sha256", "model", "seed", "n_cases", "date")
# Proveniência gravada na execução (ausente nos manifestos e sidecars antigos: vira null).
_EXEC_KEYS = (
    "answers_sha256", "kit_version", "git_commit", "git_dirty", "python", "platform",
    "ollama_version", "model_digest", "command",
)
_RT_META_KEYS = (
    "model", "seed", "guardrails_enabled", "attacks_sha256", "poisoned_sha256", "results_sha256",
    *_EXEC_KEYS[1:],
)
_FP_META_KEYS = ("model", "seed", "guardrails", "dataset_sha256", "benign_sha256", *_EXEC_KEYS[1:])


def _need(path: Path, label: str) -> None:
    if not path.is_file():
        raise ReportError(f"{label} não encontrado: {path}")


def _sha(path: Path) -> str:
    return runner.sha256_text(path.read_text(encoding="utf-8"))


def _add_input(inputs: dict[str, str], path: Path, evidence_root: str | None = None) -> str | None:
    """Registra o sha256 do arquivo (caminho relativo à raiz, ou `@evidence/...`) se ele
    existir; devolve a chave."""
    if not path.is_file():
        return None
    key, sha = provenance.rel_path(path, evidence_root=evidence_root), provenance.sha256_file(path)
    if inputs.get(key, sha) != sha:  # mesmo nome em pastas diferentes fora da raiz
        key = f"{path.resolve().parent.name}/{key}"
    inputs[key] = sha
    return key


def _role(
    prov: dict, role: str, path: Path | str | None, as_input: bool = True,
    evidence_root: str | None = None,
) -> None:
    """Mapa papel -> chave do arquivo (provenance.files): é como `report verify` acha a evidência."""
    if path is None or not Path(path).is_file():
        return
    key = (
        _add_input(prov["inputs"], Path(path), evidence_root) if as_input
        else provenance.rel_path(path, evidence_root=evidence_root)
    )
    prov["files"][role] = key


def _load_meta(path: Path, label: str) -> dict | None:
    """Lê o sidecar de proveniência; ausente (execução antiga) devolve None."""
    if not path.is_file():
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(f"sidecar de proveniência inválido ({label}): {path}") from exc
    if not isinstance(meta, dict):
        raise ReportError(f"sidecar de proveniência inválido ({label}): {path}")
    return meta


def _check_sha(recorded: object, path: Path, what: str) -> None:
    """Se há hash registrado, o arquivo atual tem de bater; sem hash registrado, não confere."""
    if not isinstance(recorded, str):
        return
    if not path.is_file():
        raise ReportError(f"{what} registrado na proveniência não encontrado: {path}")
    if provenance.sha256_file(path) != recorded:
        raise ReportError(
            f"{what} mudou desde a execução (sha256 diverge do registrado): {path}. "
            "Regrave os resultados"
        )


def _recorded_path(key: str, evidence_root: str | None) -> Path:
    """Caminho gravado no sidecar (relativo ao repositório ou `@evidence/...`) como caminho real."""
    try:
        return provenance.resolve_key(key, evidence_root)
    except ValueError as exc:
        raise ReportError(str(exc)) from exc


def _check_dir(
    meta: dict, dir_key: str, sha_key: str, pattern: str, what: str, evidence_root: str | None = None
) -> None:
    """Se o sidecar registra pasta e hash, a pasta atual tem de existir e bater."""
    key, recorded = meta.get(dir_key), meta.get(sha_key)
    if not (isinstance(key, str) and isinstance(recorded, str)):
        return
    path = _recorded_path(key, evidence_root)
    if not path.is_dir():
        raise ReportError(
            f"{what} registrado na proveniência não encontrado: {key} "
            "(se estiver fora do repositório, use --evidence-root)"
        )
    if provenance.sha256_dir(path, pattern) != recorded:
        raise ReportError(
            f"{what} mudou desde a execução (sha256 diverge do registrado): {path}. "
            "Regrave os resultados"
        )


def _redteam_meta(result_path: Path, role: str, evidence_root: str | None = None) -> dict | None:
    meta = _load_meta(Path(f"{result_path}.meta.json"), f"red team, {role}")
    if meta is None:
        return None
    _check_sha(meta.get("results_sha256"), result_path, f"resultado do red team ({role})")
    _check_dir(
        meta, "attacks_dir", "attacks_sha256", "*.jsonl", f"suíte de ataques ({role})", evidence_root
    )
    _check_dir(
        meta, "poisoned_dir", "poisoned_sha256", "*.md", f"corpus envenenado ({role})", evidence_root
    )
    return meta


def _fp_meta(fp_dir: Path, evidence_root: str | None = None) -> dict | None:
    meta = _load_meta(fp_dir / "fp.meta.json", "falsos positivos")
    if meta is None:
        return None
    results = meta.get("results_sha256")
    for name in ("fp_dataset.jsonl", "fp_benign.jsonl"):
        recorded = results.get(name) if isinstance(results, dict) else None
        _check_sha(recorded, fp_dir / name, f"resultado de falsos positivos ({name})")
    for key, label in (("dataset", "dataset dos falsos positivos"), ("benign", "conjunto benigno")):
        path, sha = meta.get(f"{key}_path"), meta.get(f"{key}_sha256")
        if isinstance(path, str):
            _check_sha(sha, _recorded_path(path, evidence_root), label)
    return meta


# Só entram na proveniência quando o sidecar os traz (pacotes antigos continuam verificáveis).
_OPTIONAL_KEYS = ("target", "n_tool_not_evaluated", "generation_limits")


def _pick(meta: dict | None, keys: tuple[str, ...], base: str | Path | None = None) -> dict | None:
    if meta is None:
        return None
    out = {k: meta.get(k) for k in keys}
    out.update({k: meta[k] for k in _OPTIONAL_KEYS if k in meta})
    if isinstance(out.get("command"), str):  # sidecars antigos podem ter caminhos pessoais
        out["command"] = provenance.sanitize_command(out["command"], base)
    return out


def manifest_view(manifest_raw: dict, variants: list[str]) -> dict:
    return {v: {k: manifest_raw[v].get(k) for k in _MANIFEST_KEYS} for v in variants}


def agent_block(config, manifest: dict, candidate: str) -> dict:
    return {
        "name": config.name,
        "prompt_version": config.prompt_version,
        "model": manifest[candidate]["model"] or config.model,
    }


def _runs(case_ids: list[str]) -> int:
    """Execuções gravadas por configuração: maior nº de registros de um mesmo caso."""
    return max(Counter(case_ids).values(), default=0)


def _asr_row(r: dict) -> dict:
    lo, hi = r["ic95"]
    return {
        "n": r["n"], "successes": r["sucessos"], "asr": r["asr"],
        "ci95_low": lo, "ci95_high": hi, "errors": r["n_erros"],
        **({"not_evaluated": r["n_nao_avaliados"]} if r.get("n_nao_avaliados") else {}),
    }


def _fp_row(recs: list[dict]) -> dict:
    r = fp_rate(recs)
    lo, hi = r["ic95"]
    return {
        "n": r["n"], "blocked": r["bloqueadas"], "rate": r["taxa"],
        "ci95_low": lo, "ci95_high": hi, "errors": r["n_erros"],
    }


def eval_numbers(
    dataset: list, records: dict[str, list[dict]], baseline: str, candidate: str, seed: int
) -> tuple[dict, dict]:
    """Números do eval a partir das respostas gravadas (compartilhado por `build` e `verify`).

    Devolve (seção do relatorio.json sem o manifesto, nota por caso de cada variante).
    """
    variants = [baseline, candidate]
    scores = {v: runner.score_records(dataset, records[v]) for v in variants}
    variance = {v: runner.summarize_runs(dataset, records[v]) for v in variants}
    try:
        ab = paired_ab(scores[baseline], scores[candidate], seed=seed)
    except ValueError as exc:
        raise ReportError(f"não foi possível comparar as variantes do eval: {exc}") from exc
    section = {
        "baseline": baseline, "candidate": candidate,
        "metric": "score das checagens determinísticas, de 0 a 1",
        "n_cases": len(dataset), "n_pairs": ab.n, "n_dropped": ab.n_dropped,
        "runs_per_config": min(_runs([r["case_id"] for r in records[v]]) for v in variants),
        "variance": variance,
        "mean_baseline": ab.mean_baseline, "mean_candidate": ab.mean_candidate,
        "mean_diff": ab.mean_diff, "ci95_low": ab.ci_low, "ci95_high": ab.ci_high,
        "p_value": ab.p_value, "p_method": ab.p_method, "seed": ab.seed,
        "n_resamples": ab.n_resamples, "alpha": ALPHA,
        "regression": ab.mean_diff < 0 and ab.p_value < ALPHA,
    }
    return section, scores


def redteam_numbers(base: list, guard: list, ds: list[dict], bn: list[dict]) -> dict:
    """Números do red team e dos falsos positivos (compartilhado por `build` e `verify`)."""
    asr = {
        name: {c: _asr_row(r) for c, r in asr_by_category(recs).items()
            if r["n"] or r.get("n_nao_avaliados")}
        for name, recs in (("baseline", base), ("guardrails", guard))
    }
    return {
        "n_attacks": len(guard),
        "n_blind_attacks": sum(r.is_blind for r in guard),
        "mcnemar": stats_mod.mcnemar_block(base, guard),
        "runs_per_config": min(_runs([r.case_id for r in recs]) for recs in (base, guard)),
        "asr": asr,
        "false_positives": {"dataset": _fp_row(ds), "benign": _fp_row(bn)},
        "n_legit_questions": len(ds) + len(bn),
    }


def not_evaluated_mismatches(numbers: dict, executions: dict) -> list[str]:
    """Contagem de casos não avaliados do sidecar (`n_tool_not_evaluated`) vs a dos resultados."""
    out = []
    for name in ("baseline", "guardrails"):
        recorded = ((executions.get("redteam") or {}).get(name) or {}).get("n_tool_not_evaluated")
        fresh = ((numbers["asr"].get(name) or {}).get("total") or {}).get("not_evaluated", 0)
        if recorded is not None and recorded != fresh:
            out.append(f"{name}: sidecar registra {recorded} não avaliados, resultados têm {fresh}")
    return out


def _eval_section(a: dict, hashes: dict, prov: dict, ctx: dict) -> tuple[dict, dict]:
    ev_root = a["evidence_root"]
    dataset_path, answers_dir = Path(a["dataset"]), Path(a["answers_dir"])
    variants = [a["baseline"], a["candidate"]]
    _need(Path(a["config"]), "config")
    _need(dataset_path, "dataset")
    _need(answers_dir / runner.MANIFEST_NAME, "manifesto")
    for v in variants:
        _need(answers_dir / f"{v}.jsonl", f"respostas gravadas de {v}")
    config = load_config(a["config"])
    try:
        runner.verify_manifest(answers_dir, variants, config, dataset_path, a["prompts_dir"])
    except runner.ManifestError as exc:
        raise ReportError(str(exc)) from exc

    dataset = load_dataset(dataset_path)
    records = {v: runner.load_records(answers_dir / f"{v}.jsonl") for v in variants}
    section, scores = eval_numbers(dataset, records, variants[0], variants[1], a["seed"])
    manifest_raw = json.loads((answers_dir / runner.MANIFEST_NAME).read_text(encoding="utf-8"))
    manifest = manifest_view(manifest_raw, variants)
    prov["executions"]["eval"] = {v: _pick(manifest_raw[v], _EXEC_KEYS) for v in variants}
    prov["seeds"]["eval_ab_bootstrap"] = a["seed"]
    prov["seeds"]["eval_generation"] = {v: manifest[v]["seed"] for v in variants}
    inputs = prov["inputs"]
    for path in (
        Path(a["config"]), dataset_path, answers_dir / runner.MANIFEST_NAME,
        *[Path(a["prompts_dir"]) / f"{v}.md" for v in variants],
        *[answers_dir / f"{v}.jsonl" for v in variants],
        *sorted((Path(a["config"]).parent / "corpus").glob("*.md")),
    ):
        _add_input(inputs, path, ev_root)
    _role(prov, "config", a["config"], evidence_root=ev_root)
    _role(prov, "eval_dataset", dataset_path, evidence_root=ev_root)
    _role(prov, "eval_manifest", answers_dir / runner.MANIFEST_NAME, evidence_root=ev_root)
    for v in variants:
        _role(prov, f"eval_answers_{v}", answers_dir / f"{v}.jsonl", evidence_root=ev_root)

    hashes["config"] = _sha(Path(a["config"]))
    hashes["eval_dataset"] = _sha(dataset_path)
    hashes["eval_manifest"] = _sha(answers_dir / runner.MANIFEST_NAME)
    for v in variants:
        hashes[f"eval_answers_{v}"] = _sha(answers_dir / f"{v}.jsonl")

    ctx["eval"] = {
        "baseline": variants[0], "candidate": variants[1],
        "baseline_path": answers_dir / f"{variants[0]}.jsonl",
        "candidate_path": answers_dir / f"{variants[1]}.jsonl",
        "scores_baseline": scores[variants[0]], "scores_candidate": scores[variants[1]],
        "categories": {c.id: c.category for c in dataset},
    }
    section["manifest"] = manifest
    return section, agent_block(config, manifest, variants[1])


def _refuse_mixed_targets(metas: dict) -> None:
    """Baseline e guardrails entram na mesma tabela e no McNemar pareado: de agentes diferentes
    não se combinam (ADR-030)."""
    tb, tg = (metas["baseline"] or {}).get("target"), (metas["guardrails"] or {}).get("target")
    if tb and tg and stats_mod.target_text(tb) != stats_mod.target_text(tg):
        raise ReportError(
            "red team baseline e guardrails são de agentes diferentes "
            f"({stats_mod.target_text(tb)} / {stats_mod.target_text(tg)}); "
            "não são combinados na mesma tabela. Informe execuções do mesmo agente"
        )


def _redteam_section(a: dict, hashes: dict, prov: dict, ctx: dict) -> dict:
    ev_root = a["evidence_root"]
    fp_dir = Path(a["fp_dir"])
    base_p, guard_p = Path(a["redteam_baseline"]), Path(a["redteam_guardrails"])
    # Os sidecars são conferidos antes de ler os resultados: adulteração falha com mensagem clara.
    metas = {
        "baseline": _redteam_meta(base_p, "baseline", ev_root),
        "guardrails": _redteam_meta(guard_p, "guardrails", ev_root),
    }
    _refuse_mixed_targets(metas)
    fp_meta = _fp_meta(fp_dir, ev_root)
    base, guard = _load_attacks(base_p), _load_attacks(guard_p)
    ds = _load_jsonl(fp_dir / "fp_dataset.jsonl")
    bn = _load_jsonl(fp_dir / "fp_benign.jsonl")
    hashes["redteam_baseline"] = _sha(base_p)
    hashes["redteam_guardrails"] = _sha(guard_p)
    hashes["fp_dataset"] = _sha(fp_dir / "fp_dataset.jsonl")
    hashes["fp_benign"] = _sha(fp_dir / "fp_benign.jsonl")
    prov["executions"]["redteam"] = {
        **{k: _pick(m, _RT_META_KEYS) for k, m in metas.items()},
        "false_positives": _pick(fp_meta, _FP_META_KEYS),
    }
    prov["seeds"]["redteam"] = {k: (m or {}).get("seed") for k, m in metas.items()}
    prov["seeds"]["false_positives"] = (fp_meta or {}).get("seed")
    inputs = prov["inputs"]
    for path in (base_p, Path(f"{base_p}.meta.json"), guard_p, Path(f"{guard_p}.meta.json")):
        _add_input(inputs, path, ev_root)
    for name in ("fp_dataset.jsonl", "fp_benign.jsonl", "fp.meta.json"):
        _add_input(inputs, fp_dir / name, ev_root)
    for meta in metas.values():
        for key, pattern in (("attacks_dir", "*.jsonl"), ("poisoned_dir", "*.md")):
            if meta and isinstance(meta.get(key), str):
                for path in sorted(_recorded_path(meta[key], ev_root).glob(pattern)):
                    _add_input(inputs, path, ev_root)
    for key in ("dataset_path", "benign_path"):
        if fp_meta and isinstance(fp_meta.get(key), str):
            _add_input(inputs, _recorded_path(fp_meta[key], ev_root), ev_root)
    ctx["redteam"] = {"baseline": base_p, "guardrails": guard_p}
    ctx["false_positives"] = {
        "dataset": fp_dir / "fp_dataset.jsonl", "benign": fp_dir / "fp_benign.jsonl",
    }
    for role, path in (
        ("redteam_baseline", base_p), ("redteam_guardrails", guard_p),
        ("fp_dataset", fp_dir / "fp_dataset.jsonl"), ("fp_benign", fp_dir / "fp_benign.jsonl"),
        ("redteam_baseline_meta", Path(f"{base_p}.meta.json")),
        ("redteam_guardrails_meta", Path(f"{guard_p}.meta.json")),
        ("fp_meta", fp_dir / "fp.meta.json"),
    ):
        _role(prov, role, path, evidence_root=ev_root)
    numbers = redteam_numbers(base, guard, ds, bn)
    if bad := not_evaluated_mismatches(numbers, prov["executions"]):
        raise ReportError("casos não avaliados divergem do sidecar: " + "; ".join(bad))
    return numbers


def _read_signed_at(signature_path: str | Path) -> str | None:
    try:
        obj = json.loads(Path(signature_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    if isinstance(obj, dict) and isinstance(obj.get("signed_at_utc"), str):
        return obj["signed_at_utc"]
    return None


def _audit_section(
    path: str | None,
    signature_path: str | None = None,
    public_key_path: str | None = None,
    hmac_key: str | bytes | None = None,
) -> dict | None:
    if path is None:
        if signature_path is not None or public_key_path is not None or bool(hmac_key):
            raise ReportError("--audit-signature exige --audit")
        return None
    try:
        res = audit.verify(path)
    except FileNotFoundError as exc:
        raise ReportError(str(exc)) from exc
    # Só resultado e âncora: nada do conteúdo dos eventos.
    out: dict = {
        "ok": res.ok, "n_events": res.n_lines, "anchor": res.last_hash,
        "first_bad_line": res.first_bad_line, "reason": res.reason,
    }
    has_hmac = hmac_key not in (None, "", b"")
    if signature_path is None:
        if public_key_path is not None or has_hmac:
            raise ReportError("chave verificadora informada sem assinatura de auditoria")
        return out

    if public_key_path is None and not has_hmac:
        out["signature"] = {
            "checked": True,
            "ok": False,
            "algorithm": None,
            "key_fingerprint": None,
            "signed_at_utc": None,
            "reason": "chave de verificação da assinatura não informada",
        }
        return out

    if public_key_path is not None and has_hmac:
        raise ReportError("informe apenas chave pública Ed25519 ou chave HMAC")
    _need(Path(signature_path), "assinatura da auditoria")
    if public_key_path is not None:
        _need(Path(public_key_path), "chave pública da auditoria")

    sres = audit_sign.verify_signature(
        path,
        signature_path,
        public_key_path=public_key_path,
        hmac_key=hmac_key,
    )
    out["signature"] = {
        "checked": True,
        "ok": sres.ok,
        "algorithm": sres.algorithm,
        "key_fingerprint": sres.key_fingerprint,
        "signed_at_utc": _read_signed_at(signature_path),
        "reason": sres.reason,
    }
    return out


def _signature_invalid(au: dict | None) -> bool:
    if not isinstance(au, dict):
        return False
    sig = au.get("signature")
    return isinstance(sig, dict) and bool(sig.get("checked")) and not bool(sig.get("ok"))


def indicators(ev: dict, rt: dict, au: dict | None) -> dict:
    """Valores derivados que as regras da política consultam (caminho `indicators.*`)."""
    fp = rt["false_positives"]
    return {
        "audit_informed": au is not None,
        "audit_invalid": au is not None and (not au["ok"] or _signature_invalid(au)),
        "fp_blocked_total": fp["dataset"]["blocked"] + fp["benign"]["blocked"],
        "eval_nonsignificant_drop": ev["mean_diff"] < 0 and not ev["regression"],
    }


def semaphore(ev: dict, rt: dict, au: dict | None, policy: dict | None = None) -> dict:
    """Cor e motivos pela política (padrão: policies/default.yaml)."""
    view = {"eval": ev, "redteam": rt, "audit": au, "indicators": indicators(ev, rt, au)}
    return policy_mod.evaluate(policy or policy_mod.load_policy(), view)[0]


def _plural(n: int) -> str:
    return "uma execução" if n == 1 else f"{n} execuções"


def _audit_limitation_text(au: dict | None) -> str:
    sig = au.get("signature") if isinstance(au, dict) else None
    if not (isinstance(sig, dict) and sig.get("checked")):
        return (
            "A auditoria usa cadeia de hashes, sem assinatura: só detecta alteração quando o "
            "hash âncora foi guardado fora do arquivo. Não é imutabilidade."
        )
    alg = sig.get("algorithm")
    if alg == "ed25519":
        return (
            "A auditoria usa cadeia de hashes com assinatura Ed25519 da âncora: cobre integridade "
            "autenticada e não-repúdio sujeito à custódia protegida da chave privada; não inclui "
            "carimbo de tempo externo confiável (RFC 3161 TSA) e depende do arquivamento do "
            "arquivo .sig.json fora do log."
        )
    if alg == "hmac-sha256":
        return (
            "A auditoria usa cadeia de hashes com assinatura HMAC-SHA256 da âncora: cobre "
            "integridade autenticada por chave simétrica compartilhada (sem não-repúdio perante "
            "terceiros sem a chave); não inclui carimbo de tempo externo confiável (RFC 3161 TSA) "
            "e depende do arquivamento do arquivo .sig.json fora do log."
        )
    return (
        "A verificação de assinatura da âncora falhou ou teve algoritmo não reconhecido; sem "
        "assinatura válida, a cadeia não possui garantia autenticada, não inclui carimbo de "
        "tempo externo confiável (RFC 3161 TSA) e depende do arquivamento do arquivo .sig.json "
        "fora do log."
    )


def _runs_limitation(ev: dict, rt: dict) -> str:
    ev_runs, rt_runs = ev["runs_per_config"], rt["runs_per_config"]
    if ev_runs <= 1 and rt_runs <= 1:
        return (
            f"Eval: {_plural(ev_runs)} por configuração; red team: "
            f"{_plural(rt_runs)} por configuração. Não há medida da variação "
            "entre execuções."
        )
    if ev_runs > 1 and rt_runs <= 1:
        return (
            f"Eval: {_plural(ev_runs)} por configuração (variância medida entre execuções); "
            f"red team: {_plural(rt_runs)} por configuração, sem medida da variação entre execuções."
        )
    if ev_runs <= 1 and rt_runs > 1:
        return (
            f"Eval: {_plural(ev_runs)} por configuração (sem medida da variação entre execuções); "
            f"red team: {_plural(rt_runs)} por configuração."
        )
    return (
        f"Eval: {_plural(ev_runs)} por configuração (variância medida entre execuções); "
        f"red team: {_plural(rt_runs)} por configuração."
    )


def limitations(data: dict) -> list[str]:
    """Texto fixo do kit mais as ressalvas estatísticas geradas dos dados (stats.statistical_caveats)."""
    ev, rt = data["eval"], data["redteam"]
    return [
        (
            f"Modelo local pequeno ({data['agent']['model']}): os resultados não valem para "
            "outros modelos nem para uso em produção."
        ),
        (
            f"Tamanho do teste: {ev['n_cases']} casos de avaliação, {rt['n_attacks']} ataques e "
            f"{rt['n_legit_questions']} perguntas legítimas para medir falsos positivos."
        ),
        _runs_limitation(ev, rt),
        (
            "As defesas são heurísticas (filtros de entrada, ferramentas e saída) e podem ser "
            "contornadas por ataques diferentes dos testados."
        ),
        _audit_limitation_text(data.get("audit")),
        (
            "As notas do juiz (modelo) não entram neste pacote; só as checagens "
            "determinísticas. Consulte docs/resultados.md."
        ),
        (
            "Quando o ASR em abuso de ferramentas é zero, isso decorre em grande parte da "
            "allowlist de ferramentas do agente e não indica robustez geral; a queda do ASR "
            "sem guardrails para com guardrails não pode ser atribuída apenas aos guardrails."
        ),
        "Não cobre ataques fora da suíte, outros modelos nem uso em produção.",
        *stats_mod.statistical_caveats(data),
    ]


def _audit_summary_label(au: dict | None) -> str:
    if au is None:
        return "não informada"
    if not au["ok"]:
        return "cadeia inválida"
    sig = au.get("signature")
    if isinstance(sig, dict) and sig.get("checked"):
        return "cadeia íntegra e assinada" if sig.get("ok") else "assinatura inválida"
    return "cadeia íntegra"


def summary_values(d: dict) -> dict[str, str]:
    """Métricas comparáveis entre versões (texto já formatado); levanta KeyError se faltar campo."""
    ev, rt = d["eval"], d["redteam"]

    def asr(name: str) -> str:
        r = rt["asr"][name]["total"]
        return (
            f"{r['successes']}/{r['n']} (IC 95% Wilson [{_pct(r['ci95_low'])}; "
            f"{_pct(r['ci95_high'])}])"
        )

    fp = rt["false_positives"]
    blocked = fp["dataset"]["blocked"] + fp["benign"]["blocked"]
    au = d["audit"]
    return {
        "Semáforo": d["semaphore"]["color"],
        "Modelo": str(d["agent"]["model"]),
        f"Eval: diferença média ({ev['candidate']} - {ev['baseline']})": (
            f"{ev['mean_diff']:+.4f} (IC 95% [{ev['ci95_low']:+.4f}; {ev['ci95_high']:+.4f}], "
            f"p = {ev['p_value']:.4f})"
        ),
        f"Eval: média de {ev['candidate']}": f"{ev['mean_candidate']:.4f}",
        "Red team: ataques com sucesso sem guardrails": asr("baseline"),
        "Red team: ataques com sucesso com guardrails": asr("guardrails"),
        "Falsos positivos (perguntas legítimas bloqueadas)": (
            f"{blocked}/{rt['n_legit_questions']}"
        ),
        "Auditoria": _audit_summary_label(au),
    }


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _previous_section(prev: dict, cur_values: dict[str, str]) -> dict:
    try:
        before = summary_values(prev)
        gen = str(prev["generated_at"])
        if prev.get("schema_version") != SCHEMA_VERSION:
            raise KeyError("schema_version")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ReportError(
            "relatório anterior inválido ou de outra versão do esquema (relatorio.json esperado)"
        ) from exc
    rows = [
        {"metric": k, "before": before.get(k, "n/d"), "after": v} for k, v in cur_values.items()
    ]
    return {"generated_at": gen, "rows": rows}


def load_previous(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ReportError(f"relatório anterior não encontrado: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ReportError(f"relatório anterior não é um JSON válido: {p}") from exc
    return data


def _first(prov: dict, key: str) -> str | None:
    """Primeiro valor registrado de `key` nas execuções (eval, depois red team)."""
    ex = prov["executions"]
    runs = [*reversed(list(ex["eval"].values())), ex["redteam"]["guardrails"], ex["redteam"]["baseline"]]
    return next((r[key] for r in runs if r and r.get(key)), None)


def _provenance_block(agent: dict, prov: dict, command: str | None, repo_dir: str | None) -> dict:
    """Bloco `provenance`: ambiente do build + o que as execuções gravaram (null = não registrado)."""
    used = any(
        str(k).startswith(provenance.EVIDENCE_PREFIX) for k in (*prov["inputs"], *prov["files"].values())
    )
    return {
        **provenance.environment(repo_dir),
        "command": None if command is None else provenance.sanitize_command(command),
        **({"evidence_root": provenance.EVIDENCE_PREFIX.rstrip("/")} if used else {}),
        "model": agent["model"],
        "model_digest": _first(prov, "model_digest"),
        "ollama_version": _first(prov, "ollama_version"),
        "seeds": prov["seeds"],
        "executions": prov["executions"],
        "inputs": prov["inputs"],
        "files": prov["files"],
    }


def build_data(
    *,
    config: str,
    dataset: str,
    prompts_dir: str,
    answers_dir: str,
    baseline: str,
    candidate: str,
    seed: int,
    redteam_baseline: str,
    redteam_guardrails: str,
    fp_dir: str,
    audit_path: str | None = None,
    audit_signature: str | None = None,
    audit_public_key: str | None = None,
    audit_hmac_key: str | bytes | None = None,
    previous: str | None = None,
    now: datetime | None = None,
    command: str | None = None,
    repo_dir: str | None = None,
    policy: str | None = None,
    coverage_map: str | None = None,
    evidence_root: str | None = None,
) -> dict:
    """Lê os resultados e devolve o dict do relatorio.json. Levanta ReportError com mensagem curta."""
    if baseline == candidate:
        raise ReportError("--baseline e --candidate devem ser variantes diferentes")
    args = dict(locals())
    for key, label in (
        ("redteam_baseline", "resultado do red team (baseline)"),
        ("redteam_guardrails", "resultado do red team (guardrails)"),
    ):
        _need(Path(args[key]), label)
    for name in ("fp_dataset.jsonl", "fp_benign.jsonl"):
        _need(Path(fp_dir) / name, "resultado de falsos positivos")
    prev = load_previous(previous) if previous else None
    try:
        pol = policy_mod.load_policy(policy)
    except policy_mod.PolicyError as exc:
        raise ReportError(str(exc)) from exc
    try:
        cmap = coverage_mod.load_map(coverage_map)
    except coverage_mod.CoverageError as exc:
        raise ReportError(str(exc)) from exc

    hashes: dict[str, str] = {}
    prov: dict = {"seeds": {}, "executions": {}, "inputs": {}, "files": {}}
    ctx: dict = {}
    try:
        ev, agent = _eval_section(args, hashes, prov, ctx)
        rt = _redteam_section(args, hashes, prov, ctx)
        found, found_paths = findings_mod.collect(
            redteam=ctx["redteam"], false_positives=ctx["false_positives"], eval_ctx=ctx["eval"],
            evidence_root=args["evidence_root"],
        )
        findings_mod.verify(found, found_paths)
    except (ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise ReportError(f"resultado ou configuração inválidos: {exc}") from exc
    au = _audit_section(
        audit_path,
        signature_path=audit_signature,
        public_key_path=audit_public_key,
        hmac_key=audit_hmac_key,
    )
    # O log cresce depois do build: referenciado pelo caminho, fora de `inputs` (a âncora o confere).
    _role(prov, "audit_log", audit_path, as_input=False, evidence_root=evidence_root)
    _role(prov, "audit_signature", audit_signature, as_input=False, evidence_root=evidence_root)
    _role(prov, "audit_public_key", audit_public_key, as_input=False, evidence_root=evidence_root)

    view = {"eval": ev, "redteam": rt, "audit": au, "indicators": indicators(ev, rt, au)}
    sem, rule_results = policy_mod.evaluate(pol, view)
    _add_input(prov["inputs"], Path(policy) if policy else policy_mod.DEFAULT_POLICY)
    _add_input(prov["inputs"], Path(coverage_map) if coverage_map else coverage_mod.DEFAULT_MAP)
    data = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "agent": agent,
        "semaphore": sem,
        "policy": policy_mod.policy_block(pol, rule_results),
        "indicators": view["indicators"],
        "eval": ev,
        "redteam": rt,
        "audit": au,
        "hashes": hashes,
        "findings": found,
        "coverage": coverage_mod.compute(cmap, rt),
        "provenance": _provenance_block(agent, prov, command, repo_dir),
        "previous": None,
    }
    data["limitations"] = limitations(data)
    if prev is not None:
        data["previous"] = _previous_section(prev, summary_values(data))
    return data
