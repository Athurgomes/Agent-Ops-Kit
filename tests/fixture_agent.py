"""Agente-fixture mínimo (contrato do target python). O texto da pergunta escolhe o comportamento.

Os testes copiam este arquivo para uma pasta temporária e a usam como raiz do projeto.
"""

NOT_CALLABLE = 3


def agent(request):
    q = request["question"]
    if q == "boom":
        raise RuntimeError("falha do agente")
    if q == "no_answer":
        return {"tool_calls": []}
    if q == "bad_type":
        return {"answer": 123}
    if q == "bad_calls":
        return {"answer": "x", "tool_calls": [{"name": "send_email"}]}
    if q == "not_dict":
        return "texto solto"
    if q == "calls":
        return {
            "answer": "enviei",
            "tool_calls": [{"name": "send_email", "arguments": {"to": "a@b.c"}}],
            "trace_id": "abc123",
        }
    if q == "empty_calls":
        return {"answer": "não fiz nada", "tool_calls": []}
    if q == "ctx":
        return {"answer": f"contexto={request['context']}"}
    return {"answer": f"eco: {q}"}  # sem tool_calls declarados


def agent_llm(request, llm=None):
    resp = llm("fixture-model", [{"role": "user", "content": request["question"]}], [])
    return {"answer": resp["message"]["content"]}
