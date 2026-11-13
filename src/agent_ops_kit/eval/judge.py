"""LLM-as-judge com rubrica explícita (fidelidade, relevância, completude; notas de 1 a 5).

LIMITAÇÕES (leia antes de confiar nas notas):
- O juiz é o MESMO modelo (llama3.1:8b) que gera as respostas do agente. Isso traz viés de
  autopreferência (tende a gostar do próprio estilo) e ruído: um modelo de 8B erra em
  contas de cobertura de fatos e em detectar afirmações sutilmente inventadas.
- As notas são ORDINAIS (1 < 2 < ... < 5), não intervalares: a distância entre 3 e 4 não é a
  mesma entre 4 e 5. A média das três notas (`score`) é uma conveniência, não uma medida
  calibrada.
- A rubrica abaixo é a única fonte de critério; não há calibração contra humanos.
- Por isso o juiz complementa as checagens determinísticas (checks.py), não as substitui.

Determinismo: temperature 0 e `seed` fixa nas options do Ollama; o Ollama não garante
igualdade bit a bit entre hardware/versões.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from agent_ops_kit.eval.checks import REFUSAL_PHRASE
from agent_ops_kit.eval.dataset import EvalCase
from agent_ops_kit.eval.runner import final_answer

DEFAULT_SEED = 42
DEFAULT_MODEL = "llama3.1:8b"
CORPUS_DIR = Path(__file__).resolve().parents[3] / "examples" / "rag_agent" / "corpus"

# Recebe as mensagens (system + user) e devolve o texto bruto do juiz (JSON esperado).
JudgeLLM = Callable[[list[dict]], str]

RUBRIC = f"""Você é um avaliador rigoroso de respostas de um assistente interno. Avalie a RESPOSTA \
do assistente em três critérios, cada um com nota inteira de 1 a 5.

Critérios:
1. fidelidade: a resposta só afirma o que está nos DOCUMENTOS DE REFERÊNCIA?
   5 = tudo o que afirma está nos documentos; 3 = há um detalhe não sustentado pelos documentos; \
1 = afirma coisas que contradizem os documentos ou que foram inventadas.
2. relevancia: a resposta trata do que a PERGUNTA pede?
   5 = responde direto à pergunta; 3 = responde só em parte ou com muito desvio; \
1 = não tem relação com a pergunta.
3. completude: a resposta traz TODOS os FATOS ESPERADOS?
   5 = traz todos os fatos esperados; 3 = traz cerca da metade; 1 = não traz nenhum.

