"""Testes unitários dos agentes externos de validação (sem Ollama)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from agent_ops_kit.config import load_config
from agent_ops_kit.eval.dataset import load_dataset
from examples.validation_agents import finance_python_agent, support_http_agent


def test_load_validation_configs_and_dataset() -> None:
    http_cfg = load_config("examples/validation_agents/support_http_agent.yaml")
    assert http_cfg.target is not None
    assert http_cfg.target.type == "http"
    assert http_cfg.target.auth_env == "VALIDATION_AGENT_TOKEN"
    assert http_cfg.profile is not None
    assert http_cfg.profile.declared_tools == ["lookup_order"]

    py_cfg = load_config("examples/validation_agents/finance_python_agent.yaml")
    assert py_cfg.target is not None
    assert py_cfg.target.type == "python"
    assert py_cfg.target.ref == "examples.validation_agents.finance_python_agent:run"
    assert py_cfg.profile is not None
    assert py_cfg.profile.forbidden_actions == []
    assert py_cfg.profile.declared_tools == []

    cases = load_dataset("examples/validation_agents/support_dataset.jsonl")
    assert len(cases) == 6
    assert sum(c.answerable for c in cases) == 4
    assert sum(not c.answerable for c in cases) == 2
    assert all(c.sources == [] for c in cases)


def test_support_http_agent_handle_chat_with_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    def fake_chat(**kwargs: object) -> dict:
        calls.append(kwargs)
        if len(calls) == 1:
            return {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "lookup_order",
                                "arguments": {"order_id": "1042"},
                            }
                        }
                    ],
                }
            }
        return {"message": {"content": "Pedido 1042 em trânsito atrasado, prioridade alta."}}

    monkeypatch.setattr(support_http_agent.ollama, "chat", fake_chat)

    reply, actions = support_http_agent.handle_chat("Qual o status do pedido 1042?")
    assert "1042" in reply
    assert "alta" in reply
    assert actions == [{"name": "lookup_order", "arguments": {"order_id": "1042"}}]
    assert len(calls) == 2


def test_support_http_server_auth_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        support_http_agent.ollama,
        "chat",
        lambda **kwargs: {"message": {"content": "Prazo de troca de 7 dias corridos."}},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), support_http_agent.make_handler("secret-tok"))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        bad_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/chat",
            data=json.dumps({"mensagem": "oi"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(bad_req, timeout=5)
        assert exc_info.value.code == 401

        ok_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/chat",
            data=json.dumps({"mensagem": "Como funciona a troca?"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer secret-tok"},
            method="POST",
        )
        with urllib.request.urlopen(ok_req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        assert payload["data"]["reply"] == "Prazo de troca de 7 dias corridos."
        assert payload["data"]["actions"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_support_http_main_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(support_http_agent.TOKEN_ENV_VAR, raising=False)
    assert support_http_agent.main([]) == 2


def test_finance_python_agent_run_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_chat(**kwargs: object) -> dict:
        captured.append(kwargs)
        return {
            "message": {
                "content": "Despesa classificada em viagem; exige nota fiscal com CNPJ."
            }
        }

    monkeypatch.setattr(finance_python_agent.ollama, "chat", fake_chat)

    out = finance_python_agent.run(
        {"question": "Como classificar um gasto com passagem aérea?", "context": None, "tools": None}
    )
    assert "viagem" in out["answer"]
    assert out["tool_calls"] == []
    assert isinstance(out["trace_id"], str) and out["trace_id"].startswith("fin-")
    assert captured[0]["model"] == "llama3.1:8b"

    with pytest.raises(TypeError, match="question"):
        finance_python_agent.run({})
