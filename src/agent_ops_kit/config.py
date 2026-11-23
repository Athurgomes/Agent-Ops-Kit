"""Schema e carregamento do agent.yaml."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# "pacote.modulo:funcao": módulo com pontos e um único atributo (sem pontos, sem caminhos).
REF_PATTERN = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$", re.ASCII)
AUTH_ENV_PATTERN = re.compile(r"[A-Z_][A-Z0-9_]{0,127}", re.ASCII)
_HEADER_NAME_RE = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", re.ASCII)
SENSITIVE_HEADERS = frozenset({
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
    "x-auth-token",
    "x-api-token",
    "x-access-token",
    "x-secret-key",
    "x-authorization",
})
_TRANSPORT_HEADERS = frozenset({
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-connection",
    "te",
    "trailer",
    "upgrade",
})
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_HTTP_ONLY_FIELDS = frozenset({
    "url",
    "auth_env",
    "auth_header",
    "auth_prefix",
    "headers",
    "request_template",
    "answer_path",
    "tool_calls_path",
    "trace_id_path",
    "timeout_s",
    "max_response_bytes",
    "max_calls",
    "allow_insecure_localhost",
})


def _has_ctl(text: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def _is_valid_header_value(text: str) -> bool:
    if _has_ctl(text):
        return False
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True


def sanitize_url(url: str) -> str:
    """URL sem credenciais, query nem fragmento (esquema + host + porta + path)."""
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    host_fmt = f"[{host}]" if ":" in host else host
    port = parsed.port
    netloc = f"{host_fmt}:{port}" if port is not None else host_fmt
    return urlunsplit((scheme, netloc, parsed.path, "", ""))


def validate_http_url(url: str, *, allow_insecure_localhost: bool = False) -> str:
    """Valida esquema, ausência de credenciais/query/fragmento e restrição de localhost."""
    if (
        not isinstance(url, str)
        or not url
        or url != url.strip()
        or _has_ctl(url)
        or any(ch.isspace() for ch in url)
    ):
        raise ValueError("target.url inválida")
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http"):
        raise ValueError(
            "target.url deve usar esquema https:// (ou http:// apenas em localhost autorizado)"
        )
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("target.url não pode conter credenciais embutidas (use target.auth_env)")
    if "\\" in parsed.netloc:
        raise ValueError("target.url inválida")
    if parsed.query or parsed.fragment or "?" in url or "#" in url:
        raise ValueError("target.url não pode conter query string nem fragmento")
    host = parsed.hostname
    if not host:
        raise ValueError("target.url sem host válido")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("target.url com porta inválida") from exc
    if scheme == "http" and (not allow_insecure_localhost or host not in LOOPBACK_HOSTS):
        raise ValueError(
            "target.url com http:// é recusada por padrão; use https:// "
            "(http:// exige allow_insecure_localhost=true e host localhost, 127.0.0.1 ou ::1)"
        )
    return url


def _validate_dot_path(value: str, field_name: str) -> str:
    if (
        not value
        or value != value.strip()
        or _has_ctl(value)
        or any(part == "" for part in value.split("."))
    ):
        raise ValueError(
            f"target.{field_name} inválido: informe caminho pontilhado não vazio "
            "(ex.: choices.0.message.content)"
        )
    return value


class PlatformConfig(BaseModel):
    """Identidade do agente na plataforma (usada por `aok check --publish URL`)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")


