"""Roda o agente sobre o dataset com uma variante de prompt e pontua as respostas.

Determinismo (o que é e o que não é):
- O LLM padrão usa temperature 0 e `seed` fixo nas options do Ollama. Com o mesmo modelo,
  versão do Ollama e hardware, isso tende a repetir as respostas, mas o Ollama não garante
  igualdade bit a bit (GPU vs CPU, versão do runtime, batching podem mudar a saída).
- A recuperação (Chroma + embeddings) é determinística para um índice fixo.
- Não determinísticos: latency_s e, em geral, a contagem de tokens se a resposta mudar.
- Por isso as respostas são gravadas em JSONL: o score pode ser recalculado sem o modelo.
"""

from __future__ import annotations

import json
import re
import time
from contextlib import nullcontext
from pathlib import Path

from agent_ops_kit.config import AgentConfig
from agent_ops_kit.eval.checks import run_checks
from agent_ops_kit.eval.dataset import EvalCase
from agent_ops_kit.eval.prompts import load_prompt
from examples.rag_agent.agent import LLMFn, run_agent

DEFAULT_SEED = 42

# "Resposta:" tolerante a caixa, acento e negrito simples (**Resposta:** / **Resposta**:).
_ANSWER_MARKER = re.compile(r"(?<!\w)\*{0,2}resp[oó]sta\*{0,2}\s*:\s*\*{0,2}", re.IGNORECASE)


def make_ollama_llm(seed: int = DEFAULT_SEED) -> LLMFn:
    """LLM do Ollama com temperature 0 e semente fixa."""

    def llm(model: str, messages: list[dict], tools: list[dict]) -> object:
        import ollama

        return ollama.chat(
            model=model,
            messages=messages,
            tools=tools,
            options={"temperature": 0, "seed": seed},
        )

    return llm


def _get(obj: object, key: str) -> object:
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


def run_variant(
    variant: str,
    dataset: list[EvalCase],
    config: AgentConfig,
    llm: LLMFn | None = None,
    out_path: str | Path | None = None,
    limit: int | None = None,
    seed: int = DEFAULT_SEED,
    prompts_dir: str | Path = "evals/prompts",
) -> list[dict]:
    """Roda o agente em cada caso com o prompt da variante.

    Devolve um registro por caso: case_id, variant, answer, latency_s, input_tokens,
    output_tokens, error. Erro em um caso é registrado em `error` e a execução segue.
    Com `out_path`, grava um registro por linha (JSONL) à medida que roda.
    `llm=None` usa o Ollama com temperature 0 e `seed`; um `llm` injetado ignora `seed`.
    """
    cfg = config.model_copy(
        update={"system_prompt": load_prompt(variant, prompts_dir), "prompt_version": variant}
    )
    base_llm = llm or make_ollama_llm(seed)
    cases = dataset[:limit] if limit is not None else dataset
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with open(out_path, "w", encoding="utf-8") if out_path else nullcontext() as out:
        for case in cases:
            record = _run_case(case, variant, cfg, base_llm)
            records.append(record)
            if out:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
    return records


def _run_case(case: EvalCase, variant: str, cfg: AgentConfig, base_llm: LLMFn) -> dict:
    tokens = [0, 0]

    def counting_llm(model: str, messages: list[dict], tools: list[dict]) -> object:
        resp = base_llm(model, messages, tools)
        tokens[0] += int(_get(resp, "prompt_eval_count") or 0)
        tokens[1] += int(_get(resp, "eval_count") or 0)
        return resp

    answer, error = "", None
    start = time.perf_counter()
    try:
        answer = run_agent(case.question, cfg, llm=counting_llm)
    except Exception as exc:  # noqa: BLE001 - um caso ruim não derruba a execução
        error = f"{type(exc).__name__}: {exc}"
    return {
        "case_id": case.id,
        "variant": variant,
        "answer": answer,
        "latency_s": time.perf_counter() - start,
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "error": error,
    }


def load_records(path: str | Path) -> list[dict]:
    """Relê um JSONL gravado por run_variant."""
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def final_answer(answer: str) -> str:
    """Texto após a ÚLTIMA ocorrência de "Resposta:"; sem o marcador, devolve a resposta inteira.

    Descarta o raciocínio (CoT) do v2 antes de pontuar. O JSONL guarda a resposta bruta.
    """
    matches = list(_ANSWER_MARKER.finditer(answer))
    return answer[matches[-1].end() :].strip() if matches else answer


def score_records(dataset: list[EvalCase], records: list[dict]) -> dict[str, float]:
    """Score determinístico (0 a 1, via run_checks sobre `final_answer`) por case_id.

    Registro com erro é pontuado como resposta vazia (não some do cálculo nem é ignorado).
    Registros de casos fora do dataset levantam KeyError; casos sem registro ficam de fora.
    """
    by_id = {c.id: c for c in dataset}
    return {
        r["case_id"]: run_checks(by_id[r["case_id"]], final_answer(r["answer"])).score
        for r in records
    }
