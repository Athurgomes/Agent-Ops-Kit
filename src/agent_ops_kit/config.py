"""Schema e carregamento do agent.yaml."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    model: str
    prompt_version: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    retrieval: dict[str, str | int | float | bool] = Field(default_factory=dict)


def load_config(path: str | Path) -> AgentConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AgentConfig.model_validate(data)
