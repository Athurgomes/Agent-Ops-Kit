"""Servidor HTTP local de exemplo: agente de triagem de suporte de pedidos (não-RAG).

Uso:
    EXTERNAL_AGENT_TOKEN=<token> python examples/external_http_agent/server.py --port 8787
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY_BYTES = 1_048_576
TOKEN_ENV_VAR = "EXTERNAL_AGENT_TOKEN"

_FORBIDDEN_KEYWORDS = (
    "senha",
    "password",
    "banco de dados",
    "database",
    "credencial",
    "token",
    "api key",
    "chave",
    "prompt",
    "instrucoes internas",
    "instruções internas",
    "system prompt",
    "reembolso",
    "estorno",
    "excluir conta",
    "deletar conta",
    "cpf",
    "admin",
)

_DELAY_KEYWORDS = (
    "atraso",
    "atrasado",
    "pedido",
    "entrega",
    "rastreio",
    "status",
)

_EXCHANGE_KEYWORDS = (
    "troca",
    "devolucao",
    "devolução",
    "defeito",
    "garantia",
)


def handle_support_message(message: str) -> tuple[str, list[dict[str, Any]]]:
    """Processa uma mensagem de triagem de suporte de pedidos de forma determinística."""
    normalized = message.lower()

    if any(keyword in normalized for keyword in _FORBIDDEN_KEYWORDS):
        reply = (
            "Não encontrei essa informação nos documentos. "
            "Atuo apenas na triagem de pedidos e não tenho acesso a credenciais, "
            "dados sensíveis ou ações administrativas."
        )
        return reply, []

    if any(keyword in normalized for keyword in _EXCHANGE_KEYWORDS):
        reply = (
            "Para solicitação de troca ou devolução, o prazo é de 7 dias corridos após o "
            "recebimento. Abri um chamado de triagem para o time de atendimento seguir com você."
        )
        return reply, [{"name": "open_ticket", "arguments": {"category": "troca"}}]

    if any(keyword in normalized for keyword in _DELAY_KEYWORDS):
        reply = (
            "Seu caso de pedido foi classificado com prioridade alta na triagem. "
            "Registrei o protocolo SUP-2026-001 para acompanhamento da entrega."
        )
        return reply, [{"name": "lookup_order", "arguments": {"query": message[:80]}}]

    reply = (
        "Posso ajudar apenas com triagem de suporte de pedidos (status, atraso, troca ou "
        "devolução). Informe o número do pedido ou o tipo de solicitação."
    )
    return reply, []


def make_handler(expected_token: str) -> type[BaseHTTPRequestHandler]:
    """Cria o handler HTTP vinculado ao token esperado (lido do ambiente)."""
    expected_header = f"Bearer {expected_token}"

    class SupportAgentHandler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/chat":
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return

            auth_header = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth_header, expected_header):
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return

            raw_length = self.headers.get("Content-Length")
            try:
                content_length = int(raw_length) if raw_length is not None else -1
            except ValueError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid content-length"})
                return

            if content_length < 0 or content_length > MAX_BODY_BYTES:
                self._send_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {"error": "payload too large or missing content-length"},
                )
                return

            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return

            if not isinstance(data, dict) or not isinstance(data.get("mensagem"), str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "field 'mensagem' (string) is required"},
                )
                return

            reply, actions = handle_support_message(data["mensagem"])
            self._send_json(
                HTTPStatus.OK,
                {"data": {"reply": reply, "actions": actions}},
            )

        def log_message(self, format: str, *args: Any) -> None:
            # Log enxuto sem cabeçalhos nem corpo para nunca expor credenciais.
            sys.stderr.write(f"[external-http-agent] {self.command} {self.path}\n")

    return SupportAgentHandler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Servidor HTTP local de exemplo para auditoria externa (triagem de pedidos)."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8787,
        help="Porta local em 127.0.0.1 (padrão: 8787).",
    )
    args = parser.parse_args(argv)

    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        sys.stderr.write(
            f"Erro: defina a variável de ambiente {TOKEN_ENV_VAR} antes de iniciar o servidor.\n"
        )
        return 2

    if not (1 <= args.port <= 65535):
        sys.stderr.write("Erro: --port deve estar entre 1 e 65535.\n")
        return 2

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(token))
    sys.stderr.write(
        f"Servidor de exemplo ouvindo em http://127.0.0.1:{args.port}/chat "
        f"(auth via {TOKEN_ENV_VAR}). Ctrl+C para encerrar.\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
