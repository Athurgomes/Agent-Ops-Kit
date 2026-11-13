from pathlib import Path

import pytest

from agent_ops_kit.eval.checks import REFUSAL_PHRASE
from agent_ops_kit.eval.dataset import load_dataset
from agent_ops_kit.eval.prompts import load_prompt

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "evals" / "prompts"


@pytest.mark.parametrize("name", ["v1", "v2"])
def test_variantes_mantem_formato_e_recusa(name):
    text = load_prompt(name, PROMPTS)
    assert "Fonte:" in text
    assert " ".join(REFUSAL_PHRASE.rstrip(".").split()) in " ".join(text.split())


def test_v2_tem_few_shot_e_raciocinio():
    v1, v2 = load_prompt("v1", PROMPTS), load_prompt("v2", PROMPTS)
    assert v1 != v2
    assert "Exemplo 1" in v2 and "Exemplo 2" in v2 and "Raciocínio:" in v2
    assert "Exemplo" not in v1


def test_v2_nao_vaza_respostas_do_dataset():
    cases = load_dataset(ROOT / "evals" / "dataset.jsonl")
    exemplos = load_prompt("v2", PROMPTS).split("Exemplo 1", 1)[1].casefold()
    for c in cases:
        for e in c.expected:
            assert e.casefold() not in exemplos, (c.id, e)
        for s in c.sources:
            assert s.casefold() not in exemplos, (c.id, s)
        assert c.question.casefold() not in exemplos


def test_variante_inexistente_ou_nome_invalido():
    with pytest.raises(FileNotFoundError):
        load_prompt("v99", PROMPTS)
    with pytest.raises(ValueError):
        load_prompt("../x", PROMPTS)


def test_diretorio_padrao_relativo_ao_repo(monkeypatch):
    monkeypatch.chdir(ROOT)
    assert load_prompt("v1") == load_prompt("v1", PROMPTS)
