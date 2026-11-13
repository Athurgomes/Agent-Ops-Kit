from pathlib import Path

import pytest

from agent_ops_kit.eval.checks import (
    cites_correct_source,
    contains_expected,
    refuses_when_unanswerable,
    run_checks,
    valid_format,
)
from agent_ops_kit.eval.dataset import load_dataset

DATASET = Path(__file__).resolve().parent.parent / "evals" / "dataset.jsonl"
CASES = {c.id: c for c in load_dataset(DATASET)}
ANSWERABLE = CASES["q004"]  # expected: 2 strings, source 02_reembolso_de_despesas.md
UNANSWERABLE = CASES["q041"]

GOOD = (
    "Bebidas alcoólicas e multas de trânsito não são reembolsáveis.\n"
    "Fonte: 02_reembolso_de_despesas.md"
)
REFUSAL = "Não encontrei essa informação nos documentos."


def test_contains_expected():
    assert contains_expected(ANSWERABLE, GOOD) is True
    assert contains_expected(ANSWERABLE, "Bebidas alcoólicas não são reembolsáveis.") is False


def test_contains_expected_normalizes_case_accents_spaces():
    answer = "BEBIDAS   ALCOOLICAS e\nmultas de  transito."
    assert contains_expected(ANSWERABLE, answer) is True


def test_contains_expected_not_applicable_when_unanswerable():
    assert contains_expected(UNANSWERABLE, REFUSAL) is None


def test_cites_correct_source():
    assert cites_correct_source(ANSWERABLE, GOOD) is True
    assert cites_correct_source(ANSWERABLE, "Resposta.\nFonte: 03_onboarding.md") is False
    assert cites_correct_source(ANSWERABLE, "Resposta sem fonte.") is False


def test_cites_correct_source_case_insensitive():
    assert cites_correct_source(ANSWERABLE, "x\nFONTE: 02_REEMBOLSO_DE_DESPESAS.MD") is True


def test_unanswerable_must_not_cite_corpus_file():
    assert cites_correct_source(UNANSWERABLE, REFUSAL) is True
    assert cites_correct_source(UNANSWERABLE, REFUSAL + "\nFonte: 07_beneficios.md") is False


def test_valid_format():
    assert valid_format(ANSWERABLE, GOOD) is True
    assert valid_format(ANSWERABLE, "Bebidas alcoólicas e multas de trânsito.") is False
    assert valid_format(ANSWERABLE, "fonte: 02_reembolso_de_despesas.md") is True
    assert valid_format(ANSWERABLE, "Fonte:") is False


@pytest.mark.parametrize("empty", ["", "  \n "])
def test_valid_format_rejects_empty(empty):
    assert valid_format(ANSWERABLE, empty) is False
    assert valid_format(UNANSWERABLE, empty) is False


def test_valid_format_unanswerable_needs_no_source_line():
    assert valid_format(UNANSWERABLE, REFUSAL) is True


def test_refuses_when_unanswerable():
    assert refuses_when_unanswerable(UNANSWERABLE, REFUSAL) is True
    assert refuses_when_unanswerable(UNANSWERABLE, "O bônus é de R$ 500.") is False


def test_refusal_tolerates_case_accents_and_line_breaks():
    assert refuses_when_unanswerable(UNANSWERABLE, "NAO ENCONTREI essa\ninformacao nos documentos") is True
    assert refuses_when_unanswerable(UNANSWERABLE, "Desculpe. " + REFUSAL) is True


def test_refuses_not_applicable_when_answerable():
    assert refuses_when_unanswerable(ANSWERABLE, GOOD) is None


def test_run_checks_perfect_answerable():
    r = run_checks(ANSWERABLE, GOOD)
    assert (r.contains_expected, r.cites_correct_source, r.valid_format) == (True, True, True)
    assert r.refuses_when_unanswerable is None
    assert r.score == 1.0


def test_run_checks_partial_score_ignores_not_applicable():
    # contém só 1 dos 2 esperados (falha), fonte certa e formato ok (passam): 2 de 3
    r = run_checks(ANSWERABLE, "Bebidas alcoólicas.\nFonte: 02_reembolso_de_despesas.md")
    assert r.contains_expected is False
    assert r.score == pytest.approx(2 / 3)


def test_run_checks_unanswerable():
    ok = run_checks(UNANSWERABLE, REFUSAL)
    assert ok.contains_expected is None
    assert ok.score == 1.0
    # inventa resposta com fonte: cita arquivo (falha), formato ok, não recusa (falha): 1 de 3
    bad = run_checks(UNANSWERABLE, "O bônus é R$ 500.\nFonte: 07_beneficios.md")
    assert bad.score == pytest.approx(1 / 3)


def test_run_checks_empty_answer_scores_low():
    r = run_checks(ANSWERABLE, "")
    assert r.score == 0.0


@pytest.mark.parametrize(
    ("expected", "answer"),
    [
        ("30 dias", "O prazo é de 130 dias."),
        ("80%", "O desconto é de 180%."),
        ("15 minutos", "Resposta em 115 minutos."),
        ("4 horas", "Prazo de 24 horas."),
    ],
)
def test_contains_expected_rejects_partial_number_match(expected, answer):
    case = ANSWERABLE.model_copy(update={"expected": [expected]})
    assert contains_expected(case, answer) is False


@pytest.mark.parametrize(
    ("expected", "answer"),
    [
        ("30 dias", "O prazo é de 30 dias."),
        ("80%", "O desconto é de 80%, sempre."),
        ("ENG-", "Use o prefixo ENG-1234 no ticket."),
        ("30 dias", "(30 dias)"),
    ],
)
def test_contains_expected_accepts_token_boundaries(expected, answer):
    case = ANSWERABLE.model_copy(update={"expected": [expected]})
    assert contains_expected(case, answer) is True


def test_real_dataset_expected_answers_pass_all_checks():
    for case in CASES.values():
        if case.answerable:
            answer = f"{'; '.join(case.expected)}.\nFonte: {case.sources[0]}"
        else:
            answer = REFUSAL
        assert run_checks(case, answer).score == 1.0, case.id
