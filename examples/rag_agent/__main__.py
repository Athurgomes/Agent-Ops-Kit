"""Uso: python -m examples.rag_agent "pergunta"."""

import sys

from agent_ops_kit.config import load_config
from agent_ops_kit.guardrails import Guardrails
from agent_ops_kit.tracing import setup_tracing

from .agent import CONFIG_PATH, run_agent


def main() -> int:
    if len(sys.argv) < 2:
        print('uso: python -m examples.rag_agent "pergunta"', file=sys.stderr)
        return 2
    config = load_config(CONFIG_PATH)
    provider = setup_tracing(config.name)
    try:
        guardrails = Guardrails(config) if config.guardrails else None
        print(run_agent(" ".join(sys.argv[1:]), config, guardrails=guardrails))
    finally:
        provider.force_flush()
        provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
