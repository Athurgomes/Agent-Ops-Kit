"""Tools do agente RAG de referência: search_docs, calculator, current_date."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from datetime import date

from agent_ops_kit.tracing import retrieval_query, set_results_count, tool_call

from .indexer import query_index

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
MAX_EXPR_CHARS = 200
MAX_EXPONENT = 100


def safe_eval(expression: str) -> float | int:
    """Avalia aritmética simples via ast. Qualquer outro nó levanta ValueError."""
    if len(expression) > MAX_EXPR_CHARS:
        raise ValueError("expressão muito longa")

    def ev(node: ast.AST) -> float | int:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
                raise ValueError("expoente grande demais")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        raise ValueError("expressão não permitida")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise ValueError("expressão inválida") from e
    return ev(tree)


def search_docs(query: str, k: int = 3) -> list[dict]:
    """Busca no índice e deduplica por source (mantém o chunk mais próximo)."""
    with retrieval_query(query) as span:
        seen: set[str] = set()
        results: list[dict] = []
        for hit in query_index(query, k=k):
            if hit["source"] in seen:
                continue
            seen.add(hit["source"])
            results.append({"text": hit["text"], "source": hit["source"]})
        set_results_count(span, len(results))
    return results


def calculator(expression: str) -> str:
    try:
        return str(safe_eval(expression))
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        return f"erro: {e}"


def current_date() -> str:
    return date.today().isoformat()


def _schema(name: str, description: str, params: dict[str, str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {p: {"type": "string", "description": d} for p, d in params.items()},
                "required": list(params),
            },
        },
    }


TOOL_SCHEMAS = {
    "search_docs": _schema(
        "search_docs",
        "Busca trechos nos documentos internos da empresa. Retorna texto e source.",
        {"query": "pergunta ou termos de busca"},
    ),
    "calculator": _schema(
        "calculator", "Calcula uma expressão aritmética.", {"expression": "ex.: 12 * (3 + 4)"}
    ),
    "current_date": _schema("current_date", "Retorna a data de hoje (AAAA-MM-DD).", {}),
}

TOOL_FUNCS: dict[str, Callable[..., object]] = {
    "search_docs": search_docs,
    "calculator": calculator,
    "current_date": current_date,
}


def run_tool(name: str, arguments: dict, k: int = 3) -> str:
    """Executa uma tool dentro do span tool.call. Erros viram texto para o LLM."""
    with tool_call(name) as span:
        func = TOOL_FUNCS.get(name)
        if func is None:
            span.set_attribute("error.type", "unknown_tool")
            return f"erro: tool desconhecida '{name}'"
        try:
            args = dict(arguments)
            if name == "search_docs":
                args.setdefault("k", k)
            result = func(**args)
        except TypeError as e:
            span.set_attribute("error.type", "bad_arguments")
            return f"erro: argumentos inválidos ({e})"
        if isinstance(result, list):
            if not result:
                return "nenhum resultado"
            return "\n\n".join(f"[fonte: {r['source']}]\n{r['text']}" for r in result)
        return str(result)
