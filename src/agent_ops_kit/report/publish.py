"""Publicação local do pacote (`aok check --publish ROOT`): pasta versionada, sem rede.

Layout: ROOT/<agent_id>/<AAAAMMDDTHHMMSSZ>/{relatorio.*, pacote.json} e ROOT/<agent_id>/index.json.
Cada versão é imutável por convenção do kit: nunca sobrescreve uma pasta existente. Não há
assinatura: o sha256 só permite detectar alteração para quem guardou o hash em outro lugar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

FILES = ("relatorio.md", "relatorio.html", "relatorio.json")
AGENT_ID_RE = re.compile(r"[a-z0-9-]{1,64}")


class PublishError(Exception):
    """Erro de publicação (id inválido, colisão, índice corrompido): mensagem curta."""


def validate_agent_id(agent_id: str) -> str:
    if not AGENT_ID_RE.fullmatch(agent_id or ""):
        raise PublishError(
            "agent-id inválido; use só letras minúsculas, dígitos e hífen (1 a 64 caracteres)"
        )
    return agent_id


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _write_atomic(path: Path, obj) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def publish(package_dir: str | Path, root: str | Path, agent_id: str, now: datetime | None = None):
    """Copia o pacote para ROOT/<agent_id>/<timestamp>/ e atualiza o índice. Devolve (pasta, cor)."""
    validate_agent_id(agent_id)
    src = Path(package_dir)
    for name in FILES:
        if not (src / name).is_file():
            raise PublishError(f"arquivo do pacote não encontrado: {src / name}")
    color = json.loads((src / "relatorio.json").read_text(encoding="utf-8"))["semaphore"]["color"]

    stamp = (now or _utcnow()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    agent_dir = Path(root) / agent_id
    index_path = agent_dir / "index.json"
    versions = []
    if index_path.exists():
        try:
            versions = json.loads(index_path.read_text(encoding="utf-8"))["versions"]
        except (ValueError, KeyError, TypeError) as exc:
            raise PublishError(f"índice corrompido: {index_path}") from exc

    agent_dir.mkdir(parents=True, exist_ok=True)
    dest = agent_dir / stamp
    try:
        dest.mkdir()  # sem exist_ok: nunca reaproveita nem sobrescreve uma versão
    except FileExistsError as exc:
        raise PublishError(f"versão já existe e é imutável: {dest} (tente de novo)") from exc

    try:
        for name in FILES:
            shutil.copyfile(src / name, dest / name)
        hashes = {name: _sha256(dest / name) for name in FILES}
        _write_atomic(
            dest / "pacote.json",
            {"agent_id": agent_id, "timestamp": stamp, "semaphore": color, "sha256": hashes},
        )
        entry = {"timestamp": stamp, "semaphore": color, "report_sha256": hashes["relatorio.json"]}
        _write_atomic(index_path, {"agent_id": agent_id, "versions": [entry, *versions]})
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest, color
