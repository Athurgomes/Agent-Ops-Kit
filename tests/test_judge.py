import json
from pathlib import Path

import pytest

from agent_ops_kit.eval.checks import REFUSAL_PHRASE
from agent_ops_kit.eval.dataset import EvalCase
from agent_ops_kit.eval.judge import JudgeError, judge_case, judge_records

CORPUS = Path(__file__).resolve().parent.parent / "examples" / "rag_agent" / "corpus"
ANSWERABLE = EvalCase(
    id="q001",
    question="Qual portal devo usar para solicitar férias?",
    answerable=True,
    expected=["Pessoas+"],
    sources=["01_politica_de_ferias.md"],
    category="factual",
)
UNANSWERABLE = EvalCase(
    id="q900",
    question="Qual é a cor do carro do CEO?",
    answerable=False,
    expected=[],
    sources=[],
    category="unanswerable",
)


def _out(f=5, r=4, c=3, j="ok"):
    return json.dumps({"fidelidade": f, "relevancia": r, "completude": c, "justificativa": j})


class FakeLLM:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls: list[list[dict]] = []

    def __call__(self, messages):
        self.calls.append(messages)
        return self.outputs.pop(0)


def test_parse_valido_e_score_media():
    r = judge_case(ANSWERABLE, "Use o Pessoas+.", FakeLLM(_out(5, 4, 3, "Boa.")), CORPUS)
    assert (r.fidelidade, r.relevancia, r.completude) == (5, 4, 3)
    assert r.justificativa == "Boa."
    assert r.error is None
    assert r.score == pytest.approx(4.0)


def test_score_media_nao_arredondada():
    r = judge_case(ANSWERABLE, "x", FakeLLM(_out(5, 5, 4)), CORPUS)
    assert r.score == pytest.approx(14 / 3)


def test_retry_uma_vez_e_sucesso():
    llm = FakeLLM("isto não é json", _out())
    r = judge_case(ANSWERABLE, "x", llm, CORPUS)
    assert len(llm.calls) == 2 and r.score is not None


def test_json_invalido_duas_vezes_levanta_erro():
    llm = FakeLLM("lixo", "{quebrado")
    with pytest.raises(JudgeError):
        judge_case(ANSWERABLE, "x", llm, CORPUS)
    assert len(llm.calls) == 2


@pytest.mark.parametrize("bad", [0, 6, -1, "4", 4.5, True])
def test_nota_invalida_e_rejeitada(bad):
    payload = json.dumps(
        {"fidelidade": bad, "relevancia": 3, "completude": 3, "justificativa": "x"}
    )
    llm = FakeLLM(payload, payload)
    with pytest.raises(JudgeError):
        judge_case(ANSWERABLE, "x", llm, CORPUS)


def test_campo_ausente_e_json_nao_objeto_rejeitados():
    with pytest.raises(JudgeError):
        judge_case(ANSWERABLE, "x", FakeLLM('{"fidelidade": 5}', "[1, 2, 3]"), CORPUS)


def test_prompt_tem_rubrica_contexto_e_expected():
    llm = FakeLLM(_out())
    judge_case(ANSWERABLE, "Use o Pessoas+.", llm, CORPUS)
    system, user = llm.calls[0][0]["content"], llm.calls[0][1]["content"]
    for termo in ("fidelidade", "relevancia", "completude", "1 a 5"):
        assert termo in system
    assert ANSWERABLE.question in user
    assert "Pessoas+" in user  # expected
    corpus_text = (CORPUS / "01_politica_de_ferias.md").read_text(encoding="utf-8").strip()
    assert corpus_text in user  # contexto lido do corpus
    assert "Use o Pessoas+." in user


def test_nao_respondivel_instrui_recusa():
    llm = FakeLLM(_out())
    judge_case(UNANSWERABLE, REFUSAL_PHRASE, llm, CORPUS)
    system, user = llm.calls[0][0]["content"], llm.calls[0][1]["content"]
    assert "recusar" in user and REFUSAL_PHRASE in user
    assert "(nenhum)" in user
    assert "FATOS ESPERADOS" not in user
    assert "recusar" in system or "Recusa" in system


def test_judge_records_usa_final_answer_e_isola_erros():
    records = [
        {"case_id": "q001", "answer": "Raciocínio: x\nResposta: Use o Pessoas+."},
        {"case_id": "q900", "answer": REFUSAL_PHRASE},
    ]
    llm = FakeLLM(_out(5, 5, 5), "lixo", "lixo")
    res = judge_records([ANSWERABLE, UNANSWERABLE], records, llm, CORPUS)
    assert res["q001"].score == pytest.approx(5.0)
    assert res["q900"].error is not None and res["q900"].score is None
    user = llm.calls[0][1]["content"]
    assert "Use o Pessoas+." in user and "Raciocínio" not in user
