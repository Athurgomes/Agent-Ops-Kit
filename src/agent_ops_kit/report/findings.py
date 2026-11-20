"""Achados rastreáveis do relatório (ADR-024): cada achado aponta para a linha do JSONL que o prova.

Só ids, categorias, contagens e hashes: nunca texto de ataque, pergunta ou resposta do modelo.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_ops_kit import provenance
from agent_ops_kit.redteam.report import ReportError

NOT_CLASSIFIED = "não classificado"
SEVERITY_RANK = {"alta": 0, "média": 1, "baixa": 2, NOT_CLASSIFIED: 3}
_SOURCE_RANK = {"redteam": 0, "false_positive": 1, "eval": 2}

# Severidade pelo impacto potencial da categoria se o ataque tiver sucesso (heurística do kit, não
# CVSS). Erro de execução, falso positivo e regressão de eval não têm severidade: "não classificado".
SEVERITY_BY_CATEGORY = {
    "exfiltracao": "alta",
    "vazamento_dados": "alta",
    "abuso_de_tools": "alta",
    "injecao_direta": "média",
    "injecao_indireta": "média",
    "saida_insegura": "média",
    "multi_turn": "média",
    "ofuscacao": "média",
    "exaustao_recursos": "baixa",
}
EVAL_TOLERANCE = 1e-9


def record_sha256(rec: dict) -> str:
    """sha256 da linha canônica: JSON com chaves ordenadas, sem espaços, UTF-8 (imune a CRLF)."""
    text = json.dumps(rec, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lines(path: Path) -> list[tuple[int, dict]]:
    """(nº da linha física, 1-based; registro) das linhas não vazias do JSONL."""
    out: list[tuple[int, dict]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.strip():
                    out.append((n, json.loads(line)))
    except (OSError, ValueError) as exc:
        raise ReportError(f"JSONL inválido ou ilegível em {path}: {exc}") from exc
    return out


class _Files:
    """Chave estável (caminho relativo à raiz) de cada arquivo citado como evidência."""

    def __init__(self, base: Path | None = None) -> None:
        self.base = base
        self.paths: dict[str, Path] = {}
        self._sha: dict[str, str] = {}

    def key(self, path: Path) -> str:
        key = provenance.rel_path(path, self.base)
        if self.paths.get(key, path.resolve()) != path.resolve():
            key = f"{path.resolve().parent.name}/{key}"
        self.paths[key] = path.resolve()
        return key

    def evidence(self, path: Path, line: int, rec: dict) -> dict:
        key = self.key(path)
        if key not in self._sha:
            self._sha[key] = provenance.sha256_file(path)
        return {
            "file": key, "line": line, "record_sha256": record_sha256(rec),
            "file_sha256": self._sha[key],
            "run_id": rec.get("run_id"), "trace_id": rec.get("trace_id"),
        }


def _ids(prefix: str, rows: list[tuple[int, dict]], suffix: str) -> dict[int, str]:
    """Id estável por linha: `<prefixo>-<case_id>-<sufixo>`; case repetido (várias execuções) ganha
    o nº da ocorrência (`-r1`, `-r2`, ...)."""
    total: dict[str, int] = {}
    for _, rec in rows:
        total[rec["case_id"]] = total.get(rec["case_id"], 0) + 1
    seen: dict[str, int] = {}
    out: dict[int, str] = {}
    for n, rec in rows:
        cid = rec["case_id"]
        seen[cid] = seen.get(cid, 0) + 1
        run = f"-r{seen[cid]}" if total[cid] > 1 else ""
        out[n] = f"{prefix}-{cid}-{suffix}{run}"
    return out


def _redteam(files: _Files, path: Path, config: str) -> list[dict]:
    rows = read_lines(path)
    ok_ids, err_ids = _ids("RT", rows, config), _ids("RT-ERR", rows, config)
    out = []
    for n, rec in rows:
        for kind, flag in (("attack_success", rec.get("success")), ("execution_error", rec.get("error"))):
            if not flag:
                continue
            cat = rec.get("category")
            ok = kind == "attack_success"
            out.append({
                "id": ok_ids[n] if ok else err_ids[n], "source": "redteam", "kind": kind,
                "config": config, "attack_id": rec["case_id"], "category": cat,
                "severity": SEVERITY_BY_CATEGORY.get(cat, NOT_CLASSIFIED) if ok else NOT_CLASSIFIED,
                "blocked_by": list(rec.get("blocked_by") or []),
                "evidence": files.evidence(path, n, rec),
            })
    return out


def _false_positives(files: _Files, path: Path, name: str) -> list[dict]:
    rows = read_lines(path)
    ids = _ids("FP", rows, name)
    return [
        {
            "id": ids[n], "source": "false_positive", "kind": "benign_blocked",
            "config": "guardrails", "attack_id": None, "case_id": rec["case_id"], "category": None,
            "severity": NOT_CLASSIFIED, "blocked_by": list(rec.get("blocked_by") or []),
            "reasons": list(rec.get("reasons") or []),
            "evidence": files.evidence(path, n, rec),
        }
        for n, rec in rows if rec.get("blocked")
    ]


def _first_lines(path: Path) -> dict[str, tuple[int, dict]]:
    first: dict[str, tuple[int, dict]] = {}
    for n, rec in read_lines(path):
        first.setdefault(rec["case_id"], (n, rec))
    return first


def _eval(files: _Files, ev: dict) -> list[dict]:
    """Casos cuja nota média caiu do baseline para o candidato (evidência: 1º registro de cada)."""
    base, cand = _first_lines(ev["baseline_path"]), _first_lines(ev["candidate_path"])
    out = []
    for cid in sorted(set(ev["scores_baseline"]) & set(ev["scores_candidate"])):
        sb, sc = ev["scores_baseline"][cid], ev["scores_candidate"][cid]
        if sc >= sb - EVAL_TOLERANCE or cid not in base or cid not in cand:
            continue
        out.append({
            "id": f"EV-{cid}-{ev['candidate']}", "source": "eval", "kind": "case_regression",
            "config": ev["candidate"], "attack_id": None, "case_id": cid,
            "category": ev["categories"].get(cid), "severity": NOT_CLASSIFIED,
            "baseline_config": ev["baseline"], "baseline_score": round(sb, 4),
            "candidate_score": round(sc, 4),
            "evidence": files.evidence(ev["candidate_path"], *cand[cid]),
            "baseline_evidence": files.evidence(ev["baseline_path"], *base[cid]),
        })
    return out


def _sort_key(f: dict) -> tuple:
    return (_SOURCE_RANK[f["source"]], f["config"], f["id"])


def collect(
    *, redteam: dict[str, Path], false_positives: dict[str, Path], eval_ctx: dict | None = None,
    base: Path | None = None,
) -> tuple[list[dict], dict[str, Path]]:
    """Achados em ordem determinística e o mapa arquivo -> caminho real (para `verify`).

    `base`: raiz para as chaves relativas (padrão: diretório atual)."""
    files = _Files(base)
    found: list[dict] = []
    for config, path in redteam.items():
        found += _redteam(files, path, config)
    for name, path in false_positives.items():
        found += _false_positives(files, path, name)
    if eval_ctx is not None:
        found += _eval(files, eval_ctx)
    found.sort(key=_sort_key)
    ids = [f["id"] for f in found]
    if len(set(ids)) != len(ids):
        raise ReportError("ids de achados duplicados")
    return found, files.paths


def verify(found: list[dict], paths: dict[str, Path]) -> None:
    """Relê cada arquivo citado: linha, hash do registro e hash do arquivo têm de bater."""
    cache: dict[str, tuple[str, dict[int, dict]]] = {}
    for f in found:
        for ev in (f["evidence"], f.get("baseline_evidence")):
            if ev is None:
                continue
            key = ev["file"]
            if key not in paths:
                raise ReportError(f"achado {f['id']}: evidência sem arquivo ({key})")
            if key not in cache:
                cache[key] = (
                    provenance.sha256_file(paths[key]),
                    dict(read_lines(paths[key])),
                )
            file_sha, by_line = cache[key]
            rec = by_line.get(ev["line"])
            if file_sha != ev["file_sha256"]:
                raise ReportError(f"achado {f['id']}: {key} mudou (sha256 do arquivo diverge)")
            if rec is None or record_sha256(rec) != ev["record_sha256"]:
                raise ReportError(
                    f"achado {f['id']}: linha {ev['line']} de {key} não confere com o sha256 do registro"
                )
            if rec.get("case_id") != f.get("case_id", f.get("attack_id")):
                raise ReportError(f"achado {f['id']}: linha {ev['line']} de {key} é de outro caso")
