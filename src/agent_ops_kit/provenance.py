"""Proveniência: versão do kit, git, ambiente, Ollama e hashes dos arquivos de entrada.

Tudo é capturado sem quebrar: git ou Ollama ausentes viram None. O digest do modelo e a versão
do Ollama só podem ser lidos NA EXECUÇÃO (eval, red team); o build do relatório apenas lê o
que foi gravado no manifesto ou no sidecar.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import subprocess
import urllib.request
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

NOT_RECORDED = "não registrado"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


def sha256_file(path: str | Path) -> str:
    """sha256 do arquivo lido como texto UTF-8 (CRLF e LF dão o mesmo hash); binário usa os bytes."""
    p = Path(path)
    try:
        return hashlib.sha256(p.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    except UnicodeDecodeError:
        return hashlib.sha256(p.read_bytes()).hexdigest()


def sha256_dir(directory: str | Path, pattern: str = "*.jsonl") -> str:
    """sha256 determinístico dos arquivos que casam com `pattern` (nome e conteúdo, em ordem)."""
    hasher = hashlib.sha256()
    for path in sorted(Path(directory).glob(pattern)):
        hasher.update(path.name.encode("utf-8") + b"\x00")
        hasher.update(sha256_file(path).encode("ascii") + b"\x00")
    return hasher.hexdigest()


EVIDENCE_PREFIX = "@evidence/"  # raiz lógica das evidências fora do repositório (ADR-030)


def rel_path(
    path: str | Path, base: str | Path | None = None, evidence_root: str | Path | None = None
) -> str:
    """Caminho relativo (com /) à base (padrão: diretório atual). Fora dela, mas dentro de
    `evidence_root`, vira `@evidence/<relativo>` (sem caminho absoluto); senão, só o nome."""
    p = Path(path).resolve()
    try:
        return p.relative_to(Path(base or Path.cwd()).resolve()).as_posix()
    except ValueError:
        pass
    if evidence_root is not None:
        try:
            return EVIDENCE_PREFIX + p.relative_to(Path(evidence_root).resolve()).as_posix()
        except ValueError:
            pass
    return p.name


def resolve_key(key: str | Path, evidence_root: str | Path | None = None) -> Path:
    """Inverso de `rel_path`: chave `@evidence/...` sob a raiz de evidências; outra, como está."""
    text = Path(key).as_posix() if not isinstance(key, str) else key
    if not text.startswith(EVIDENCE_PREFIX):
        return Path(text)
    if evidence_root is None:
        raise ValueError(f"{text} está na raiz de evidências: informe --evidence-root")
    return Path(evidence_root) / text[len(EVIDENCE_PREFIX):]


_SECRET_OPTS = {
    "key", "token", "password", "passwd", "secret", "api-key", "apikey", "hmac-key", "access-token",
}
_SECRET_SUFFIXES = ("-token", "-password", "-passwd", "-secret", "-api-key")
_SECRET_ENV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_URL_USERINFO = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")
REDACTED = "<redacted>"


def _is_secret_name(name: str) -> bool:
    return name in _SECRET_OPTS or name.endswith(_SECRET_SUFFIXES)


def _clean_path(value: str, base: Path) -> str:
    """Caminho relativo à raiz se estiver dentro dela; fora dela, `<externo>/nome`."""
    if "://" in value or (not re.search(r"[/\\]", value) and not value.startswith("~")):
        return value
    if os.name != "nt" and (re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value) or "\\" in value):
        # estilo Windows (unidade, UNC, barras invertidas) em Linux/macOS: Path não o reconhece
        win = PureWindowsPath(value)
        if win.is_absolute() or win.drive or ".." in win.parts:
            name = re.split(r"[/\\]", value.rstrip("/\\"))[-1]
            return f"<externo>/{name}"
        return win.as_posix()
    path = Path(value).expanduser()
    if not path.is_absolute() and ".." not in path.parts:
        return path.as_posix()
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        name = re.split(r"[/\\]", value.rstrip("/\\"))[-1]
        return f"<externo>/{name}"


def sanitize_command(command: str | list[str], base: str | Path | None = None) -> str:
    """Comando seguro para publicar: caminhos relativos à raiz (fora dela, `<externo>/nome`) e
    valores de opções e variáveis que parecem segredo (token, key, password...) viram `<redacted>`."""
    root = Path(base or Path.cwd()).resolve()
    try:
        tokens = shlex.split(command) if isinstance(command, str) else list(command)
    except ValueError:
        tokens = str(command).split()
    out: list[str] = []
    redact_next = False
    for tok in tokens:
        if redact_next:
            out.append(REDACTED)
            redact_next = False
            continue
        env = _SECRET_ENV.match(tok)
        if tok.startswith("-"):
            name, eq, value = tok.lstrip("-").partition("=")
            dashes = tok[: len(tok) - len(tok.lstrip("-"))]
            if _is_secret_name(name):
                if eq:
                    out.append(f"{dashes}{name}={REDACTED}")
                else:
                    out.append(tok)
                    redact_next = True
            elif eq:
                out.append(f"{dashes}{name}={_clean_path(value, root)}")
            else:
                out.append(tok)
        elif env and _is_secret_name(env.group(1).lower().replace("_", "-")):
            out.append(f"{env.group(1)}={REDACTED}")
        else:
            out.append(_URL_USERINFO.sub(r"\g<1><redacted>@", _clean_path(tok, root)))
    return shlex.join(out)


def _git(args: list[str], cwd: str | Path | None, timeout: float = 5.0) -> str | None:
    try:
        res = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() if res.returncode == 0 else None


def git_info(cwd: str | Path | None = None) -> tuple[str | None, bool | None]:
    """(commit, árvore com mudanças em arquivos rastreados). Sem git ou sem repositório: (None, None)."""
    commit = _git(["rev-parse", "HEAD"], cwd)
    if not commit:
        return None, None
    status = _git(["status", "--porcelain", "--untracked-files=no"], cwd)
    return commit, (None if status is None else bool(status))


def _ollama_get(path: str, timeout: float = 3.0) -> dict:
    host = os.environ.get("OLLAMA_HOST", "").strip() or DEFAULT_OLLAMA_HOST
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    with urllib.request.urlopen(host.rstrip("/") + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ollama_info(model: str, fetch: Callable[[str], dict] | None = None) -> dict:
    """Versão do Ollama e digest do modelo (consultas leves: /api/version e /api/tags)."""
    get = fetch or _ollama_get
    out: dict = {"ollama_version": None, "model_digest": None}
    try:
        out["ollama_version"] = get("/api/version").get("version")
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    want = model if ":" in model else f"{model}:latest"
    try:
        for m in get("/api/tags").get("models", []):
            if want in (m.get("name"), m.get("model")):
                out["model_digest"] = m.get("digest")
                break
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return out


def environment(cwd: str | Path | None = None) -> dict:
    """Versão do kit, commit git (e árvore suja), Python e sistema operacional."""
    from agent_ops_kit import __version__

    commit, dirty = git_info(cwd)
    return {
        "kit_version": __version__,
        "git_commit": commit,
        "git_dirty": dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def target_info(cfg: object) -> dict:
    """Proveniência do agente auditado (só lê o config; não importa nem executa o target).

    Sem `target` vale o agente de exemplo, com semente controlada pelo kit. Com `target`
    externo, o kit não controla a semente nem o modelo do agente."""
    target = getattr(cfg, "target", None)
    if target is None:
        return {"target": {
            "type": "python", "ref": "examples.rag_agent.agent:run_agent",
            "seed_controlled_by_kit": True,
        }}
    if target.type == "http":
        from agent_ops_kit.config import sanitize_url

        return {"target": {
            "type": "http", "ref": sanitize_url(target.url), "seed_controlled_by_kit": False,
            "note": "semente não controlada pelo kit; alvo HTTP",
        }}
    return {"target": {
        "type": target.type, "ref": target.ref, "seed_controlled_by_kit": False,
        "note": "semente não controlada pelo kit",
    }}


def execution_info(
    model: str,
    command: str,
    fetch: Callable[[str], dict] | None = None,
    cwd: str | Path | None = None,
) -> dict:
    """Proveniência de uma execução com modelo: ambiente, Ollama (versão, digest), comando e
    limites de geração (num_predict, timeout; execuções antigas não tinham limite)."""
    from agent_ops_kit import ollama_chat

    return {
        **environment(cwd), **ollama_info(model, fetch),
        "command": sanitize_command(command), "generation_limits": ollama_chat.limits(),
    }
