"""Checagens determinísticas (sem LLM, sem rede) sobre a resposta do agente.

Cada checagem devolve True/False, ou None quando não se aplica ao caso.
"""

import re
import unicodedata
from dataclasses import dataclass

from agent_ops_kit.eval.dataset import EvalCase

# Frase de recusa exigida pelo system_prompt de examples/rag_agent/agent.yaml.
REFUSAL_PHRASE = "Não encontrei essa informação nos documentos."

_FILE_RE = re.compile(r"[\w\-]+\.md\b")
_SOURCE_LINE_RE = re.compile(r"^\W*fonte\s*:\s*\S", re.MULTILINE)


def _fold(text: str) -> str:
    """Minúsculas e sem acentos; mantém quebras de linha."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _norm(text: str) -> str:
    """Como _fold, mas colapsando qualquer espaço em branco em um espaço."""
    return re.sub(r"\s+", " ", _fold(text)).strip()


def _has_token(text: str, needle: str) -> bool:
    """Substring com limite de token: "30 dias" não casa com "130 dias".

    O limite só vale nas pontas que são letra/dígito; "ENG-" ainda casa com "ENG-1234".
    """
    if not needle:
        return True
    before = r"(?<!\w)" if re.match(r"\w", needle[0]) else ""
    after = r"(?!\w)" if re.match(r"\w", needle[-1]) else ""
    return re.search(before + re.escape(needle) + after, text) is not None


def contains_expected(case: EvalCase, answer: str) -> bool | None:
    if not case.answerable:
        return None
    ans = _norm(answer)
    return all(_has_token(ans, _norm(e)) for e in case.expected)


def cites_correct_source(case: EvalCase, answer: str) -> bool:
    ans = _fold(answer)
    if case.answerable:
        return any(_fold(s) in ans for s in case.sources)
    return not _FILE_RE.search(ans)


def valid_format(case: EvalCase, answer: str) -> bool:
    if not answer.strip():
        return False
    if case.answerable:
        return bool(_SOURCE_LINE_RE.search(_fold(answer)))
    return True


def refuses_when_unanswerable(case: EvalCase, answer: str) -> bool | None:
    if case.answerable:
        return None
    return _norm(REFUSAL_PHRASE).rstrip(".") in _norm(answer)


@dataclass(frozen=True)
class CheckResult:
    contains_expected: bool | None
    cites_correct_source: bool | None
    valid_format: bool | None
    refuses_when_unanswerable: bool | None

    @property
    def score(self) -> float:
        """Fração das checagens aplicáveis que passaram (0 a 1)."""
        applicable = [
            v
            for v in (
                self.contains_expected,
                self.cites_correct_source,
                self.valid_format,
                self.refuses_when_unanswerable,
            )
            if v is not None
        ]
        return sum(applicable) / len(applicable)


def run_checks(case: EvalCase, answer: str) -> CheckResult:
    return CheckResult(
        contains_expected=contains_expected(case, answer),
        cites_correct_source=cites_correct_source(case, answer),
        valid_format=valid_format(case, answer),
        refuses_when_unanswerable=refuses_when_unanswerable(case, answer),
    )
