"""Tipos e normalização de texto compartilhados pelos guardrails."""

import re
import unicodedata
from dataclasses import dataclass, field

_ZERO_WIDTH = re.compile("[" + "".join(chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0xAD)) + "]")
_LEET = str.maketrans("013457@$", "oieastas")


@dataclass(frozen=True)
class Verdict:
    blocked: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


def strip_invisible(text: str) -> str:
    """NFKC e remoção de caracteres zero-width (preserva quebras de linha)."""
    return _ZERO_WIDTH.sub("", unicodedata.normalize("NFKC", text))


def normalize(text: str, leet: bool = False) -> str:
    """Minúsculas, sem acentos, sem zero-width, espaços colapsados (leet opcional)."""
    text = unicodedata.normalize("NFD", strip_invisible(text))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    if leet:
        text = text.translate(_LEET)
    return re.sub(r"\s+", " ", text).strip()
