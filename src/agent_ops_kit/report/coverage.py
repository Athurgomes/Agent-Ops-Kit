"""Cobertura OWASP Top 10 for LLM Applications: mapa YAML versionado + cálculo sobre os números do red team.

O mapa liga categorias de ataque da suíte e guardrails do kit aos IDs LLM01..LLM10. Os números
(n, sucessos) vêm de `build.redteam_numbers` (mesmo dict usado pelo `report verify`); aqui só se
agrupa. Sem texto de ataque.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from agent_ops_kit import provenance
from agent_ops_kit.redteam.harness import ALL_GUARDRAILS, OWASP_CATEGORIES

DEFAULT_MAP = Path(__file__).resolve().parents[3] / "policies" / "coverage" / "owasp_llm_2025.yaml"
OWASP_IDS = tuple(f"LLM{i:02d}" for i in range(1, 11))
_ID = re.compile(r"^LLM(0[1-9]|10)$")
TESTED, CONTROL_ONLY, NOT_COVERED = "testado", "só controle", "não coberto"


class CoverageError(ValueError):
    """Mapa ilegível ou inválido (o build converte em ReportError)."""


def _ids(where: str, value: object) -> list[str]:
    if not (isinstance(value, list) and value):
        raise CoverageError(f"mapa de cobertura: {where} deve ser uma lista não vazia de IDs")
    for v in value:
        if not (isinstance(v, str) and _ID.match(v)):
            raise CoverageError(f"mapa de cobertura: {where} tem ID inválido '{v}' (use LLM01..LLM10)")
    return list(dict.fromkeys(value))


def _mapping(doc: dict, key: str) -> dict:
    m = doc.get(key)
    if not isinstance(m, dict):
        raise CoverageError(f"mapa de cobertura: '{key}' deve ser um mapa")
    return m


def load_map(path: str | Path | None = None) -> dict:
    """Lê e valida o mapa (yaml.safe_load). Devolve o mapa normalizado + sha256 e path_relative."""
    p = Path(path) if path else DEFAULT_MAP
    if not p.is_file():
        raise CoverageError(f"mapa de cobertura não encontrado: {p}")
    raw = p.read_bytes()
    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise CoverageError(f"mapa de cobertura inválido (YAML ilegível): {p}") from exc
    if not isinstance(doc, dict):
        raise CoverageError(f"mapa de cobertura inválido: esperado um mapa ({p})")
    for key in ("id", "version", "source"):
        if not (isinstance(doc.get(key), (str, int, float)) and str(doc[key]).strip()):
            raise CoverageError(f"mapa de cobertura inválido: '{key}' ausente ou vazio ({p})")
    names = _mapping(doc, "categories")
    if set(names) != set(OWASP_IDS) or not all(isinstance(v, str) and v.strip() for v in names.values()):
        raise CoverageError("mapa de cobertura: 'categories' deve trazer exatamente LLM01..LLM10 com nome")
    attacks = {k: _ids(f"attack_categories.{k}", v) for k, v in _mapping(doc, "attack_categories").items()}
    for k in attacks:
        if k not in OWASP_CATEGORIES:
            raise CoverageError(f"mapa de cobertura: categoria de ataque desconhecida '{k}'")
    controls = {k: _ids(f"controls.{k}", v) for k, v in _mapping(doc, "controls").items()}
    for k in controls:
        if k not in ALL_GUARDRAILS:
            raise CoverageError(f"mapa de cobertura: guardrail desconhecido '{k}'")
    not_covered = _mapping(doc, "not_covered")
    linked = {i for ids in (*attacks.values(), *controls.values()) for i in ids}
    for i, reason in not_covered.items():
        if i not in OWASP_IDS:
            raise CoverageError(f"mapa de cobertura: not_covered tem ID inválido '{i}'")
        if not (isinstance(reason, str) and reason.strip()):
            raise CoverageError(f"mapa de cobertura: not_covered.{i} precisa de um motivo")
        if i in linked:
            raise CoverageError(f"mapa de cobertura: {i} está em not_covered e também tem ataque ou controle")
    missing = [i for i in OWASP_IDS if i not in linked and i not in not_covered]
    if missing:
        raise CoverageError(f"mapa de cobertura: {', '.join(missing)} sem ataque, controle ou 'not_covered'")
    return {
        "id": str(doc["id"]), "version": str(doc["version"]), "source": str(doc["source"]),
        "names": dict(names), "attack_categories": attacks, "controls": controls,
        "not_covered": {k: str(v) for k, v in not_covered.items()},
        "sha256": hashlib.sha256(raw).hexdigest(), "path_relative": provenance.rel_path(p),
    }


def _sum(asr: dict, cats: list[str]) -> dict:
    rows = [asr[c] for c in cats if c in asr]
    return {"n": sum(r["n"] for r in rows), "successes": sum(r["successes"] for r in rows)}


def compute(cmap: dict, rt: dict) -> dict:
    """Bloco `coverage` a partir do mapa e de `redteam_numbers` (ou da seção `redteam` do json)."""
    asr = rt["asr"]
    out = []
    for lid in OWASP_IDS:
        cats = [c for c, ids in cmap["attack_categories"].items() if lid in ids]
        controls = [c for c, ids in cmap["controls"].items() if lid in ids]
        base, guard = _sum(asr["baseline"], cats), _sum(asr["guardrails"], cats)
        if guard["n"] or base["n"]:
            status, reason = TESTED, None
        elif controls:
            status = CONTROL_ONLY
            reason = "nenhum ataque desta categoria na execução" if cats else "sem categoria de ataque dedicada na suíte"
        else:
            status = NOT_COVERED
            reason = cmap["not_covered"].get(lid, "nenhum ataque desta categoria na execução")
        out.append({
            "id": lid, "name": cmap["names"][lid], "status": status, "reason": reason,
            "attack_categories": cats, "controls": controls,
            "baseline": base, "guardrails": guard,
        })
    known = set(cmap["attack_categories"])
    unmapped = sorted({c for cfg in asr.values() for c in cfg} - known - {"total"})
    return {
        "map": {k: cmap[k] for k in ("id", "version", "source", "path_relative", "sha256")},
        "categories": out,
        "unmapped_attack_categories": unmapped,
    }
