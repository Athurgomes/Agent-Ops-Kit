"""Limite de geração e timeout das chamadas ao Ollama (sem modelo: cliente falso)."""

from typing import ClassVar

import httpx
import pytest

ollama = pytest.importorskip("ollama")  # extra rag; sem ele o módulo inteiro é pulado

from agent_ops_kit import ollama_chat, provenance
from agent_ops_kit.eval import runner
from agent_ops_kit.redteam import harness


class FakeClient:
    seen: ClassVar[dict] = {}
    reply: ClassVar[object] = {"message": {"content": "ok"}, "done_reason": "stop"}

    def __init__(self, *a, **kw):
        FakeClient.seen = {"timeout": kw.get("timeout")}

    def chat(self, **kw):
        FakeClient.seen.update(kw)
        if isinstance(FakeClient.reply, Exception):
            raise FakeClient.reply
        return FakeClient.reply


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(ollama, "Client", FakeClient)
    FakeClient.reply = {"message": {"content": "ok"}, "done_reason": "stop"}
    return FakeClient


@pytest.mark.parametrize("factory", [runner.make_ollama_llm, harness.make_seeded_llm])
def test_llm_sends_limit_timeout_and_keeps_seed(fake, factory):
    resp = factory(7)("m", [{"role": "user", "content": "x"}], [])
    assert resp["message"]["content"] == "ok"
    assert fake.seen["timeout"] == ollama_chat.TIMEOUT_S
    assert fake.seen["options"] == {"temperature": 0, "seed": 7, "num_predict": ollama_chat.NUM_PREDICT}


def test_truncated_generation_is_an_error(fake):
    fake.reply = {"message": {"content": "aaa"}, "done_reason": "length"}
    with pytest.raises(ollama_chat.GenerationLimitError):
        runner.make_ollama_llm()("m", [], [])


def test_timeout_becomes_timeout_error(fake):
    fake.reply = httpx.ReadTimeout("x")
    with pytest.raises(TimeoutError, match="excedeu"):
        runner.make_ollama_llm()("m", [], [])


def test_limit_error_is_recorded_as_case_error_and_run_goes_on(fake):
    def llm(model, messages, tools):
        raise ollama_chat.GenerationLimitError("truncada")

    from agent_ops_kit.config import load_config
    from agent_ops_kit.redteam.attacks import AttackCase
    from examples.rag_agent.agent import CONFIG_PATH

    case = AttackCase.model_validate({
        "id": "x-1", "category": "injecao_direta", "owasp_id": "LLM01", "description": "d",
        "user_input": "oi", "success": {"type": "canary_in_output"},
    })
    rec = harness.run_attack(case, load_config(CONFIG_PATH), llm=llm)
    assert rec.error and "GenerationLimitError" in rec.error and rec.success is False


def test_execution_info_records_generation_limits():
    info = provenance.execution_info("m", "x", fetch=lambda p: {})
    assert info["generation_limits"] == {
        "num_predict": ollama_chat.NUM_PREDICT, "timeout_s": ollama_chat.TIMEOUT_S,
    }
