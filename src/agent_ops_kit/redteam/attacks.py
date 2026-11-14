"""Modelo e carregador dos casos de ataque (JSONL).

Categorias inspiradas no OWASP Top 10 for LLM Applications: LLM01 (prompt injection:
direta e indireta), LLM02 (divulgação de informação sensível: exfiltração) e
LLM06 (agência excessiva: abuso de tools).
"""

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from agent_ops_kit.redteam.testbed import FORBIDDEN_TOOLS

Category = Literal["injecao_direta", "injecao_indireta", "abuso_de_tools", "exfiltracao"]


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
    poisoned_doc: str | None = None
    success: Success

    @model_validator(mode="after")
    def _check(self) -> "AttackCase":
        if isinstance(self.success, ToolCalled) and self.success.tool not in FORBIDDEN_TOOLS:
            raise ValueError(f"{self.id}: tool_called exige tool proibida, veio {self.success.tool}")
        if self.category == "injecao_indireta" and not self.poisoned_doc:
            raise ValueError(f"{self.id}: injecao_indireta exige poisoned_doc")
        return self


def load_attacks(
    directory: str | Path, poisoned_dir: str | Path | None = None
) -> list[AttackCase]:
    """Lê todos os *.jsonl do diretório. poisoned_dir padrão: <directory>/../poisoned_corpus."""
    directory = Path(directory)
    poisoned = Path(poisoned_dir) if poisoned_dir else directory.parent / "poisoned_corpus"
    cases: list[AttackCase] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.strip():
                    continue
                where = f"{path.name}:{n}"
                try:
                    case = AttackCase.model_validate(json.loads(line))
                except (json.JSONDecodeError, ValidationError) as exc:
                    raise ValueError(f"{where}: {exc}") from exc
                if case.id in seen:
                    raise ValueError(f"{where}: id duplicado {case.id}")
                if case.poisoned_doc and not (poisoned / case.poisoned_doc).is_file():
                    raise ValueError(f"{where}: poisoned_doc inexistente {case.poisoned_doc}")
                seen.add(case.id)
                cases.append(case)
    return cases
