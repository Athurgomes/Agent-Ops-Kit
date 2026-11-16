"""Cria (ou redefine a senha de) um operador da plataforma. SÓ por linha de comando.

`python -m aok_platform.create_operator --email ops@example.com`
`python -m aok_platform.create_operator --email ops@example.com --reset-password`

A senha é aleatória (20 caracteres), impressa UMA vez no terminal; nunca vem por argumento nem fica em
arquivo. Usa o banco de AOK_DATABASE_URL (SQLite local se vazio). O operador não pertence a organização.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import generate_password, hash_password
from .db import init_db, make_engine
from .models import OperatorSession, PlatformOperator, utcnow
from .ops import normalize_email


def create_operator(email: str, reset: bool = False, url: str | None = None) -> tuple[str, bool]:
    """Devolve (senha gerada, criado). Levanta SystemExit com mensagem curta se não puder."""
    try:
        email = normalize_email(email)
    except ValueError:
        raise SystemExit("e-mail inválido") from None
    engine = make_engine(url)
    init_db(engine)
    password = generate_password(20)
    with Session(engine) as s:
        op = s.scalar(select(PlatformOperator).where(PlatformOperator.email == email))
        if op is not None and not reset:
            raise SystemExit("já existe um operador com esse e-mail (use --reset-password para trocar a senha)")
        if op is None and reset:
            raise SystemExit("não existe operador com esse e-mail")
        if op is None:
            s.add(PlatformOperator(email=email, password_hash=hash_password(password), active=True))
        else:
            op.password_hash = hash_password(password)
            op.active = True
            now = utcnow()
            for row in s.scalars(
                select(OperatorSession).where(OperatorSession.operator_id == op.id, OperatorSession.revoked_at.is_(None))
            ):
                row.revoked_at = now  # senha nova encerra as sessões antigas
        s.commit()
    return password, op is None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cria ou redefine a senha de um operador da plataforma.")
    ap.add_argument("--email", required=True)
    ap.add_argument("--reset-password", action="store_true", help="gera senha nova para um operador existente")
    args = ap.parse_args(argv)
    password, created = create_operator(args.email, args.reset_password)
    print(f"Operador {'criado' if created else 'com senha redefinida'}: {args.email.strip().lower()}")
    print("Senha (aparece só desta vez; não fica gravada em arquivo):")
    print(f"  {password}")
    print("As rotas /v1/ops só existem com AOK_OPS_ENABLED=true.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
