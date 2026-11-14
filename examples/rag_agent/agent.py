"""Loop simples de agente com tool calling nativo do Ollama."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_ops_kit.config import AgentConfig, load_config
from agent_ops_kit.tracing import agent_run, llm_call, set_tokens

from .tools import TOOL_SCHEMAS, run_tool

CONFIG_PATH = Path(__file__).parent / "agent.yaml"
MAX_ITERATIONS = 5
LIMIT_MESSAGE = "Não consegui concluir a resposta dentro do limite de iterações."

# llm(model, messages, tools) -> resposta no formato do ollama.chat (dict ou objeto subscritável)
LLMFn = Callable[[str, list[dict], list[dict]], object]
# tool_runner(name, arguments, k) -> texto do resultado (padrão: run_tool)
ToolRunner = Callable[[str, dict, int], str]


def ollama_llm(model: str, messages: list[dict], tools: list[dict]) -> object:
    import ollama

    return ollama.chat(model=model, messages=messages, tools=tools, options={"temperature": 0})


def _get(obj: object, key: str, default: object = None) -> object:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def run_agent(
    question: str,
    config: AgentConfig | None = None,
    llm: LLMFn = ollama_llm,
    max_iterations: int = MAX_ITERATIONS,
    tools: list[dict] | None = None,
    tool_runner: ToolRunner = run_tool,
) -> str:
    config = config or load_config(CONFIG_PATH)
    if tools is None:
        tools = [TOOL_SCHEMAS[t] for t in config.tools]
    k = int(config.retrieval.get("k", 3))
    messages: list[dict] = [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": question},
    ]
    with agent_run(config.name, prompt_version=config.prompt_version):
        return _loop(messages, tools, k, config, llm, max_iterations, tool_runner)


def _loop(
    messages: list[dict],
    tools: list[dict],
    k: int,
    config: AgentConfig,
    llm: LLMFn,
    max_iterations: int,
    tool_runner: ToolRunner = run_tool,
) -> str:
    for _ in range(max_iterations):
        with llm_call(config.model, prompt_version=config.prompt_version) as span:
            resp = llm(config.model, messages, tools)
            set_tokens(
                span,
                int(_get(resp, "prompt_eval_count", 0) or 0),
                int(_get(resp, "eval_count", 0) or 0),
            )
        msg = _get(resp, "message")
        content = _get(msg, "content", "") or ""
        calls = _get(msg, "tool_calls") or []
        if not calls:
            return content
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "function": {
                            "name": _get(_get(c, "function"), "name"),
                            "arguments": dict(_get(_get(c, "function"), "arguments") or {}),
                        }
                    }
                    for c in calls
                ],
            }
        )
        for c in calls:
            fn = _get(c, "function")
            name = str(_get(fn, "name"))
            result = tool_runner(name, dict(_get(fn, "arguments") or {}), k=k)
            messages.append({"role": "tool", "tool_name": name, "content": result})
    return LIMIT_MESSAGE
