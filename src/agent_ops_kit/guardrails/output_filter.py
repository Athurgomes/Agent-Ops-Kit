"""Filtro de saida (LLM02): canary e vazamento do system prompt."""

import re

from .canary import detect_canary
from .verdict import Verdict, normalize

REFUSAL_MESSAGE = (
    "Desculpe, não posso atender esse pedido porque ele envolve informações internas "
    "ou instruções que não posso compartilhar. Posso ajudar com outra dúvida?"
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", normalize(text))


def _windows(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def check_output(
    text: str,
    canary: str | None = None,
    system_prompt: str | None = None,
    window: int = 8,
) -> Verdict:
    reasons: list[str] = []
    if canary and detect_canary(text, canary):
        reasons.append("canary_leak")
    if system_prompt and _windows(_words(text), window) & _windows(_words(system_prompt), window):
        reasons.append("system_prompt_leak")
    return Verdict(bool(reasons), tuple(reasons))