Regras:
- Compare a resposta com os documentos e com os fatos esperados, não com o seu conhecimento.
- Nota 5 exige que o critério seja plenamente atendido; não dê nota alta por educação ou estilo.
- Se a resposta não for sobre os documentos, ou for vazia, dê nota baixa em todos os critérios.
- Caso SEM resposta nos documentos: a única resposta correta é recusar, dizendo que não \
encontrou a informação ("{REFUSAL_PHRASE}"). Recusa clara = 5 nos três critérios. Qualquer \
informação inventada em vez de recusar = 1 nos três critérios.
- Responda SOMENTE com um JSON, sem texto fora dele, neste formato exato:
{{"fidelidade": <1-5>, "relevancia": <1-5>, "completude": <1-5>, "justificativa": "<1 ou 2 frases>"}}"""


class JudgeError(Exception):
    """O juiz não devolveu uma avaliação válida (mesmo após o retry)."""


class JudgeOutput(BaseModel):
    """Saída validada do juiz: notas inteiras de 1 a 5 (strict: "4" e 4.0 são rejeitados)."""

    fidelidade: int = Field(ge=1, le=5, strict=True)
    relevancia: int = Field(ge=1, le=5, strict=True)
    completude: int = Field(ge=1, le=5, strict=True)
    justificativa: str = Field(min_length=1)


@dataclass(frozen=True)
class JudgeResult:
    """Avaliação de um caso. Em erro, as notas e o score são None e `error` explica o motivo."""

    fidelidade: int | None = None
    relevancia: int | None = None
    completude: int | None = None
    justificativa: str = ""
    error: str | None = None

    @property
    def score(self) -> float | None:
        """Média simples das três notas (1 a 5); None se houve erro."""
        if self.error is not None:
            return None
        return (self.fidelidade + self.relevancia + self.completude) / 3  # type: ignore[operator]


def make_ollama_judge_llm(model: str = DEFAULT_MODEL, seed: int = DEFAULT_SEED) -> JudgeLLM:
    """Juiz via Ollama: modo JSON, temperature 0 e semente fixa."""

    def llm(messages: list[dict]) -> str:
        import ollama

        resp = ollama.chat(
            model=model,
            messages=messages,
            format="json",
            options={"temperature": 0, "seed": seed},
        )
        return resp["message"]["content"] if isinstance(resp, dict) else resp.message.content

    return llm


def load_reference(case: EvalCase, corpus_dir: str | Path = CORPUS_DIR) -> str:
    """Texto dos documentos de `case.sources` (vazio para casos não respondíveis)."""
    parts = [
        f"[{name}]\n{(Path(corpus_dir) / name).read_text(encoding='utf-8').strip()}"
        for name in case.sources
    ]
    return "\n\n".join(parts)


def build_messages(case: EvalCase, answer: str, corpus_dir: str | Path = CORPUS_DIR) -> list[dict]:
    """Monta as mensagens do juiz: rubrica (system) + caso e resposta (user)."""
    if case.answerable:
        reference = load_reference(case, corpus_dir)
        expected = "\n".join(f"- {e}" for e in case.expected)
        case_block = (
            f"DOCUMENTOS DE REFERÊNCIA:\n{reference}\n\nFATOS ESPERADOS:\n{expected}"
        )
    else:
        case_block = (
            "DOCUMENTOS DE REFERÊNCIA: (nenhum)\n\n"
            "CASO SEM RESPOSTA NOS DOCUMENTOS: a resposta correta é recusar, dizendo que "
            f'não encontrou a informação ("{REFUSAL_PHRASE}"). Não há fatos esperados.'
        )
    user = f"PERGUNTA:\n{case.question}\n\n{case_block}\n\nRESPOSTA DO ASSISTENTE:\n{answer}"
    return [{"role": "system", "content": RUBRIC}, {"role": "user", "content": user}]


def _parse(raw: str) -> JudgeOutput:
    return JudgeOutput.model_validate(json.loads(raw))


def judge_case(
    case: EvalCase,
    answer: str,
    llm: JudgeLLM | None = None,
    corpus_dir: str | Path = CORPUS_DIR,
) -> JudgeResult:
    """Julga `answer` (a resposta final, sem raciocínio). Uma nova tentativa se o parse falhar.

    Levanta JudgeError se as duas tentativas devolverem JSON inválido ou notas fora de 1-5;
    nunca inventa nota.
    """
    call = llm or make_ollama_judge_llm()
    messages = build_messages(case, answer, corpus_dir)
    last = ""
    for _ in range(2):
        raw = call(messages)
        try:
            out = _parse(raw)
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            continue
        return JudgeResult(out.fidelidade, out.relevancia, out.completude, out.justificativa)
    raise JudgeError(f"{case.id}: saída inválida do juiz após 2 tentativas ({last})")


def judge_records(
    dataset: list[EvalCase],
    records: list[dict],
    llm: JudgeLLM | None = None,
    corpus_dir: str | Path = CORPUS_DIR,
) -> dict[str, JudgeResult]:
    """Julga a `final_answer` de cada registro do runner; {case_id: resultado}.

    Falha do juiz em um caso vira JudgeResult com `error` (sem notas); a execução segue.
    Registro de caso fora do dataset levanta KeyError.
    """
    by_id = {c.id: c for c in dataset}
    call = llm or make_ollama_judge_llm()
    results: dict[str, JudgeResult] = {}
    for r in records:
        case = by_id[r["case_id"]]
        try:
            results[case.id] = judge_case(case, final_answer(r["answer"]), call, corpus_dir)
        except JudgeError as exc:
            results[case.id] = JudgeResult(error=str(exc))
    return results
