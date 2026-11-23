"""Agente a auditar: resolve `target` do agent.yaml e aplica o contrato de entrada e saída.

Sem `target`, vale o agente de exemplo (examples.rag_agent). Com `target: {type: python,
ref: "pacote.modulo:funcao"}`, a função é importada e chamada como `fn(request)` (ou
`fn(request, llm=...)` se ela tiver o parâmetro `llm`, e então os tokens são contados).

Contrato (o mesmo que servirá ao HTTP depois):
  entrada: {"question": str, "context": str | None, "tools": list | None}
  saída:   {"answer": str, "tool_calls": [{"name": str, "arguments": dict}] (opcional),
            "trace_id": str | None (opcional)}

SEGURANÇA: `mod:fn` importa e EXECUTA código do projeto. Só módulos dentro da raiz do projeto
são importados; mesmo assim, não rode target python vindo de PR de fork no CI.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import inspect
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from agent_ops_kit.config import REF_PATTERN, AgentConfig, sanitize_url

EXAMPLE_REF = "examples.rag_agent.agent:run_agent"


class TargetError(ValueError):
    """`ref` inválido, fora do projeto ou não chamável (mensagem em português)."""


class ContractError(ValueError):
    """Resposta do agente fora do contrato (vira o `error` do caso)."""


def validate_response(raw: object) -> dict:
    """Valida a saída do agente e a devolve normalizada; fora do contrato levanta ContractError."""
    if not isinstance(raw, dict):
        raise ContractError(f"resposta deve ser um dict, veio {type(raw).__name__}")
    answer = raw.get("answer")
    if not isinstance(answer, str):
        raise ContractError("campo 'answer' ausente ou não é str")
    calls = raw.get("tool_calls")
    if calls is not None:
        if not isinstance(calls, list):
            raise ContractError("campo 'tool_calls' deve ser uma lista")
        for c in calls:
            if not isinstance(c, dict) or not isinstance(c.get("name"), str):
                raise ContractError("cada tool_call precisa de 'name' (str)")
            if not isinstance(c.get("arguments"), dict):
                raise ContractError("cada tool_call precisa de 'arguments' (dict)")
    trace_id = raw.get("trace_id")
    if trace_id is not None and not isinstance(trace_id, str):
        raise ContractError("campo 'trace_id' deve ser str ou null")
    return {"answer": answer, "tool_calls": calls, "trace_id": trace_id}


@dataclass(frozen=True)
class Target:
    type: str
    ref: str
    is_example: bool
    fn: Callable
    accepts_llm: bool

    def call(
        self,
        question: str,
        cfg: AgentConfig | None = None,
        *,
        context: str | None = None,
        tools: list[dict] | None = None,
        llm: Callable | None = None,
        **example_kwargs: object,
    ) -> dict:
        """Chama o agente e devolve a resposta validada. `example_kwargs` (tools, guardrails,
        events...) só valem para o agente de exemplo. Exceções do agente propagam."""
        if self.is_example:
            kwargs = dict(example_kwargs)
            if llm is not None:
                kwargs["llm"] = llm
            if tools is not None:
                kwargs["tools"] = tools
            return {"answer": self.fn(question, cfg, **kwargs), "tool_calls": None, "trace_id": None}
        request = {"question": question, "context": context, "tools": tools}
        if self.accepts_llm and llm is not None:
            return validate_response(self.fn(request, llm=llm))
        return validate_response(self.fn(request))


def _example_fn() -> Callable:
    try:
        from examples.rag_agent.agent import run_agent
    except ImportError as exc:
        raise ImportError(
            "agente de referência (examples.rag_agent) indisponível; "
            "execute a partir da raiz do repositório"
        ) from exc
    return run_agent


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return False
    return True


def _load_python_ref(ref: str, root: Path) -> Callable:
    if not REF_PATTERN.match(ref):
        raise TargetError(f"target.ref inválido: {ref!r}; use 'pacote.modulo:funcao'")
    mod_name, attr = ref.split(":")
    top = mod_name.split(".")[0]
    spec = importlib.machinery.PathFinder.find_spec(top, [str(root)])  # não executa nada
    if spec is None:
        raise TargetError(f"módulo {top!r} não encontrado dentro da raiz do projeto ({root})")
    locations = [spec.origin] if spec.origin else list(spec.submodule_search_locations or [])
    if not locations or not all(_inside(Path(p), root) for p in locations):
        raise TargetError(f"target.ref {ref!r} resolve para fora da raiz do projeto")
    loaded = sys.modules.get(top)
    loaded_file = getattr(loaded, "__file__", None)
    if loaded is not None and loaded_file and not _inside(Path(loaded_file), root):
        raise TargetError(f"módulo {top!r} já carregado de fora da raiz do projeto")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        module = importlib.import_module(mod_name)
    except ImportError as exc:
        raise TargetError(f"não foi possível importar {mod_name!r}: {exc}") from exc
    mod_file = getattr(module, "__file__", None)
    if not mod_file or not _inside(Path(mod_file), root):
        raise TargetError(f"target.ref {ref!r} resolve para fora da raiz do projeto")
    fn = getattr(module, attr, None)
    if not callable(fn):
        raise TargetError(f"{ref!r}: {attr!r} não existe ou não é chamável")
    return fn


def resolve_target(cfg: AgentConfig, root: str | Path | None = None) -> Target:
    """Agente a auditar. Sem `cfg.target`: o exemplo. `root` = raiz do projeto (padrão: cwd)."""
    if cfg.target is None:
        return Target("python", EXAMPLE_REF, True, _example_fn(), True)
    if cfg.target.type == "http":
        from agent_ops_kit.target_http import make_http_caller

        return Target(
            "http", sanitize_url(cfg.target.url or ""), False, make_http_caller(cfg.target), False
        )
    fn = _load_python_ref(cfg.target.ref or "", Path(root or Path.cwd()).resolve())
    try:
        accepts_llm = "llm" in inspect.signature(fn).parameters
    except (ValueError, TypeError):
        accepts_llm = False
    return Target(cfg.target.type, cfg.target.ref or "", False, fn, accepts_llm)
