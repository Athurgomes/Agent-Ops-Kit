"""Modelo e carregador do dataset de avaliação (JSONL)."""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError, model_validator


class EvalCase(BaseModel):
    id: str
    question: str
    answerable: bool
    expected: list[str]
    sources: list[str]
    category: str

    @model_validator(mode="after")
    def _check_consistency(self) -> "EvalCase":
        if self.answerable and not (self.expected and self.sources):
            raise ValueError(f"{self.id}: caso respondível exige expected e sources não vazios")
        if not self.answerable and (self.expected or self.sources):
            raise ValueError(f"{self.id}: caso não respondível exige expected e sources vazios")
        return self


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Lê um JSONL e valida cada caso. Levanta ValueError com a linha do problema."""
    cases: list[EvalCase] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                case = EvalCase.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(f"{path}:{n}: caso inválido: {exc}") from exc
            if case.id in seen:
                raise ValueError(f"{path}:{n}: id duplicado: {case.id}")
            seen.add(case.id)
            cases.append(case)
    return cases
