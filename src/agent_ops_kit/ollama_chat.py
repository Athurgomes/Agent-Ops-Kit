"""Chamada ao Ollama com limite de geração e timeout por chamada (ADR-028).

Sem limite, um modelo em laço de repetição gera milhares de tokens e trava a execução.
`NUM_PREDICT` é generoso (as respostas dos agentes de teste têm centenas de tokens); estourar
o limite ou o tempo levanta erro, que o eval, o red team e os falsos positivos registram como
`error` do caso e seguem. Execuções gravadas antes deste módulo não tinham limite algum.
"""

from __future__ import annotations

NUM_PREDICT = 2048  # tokens gerados por chamada
TIMEOUT_S = 180.0  # segundos por chamada (não acumula entre as chamadas de um caso)


class GenerationLimitError(RuntimeError):
    """A geração parou no limite de tokens (resposta truncada)."""


def limits() -> dict:
    """Limites em vigor, para registrar na proveniência das execuções novas."""
    return {"num_predict": NUM_PREDICT, "timeout_s": TIMEOUT_S}


def chat(model: str, messages: list[dict], tools: list[dict] | None = None,
         options: dict | None = None, **kwargs: object) -> object:
    """`ollama.chat` com `num_predict` e timeout. Estouro levanta TimeoutError ou GenerationLimitError."""
    import httpx
    import ollama

    opts = {**(options or {}), "num_predict": NUM_PREDICT}
    try:
        resp = ollama.Client(timeout=TIMEOUT_S).chat(
            model=model, messages=messages, tools=tools, options=opts, **kwargs
        )
    except httpx.TimeoutException:
        raise TimeoutError(f"chamada ao Ollama excedeu {TIMEOUT_S:g} s") from None
    reason = resp.get("done_reason") if isinstance(resp, dict) else getattr(resp, "done_reason", None)
    if reason == "length":
        raise GenerationLimitError(f"geração truncada no limite de {NUM_PREDICT} tokens")
    return resp
