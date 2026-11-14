"""Guardrails de seguranca (biblioteca padrao). Facade `Guardrails`."""

from collections.abc import Callable
from typing import Any

from agent_ops_kit.config import AgentConfig

from .canary import canary_line, detect_canary, generate_canary, inject_canary
from .input_filter import check_input, make_ollama_classifier
from .output_filter import REFUSAL_MESSAGE, check_output
from .tool_allowlist import ToolAllowlist
from .untrusted import UNTRUSTED_SYSTEM_NOTE, mark_untrusted
from .verdict import Verdict

__all__ = [
    "REFUSAL_MESSAGE",
    "UNTRUSTED_SYSTEM_NOTE",
    "Guardrails",
    "ToolAllowlist",
    "Verdict",
    "canary_line",
    "check_input",
    "check_output",
    "detect_canary",
    "generate_canary",
    "inject_canary",
    "make_ollama_classifier",
    "mark_untrusted",
]

_PASS = Verdict(False, ())


class Guardrails:
    """Liga/desliga cada guardrail pela lista `guardrails` do agent.yaml."""

    def __init__(
        self,
        config: AgentConfig,
        canary: str | None = None,
        system_prompt: str | None = None,
        classifier: Callable[[str], bool] | None = None,
    ):
        self.enabled = set(config.guardrails)
        self.system_prompt = system_prompt if system_prompt is not None else config.system_prompt
        self.classifier = classifier
        self.allowlist = ToolAllowlist.from_config(config)
        self.canary = canary
        if "canary" in self.enabled and self.canary is None:
            self.canary = generate_canary()

    def screen_input(self, text: str) -> Verdict:
        if "input_filter" not in self.enabled:
            return _PASS
        return check_input(text, self.classifier)

    def wrap_retrieved(self, text: str, source: str) -> str:
        if "untrusted_content" not in self.enabled:
            return text
        return mark_untrusted(text, source)

    def allow_tool(self, name: Any, args: Any) -> Verdict:
        if "tool_allowlist" not in self.enabled:
            return _PASS
        return self.allowlist.check(name, args)

    def screen_output(self, text: str) -> Verdict:
        if "output_filter" not in self.enabled:
            return _PASS
        return check_output(text, self.canary, self.system_prompt)

    def system_prompt_addendum(self) -> str:
        parts = []
        if "untrusted_content" in self.enabled:
            parts.append(UNTRUSTED_SYSTEM_NOTE)
        if "canary" in self.enabled and self.canary:
            parts.append(canary_line(self.canary))
        return "\n\n".join(parts)
