#!/usr/bin/env python3
"""Sobe a plataforma de demonstração com um comando (somente stdlib; Windows e Linux).

    python scripts/demo_plataforma.py [--porta 8000] [--publicar] [--reset]

Prepara o banco SQLite e os arquivos em .demo/ (ignorado pelo git), cria os dados de demonstração,
um operador e a organização "beta", e inicia a API (com o portal) só em 127.0.0.1. Nenhuma senha,
token ou chave é gravada em arquivo: as senhas aparecem uma vez no terminal. Ctrl+C encerra.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / ".demo"
PORTAL = ROOT / "platform" / "portal"
HOST = "127.0.0.1"
AGENT_SLUG = "assistente-politicas"
OPS_EMAIL = "ops@demo.example"
LOGINS = ["admin@demo.example", "operacoes@demo.example", "financas@demo.example"]
# Com a organização "beta" existindo, a chave de bootstrap exige X-Org-Slug; o seed usa a primeira.
DEFAULT_ORG_SLUG = "default"


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"erro: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def base_env() -> dict[str, str]:
    """Ambiente herdado, sem nenhuma variável AOK_* do usuário, mais as da demonstração."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AOK_")}
    env["AOK_DATABASE_URL"] = "sqlite:///" + (DEMO / "demo.db").resolve().as_posix()
    env["AOK_DATA_DIR"] = str((DEMO / "aok_data").resolve())
    env["AOK_COOKIE_SECURE"] = "false"
    env["AOK_OPS_ENABLED"] = "true"
    return env


def run_step(titulo: str, cmd: list[str], env: dict[str, str], *, duplicado_ok: bool = False) -> None:
    """Roda um passo herdando o stdout (as senhas saem direto no terminal e não são capturadas)."""
    log(f"\n== {titulo}")
    res = subprocess.run(cmd, cwd=ROOT, env=env, stderr=subprocess.PIPE, text=True, errors="replace", check=False)
    err = (res.stderr or "").strip()
    if res.returncode == 0:
        if err:
            print(err, file=sys.stderr, flush=True)
        return
    if duplicado_ok and "já existe" in err:
        log(f"aviso: {err} (seguindo)")
        return
    die(f"{titulo} falhou (código {res.returncode}). {err[-600:]}", 1)


def porta_ocupada(porta: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, porta)) == 0


def garantir_portal() -> None:
    if (PORTAL / "dist" / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if npm is None:
        log("aviso: portal não compilado e npm não encontrado; a API sobe sem o portal. "
            "Rode: cd platform/portal && npm ci && npm run build")
        return
    log("\n== Compilando o portal (npm ci && npm run build)")
    for args in (["ci"], ["run", "build"]):
        if subprocess.run([npm, *args], cwd=PORTAL, check=False).returncode != 0:
            die(f"npm {' '.join(args)} falhou em platform/portal")


def esperar_api(proc: subprocess.Popen, url: str, limite: float = 20.0) -> None:
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if proc.poll() is not None:
            die(f"o uvicorn encerrou (código {proc.returncode}); veja a mensagem acima", 1)
        try:
            with urllib.request.urlopen(url + "/docs", timeout=1) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.25)
    die(f"a API não respondeu em {limite:.0f} s", 1)


