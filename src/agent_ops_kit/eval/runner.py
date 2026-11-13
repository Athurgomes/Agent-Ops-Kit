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

import hashlib
import json
import re
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from agent_ops_kit.config import AgentConfig
from agent_ops_kit.eval.checks import run_checks
from agent_ops_kit.eval.dataset import EvalCase
from agent_ops_kit.eval.prompts import load_prompt
from examples.rag_agent.agent import LLMFn, run_agent

DEFAULT_SEED = 42
MANIFEST_NAME = "manifest.json"
STALE_MESSAGE = "respostas gravadas desatualizadas: regrave com aok eval"


class ManifestError(ValueError):
    """Manifesto ausente ou divergente dos arquivos atuais (mensagem em português)."""

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


def sha256_text(text: str) -> str:
    """sha256 do texto em UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dataset_hash(path: str | Path) -> str:
    """sha256 do dataset lido como texto (CRLF e LF dão o mesmo hash)."""
    return sha256_text(Path(path).read_text(encoding="utf-8"))


def manifest_entry(
    variant: str,
    config: AgentConfig,
    dataset_path: str | Path,
    n_cases: int,
    seed: int,
    prompts_dir: str | Path = "evals/prompts",
) -> dict:
    """Entrada do manifesto de uma variante: o que as respostas gravadas dependem."""
    return {
        "prompt_sha256": sha256_text(load_prompt(variant, prompts_dir)),
        "dataset_sha256": dataset_hash(dataset_path),
        "model": config.model,
        "seed": seed,
        "n_cases": n_cases,
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def write_manifest_entry(answers_dir: str | Path, variant: str, entry: dict) -> Path:
    """Grava (ou atualiza) a entrada da variante em <answers_dir>/manifest.json."""
    path = Path(answers_dir) / MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data[variant] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def verify_manifest(
    answers_dir: str | Path,
    variants: list[str],
    config: AgentConfig,
    dataset_path: str | Path,
    prompts_dir: str | Path = "evals/prompts",
) -> None:
    """Confere prompt, dataset, modelo e nº de respostas contra o manifesto.

    Levanta ManifestError com a causa em português se algo divergir.
    """
    path = Path(answers_dir) / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(
            f"manifesto não encontrado: {path}. {STALE_MESSAGE} (ou use --no-verify)"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    current_dataset = dataset_hash(dataset_path)
    for v in variants:
        entry = data.get(v)
        if entry is None:
            raise ManifestError(f"variante {v!r} ausente no manifesto {path}. {STALE_MESSAGE}")
        try:
            current_prompt = sha256_text(load_prompt(v, prompts_dir))
        except (FileNotFoundError, ValueError) as exc:
            raise ManifestError(str(exc)) from exc
        problems = []
        if entry.get("prompt_sha256") != current_prompt:
            problems.append(f"o prompt {v} mudou")
        if entry.get("dataset_sha256") != current_dataset:
            problems.append("o dataset mudou")
        if entry.get("model") != config.model:
            problems.append(f"o modelo mudou ({entry.get('model')} -> {config.model})")
        n_records = len(load_records(Path(answers_dir) / f"{v}.jsonl"))
        if entry.get("n_cases") != n_records:
            problems.append(
                f"o arquivo tem {n_records} respostas, o manifesto registra {entry.get('n_cases')}"
            )
        if problems:
            raise ManifestError(f"{STALE_MESSAGE} ({v}: {'; '.join(problems)})")