class TargetConfig(BaseModel):
    """Agente a auditar: módulo Python local (`type: python`) ou endpoint HTTP (`type: http`)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["python", "http"] = "python"
    ref: str | None = None

    url: str | None = None
    auth_env: str | None = None
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    headers: dict[str, str] = Field(default_factory=dict)
    request_template: dict[str, Any] | None = None
    answer_path: str = "answer"
    tool_calls_path: str | None = "tool_calls"
    trace_id_path: str | None = "trace_id"
    timeout_s: float = Field(default=30.0, gt=0, le=300.0)
    max_response_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    max_calls: int | None = Field(default=None, ge=1)
    allow_insecure_localhost: bool = False

    @field_validator("auth_env")
    @classmethod
    def _valid_auth_env(cls, value: str | None) -> str | None:
        if value is not None and not AUTH_ENV_PATTERN.fullmatch(value):
            raise ValueError(
                "target.auth_env inválido: informe apenas o nome da variável de ambiente "
                "(^[A-Z_][A-Z0-9_]{0,127}$)"
            )
        return value

    @field_validator("auth_header")
    @classmethod
    def _valid_auth_header(cls, value: str) -> str:
        if not _HEADER_NAME_RE.fullmatch(value) or value.lower() in _TRANSPORT_HEADERS:
            raise ValueError("target.auth_header inválido")
        return value

    @field_validator("auth_prefix")
    @classmethod
    def _valid_auth_prefix(cls, value: str) -> str:
        if not _is_valid_header_value(value):
            raise ValueError("target.auth_prefix inválido")
        return value

    @field_validator("headers")
    @classmethod
    def _valid_headers(cls, value: dict[str, str]) -> dict[str, str]:
        for key, val in value.items():
            if not _HEADER_NAME_RE.fullmatch(key) or not _is_valid_header_value(val):
                raise ValueError(f"cabeçalho inválido em target.headers: {key!r}")
            low = key.lower()
            if low in SENSITIVE_HEADERS:
                raise ValueError(
                    f"cabeçalho sensível {key!r} não é permitido em target.headers; "
                    "use target.auth_env"
                )
            if low in _TRANSPORT_HEADERS:
                raise ValueError(
                    f"cabeçalho de transporte {key!r} não é permitido em target.headers"
                )
        return value

    @field_validator("answer_path")
    @classmethod
    def _valid_answer_path(cls, value: str) -> str:
        return _validate_dot_path(value, "answer_path")

    @field_validator("tool_calls_path")
    @classmethod
    def _valid_tool_calls_path(cls, value: str | None) -> str | None:
        return None if value is None else _validate_dot_path(value, "tool_calls_path")

    @field_validator("trace_id_path")
    @classmethod
    def _valid_trace_id_path(cls, value: str | None) -> str | None:
        return None if value is None else _validate_dot_path(value, "trace_id_path")

    @field_validator("timeout_s", "max_response_bytes", "max_calls", mode="before")
    @classmethod
    def _reject_bool_numeric(cls, value: object) -> object:
        if isinstance(value, bool):
            raise TypeError("valor booleano não permitido em campo numérico")
        return value

    @field_validator("timeout_s")
    @classmethod
    def _finite_timeout(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("target.timeout_s deve ser finito")
        return value

    @model_validator(mode="after")
    def _validate_by_type(self) -> TargetConfig:
        if self.type == "python":
            bad = self.model_fields_set & _HTTP_ONLY_FIELDS
            if bad:
                raise ValueError(
                    "campos HTTP não são permitidos para target.type='python': "
                    + ", ".join(sorted(bad))
                )
            if self.ref is None:
                raise ValueError("target.ref é obrigatório para target.type='python'")
            if not REF_PATTERN.match(self.ref):
                raise ValueError(f"target.ref inválido: {self.ref!r}; use 'pacote.modulo:funcao'")
            return self

        if "ref" in self.model_fields_set:
            raise ValueError("target.ref não é permitido para target.type='http'")
        if not self.url:
            raise ValueError("target.url é obrigatório para target.type='http'")
        validate_http_url(self.url, allow_insecure_localhost=self.allow_insecure_localhost)
        if self.auth_env and any(k.lower() == self.auth_header.lower() for k in self.headers):
            raise ValueError(
                f"cabeçalho {self.auth_header!r} em target.headers conflita com target.auth_header"
            )
        return self


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
