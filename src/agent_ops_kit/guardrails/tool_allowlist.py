"""Allowlist de tools (LLM06: agencia excessiva).

Limite: so valida o NOME da tool (contra config.tools) e o TIPO dos argumentos
(nome string, args dict). O CONTEUDO dos argumentos nao e validado: uma tool
permitida chamada com argumentos maliciosos passa.
"""

from collections.abc import Iterable
from typing import Any

from agent_ops_kit.config import AgentConfig

from .verdict import Verdict


class ToolAllowlist:
    def __init__(self, allowed: Iterable[str]):
        self.allowed = frozenset(allowed)

    @classmethod
    def from_config(cls, config: AgentConfig) -> "ToolAllowlist":
        return cls(config.tools)

    def check(self, tool_name: Any, args: Any) -> Verdict:
        if not isinstance(tool_name, str) or not tool_name.strip():
            return Verdict(True, ("invalid_tool_name",))
        if not isinstance(args, dict):
            return Verdict(True, ("invalid_args",))
        if tool_name not in self.allowed:
            return Verdict(True, (f"tool_not_allowed:{tool_name}",))
        return Verdict(False, ())
