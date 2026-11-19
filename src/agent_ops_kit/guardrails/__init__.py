"""Guardrails de seguranca (biblioteca padrao). Facade `Guardrails`."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from agent_ops_kit.config import AgentConfig

from .canary import canary_line, detect_canary, generate_canary, inject_canary
from .input_filter import (
    _extract_user_messages,
    check_conversation,
    check_input,
    make_ollama_classifier,
)
from .obfuscation import expand_obfuscated_variants
from .output_filter import REFUSAL_MESSAGE, check_output
from .semantic import LocalSemanticClassifier, SemanticScore, make_local_semantic_classifier
from .tool_allowlist import ToolAllowlist
from .untrusted import UNTRUSTED_SYSTEM_NOTE, mark_untrusted
from .verdict import Verdict

__all__ = [
    "REFUSAL_MESSAGE",
    "UNTRUSTED_SYSTEM_NOTE",
    "Guardrails",
    "LocalSemanticClassifier",
    "SemanticScore",
    "ToolAllowlist",
    "Verdict",
    "canary_line",
    "check_conversation",
    "check_input",
    "check_output",
    "detect_canary",
    "expand_obfuscated_variants",
    "generate_canary",
    "inject_canary",
    "make_local_semantic_classifier",
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
        semantic_classifier: LocalSemanticClassifier | None = None,
    ):
        self.enabled = set(config.guardrails)
        self.system_prompt = system_prompt if system_prompt is not None else config.system_prompt
        self.classifier = classifier
        if semantic_classifier is not None:
            self.semantic_classifier: LocalSemanticClassifier | None = semantic_classifier
        elif "semantic_filter" in self.enabled:
            self.semantic_classifier = make_local_semantic_classifier()
        else:
            self.semantic_classifier = None
        self.allowlist = ToolAllowlist.from_config(config)
        self.canary = canary
        if "canary" in self.enabled and self.canary is None:
            self.canary = generate_canary()

    def screen_input(self, text: str) -> Verdict:
        if "input_filter" in self.enabled:
            return check_input(
                text,
                self.classifier,
                semantic_classifier=self.semantic_classifier,
            )
        if "semantic_filter" in self.enabled and self.semantic_classifier is not None:
            if self.semantic_classifier(text):
                return Verdict(True, ("semantic_classifier",))
            return _PASS
        return _PASS

    def screen_conversation(
        self,
        messages: Sequence[str | Mapping[str, Any]],
        window: int = 4,
    ) -> Verdict:
        if "input_filter" in self.enabled:
            return check_conversation(
                messages,
                self.classifier,
                window=window,
                semantic_classifier=self.semantic_classifier,
            )
        if "semantic_filter" in self.enabled and self.semantic_classifier is not None:
            if window < 1:
                raise ValueError("window deve ser >= 1")
            user_texts = _extract_user_messages(messages)
            for msg in user_texts:
                if self.semantic_classifier(msg):
                    return Verdict(True, ("semantic_classifier",))
            recent = user_texts[-window:]
            for span in range(2, len(recent) + 1):
                for start in range(len(recent) - span + 1):
                    if self.semantic_classifier(" ".join(recent[start : start + span])):
                        return Verdict(True, ("multi_turn_injection", "semantic_classifier"))
            return _PASS
        return _PASS

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
