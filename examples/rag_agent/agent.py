"""Loop simples de agente com tool calling nativo do Ollama."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from agent_ops_kit.config import AgentConfig, load_config
from agent_ops_kit.guardrails import REFUSAL_MESSAGE, Guardrails, canary_line
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


_SOURCE_HEADER = re.compile(r"^\[fonte: ([^\]\n]+)\]\n", re.MULTILINE)
TOOL_BLOCKED_MESSAGE = "Chamada bloqueada pela política de segurança. Não use esta ferramenta."


def _wrap_search_result(result: str, guardrails: Guardrails) -> str:
    """Marca cada documento do resultado de search_docs como conteúdo não confiável."""
    parts = _SOURCE_HEADER.split(result)  # [pré, fonte1, corpo1, fonte2, corpo2, ...]
    if len(parts) == 1:
        return guardrails.wrap_retrieved(result, "search_docs")
    wrapped = [parts[0]] if parts[0].strip() else []
    for source, body in zip(parts[1::2], parts[2::2]):
        wrapped.append(guardrails.wrap_retrieved(body.strip(), source))
    return "\n\n".join(wrapped)


def _system_prompt(config: AgentConfig, guardrails: Guardrails | None) -> str:
    """Prompt do sistema + addendum dos guardrails.

    Se o canary já está no prompt (caso do testbed do red team), a linha do canary do
    addendum é omitida para não duplicá-lo; a nota de conteúdo não confiável fica.
    """
    if guardrails is None:
        return config.system_prompt
    addendum = guardrails.system_prompt_addendum()
    if guardrails.canary and guardrails.canary in config.system_prompt:
        addendum = addendum.replace(canary_line(guardrails.canary), "").strip()
    if not addendum:
        return config.system_prompt
    return f"{config.system_prompt.rstrip()}\n\n{addendum}\n"


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
    guardrails: Guardrails | None = None,
    events: list[dict] | None = None,
) -> str:
    """Roda o agente. Com `guardrails`, cada bloqueio vira um dict em `events`
    ({"stage": "input"|"tool"|"output", "reasons": [...]}; no estágio "output" também
    "raw_answer", a resposta antes do filtro). Sem guardrails o comportamento é o original."""
    config = config or load_config(CONFIG_PATH)
    if tools is None:
        tools = [TOOL_SCHEMAS[t] for t in config.tools]
    k = int(config.retrieval.get("k", 3))
    messages: list[dict] = [
        {"role": "system", "content": _system_prompt(config, guardrails)},
        {"role": "user", "content": question},
    ]
    with agent_run(config.name, prompt_version=config.prompt_version):
        if guardrails is None:
            return _loop(messages, tools, k, config, llm, max_iterations, tool_runner)
        if events is None:
            events = []
        verdict = guardrails.screen_input(question)
        if verdict.blocked:
            events.append({"stage": "input", "reasons": list(verdict.reasons)})
            return REFUSAL_MESSAGE
        answer = _loop(
            messages, tools, k, config, llm, max_iterations, tool_runner, guardrails, events
        )
        verdict = guardrails.screen_output(answer)
        if verdict.blocked:
            events.append(
                {"stage": "output", "reasons": list(verdict.reasons), "raw_answer": answer}
            )
            return REFUSAL_MESSAGE
        return answer


def _loop(
    messages: list[dict],
    tools: list[dict],
    k: int,
    config: AgentConfig,
    llm: LLMFn,
    max_iterations: int,
    tool_runner: ToolRunner = run_tool,
    guardrails: Guardrails | None = None,
    events: list[dict] | None = None,
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
            args = dict(_get(fn, "arguments") or {})
            if guardrails is not None:
                verdict = guardrails.allow_tool(name, args)
                if verdict.blocked:
                    if events is not None:
                        events.append(
                            {"stage": "tool", "reasons": list(verdict.reasons), "tool": name}
                        )
                    messages.append(
                        {"role": "tool", "tool_name": name, "content": TOOL_BLOCKED_MESSAGE}
                    )
                    continue
            result = tool_runner(name, args, k=k)
            if guardrails is not None and name == "search_docs":
                result = _wrap_search_result(result, guardrails)
            messages.append({"role": "tool", "tool_name": name, "content": result})
    return LIMIT_MESSAGE