def chamar(url: str, metodo: str, chave: str, corpo: dict | None = None) -> dict | list:
    req = urllib.request.Request(
        url,
        method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={
            "Authorization": f"Bearer {chave}",
            "X-Org-Slug": DEFAULT_ORG_SLUG,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def publicar(base: str, chave: str, env: dict[str, str]) -> None:
    log(f"\n== Publicando um relatório do agente {AGENT_SLUG}")
    try:
        agentes = chamar(f"{base}/v1/admin/agents", "GET", chave)
        agente = next(a for a in agentes if a["slug"] == AGENT_SLUG)
        token = chamar(f"{base}/v1/admin/agents/{agente['id']}/tokens", "POST", chave, {})["token"]
    except (urllib.error.URLError, OSError, StopIteration, KeyError, ValueError) as exc:
        die(f"não foi possível emitir o token do agente ({type(exc).__name__}: {exc})")
    log(f"token emitido para {AGENT_SLUG} (guardado só em memória, não exibido)")
    cmd = [
        sys.executable, "-m", "agent_ops_kit.cli", "check",
        "--config", "examples/rag_agent/agent.yaml",
        "--publish", base, "--agent-id", AGENT_SLUG,
    ]
    res = subprocess.run(
        cmd, cwd=ROOT, env={**env, "AOK_PLATFORM_TOKEN": token},
        capture_output=True, text=True, errors="replace", check=False,
    )
    saida = [ln for ln in (res.stdout or "").splitlines() if ln.startswith(("Publicado", "Semáforo"))]
    if res.returncode != 0:
        die(f"a publicação falhou: {(res.stderr or '').strip()[-400:]}", 1)
    log("\n".join(saida) or "publicado")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Sobe a plataforma de demonstração (local, sem Docker).")
    ap.add_argument("--porta", type=int, default=8000, help="porta em 127.0.0.1 (padrão 8000)")
    ap.add_argument("--publicar", action="store_true", help="emite um token e publica um relatório pelo kit")
    ap.add_argument("--reset", action="store_true", help="apaga a pasta .demo/ antes de começar")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if not 1 <= args.porta <= 65535:
        die("porta inválida")
    if porta_ocupada(args.porta):
        die(f"a porta {args.porta} já está em uso; escolha outra com --porta")

    if args.reset and DEMO.exists():
        if DEMO.resolve().parent != ROOT:
            die("pasta de dados inesperada; nada foi apagado")
        shutil.rmtree(DEMO)
        log("pasta .demo/ apagada (--reset)")
    (DEMO / "aok_data").mkdir(parents=True, exist_ok=True)

    log("aviso: AOK_COOKIE_SECURE=false só porque o acesso é http local; nunca use isso em produção.")
    garantir_portal()
    env = base_env()
    py = sys.executable
    run_step("Dados de demonstração", [py, "-m", "aok_platform.seed_demo"], env)
    run_step("Operador da plataforma", [py, "-m", "aok_platform.create_operator", "--email", OPS_EMAIL],
             env, duplicado_ok=True)
    run_step("Organização beta", [py, "-m", "aok_platform.create_org", "--slug", "beta", "--name", "Beta"],
             env, duplicado_ok=True)

    chave = secrets.token_urlsafe(32)  # só em memória, nunca impressa
    base = f"http://{HOST}:{args.porta}"
    log(f"\n== Iniciando a API em {base} (somente loopback)")
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "aok_platform.app:create_app", "--factory",
         "--host", HOST, "--port", str(args.porta), "--log-level", "warning"],
        cwd=ROOT, env={**env, "AOK_ADMIN_BOOTSTRAP_KEY": chave},
    )
    try:
        esperar_api(proc, base)
        if args.publicar:
            publicar(base, chave, env)
        log(f"\n== Pronto\nPortal:             {base}\nConsole do operador: {base}/ops/login")
        log("Logins (as senhas foram mostradas acima, uma única vez; rode com --reset para gerar outras):")
        for email in [*LOGINS, f"{OPS_EMAIL} (operador, em /ops/login)"]:
            log(f"  {email}")
        log("\nRoteiros:")
        log("  SEC: entre em /ops/login como operador e veja só metadados das organizações, sem conteúdo de relatório.")
        log("  Time do agente: com o token emitido pelo admin, rode `aok check --publish URL --agent-id <slug>`.")
        log("  Empresa: entre como admin@demo.example no portal, abra Operações > agente > relatório e baixe MD/HTML/JSON.")
        log("\nCtrl+C para encerrar.")
        while proc.poll() is None:
            time.sleep(0.5)
        die(f"o uvicorn encerrou inesperadamente (código {proc.returncode})", 1)
    except KeyboardInterrupt:
        log("\nEncerrando...")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    sys.exit(main())
