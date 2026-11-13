import json
import re
from pathlib import Path

import pytest

from agent_ops_kit.eval.dataset import load_dataset

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "evals" / "dataset.jsonl"
CORPUS = ROOT / "examples" / "rag_agent" / "corpus"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _write(tmp_path, rows):
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return p


def _ok(id="q001"):
    return {"id": id, "question": "Pergunta?", "answerable": True,
            "expected": ["x"], "sources": ["a.md"], "category": "factual"}


def _unanswerable(id="q002"):
    return {"id": id, "question": "Fora?", "answerable": False,
            "expected": [], "sources": [], "category": "fora_do_corpus"}


def test_loader_accepts_valid_cases(tmp_path):
    cases = load_dataset(_write(tmp_path, [_ok(), _unanswerable()]))
    assert [c.id for c in cases] == ["q001", "q002"]


def test_loader_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicado"):
        load_dataset(_write(tmp_path, [_ok(), _ok()]))


@pytest.mark.parametrize("field", ["expected", "sources"])
def test_loader_rejects_answerable_with_empty_field(tmp_path, field):
    row = _ok()
    row[field] = []
    with pytest.raises(ValueError, match="inválido"):
        load_dataset(_write(tmp_path, [row]))


@pytest.mark.parametrize("field,value", [("expected", ["x"]), ("sources", ["a.md"])])
def test_loader_rejects_unanswerable_with_content(tmp_path, field, value):
    row = _unanswerable()
    row[field] = value
    with pytest.raises(ValueError, match="inválido"):
        load_dataset(_write(tmp_path, [row]))


def test_loader_rejects_missing_field_and_bad_json(tmp_path):
    row = _ok()
    del row["question"]
    with pytest.raises(ValueError, match="inválido"):
        load_dataset(_write(tmp_path, [row]))
    p = tmp_path / "bad.jsonl"
    p.write_text("{nao eh json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="inválido"):
        load_dataset(p)


def test_real_dataset_integrity():
    cases = load_dataset(DATASET)
    assert 40 <= len(cases) <= 60
    assert len({c.id for c in cases}) == len(cases)
    for c in cases:
        texts = []
        for name in c.sources:
            path = CORPUS / name
            assert path.is_file(), f"{c.id}: fonte inexistente {name}"
            texts.append(_norm(path.read_text(encoding="utf-8")))
        for exp in c.expected:
            assert any(_norm(exp) in t for t in texts), f"{c.id}: '{exp}' não está nas fontes"
