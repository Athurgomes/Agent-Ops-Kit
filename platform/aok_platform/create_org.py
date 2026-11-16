"""Cria uma organização: `python -m aok_platform.create_org --slug acme --name "Acme"`.

Solução provisória até existir o papel de operador da plataforma (a rota/tela virá depois). Usa o
banco de AOK_DATABASE_URL (SQLite local se vazio). Não cria usuários: faça isso com a chave de
bootstrap e o cabeçalho X-Org-Slug (ver platform/README.md).
"""

from __future__ import annotations

import argparse
import re
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import init_db, make_engine
from .models import Organization

SLUG = re.compile(r"[a-z0-9-]{1,64}")


def create_org(slug: str, name: str, url: str | None = None) -> int:
    if not SLUG.fullmatch(slug):
        raise SystemExit("slug inválido: use [a-z0-9-], de 1 a 64 caracteres")
    if not name.strip():
        raise SystemExit("informe um nome")
    engine = make_engine(url)
    init_db(engine)
    with Session(engine) as s:
        if s.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
            raise SystemExit(f"já existe uma organização com o slug {slug!r}")
        org = Organization(name=name.strip(), slug=slug, active=True)
        s.add(org)
        s.commit()
        return org.id


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cria uma organização (provisório, sem papel de operador).")
    ap.add_argument("--slug", required=True, help="[a-z0-9-], 1 a 64; vai no cabeçalho X-Org-Slug")
    ap.add_argument("--name", required=True)
    args = ap.parse_args(argv)
    org_id = create_org(args.slug, args.name)
    print(f"Organização criada: id={org_id} slug={args.slug}")
    print("Crie o primeiro admin com a chave de bootstrap e o cabeçalho X-Org-Slug (veja platform/README.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
