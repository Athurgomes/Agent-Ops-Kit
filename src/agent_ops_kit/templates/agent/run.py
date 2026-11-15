"""Uso: python run.py "pergunta".

Tracing, auditoria e guardrails vêm do agent.yaml. O corpus é indexado na 1ª execução
(Chroma local em chroma/, embeddings via Ollama). Para desligar o tracing: AOK_TRACING=off.
"""

import os
import sys
from pathlib import Path

from agent_ops_kit.audit import AuditLog
from agent_ops_kit.config import load_config
from agent_ops_kit.guardrails import Guardrails
from agent_ops_kit.tracing import setup_tracing

from app.agent import CONFIG_PATH, ollama_llm, run_agent
from app.indexer import PERSIST_DIR, build_index

ROOT = Path(__file__).resolve().parent


def ask(question: str, llm=ollama_llm) -> str:
    """Roda uma pergunta com os guardrails e a auditoria definidos no agent.yaml."""
    config = load_config(CONFIG_PATH)
    if not PERSIST_DIR.exists():
        print(f"Indexando o corpus: {build_index()} trechos.", file=sys.stderr)
    guardrails = Guardrails(config) if config.guardrails else None
    audit = AuditLog(ROOT / config.audit) if config.audit else None
    return run_agent(question, config, llm, guardrails=guardrails, audit=audit)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print('uso: python run.py "pergunta"', file=sys.stderr)
        return 2
    tracing_on = os.environ.get("AOK_TRACING", "on").lower() not in ("off", "0", "false")
    provider = setup_tracing(load_config(CONFIG_PATH).name) if tracing_on else None
    try:
        print(ask(" ".join(argv)))
    finally:
        if provider is not None:
            provider.force_flush()
            provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
