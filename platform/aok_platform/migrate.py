"""Runner e CLI de migrações Alembic da plataforma."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: str | None = None) -> Config:
    """Cria objeto Alembic Config apontando para `aok_platform/migrations`, independente do cwd."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    resolved = url or os.environ.get("AOK_DATABASE_URL")
    if resolved:
        cfg.attributes["url"] = resolved
        cfg.set_main_option("sqlalchemy.url", resolved.replace("%", "%%"))
    return cfg


def run_migrations(engine: Engine, revision: str = "head") -> None:
    """Executa `alembic upgrade` sobre a conexão do `engine`; idempotente se já estiver em `head`."""
    cfg = alembic_config()
    with engine.connect() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def main(argv: list[str] | None = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--url",
        default=argparse.SUPPRESS,
        help="URL do banco (padrão: AOK_DATABASE_URL ou SQLite local)",
    )

    parser = argparse.ArgumentParser(
        prog="python -m aok_platform.migrate",
        description="Gerencia migrações Alembic da plataforma agent-ops-kit.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("upgrade", parents=[common], help="Aplica migrações pendentes até a revisão.")
    up.add_argument("revision", nargs="?", default="head", help="Revisão alvo (padrão: head)")

    sub.add_parser("current", parents=[common], help="Mostra a revisão aplicada no banco.")
    sub.add_parser("heads", parents=[common], help="Mostra as cabeças disponíveis nas migrações.")

    args = parser.parse_args(argv)
    from .db import DEFAULT_URL, make_engine

    url = getattr(args, "url", None) or os.environ.get("AOK_DATABASE_URL") or DEFAULT_URL

    if args.command == "heads":
        command.heads(alembic_config())
        return 0

    engine = make_engine(url)
    try:
        if args.command == "upgrade":
            run_migrations(engine, revision=args.revision)
        elif args.command == "current":
            cfg = alembic_config(url)
            with engine.connect() as connection:
                cfg.attributes["connection"] = connection
                command.current(cfg)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
