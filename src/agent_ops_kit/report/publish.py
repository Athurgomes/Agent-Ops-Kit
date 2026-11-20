"""Publicação local do pacote (`aok check --publish ROOT`): pasta versionada, sem rede.

Layout: ROOT/<agent_id>/<AAAAMMDDTHHMMSSZ>/{relatorio.*, pacote.json} e ROOT/<agent_id>/index.json.
Cada versão é imutável por convenção do kit: nunca sobrescreve uma pasta existente. O sha256 só
detecta alteração para quem guardou o hash em outro lugar; se existir `relatorio.json.sig` (ADR-029),
ele é copiado junto (local) ou enviado em `signature` (remoto), fora do pacote.json.
Com URL http(s) em vez de pasta, `publish_remote` envia o pacote à plataforma (POST /v1/reports).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

FILES = ("relatorio.md", "relatorio.html", "relatorio.json")
SIG_FILE = "relatorio.json.sig"  # opcional: só existe se o relatório foi assinado
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
        for name in (*FILES, *([SIG_FILE] if (src / SIG_FILE).is_file() else [])):
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


TOKEN_ENV = "AOK_PLATFORM_TOKEN"


def is_url(target: str) -> bool:
    return target.lower().startswith(("http://", "https://"))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # nunca reenvia o token para outro destino
        return None


def publish_remote(
    package_dir: str | Path,
    url: str,
    agent_id: str,
    token: str | None = None,
    timeout: float = 30,
    now: datetime | None = None,
):
    """Envia o pacote para URL/v1/reports. O token vem de AOK_PLATFORM_TOKEN. Devolve (seq, cor)."""
    validate_agent_id(agent_id)
    token = token if token is not None else os.environ.get(TOKEN_ENV, "")
    if not token.strip():
        raise PublishError(f"defina a variável de ambiente {TOKEN_ENV} com o token do agente")
    src = Path(package_dir)
    files, hashes = {}, {}
    for name in FILES:
        if not (src / name).is_file():
            raise PublishError(f"arquivo do pacote não encontrado: {src / name}")
        raw = (src / name).read_bytes()
        try:
            files[name] = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PublishError(f"{name} não está em UTF-8") from exc
        hashes[name] = hashlib.sha256(raw).hexdigest()
    try:
        color = json.loads(files["relatorio.json"])["semaphore"]["color"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PublishError("relatorio.json inválido: semáforo não encontrado") from exc
    payload = {
        "agent_id": agent_id,
        "timestamp": (now or _utcnow()).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "semaphore": color,
        "sha256": hashes,
        "files": files,
    }
    if (src / SIG_FILE).is_file():  # campo opcional; plataforma antiga (esquema fechado) o recusa
        try:
            payload["signature"] = (src / SIG_FILE).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PublishError(f"não foi possível ler {SIG_FILE}") from exc
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/reports",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token.strip()}"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            seq = json.loads(resp.read())["seq"]
    except urllib.error.HTTPError as exc:
        raise PublishError(_http_message(exc)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise PublishError(f"não foi possível falar com a plataforma: {reason}") from None
    except (ValueError, KeyError, TypeError):
        raise PublishError("resposta inesperada da plataforma") from None
    return seq, color


def _http_message(exc: urllib.error.HTTPError) -> str:
    base = {
        401: "token recusado (ausente, inválido ou revogado)",
        403: "publicação negada (agent-id diferente do agente do token, ou agente inativo)",
        409: "este relatório já foi publicado para o agente",
        413: "pacote acima do limite de 1 MiB",
        422: "pacote recusado pela validação do servidor",
    }.get(exc.code, f"plataforma respondeu HTTP {exc.code}")
    try:
        detail = json.loads(exc.read()).get("detail")
    except (ValueError, AttributeError, OSError):
        detail = None
    return f"{base}: {detail}" if isinstance(detail, str) and exc.code in (403, 422) else base
