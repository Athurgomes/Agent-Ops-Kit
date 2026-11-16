"""Demo local: `python -m aok_platform.seed_demo` (rode na raiz do repositório). Idempotente.

Cria áreas, agentes fictícios e usuários com senhas aleatórias (impressas UMA vez, nunca gravadas)
e publica 2 versões de relatório por agente. O relatório é o REAL gerado por `aok report build`
a partir dos resultados gravados no repositório (nenhum número inventado): a segunda versão é
gerada com --previous, então difere da primeira. Recusa bancos que não sejam locais.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .auth import AREA_VIEWER, ORG_ADMIN, hash_password
from .db import init_db, make_engine
from .models import Agent, Area, Membership, Organization, ReportVersion, User, UserSession, utcnow
from .reports import FILES, PackageIn, _store

LABEL = "dados de demonstração: relatório do exemplo do repositório"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# (nome, nome do pai ou None)
AREAS = [("Operações", None), ("Atendimento", "Operações"), ("Finanças", None)]
# (slug, nome, área)
AGENTS = [
    ("assistente-politicas", "Assistente de políticas internas (demonstração)", "Operações"),
    ("triagem-chamados", "Triagem de chamados (demonstração)", "Atendimento"),
    ("conferencia-despesas", "Conferência de despesas (demonstração)", "Finanças"),
]
# (e-mail, perfil, área)
USERS = [
    ("admin@demo.example", ORG_ADMIN, None),
    ("operacoes@demo.example", AREA_VIEWER, "Operações"),
    ("financas@demo.example", AREA_VIEWER, "Finanças"),
]


def _check_local(engine) -> None:
    url = make_url(str(engine.url))
    if not url.drivername.startswith("sqlite") and (url.host or "") not in LOCAL_HOSTS:
        raise SystemExit("recusado: o seed de demonstração só roda em banco local (SQLite ou localhost)")


def _build_reports(root: Path) -> list[dict[str, str]]:
    """Gera 2 pacotes reais (v1 e v2 com --previous). Devolve o texto dos 3 arquivos de cada um."""
    from agent_ops_kit import cli

    if not (root / "evals" / "answers" / "manifest.json").is_file():
        raise SystemExit("rode na raiz do repositório (resultados gravados em evals/ e redteam/)")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    out: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory() as tmp:
        prev: Path | None = None
        for i in (1, 2):
            dest = Path(tmp) / f"v{i}"
            argv = ["report", "build", "--out", str(dest)]
            if prev is not None:
                argv += ["--previous", str(prev / "relatorio.json")]
            with contextlib.redirect_stdout(io.StringIO()):
                if cli.main(argv) != 0:
                    raise SystemExit("falha ao gerar o relatório (veja a mensagem acima)")
            out.append({n: (dest / n).read_text(encoding="utf-8") for n in FILES})
            prev = dest
    return out


def _get_or_create_area(s: Session, org_id: int, name: str, parent_id: int | None) -> Area:
    area = s.scalar(
        select(Area).where(
            Area.org_id == org_id,
            Area.name == name,
            Area.parent_id.is_(None) if parent_id is None else Area.parent_id == parent_id,
        )
    )
    if area is None:
        area = Area(org_id=org_id, name=name, parent_id=parent_id)
        s.add(area)
        s.flush()
    return area


def _package(slug: str, files: dict[str, str]) -> PackageIn:
    import json

    color = json.loads(files["relatorio.json"])["semaphore"]["color"]
    return PackageIn(
        agent_id=slug,
        timestamp=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        semaphore=color,
        sha256={n: hashlib.sha256(files[n].encode("utf-8")).hexdigest() for n in FILES},
        files=files,
    )


def seed(root: Path, data_dir: Path, reset_passwords: bool = False) -> dict[str, str]:
    """Devolve {e-mail: senha} só dos usuários criados (ou redefinidos) nesta execução."""
    engine = make_engine()
    _check_local(engine)
    init_db(engine)
    passwords: dict[str, str] = {}
    with Session(engine, expire_on_commit=False) as s:
        org_id = s.scalar(select(Organization.id).order_by(Organization.id).limit(1))
        areas: dict[str, Area] = {}
        for name, parent in AREAS:
            areas[name] = _get_or_create_area(
                s, org_id, name, areas[parent].id if parent else None
            )
        agents: dict[str, Agent] = {}
        for slug, name, area in AGENTS:
            agent = s.scalar(select(Agent).where(Agent.slug == slug))
            if agent is None:
                agent = Agent(area_id=areas[area].id, slug=slug, name=name, active=True)
                s.add(agent)
                s.flush()
            agents[slug] = agent
        for email, role, area in USERS:
            user = s.scalar(select(User).where(User.email == email))
            if user is None or reset_passwords:
                pwd = secrets.token_urlsafe(12)
                if user is None:
                    user = User(org_id=org_id, email=email, password_hash="", active=True)
                    s.add(user)
                user.password_hash = hash_password(pwd)
                s.flush()
                for old in s.scalars(select(UserSession).where(UserSession.user_id == user.id)):
                    old.revoked_at = old.revoked_at or utcnow()
                passwords[email] = pwd
            area_id = areas[area].id if area else None
            has = s.scalar(
                select(Membership.id).where(
                    Membership.user_id == user.id,
                    Membership.role == role,
                    Membership.area_id.is_(None) if area_id is None else Membership.area_id == area_id,
                )
            )
            if has is None:
                s.add(Membership(user_id=user.id, role=role, area_id=area_id))
        s.commit()

        pending = [
            a
            for a in agents.values()
            if not s.scalar(select(func.count(ReportVersion.id)).where(ReportVersion.agent_id == a.id))
        ]
        if pending:
            packs = _build_reports(root)
            for agent in pending:
                for files in packs:
                    _store(_package(agent.slug, files), agent, s, data_dir)
    return passwords


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Dados de demonstração do portal (somente local).")
    ap.add_argument("--reset-passwords", action="store_true", help="gera senhas novas para os usuários existentes")
    args = ap.parse_args(argv)
    data_dir = Path(os.environ.get("AOK_DATA_DIR") or "./aok_data")
    data_dir.mkdir(parents=True, exist_ok=True)
    passwords = seed(Path.cwd(), data_dir, args.reset_passwords)
    print(f"Demonstração pronta ({LABEL}).")
    print("Os agentes têm nomes fictícios; o conteúdo dos relatórios é o do exemplo do repositório.")
    if passwords:
        print("\nSenhas geradas agora (aparecem só desta vez; não ficam gravadas em arquivo):")
        for email, pwd in passwords.items():
            print(f"  {email}  {pwd}")
    else:
        print("\nUsuários já existiam: senhas não são exibidas de novo (use --reset-passwords).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
