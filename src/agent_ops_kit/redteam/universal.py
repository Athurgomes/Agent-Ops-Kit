"""Bateria universal v1 parametrizada pelo AgentProfile (`agent.yaml`)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from agent_ops_kit.config import AgentConfig
from agent_ops_kit.redteam.attacks import AttackCase

DEFAULT_TEMPLATES = (
    Path(__file__).resolve().parents[3] / "redteam" / "universal" / "templates.yaml"
)
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


class UniversalSuiteResult(NamedTuple):
    """Resultado da geração da bateria universal: casos gerados e categorias puladas."""

    cases: list[AttackCase]
    skipped_categories: list[dict[str, str]]


def _render(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def _collapse(text: str) -> str:
    return " ".join(text.split()).strip()


def _prompt_snippet(system_prompt: str) -> str | None:
    cleaned = _collapse(system_prompt)
    if len(cleaned) < 20:
        return None
    return cleaned[:64].strip()


def _load_templates(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"templates da bateria universal não encontrados: {path}")
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"templates da bateria universal inválidos ({path}): {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("cases"), list):
        raise TypeError(f"templates da bateria universal devem definir lista 'cases' ({path})")
    return doc["cases"]


def _build_success(spec: dict[str, Any], *, tool_name: str | None, snippet: str | None) -> dict:
    stype = spec.get("type")
    if stype == "prompt_snippet_or_marker":
        return {"type": "output_contains", "text": snippet or str(spec["fallback_text"])}
    if stype == "tool_called_profile":
        return {"type": "tool_called", "tool": tool_name or ""}
    return dict(spec)


def build_universal_suite(
    cfg: AgentConfig, templates_path: str | Path | None = None
) -> UniversalSuiteResult:
    """Gera a bateria universal v1 parametrizada pelo `AgentProfile` de `cfg`."""
    raw_cases = _load_templates(Path(templates_path) if templates_path else DEFAULT_TEMPLATES)
    prof = cfg.profile
    role = prof.role if prof and prof.role else "assistente"
    allowed_scope = list(prof.allowed_scope) if prof else []
    forbidden_scope = list(prof.forbidden_scope) if prof else []
    sensitive_data = list(prof.sensitive_data) if prof else []
    forbidden_actions = list(prof.forbidden_actions) if prof else []
    declared_tools = list(prof.declared_tools) if prof else []
    effective_tools = declared_tools if declared_tools else list(cfg.tools)

    snippet = _prompt_snippet(cfg.system_prompt)
    skipped: list[dict[str, str]] = []
    if not sensitive_data:
        skipped.append({
            "category": "vazamento_dados",
            "reason": "não testado: profile.sensitive_data vazio ou perfil ausente no agent.yaml",
        })
    if not allowed_scope and not forbidden_scope:
        skipped.append({
            "category": "desvio_de_escopo",
            "reason": (
                "não testado: profile.allowed_scope e profile.forbidden_scope vazios ou "
                "perfil ausente no agent.yaml"
            ),
        })
    if not forbidden_actions and not effective_tools:
        skipped.append({
            "category": "abuso_de_tools",
            "reason": (
                "não testado: profile.forbidden_actions e declared_tools/tools vazios "
                "no agent.yaml"
            ),
        })

    available = {
        "sensitive_data": sensitive_data,
        "forbidden_scope": forbidden_scope,
        "allowed_scope": allowed_scope,
        "effective_tools": effective_tools,
        "forbidden_actions": forbidden_actions,
    }
    cases: list[AttackCase] = []
    sensitive_idx = 0

    for entry in raw_cases:
        reqs = list(entry.get("requires") or [])
        if any(not available.get(req) for req in reqs):
            continue

        if entry["id"] == "univ-tls-01":
            for idx, tool in enumerate(effective_tools, start=1):
                cid = entry["id"] if len(effective_tools) == 1 else f"{entry['id']}-{idx:02d}"
                values = {"role": role, "tool": tool}
                cases.append(
                    AttackCase.model_validate({
                        "id": cid,
                        "category": entry["category"],
                        "owasp_id": entry["owasp_id"],
                        "scope": "universal",
                        "description": entry["description"],
                        "user_input": _collapse(_render(entry["user_input"], values)),
                        "success": _build_success(entry["success"], tool_name=tool, snippet=snippet),
                    })
                )
            continue

        if entry["id"] == "univ-tls-02":
            for idx, action in enumerate(forbidden_actions, start=1):
                cid = entry["id"] if len(forbidden_actions) == 1 else f"{entry['id']}-{idx:02d}"
                values = {"role": role, "forbidden_action": action}
                cases.append(
                    AttackCase.model_validate({
                        "id": cid,
                        "category": entry["category"],
                        "owasp_id": entry["owasp_id"],
                        "scope": "universal",
                        "description": entry["description"],
                        "user_input": _collapse(_render(entry["user_input"], values)),
                        "success": _build_success(entry["success"], tool_name=None, snippet=snippet),
                    })
                )
            continue

        values: dict[str, str] = {"role": role}
        if sensitive_data:
            values["sensitive_data"] = sensitive_data[sensitive_idx % len(sensitive_data)]
            if entry["category"] == "vazamento_dados":
                sensitive_idx += 1
        if allowed_scope:
            values["allowed_scope"] = allowed_scope[0]
        if forbidden_scope:
            values["forbidden_scope"] = forbidden_scope[0]

        has_all_context = (
            (prof is not None and prof.role is not None)
            or bool(allowed_scope)
            or bool(forbidden_scope)
        )
        raw_input = entry["user_input"]
        if "user_input_fallback" in entry and (
            not has_all_context
            or (entry["category"] == "injecao_indireta" and not (prof and allowed_scope))
            or (entry["category"] == "jailbreak" and not (prof and (prof.role or forbidden_scope)))
        ):
            raw_input = entry["user_input_fallback"]
        if entry["category"] == "jailbreak" and raw_input == entry["user_input"] and not forbidden_scope:
            values["forbidden_scope"] = "assuntos fora das políticas"

        payload: dict[str, Any] = {
            "id": entry["id"],
            "category": entry["category"],
            "owasp_id": entry["owasp_id"],
            "scope": "universal",
            "description": entry["description"],
            "user_input": _collapse(_render(raw_input, values)),
            "success": _build_success(entry["success"], tool_name=None, snippet=snippet),
        }
        if "untrusted_context" in entry:
            payload["untrusted_context"] = _collapse(_render(entry["untrusted_context"], values))
        cases.append(AttackCase.model_validate(payload))

    return UniversalSuiteResult(cases=cases, skipped_categories=skipped)
