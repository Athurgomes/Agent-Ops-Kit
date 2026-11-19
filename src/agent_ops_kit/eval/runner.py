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
import statistics
import time
from collections.abc import Callable
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_ops_kit.config import AgentConfig
from agent_ops_kit.eval.checks import run_checks
from agent_ops_kit.eval.dataset import EvalCase
from agent_ops_kit.eval.prompts import load_prompt

LLMFn = Callable[[str, list[dict], list[dict]], object]
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


def _load_run_agent() -> Callable[..., str]:
    try:
        from examples.rag_agent.agent import run_agent
    except ImportError as exc:
        raise ImportError(
            "agente de referência (examples.rag_agent) indisponível; "
            "execute a partir da raiz do repositório ou use respostas gravadas (--reuse)"
        ) from exc
    return run_agent


def run_variant(
    variant: str,
    dataset: list[EvalCase],
    config: AgentConfig,
    llm: LLMFn | None = None,
    out_path: str | Path | None = None,
    limit: int | None = None,
    seed: int = DEFAULT_SEED,
    prompts_dir: str | Path = "evals/prompts",
    runs: int = 1,
) -> list[dict]:
    """Roda o agente em cada caso com o prompt da variante.

    Devolve um registro por caso (ou por execução e caso quando `runs > 1`): case_id,
    variant, answer, latency_s, input_tokens, output_tokens, error (e `run_index` quando
    `runs > 1`). Erro em um caso é registrado em `error` e a execução segue.
    Com `out_path`, grava um registro por linha (JSONL) à medida que roda.
    `llm=None` usa o Ollama com temperature 0 e `seed + run_index`; um `llm` injetado
    ignora `seed`.
    """
    if runs < 1:
        raise ValueError("runs deve ser >= 1")
    run_agent_fn = _load_run_agent()
    cfg = config.model_copy(
        update={"system_prompt": load_prompt(variant, prompts_dir), "prompt_version": variant}
    )
    cases = dataset[:limit] if limit is not None else dataset
    if out_path is not None:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    with open(out_path, "w", encoding="utf-8") if out_path else nullcontext() as out:
        for run_index in range(runs):
            base_llm = llm if llm is not None else make_ollama_llm(seed + run_index)
            for case in cases:
                record = _run_case(case, variant, cfg, base_llm, run_agent_fn)
                if runs > 1:
                    record["run_index"] = run_index
                records.append(record)
                if out:
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    out.flush()
    return records


def _run_case(
    case: EvalCase,
    variant: str,
    cfg: AgentConfig,
    base_llm: LLMFn,
    run_agent_fn: Callable[..., str] | None = None,
) -> dict:
    agent_fn = run_agent_fn or _load_run_agent()
    tokens = [0, 0]

    def counting_llm(model: str, messages: list[dict], tools: list[dict]) -> object:
        resp = base_llm(model, messages, tools)
        tokens[0] += int(_get(resp, "prompt_eval_count") or 0)
        tokens[1] += int(_get(resp, "eval_count") or 0)
        return resp

    answer, error = "", None
    start = time.perf_counter()
    try:
        answer = agent_fn(case.question, cfg, llm=counting_llm)
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

    Quando houver mais de um registro para o mesmo `case_id`, devolve a média dos scores.
    Registro com erro é pontuado como resposta vazia (não some do cálculo nem é ignorado).
    Registros de casos fora do dataset levantam KeyError; casos sem registro ficam de fora.
    """
    by_id = {c.id: c for c in dataset}
    grouped: dict[str, list[float]] = {}
    for r in records:
        cid = r["case_id"]
        score = run_checks(by_id[cid], final_answer(r["answer"])).score
        grouped.setdefault(cid, []).append(score)
    return {cid: sum(xs) / len(xs) for cid, xs in grouped.items()}


def _group_records_by_run(records: list[dict]) -> dict[int, list[dict]]:
    """Agrupa registros por `run_index`, com fallback sequencial por `case_id` se ausente."""
    runs: dict[int, list[dict]] = {}
    seen_per_case: dict[str, int] = {}
    for rec in records:
        cid = rec["case_id"]
        seq = seen_per_case.get(cid, 0)
        seen_per_case[cid] = seq + 1
        raw_idx = rec.get("run_index")
        run_idx = seq if raw_idx is None else int(raw_idx)
        runs.setdefault(run_idx, []).append(rec)
    return dict(sorted(runs.items()))


def score_runs(dataset: list[EvalCase], records: list[dict]) -> list[dict[str, float]]:
    """Lista de `{case_id: score}` por execução, agrupada por `run_index` (ou sequencial)."""
    runs = _group_records_by_run(records)
    return [score_records(dataset, run_recs) for run_recs in runs.values()]


def summarize_runs(dataset: list[EvalCase], records: list[dict]) -> dict[str, Any]:
    """Resumo de variância e consistência entre execuções para os registros de uma variante."""
    by_id = {c.id: c for c in dataset}
    run_scores = score_runs(dataset, records)
    n_runs = len(run_scores)
    per_run_means = [statistics.fmean(scores.values()) for scores in run_scores if scores]
    mean = statistics.fmean(per_run_means) if per_run_means else 0.0
    run_stdev = statistics.stdev(per_run_means) if len(per_run_means) >= 2 else 0.0

    scores_by_case: dict[str, list[float]] = {}
    answers_by_case: dict[str, list[str]] = {}
    for r in records:
        cid = r["case_id"]
        fa = final_answer(r["answer"])
        score = run_checks(by_id[cid], fa).score
        scores_by_case.setdefault(cid, []).append(score)
        answers_by_case.setdefault(cid, []).append(fa)

    case_stdevs = [statistics.stdev(xs) for xs in scores_by_case.values() if len(xs) >= 2]
    mean_case_stdev = statistics.fmean(case_stdevs) if n_runs >= 2 and case_stdevs else 0.0
    n_cases = len(scores_by_case)
    exact_score_consistency_rate = (
        sum(1 for xs in scores_by_case.values() if len(set(xs)) == 1) / n_cases
        if n_cases
        else 0.0
    )
    exact_answer_consistency_rate = (
        sum(1 for ans in answers_by_case.values() if len(set(ans)) == 1) / n_cases
        if n_cases
        else 0.0
    )
    return {
        "n_runs": n_runs,
        "per_run_means": per_run_means,
        "mean": mean,
        "run_stdev": run_stdev,
        "mean_case_stdev": mean_case_stdev,
        "exact_score_consistency_rate": exact_score_consistency_rate,
        "exact_answer_consistency_rate": exact_answer_consistency_rate,
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
