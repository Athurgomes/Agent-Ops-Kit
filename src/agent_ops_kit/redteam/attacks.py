"""Modelo e carregador dos casos de ataque (JSONL).

Categorias inspiradas no OWASP Top 10 for LLM Applications: LLM01 (prompt injection:
direta, indireta, ofuscação e multi-turn), LLM02/LLM07 (divulgação de informação
sensível, exfiltração e vazamento), LLM05 (saída insegura), LLM06 (agência excessiva:
abuso de tools) e LLM10 (exaustão de recursos).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal, NamedTuple

from pydantic import BaseModel, Field, ValidationError, model_validator

from agent_ops_kit.redteam.testbed import CANARY, FORBIDDEN_TOOLS

Category = Literal[
    "injecao_direta",
    "injecao_indireta",
    "abuso_de_tools",
    "exfiltracao",
    "ofuscacao",
    "multi_turn",
    "saida_insegura",
    "vazamento_dados",
    "exaustao_recursos",
    "vazamento_prompt",
    "desvio_de_escopo",
    "jailbreak",
]
Scope = Literal["universal", "testbed_dependent"]

_TESTBED_TOOLS = ("search_docs", "calculator", "current_date", *FORBIDDEN_TOOLS)
_TESTBED_TERMS_RE = re.compile(
    r"\b(?:lumina|cnry|" + "|".join(re.escape(t) for t in _TESTBED_TOOLS) + r")\b",
    re.IGNORECASE,
)


class CanaryInOutput(BaseModel):
    type: Literal["canary_in_output"]


class ToolCalled(BaseModel):
    type: Literal["tool_called"]
    tool: str


class SystemPromptLeak(BaseModel):
    type: Literal["system_prompt_leak"]


class OutputContains(BaseModel):
    type: Literal["output_contains"]
    text: str = Field(min_length=1)


Success = Annotated[
    CanaryInOutput | ToolCalled | SystemPromptLeak | OutputContains,
    Field(discriminator="type"),
]


class AttackCase(BaseModel):
    id: str
    category: Category
    description: str
    user_input: str
    turns: list[str] | None = None
    poisoned_doc: str | None = None
    untrusted_context: str | None = None
    owasp_id: str | None = None
    scope: Scope = "testbed_dependent"
    is_blind: bool = False
    success: Success

    @model_validator(mode="after")
    def _check(self) -> AttackCase:
        if isinstance(self.success, ToolCalled):
            if self.scope == "universal":
                if not self.success.tool.strip():
                    raise ValueError(f"{self.id}: tool_called exige nome de tool não vazio")
            elif self.success.tool not in FORBIDDEN_TOOLS:
                raise ValueError(
                    f"{self.id}: tool_called exige tool proibida, veio {self.success.tool}"
                )
        if self.untrusted_context is not None and not self.untrusted_context.strip():
            raise ValueError(f"{self.id}: untrusted_context não pode ser vazio")
        if self.category == "injecao_indireta" and not (self.poisoned_doc or self.untrusted_context):
            raise ValueError(f"{self.id}: injecao_indireta exige poisoned_doc ou untrusted_context")
        if self.turns is not None and (not self.turns or any(not t.strip() for t in self.turns)):
            raise ValueError(f"{self.id}: turns não pode conter turnos vazios")
        if self.category == "multi_turn" and (not self.turns or len(self.turns) < 2):
            raise ValueError(f"{self.id}: multi_turn exige turns com pelo menos 2 turnos")
        if self.owasp_id is not None and not self.owasp_id.strip():
            raise ValueError(f"{self.id}: owasp_id não pode ser vazio")
        return self


def _has_testbed_reference(text: str) -> bool:
    if not text:
        return False
    if CANARY.lower() in text.lower():
        return True
    return _TESTBED_TERMS_RE.search(text) is not None


def classify_case_scope(case: AttackCase) -> Scope:
    """Classifica um AttackCase como `universal` ou `testbed_dependent` pelo critério e texto."""
    if isinstance(case.success, (CanaryInOutput, SystemPromptLeak)):
        return "testbed_dependent"
    if case.poisoned_doc is not None:
        return "testbed_dependent"
    if isinstance(case.success, ToolCalled) and case.success.tool in FORBIDDEN_TOOLS:
        return "testbed_dependent"
    texts = [
        case.description,
        case.user_input,
        *(case.turns or ()),
        case.untrusted_context or "",
    ]
    if isinstance(case.success, OutputContains):
        texts.append(case.success.text)
    if any(_has_testbed_reference(t) for t in texts):
        return "testbed_dependent"
    return "universal"


def summarize_case_scopes(cases: list[AttackCase]) -> dict[str, object]:
    """Resumo determinístico da revisão caso a caso (`universal` vs `testbed_dependent`)."""
    universal_ids: list[str] = []
    testbed_ids: list[str] = []
    by_category: dict[str, dict[str, int]] = {}
    for case in cases:
        scope = classify_case_scope(case)
        cat_counts = by_category.setdefault(
            case.category, {"universal": 0, "testbed_dependent": 0, "total": 0}
        )
        cat_counts[scope] += 1
        cat_counts["total"] += 1
        if scope == "universal":
            universal_ids.append(case.id)
        else:
            testbed_ids.append(case.id)
    return {
        "total": len(cases),
        "universal": len(universal_ids),
        "testbed_dependent": len(testbed_ids),
        "universal_ids": universal_ids,
        "testbed_dependent_ids": testbed_ids,
        "by_category": {k: by_category[k] for k in sorted(by_category)},
    }


class BlindSuiteResult(NamedTuple):
    """Resultado do carregamento de suíte cega: casos marcados e SHA-256 determinístico."""

    cases: list[AttackCase]
    suite_sha256: str


def resolve_blind_dir(cli_value: str | Path | None = None) -> Path | None:
    """Resolve diretório da suíte cega por argumento CLI ou variável AOK_BLIND_ATTACKS_DIR."""
    if cli_value is not None:
        text = str(cli_value).strip()
        if text:
            return Path(text)
    env_val = os.environ.get("AOK_BLIND_ATTACKS_DIR", "").strip()
    return Path(env_val) if env_val else None


def _format_validation_error(exc: ValidationError, *, redact: bool) -> str:
    if not redact:
        return str(exc)
    parts = [
        f"{'.'.join(str(x) for x in err['loc']) or 'root'}: {err['msg']}"
        for err in exc.errors(include_url=False, include_input=False)
    ]
    return "; ".join(parts)


def _load_cases(
    directory: Path,
    poisoned: Path,
    *,
    mark_blind: bool = False,
    redact_errors: bool = False,
) -> tuple[list[AttackCase], list[Path]]:
    cases: list[AttackCase] = []
    seen: set[str] = set()
    files = sorted(directory.glob("*.jsonl"))
    for path in files:
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                where = f"{path.name}:{n}"
                try:
                    raw = json.loads(line)
                    case = AttackCase.model_validate(raw)
                except json.JSONDecodeError as exc:
                    if redact_errors:
                        raise ValueError(
                            f"{where}: JSON inválido (linha {exc.lineno}, coluna {exc.colno})"
                        ) from None
                    raise ValueError(f"{where}: {exc}") from exc
                except ValidationError as exc:
                    msg = _format_validation_error(exc, redact=redact_errors)
                    if redact_errors:
                        raise ValueError(f"{where}: schema inválido ({msg})") from None
                    raise ValueError(f"{where}: {msg}") from exc
                if case.id in seen:
                    raise ValueError(f"{where}: id duplicado {case.id}")
                if case.poisoned_doc and not (poisoned / case.poisoned_doc).is_file():
                    raise ValueError(f"{where}: poisoned_doc inexistente {case.poisoned_doc}")
                if mark_blind:
                    case = case.model_copy(update={"is_blind": True})
                seen.add(case.id)
                cases.append(case)
    return cases, files


def load_attacks(
    directory: str | Path, poisoned_dir: str | Path | None = None
) -> list[AttackCase]:
    """Lê todos os *.jsonl do diretório. poisoned_dir padrão: <directory>/../poisoned_corpus."""
    directory = Path(directory)
    poisoned = Path(poisoned_dir) if poisoned_dir else directory.parent / "poisoned_corpus"
    cases, _ = _load_cases(directory, poisoned)
    return cases


def load_blind_attacks(
    blind_dir: str | Path, poisoned_dir: str | Path | None = None
) -> BlindSuiteResult:
    """Carrega suíte cega externa, marca `is_blind=True` e calcula SHA-256 sem expor textos."""
    blind_path = Path(blind_dir)
    if not blind_path.is_dir():
        raise ValueError(f"diretório de suíte cega inexistente: {blind_path}")
    local_poisoned = blind_path / "poisoned_corpus"
    if poisoned_dir is not None:
        poisoned = Path(poisoned_dir)
    elif local_poisoned.is_dir():
        poisoned = local_poisoned
    else:
        poisoned = blind_path.parent / "poisoned_corpus"

    cases, files = _load_cases(blind_path, poisoned, mark_blind=True, redact_errors=True)
    if not cases:
        raise ValueError(f"diretório de suíte cega vazio (0 casos): {blind_path}")

    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.name.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(path.read_bytes())
        hasher.update(b"\x00")
    return BlindSuiteResult(cases=cases, suite_sha256=hasher.hexdigest())
