"""Política de classificação (semáforo): arquivo YAML versionado + avaliador mínimo.

Cada regra compara UMA métrica do relatorio.json com UM limiar e descreve a condição que o agente
deve atender (passou = condição verdadeira). Sem expressões livres. Métrica ausente não passa nem
falha: fica "não avaliada" e nunca resulta em verde.
"""

from __future__ import annotations

import hashlib
import operator
from pathlib import Path

import yaml

from agent_ops_kit import provenance

DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "policies" / "default.yaml"
OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge, "==": operator.eq,
}
_SEVERITY = {"yellow": "yellow", "red": "red", "amarelo": "yellow", "vermelho": "red"}
_RULE_KEYS = {"id", "metric", "op", "threshold", "severity", "rationale"}
_ORDER = {"green": 0, "yellow": 1, "red": 2}


class PolicyError(ValueError):
    """Política ilegível ou inválida (a CLI converte em exit 2)."""


def _num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _check_rule(i: int, r: object, seen: set[str]) -> dict:
    where = f"regra #{i + 1}"
    if not isinstance(r, dict):
        raise PolicyError(f"{where}: esperado um mapa com {sorted(_RULE_KEYS)}")
    missing, extra = _RULE_KEYS - r.keys(), r.keys() - _RULE_KEYS
    if missing or extra:
        raise PolicyError(f"{where}: campos ausentes {sorted(missing)}, desconhecidos {sorted(extra)}")
    rid = r["id"]
    if not (isinstance(rid, str) and rid.strip()):
        raise PolicyError(f"{where}: id deve ser texto não vazio")
    where = f"regra '{rid}'"
    if rid in seen:
        raise PolicyError(f"{where}: id duplicado")
    seen.add(rid)
    if not (isinstance(r["metric"], str) and r["metric"].strip()):
        raise PolicyError(f"{where}: metric deve ser um caminho (ex.: eval.mean_candidate)")
    if r["op"] not in OPS:
        raise PolicyError(f"{where}: op '{r['op']}' inválido; use {', '.join(OPS)}")
    thr = r["threshold"]
    if not (_num(thr) or isinstance(thr, bool)):
        raise PolicyError(f"{where}: threshold deve ser número ou booleano")
    if isinstance(thr, bool) and r["op"] != "==":
        raise PolicyError(f"{where}: threshold booleano só aceita op '=='")
    sev = _SEVERITY.get(r["severity"]) if isinstance(r["severity"], str) else None
    if sev is None:
        raise PolicyError(f"{where}: severity '{r['severity']}' inválida; use yellow ou red")
    if not (isinstance(r["rationale"], str) and r["rationale"].strip()):
        raise PolicyError(f"{where}: rationale deve ser texto não vazio")
    return {**r, "severity": sev}


def load_policy(path: str | Path | None = None) -> dict:
    """Lê e valida a política. Devolve id, version, description, rules, sha256 e path_relative."""
    p = Path(path) if path else DEFAULT_POLICY
    if not p.is_file():
        raise PolicyError(f"política não encontrada: {p}")
    raw = p.read_bytes()
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PolicyError(f"política inválida (YAML ilegível): {p}") from exc
    if not isinstance(doc, dict):
        raise PolicyError(f"política inválida: esperado um mapa com id, version e rules ({p})")
    for key in ("id", "version"):
        if not (isinstance(doc.get(key), (str, int, float)) and str(doc[key]).strip()):
            raise PolicyError(f"política inválida: '{key}' ausente ou vazio ({p})")
    rules = doc.get("rules")
    if not (isinstance(rules, list) and rules):
        raise PolicyError(f"política inválida: 'rules' deve ser uma lista não vazia ({p})")
    seen: set[str] = set()
    return {
        "id": str(doc["id"]),
        "version": str(doc["version"]),
        "description": str(doc.get("description") or ""),
        "rules": [_check_rule(i, r, seen) for i, r in enumerate(rules)],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "path_relative": provenance.rel_path(p),
    }


def lookup(data: dict, metric: str) -> object:
    """Valor no caminho pontilhado do relatorio.json; None se algum trecho faltar."""
    cur: object = data
    for part in metric.split("."):
        if not (isinstance(cur, dict) and part in cur):
            return None
        cur = cur[part]
    return cur


def _passed(op: str, observed: object, threshold: object) -> bool | None:
    if observed is None or isinstance(observed, bool) != isinstance(threshold, bool):
        return None
    if not (_num(observed) or isinstance(observed, bool)):
        return None
    return bool(OPS[op](observed, threshold))


def evaluate(policy: dict, data: dict) -> tuple[dict, list[dict]]:
    """Aplica a política aos dados. Devolve (semáforo, regras avaliadas).

    Cor = pior severidade entre as regras que falharam; verde se todas passaram. Regra não
    avaliada eleva a cor a, no mínimo, amarelo.
    """
    results = []
    for r in policy["rules"]:
        observed = lookup(data, r["metric"])
        passed = _passed(r["op"], observed, r["threshold"])
        results.append({
            "id": r["id"], "metric": r["metric"], "op": r["op"], "threshold": r["threshold"],
            "observed": observed if passed is not None else None, "passed": passed,
            "severity": r["severity"], "rationale": r["rationale"],
        })
    failed = [x for x in results if x["passed"] is False]
    unevaluated = [x["id"] for x in results if x["passed"] is None]
    triggered = [x["id"] for sev in ("red", "yellow") for x in failed if x["severity"] == sev]
    color = max((x["severity"] for x in failed), key=_ORDER.__getitem__, default="green")
    if unevaluated and color == "green":
        color = "yellow"
    sem = {
        "color": color, "triggered": triggered, "rules_version": policy["version"],
        "not_evaluated": unevaluated,
        "caveats": [f"regra não avaliada: {i}" for i in unevaluated],
    }
    return sem, results


def policy_block(policy: dict, results: list[dict]) -> dict:
    return {
        "id": policy["id"], "version": policy["version"], "sha256": policy["sha256"],
        "path_relative": policy["path_relative"], "rules": results,
    }
