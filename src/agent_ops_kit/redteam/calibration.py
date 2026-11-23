"""Calibração e concordância do juiz de ataques contra rotulagem humana."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent_ops_kit.redteam import attack_judge
from agent_ops_kit.redteam.attack_judge import AttackJudgeLLM, AttackJudgeResult


class HumanLabeledCase(BaseModel):
    """Caso de red team rotulado manualmente por humano para calibração."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    agent_answer: str
    human_label: bool = Field(strict=True)
    tool_calls: list[str] = Field(default_factory=list)
    annotator: str | None = None
    notes: str | None = None

    @field_validator("case_id", "category", "description")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("campo de texto obrigatório não pode ser vazio")
        return value


class AttackJudgePrediction(BaseModel):
    """Registro gravável/carregável (JSONL) de predição do juiz de ataques."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    attack_succeeded: bool | None = Field(default=None, strict=True)
    reason: str = ""
    error: str | None = None
    model: str | None = None


def load_human_labels(path: str | Path) -> list[HumanLabeledCase]:
    """Lê e valida um JSONL de casos rotulados por humanos."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"arquivo de rótulos humanos não encontrado: {file_path}")

    cases: list[HumanLabeledCase] = []
    seen: set[str] = set()
    with open(file_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                case = HumanLabeledCase.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(f"{file_path}:{line_no}: rótulo humano inválido: {exc}") from exc
            if case.case_id in seen:
                raise ValueError(f"{file_path}:{line_no}: case_id duplicado: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)

    if not cases:
        raise ValueError(f"arquivo de rótulos humanos vazio (0 casos): {file_path}")
    return cases


def load_predictions(path: str | Path) -> list[AttackJudgePrediction]:
    """Lê e valida um JSONL de predições do juiz de ataques."""
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"arquivo de predições não encontrado: {file_path}")

    preds: list[AttackJudgePrediction] = []
    seen: set[str] = set()
    with open(file_path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                pred = AttackJudgePrediction.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as exc:
                raise ValueError(f"{file_path}:{line_no}: predição inválida: {exc}") from exc
            if pred.case_id in seen:
                raise ValueError(f"{file_path}:{line_no}: case_id duplicado: {pred.case_id}")
            seen.add(pred.case_id)
            preds.append(pred)

    if not preds:
        raise ValueError(f"arquivo de predições vazio (0 casos): {file_path}")
    return preds


def write_predictions(path: str | Path, predictions: Sequence[AttackJudgePrediction]) -> None:
    """Grava predições do juiz em JSONL (UTF-8)."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [pred.model_dump_json() for pred in predictions]
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def judge_labeled_cases(
    labels: Sequence[HumanLabeledCase],
    *,
    llm: AttackJudgeLLM | None = None,
    model: str | None = None,
    seed: int = attack_judge.DEFAULT_SEED,
) -> list[AttackJudgePrediction]:
    """Executa o juiz de ataques sobre uma amostra rotulada por humanos."""
    resolved_model = attack_judge.resolve_judge_model(model)
    call = llm or attack_judge.make_ollama_attack_judge_llm(resolved_model, seed=seed)
    preds: list[AttackJudgePrediction] = []
    for case in labels:
        res = attack_judge.judge_attack(
            case.category,
            case.description,
            case.agent_answer,
            tool_calls=case.tool_calls,
            llm=call,
            seed=seed,
        )
        preds.append(
            AttackJudgePrediction(
                case_id=case.case_id,
                attack_succeeded=res.attack_succeeded,
                reason=res.reason,
                error=res.error,
                model=resolved_model,
            )
        )
    return preds


def _coerce_prediction(
    case_id: str, item: AttackJudgeResult | AttackJudgePrediction | Mapping[str, object]
) -> AttackJudgePrediction:
    if isinstance(item, AttackJudgePrediction):
        return item
    if isinstance(item, AttackJudgeResult):
        return AttackJudgePrediction(
            case_id=case_id,
            attack_succeeded=item.attack_succeeded,
            reason=item.reason,
            error=item.error,
        )
    if isinstance(item, Mapping):
        payload = {"case_id": case_id, **dict(item)}
        return AttackJudgePrediction.model_validate(payload)
    raise TypeError(f"tipo de predição não suportado para {case_id}: {type(item).__name__}")


def _index_predictions(
    predictions: (
        Mapping[str, AttackJudgeResult | AttackJudgePrediction | Mapping[str, object]]
        | Sequence[AttackJudgePrediction | Mapping[str, object]]
    ),
) -> dict[str, AttackJudgePrediction]:
    if isinstance(predictions, Mapping):
        return {cid: _coerce_prediction(cid, item) for cid, item in predictions.items()}

    indexed: dict[str, AttackJudgePrediction] = {}
    for item in predictions:
        if isinstance(item, AttackJudgePrediction):
            pred = item
        elif isinstance(item, Mapping):
            pred = AttackJudgePrediction.model_validate(dict(item))
        else:
            raise TypeError(f"item de predição inválido: {type(item).__name__}")
        if pred.case_id in indexed:
            raise ValueError(f"predição duplicada para case_id: {pred.case_id}")
        indexed[pred.case_id] = pred
    return indexed


def _compute_metrics(pairs: list[tuple[bool, bool | None, str | None]]) -> dict[str, object]:
    n_total = len(pairs)
    valid = [(human, pred) for human, pred, err in pairs if err is None and pred is not None]
    n = len(valid)
    n_errors = n_total - n

    tp = sum(1 for h, p in valid if h and p)
    fp = sum(1 for h, p in valid if not h and p)
    tn = sum(1 for h, p in valid if not h and not p)
    fn = sum(1 for h, p in valid if h and not p)

    if n == 0:
        return {
            "n": 0,
            "n_total": n_total,
            "n_errors": n_errors,
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "cohen_kappa": None,
        }

    accuracy = (tp + tn) / n
    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    if precision is not None and recall is not None:
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    else:
        f1 = None

    po = accuracy
    pe = ((tp + fp) * (tp + fn) + (tn + fn) * (tn + fp)) / (n * n)
    if abs(1.0 - pe) <= 1e-12:
        cohen_kappa = 1.0 if abs(1.0 - po) <= 1e-12 else None
    else:
        cohen_kappa = (po - pe) / (1.0 - pe)

    return {
        "n": n,
        "n_total": n_total,
        "n_errors": n_errors,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "cohen_kappa": cohen_kappa,
    }


def compute_agreement(
    labels: Sequence[HumanLabeledCase],
    predictions: (
        Mapping[str, AttackJudgeResult | AttackJudgePrediction | Mapping[str, object]]
        | Sequence[AttackJudgePrediction | Mapping[str, object]]
    ),
) -> dict[str, object]:
    """Calcula concordância e matriz de confusão do juiz contra rótulos humanos."""
    if not labels:
        raise ValueError("nenhum caso rotulado informado para calibração")

    by_id = _index_predictions(predictions)
    all_pairs: list[tuple[bool, bool | None, str | None]] = []
    by_cat_pairs: dict[str, list[tuple[bool, bool | None, str | None]]] = {}

    for label in labels:
        if label.case_id not in by_id:
            raise ValueError(f"predição ausente para case_id: {label.case_id}")
        pred = by_id[label.case_id]
        entry = (label.human_label, pred.attack_succeeded, pred.error)
        all_pairs.append(entry)
        by_cat_pairs.setdefault(label.category, []).append(entry)

    overall = _compute_metrics(all_pairs)
    by_category = {cat: _compute_metrics(by_cat_pairs[cat]) for cat in sorted(by_cat_pairs)}
    return {**overall, "by_category": by_category}


def _fmt_float(value: object) -> str:
    return "n/d" if value is None else f"{float(value):.4f}"


def format_calibration_markdown(
    metrics: Mapping[str, object],
    *,
    model: str,
    seed: int,
    labels_path: str | Path,
) -> str:
    """Formata relatório Markdown em português da calibração do juiz de ataques."""
    lines = [
        "# Calibração do juiz de ataques",
        "",
        f"- Modelo do juiz: {model}",
        f"- Semente: {seed}",
        f"- Amostra rotulada: {Path(labels_path).as_posix()}",
        (
            f"- Casos na amostra: {metrics['n_total']} "
            f"(válidos: {metrics['n']}; erros do juiz: {metrics['n_errors']})"
        ),
        "",
        "## Métricas gerais",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| n (pares válidos) | {metrics['n']} |",
        f"| n_total | {metrics['n_total']} |",
        f"| n_errors (erros do juiz) | {metrics['n_errors']} |",
        f"| accuracy | {_fmt_float(metrics['accuracy'])} |",
        f"| cohen_kappa | {_fmt_float(metrics['cohen_kappa'])} |",
        f"| precision | {_fmt_float(metrics['precision'])} |",
        f"| recall | {_fmt_float(metrics['recall'])} |",
        f"| f1 | {_fmt_float(metrics['f1'])} |",
        (
            f"| Matriz (tp / fp / tn / fn) | "
            f"{metrics['tp']} / {metrics['fp']} / {metrics['tn']} / {metrics['fn']} |"
        ),
        "",
        "## Por categoria",
        "",
        "| Categoria | n | Erros | TP | FP | TN | FN | Accuracy | Kappa |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    by_cat = metrics.get("by_category", {})
    assert isinstance(by_cat, Mapping)
    for cat in sorted(by_cat):
        c = by_cat[cat]
        lines.append(
            f"| {cat} | {c['n']} | {c['n_errors']} | {c['tp']} | {c['fp']} | "
            f"{c['tn']} | {c['fn']} | {_fmt_float(c['accuracy'])} | "
            f"{_fmt_float(c['cohen_kappa'])} |"
        )
    lines += [
        "",
        "## Ressalvas",
        "",
        (
            "- O juiz local padrão (8B) pode ter baixa concordância em ataques sutis, "
            "indiretos ou específicos do domínio do agente; estes números valem apenas "
            "para a amostra rotulada acima."
        ),
        (
            "- Para testar um modelo local maior ou diferente via Ollama (sem custo "
            "obrigatório), informe `--judge-model` ou `AOK_JUDGE_MODEL`."
        ),
        (
            "- Casos com falha de JSON/schema do juiz (`n_errors`) são descartados do "
            "cálculo de concordância; nenhum veredito é inventado."
        ),
        (
            "- Em auditorias caixa-preta, o juiz e a rotulagem observam apenas entrada, "
            "saída e tool calls declaradas; use como complemento aos critérios determinísticos."
        ),
    ]
    return "\n".join(lines) + "\n"
