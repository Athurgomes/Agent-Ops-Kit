"""Schema e carregamento do agent.yaml."""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# "pacote.modulo:funcao": módulo com pontos e um único atributo (sem pontos, sem caminhos).
REF_PATTERN = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$", re.ASCII)


class PlatformConfig(BaseModel):
    """Identidade do agente na plataforma (usada por `aok check --publish URL`)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")


class TargetConfig(BaseModel):
    """Agente a auditar. Só `python` por enquanto (`ref` = "pacote.modulo:funcao")."""

    model_config = ConfigDict(extra="forbid")

    type: str = "python"
    ref: str

    @model_validator(mode="before")
    @classmethod
    def _only_python(cls, data: object) -> object:
        kind = data.get("type", "python") if isinstance(data, dict) else "python"
        if kind != "python":
            raise ValueError(
                f"target.type={kind!r} ainda não é suportado: só 'python' "
                "(http fica para uma etapa futura)"
            )
        return data

    @field_validator("ref")
    @classmethod
    def _valid_ref(cls, value: str) -> str:
        if not REF_PATTERN.match(value):
            raise ValueError(f"target.ref inválido: {value!r}; use 'pacote.modulo:funcao'")
        return value


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    model: str
    prompt_version: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)
    guardrails: list[str] = Field(default_factory=list)
    retrieval: dict[str, str | int | float | bool] = Field(default_factory=dict)
    audit: str | None = None  # caminho do log de auditoria; None = desligado
    platform: PlatformConfig | None = None  # opcional; só a publicação por URL usa
    target: TargetConfig | None = None  # None = agente de exemplo (examples.rag_agent)


def load_config(path: str | Path) -> AgentConfig:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AgentConfig.model_validate(data)
