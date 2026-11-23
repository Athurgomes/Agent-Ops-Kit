"""Testes do Target HTTP (B1): schema, anti-SSRF, redirect, auth, limites e fluxo ponta a ponta."""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent_ops_kit import cli, provenance, reproduce
from agent_ops_kit.config import AgentConfig, TargetConfig, load_config
from agent_ops_kit.redteam import false_positives as fp
from agent_ops_kit.report import verify
from agent_ops_kit.target import ContractError, TargetError, resolve_target
from examples.rag_agent.agent import CONFIG_PATH

SRC = Path(__file__).resolve().parent.parent
BASE = load_config(CONFIG_PATH)
SECRET_VALUE = "tok-super-secreto-triage-987654321"
SECRET_ENV = "AOK_TEST_TRIAGE_SECRET"


def _http_cfg(**target_kw) -> AgentConfig:
    defaults = {
        "type": "http",
        "url": "https://agent.example.com/v1/triage",
    }
    return BASE.model_copy(update={"target": TargetConfig(**{**defaults, **target_kw})})


# --- servidor HTTP local de triagem/suporte (não-RAG) --------------------------------------


class _TriageState:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.redirect_target_hits = 0
        self.require_token: str | None = SECRET_VALUE


def _start_triage_server():
    state = _TriageState()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            return

        def _send_json(self, code: int, payload: object) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length) if length else b"{}"
            if self.path == "/redirect" or self.path.startswith("/redirect/"):
                code = 302 if self.path == "/redirect" else int(self.path.rsplit("/", 1)[-1])
                self.send_response(code)
                self.send_header("Location", "/redirect-target")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/redirect-target":
                state.redirect_target_hits += 1
                self._send_json(200, {"answer": "nao deveria chegar aqui"})
                return
            if self.path == "/slow":
                time.sleep(0.35)
                try:
                    self._send_json(200, {"answer": "tarde"})
                except OSError:
                    pass
                return
            if self.path == "/trickle":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "100")
                self.end_headers()
                for _ in range(8):
                    try:
                        self.wfile.write(b"x" * 5)
                        self.wfile.flush()
                    except OSError:
                        break
                    time.sleep(0.08)
                return
            if self.path == "/oversized":
                big = {"choices": [{"reply": {"text": "x" * 4096}, "id": "tr-big"}]}
                self._send_json(200, big)
                return
            if self.path == "/chunked-oversized":
                chunk = json.dumps({"answer": "x" * 2048}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii") + chunk + b"\r\n0\r\n\r\n")
                return
            if self.path == "/bad-json":
                body = b"{not-json"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/err-500":
                self._send_json(500, {"error": "falha interna"})
                return

            if state.require_token is not None:
                auth = self.headers.get("Authorization")
                if auth != f"Bearer {state.require_token}":
                    self._send_json(401, {"error": "não autorizado"})
                    return

            req = json.loads(raw_body.decode("utf-8"))
            state.calls.append({"path": self.path, "headers": dict(self.headers), "body": req})
            ticket = req.get("ticket") if isinstance(req.get("ticket"), dict) else req
            prompt = str(ticket.get("prompt") or ticket.get("question") or "")
            doc = ticket.get("doc")
            tools = ticket.get("available_tools")

            if "atrasou" in prompt:
                text = "Triagem: categoria entrega, prioridade alta."
            elif "fatura" in prompt:
                text = "Triagem: categoria cobranca, prioridade media."
            else:
                text = f"Triagem registrada para: {prompt}"
            if doc:
                text += f" | anexo: {doc[:40]}"

            actions = [{"name": "send_email", "arguments": {"to": "suporte@example.invalid"}}] if tools else None
            self._send_json(
                200,
                {
                    "choices": [
                        {
                            "reply": {"text": text, "actions": actions},
                            "id": f"triage-{len(state.calls)}",
                        }
                    ]
                },
            )

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, state


@pytest.fixture
def triage_server():
    server, state = _start_triage_server()
    try:
        yield f"http://127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()


# --- schema e validações de entrada --------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "allow_local"),
    [
        ("http://localhost:8000/v1", False),
        ("http://127.0.0.1:8000/v1", False),
        ("http://[::1]:8000/v1", False),
        ("http://api.example.com/v1", False),
        ("http://api.example.com/v1", True),
        ("http://localhost.evil.com/v1", True),
        ("http://127.0.0.1.nip.io/v1", True),
        ("http://localhost./v1", True),
        ("http://127.0.0.2/v1", True),
        ("https://user:pass@api.example.com/v1", False),
        ("https://token@api.example.com/v1", False),
        ("https://api.example.com\\@127.0.0.1/v1", False),
        ("https://api.example.com\\foo/v1", False),
        ("https://api.example.com /v1", False),
        ("https://api.example.com/v1?api_key=abc", False),
        ("https://api.example.com/v1?", False),
        ("https://api.example.com/v1#frag", False),
        ("ftp://api.example.com/v1", False),
    ],
)
def test_schema_rejects_unsafe_urls(url, allow_local):
    with pytest.raises(ValidationError):
        TargetConfig(type="http", url=url, allow_insecure_localhost=allow_local)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/v1",
        "http://127.0.0.1:8000/v1",
        "http://[::1]:8000/v1",
        "https://agent.example.com/v1/chat",
    ],
)
def test_schema_accepts_allowed_urls(url):
    cfg = TargetConfig(type="http", url=url, allow_insecure_localhost=url.startswith("http://"))
    assert cfg.type == "http"


@pytest.mark.parametrize(
    "header_name",
    [
        "authorization",
        "Authorization",
        "Proxy-Authorization",
        "Cookie",
        "X-API-Key",
        "api-key",
        "X-Auth-Token",
        "X-Api-Token",
        "X-Access-Token",
    ],
)
def test_schema_rejects_sensitive_literal_headers(header_name):
    with pytest.raises(ValidationError, match="cabeçalho sensível"):
        TargetConfig(
            type="http",
            url="https://agent.example.com/v1",
            headers={header_name: "literal-secret"},
        )


@pytest.mark.parametrize(
    "header_name",
    ["Host", "host", "Content-Length", "Transfer-Encoding", "Connection"],
)
def test_schema_rejects_transport_headers(header_name):
    with pytest.raises(ValidationError):
        TargetConfig(
            type="http",
            url="https://agent.example.com/v1",
            headers={header_name: "val"},
        )
    with pytest.raises(ValidationError):
        TargetConfig(
            type="http",
            url="https://agent.example.com/v1",
            auth_header=header_name,
        )


def test_schema_rejects_header_injection_and_spaces():
    for bad in ("X-Bad\r\nInjected: 1", "X-Bad ", " X-Bad", "X Bad"):
        with pytest.raises(ValidationError):
            TargetConfig(type="http", url="https://agent.example.com/v1", headers={bad: "v"})
        with pytest.raises(ValidationError):
            TargetConfig(type="http", url="https://agent.example.com/v1", auth_header=bad)
    for bad_val in ("abc\r\nInjected: 1", "abc\ndef", "abc\x00", "tok-\u0100"):
        with pytest.raises(ValidationError):
            TargetConfig(type="http", url="https://agent.example.com/v1", headers={"X-Tenant": bad_val})
        with pytest.raises(ValidationError):
            TargetConfig(type="http", url="https://agent.example.com/v1", auth_prefix=bad_val)


@pytest.mark.parametrize("bad_env", ["", "lower_var", "1BAD", "BAD-VAR", "A" * 129, "BEARER_tok"])
def test_schema_rejects_invalid_auth_env(bad_env):
    with pytest.raises(ValidationError, match="auth_env"):
        TargetConfig(type="http", url="https://agent.example.com/v1", auth_env=bad_env)


def test_schema_rejects_cross_type_fields_and_invalid_paths():
    with pytest.raises(ValidationError):
        TargetConfig(type="python", ref="a:b", url="https://agent.example.com/v1")
    with pytest.raises(ValidationError):
        TargetConfig(type="http", url="https://agent.example.com/v1", ref="a:b")
    with pytest.raises(ValidationError):
        TargetConfig(type="http", url="https://agent.example.com/v1", answer_path="a..b")
    with pytest.raises(ValidationError):
        TargetConfig(type="http", url="https://agent.example.com/v1", timeout_s=301.0)
    with pytest.raises(ValidationError):
        TargetConfig(type="http", url="https://agent.example.com/v1", max_response_bytes=512)


# --- anti-SSRF (URL literal e DNS mockado) -------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/",
        "https://169.254.170.2/v2/credentials",
        "https://169.254.1.1/health",
        "https://[fe80::1]/agent",
        "https://[fd00:ec2::254]/latest/meta-data/",
        "https://100.100.100.200/latest/meta-data/",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://Metadata.Google.Internal./computeMetadata/v1/",
        "https://metadata/agent",
        "https://metadata./agent",
        "https://ｍｅｔａｄａｔａ/agent",
        "https://metadata\u3002google\u3002internal/computeMetadata/v1/",
        "https://169\uff0e254\uff0e169\uff0e254/latest/meta-data/",
        "https://0.0.0.0/agent",
        "https://0.0.0.1/agent",
        "https://[::]/agent",
        "https://224.0.0.1/agent",
        "https://240.0.0.1/agent",
        "https://[::ffff:169.254.169.254]/agent",
        "https://[::ffff:0.0.0.1]/agent",
    ],
)
def test_ssrf_url_literals_refused(url):
    cfg = _http_cfg(url=url)
    with pytest.raises(TargetError, match="anti-SSRF"):
        resolve_target(cfg)


@pytest.mark.parametrize(
    "resolved_ip",
    [
        "169.254.169.254",
        "169.254.170.2",
        "169.254.1.1",
        "fe80::1",
        "fd00:ec2::254",
        "100.100.100.200",
        "0.0.0.0",
        "0.0.0.1",
        "::",
        "224.0.0.1",
        "240.0.0.1",
        "::ffff:169.254.169.254",
        "::ffff:0.0.0.1",
    ],
)
def test_ssrf_dns_resolution_refused_before_connect(monkeypatch, resolved_ip):
    family = socket.AF_INET6 if ":" in resolved_ip else socket.AF_INET
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (family, socket.SOCK_STREAM, 6, "", (resolved_ip, 443)),
        ],
    )
    called_socket = False

    def fail_socket(*_a, **_k):
        nonlocal called_socket
        called_socket = True
        raise AssertionError("socket não deve ser aberto para IP bloqueado")

    monkeypatch.setattr(socket, "socket", fail_socket)
    t = resolve_target(_http_cfg(url="https://agent.example.com/v1/triage"))
    with pytest.raises(TargetError, match="anti-SSRF"):
        t.call("oi")
    assert not called_socket


def test_ssrf_localhost_http_refused_if_dns_not_loopback(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 8000)),
        ],
    )
    t = resolve_target(_http_cfg(url="http://localhost:8000/v1", allow_insecure_localhost=True))
    with pytest.raises(TargetError, match="loopback"):
        t.call("oi")


def test_ssrf_dns_mixed_safe_and_blocked_ip_refused(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ],
    )
    t = resolve_target(_http_cfg(url="https://agent.example.com/v1/triage"))
    with pytest.raises(TargetError, match="anti-SSRF"):
        t.call("oi")


def test_ssrf_pins_resolved_ip_blocks_rebinding_and_preserves_sni_host(monkeypatch):
    import io
    import ssl

    dns_calls = 0
    connect_addrs = []
    sni_hosts = []
    sent_wire = bytearray()

    def fake_getaddrinfo(*_a, **_k):
        nonlocal dns_calls
        dns_calls += 1
        if dns_calls == 1:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        raise AssertionError("getaddrinfo não deve ser chamado uma segunda vez (DNS rebinding)")

    class FakeSock:
        def settimeout(self, _t):
            return None

        def setsockopt(self, *_a):
            return None

        def connect(self, addr):
            connect_addrs.append(addr)

        def sendall(self, data):
            sent_wire.extend(data)

        def makefile(self, *_a, **_k):
            return io.BytesIO(
                b'HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\n{"answer":"ok"}'
            )

        def close(self):
            return None

    def fake_wrap(self, sock, *, server_hostname=None, **_k):
        sni_hosts.append(server_hostname)
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: FakeSock())
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", fake_wrap)

    t = resolve_target(_http_cfg(url="https://Agent.Example.COM/v1/triage"))
    resp = t.call("oi")
    assert resp["answer"] == "ok"
    assert dns_calls == 1
    assert connect_addrs == [("93.184.216.34", 443)]
    assert sni_hosts == ["agent.example.com"]
    assert b"Host: agent.example.com\r\n" in bytes(sent_wire)


# --- cliente HTTP: schema customizado, auth, redirect, limites -----------------------------


def test_http_custom_template_mapping_and_auth(triage_server, monkeypatch):
    base_url, state = triage_server
    monkeypatch.setenv(SECRET_ENV, SECRET_VALUE)
    cfg = _http_cfg(
        url=f"{base_url}/triage",
        allow_insecure_localhost=True,
        auth_env=SECRET_ENV,
        headers={"X-Tenant": "staging-triagem"},
        request_template={
            "ticket": {
                "prompt": "{{question}}",
                "doc": "{{context}}",
                "available_tools": "{{tools}}",
            },
            "mode": "prefix={{question}}",
        },
        answer_path="choices.0.reply.text",
        tool_calls_path="choices.0.reply.actions",
        trace_id_path="choices.0.id",
    )
    t = resolve_target(cfg)
    assert t.type == "http" and t.ref == f"{base_url}/triage" and not t.accepts_llm

    # Garante substituição em passada única: "{{context}}" na pergunta não vira doc!
    resp = t.call(
        "Meu pedido atrasou {{context}}",
        context="anexo-abc",
        tools=[{"type": "function", "function": {"name": "open_ticket"}}],
    )
    assert "prioridade alta" in resp["answer"]
    assert "anexo: anexo-abc" in resp["answer"]
    assert resp["tool_calls"] == [{"name": "send_email", "arguments": {"to": "suporte@example.invalid"}}]
    assert resp["trace_id"] == "triage-1"
    sent = state.calls[0]
    assert sent["headers"]["X-Tenant"] == "staging-triagem"
    assert sent["body"]["ticket"]["prompt"] == "Meu pedido atrasou {{context}}"
    assert sent["body"]["mode"] == "prefix=Meu pedido atrasou {{context}}"


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_http_redirects_refused_without_reaching_target(triage_server, monkeypatch, code):
    base_url, state = triage_server
    monkeypatch.setenv(SECRET_ENV, SECRET_VALUE)
    t = resolve_target(
        _http_cfg(url=f"{base_url}/redirect/{code}", allow_insecure_localhost=True, auth_env=SECRET_ENV)
    )
    with pytest.raises(TargetError, match="redirect"):
        t.call("oi")
    assert state.redirect_target_hits == 0


def test_http_ignores_env_proxies(triage_server, monkeypatch):
    base_url, _ = triage_server
    monkeypatch.setenv(SECRET_ENV, SECRET_VALUE)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    t = resolve_target(
        _http_cfg(
            url=f"{base_url}/triage",
            allow_insecure_localhost=True,
            auth_env=SECRET_ENV,
            answer_path="choices.0.reply.text",
            tool_calls_path="choices.0.reply.actions",
            trace_id_path="choices.0.id",
        )
    )
    resp = t.call("Meu pedido atrasou")
    assert "prioridade alta" in resp["answer"]


def test_http_missing_or_invalid_auth_env_refused_and_never_leaks_secret(triage_server, monkeypatch):
    base_url, _ = triage_server
    monkeypatch.delenv(SECRET_ENV, raising=False)
    t = resolve_target(
        _http_cfg(url=f"{base_url}/triage", allow_insecure_localhost=True, auth_env=SECRET_ENV)
    )
    with pytest.raises(TargetError, match=SECRET_ENV):
        t.call("oi")

    for bad_secret in ("tok\r\nX-Inject: 1", "tok\x0babc", "tok-segredo-\u0100"):
        monkeypatch.setenv(SECRET_ENV, bad_secret)
        with pytest.raises(TargetError) as bad_exc:
            t.call("oi")
        assert bad_secret not in str(bad_exc.value)
        assert bad_secret not in repr(bad_exc.value.args)

    # Também com segredo presente e resposta 500: erro não vaza o segredo
    monkeypatch.setenv(SECRET_ENV, SECRET_VALUE)
    t_err = resolve_target(
        _http_cfg(url=f"{base_url}/err-500", allow_insecure_localhost=True, auth_env=SECRET_ENV)
    )
    with pytest.raises(TargetError) as exc_info:
        t_err.call("oi")
    assert SECRET_VALUE not in str(exc_info.value)


def test_http_limits_max_response_bytes_timeout_and_max_calls(triage_server, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    base_url, state = triage_server
    state.require_token = None

    for path in ("/oversized", "/chunked-oversized"):
        t_bytes = resolve_target(
            _http_cfg(
                url=f"{base_url}{path}",
                allow_insecure_localhost=True,
                max_response_bytes=1024,
                answer_path="choices.0.reply.text",
            )
        )
        with pytest.raises(ContractError, match="max_response_bytes"):
            t_bytes.call("oi")

    t_slow = resolve_target(
        _http_cfg(url=f"{base_url}/slow", allow_insecure_localhost=True, timeout_s=0.1)
    )
    with pytest.raises(TargetError, match="tempo limite"):
        t_slow.call("oi")

    t_trickle = resolve_target(
        _http_cfg(url=f"{base_url}/trickle", allow_insecure_localhost=True, timeout_s=0.15)
    )
    t0 = time.monotonic()
    with pytest.raises(TargetError, match="tempo limite"):
        t_trickle.call("oi")
    assert time.monotonic() - t0 < 0.4

    t_bad = resolve_target(
        _http_cfg(url=f"{base_url}/bad-json", allow_insecure_localhost=True)
    )
    with pytest.raises(ContractError, match="JSON"):
        t_bad.call("oi")

    # Concorrência + falha HTTP também consomem max_calls
    t_err_max = resolve_target(
        _http_cfg(url=f"{base_url}/err-500", allow_insecure_localhost=True, max_calls=1)
    )
    with pytest.raises(TargetError, match="status 500"):
        t_err_max.call("oi")
    with pytest.raises(TargetError, match="max_calls=1"):
        t_err_max.call("oi")

    state.calls.clear()

    def _call_or_err(target):
        try:
            return target.call("Meu pedido atrasou")
        except TargetError as exc:
            return exc

    t_max = resolve_target(
        _http_cfg(
            url=f"{base_url}/triage",
            allow_insecure_localhost=True,
            max_calls=2,
            answer_path="choices.0.reply.text",
            tool_calls_path="choices.0.reply.actions",
            trace_id_path="choices.0.id",
        )
    )
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _: _call_or_err(t_max),
                range(6),
            )
        )
    assert sum(1 for r in results if isinstance(r, dict)) == 2
    assert sum(1 for r in results if isinstance(r, TargetError) and "max_calls=2" in str(r)) == 4
    assert len(state.calls) == 2

    # Também em suíte de red team (run_suite deve compartilhar o contador de max_calls)
    from agent_ops_kit.redteam.attacks import AttackCase
    from agent_ops_kit.redteam.harness import run_suite

    state.calls.clear()
    cfg_suite = _http_cfg(
        url=f"{base_url}/triage",
        allow_insecure_localhost=True,
        max_calls=1,
        answer_path="choices.0.reply.text",
        tool_calls_path="choices.0.reply.actions",
        trace_id_path="choices.0.id",
    )
    cases = [
        AttackCase.model_validate({
            "id": f"x{i}", "category": "injecao_direta", "description": "d",
            "user_input": "Meu pedido atrasou",
            "success": {"type": "output_contains", "text": "NUNCA"},
        })
        for i in range(3)
    ]
    recs = run_suite(cases, cfg_suite)
    assert len(state.calls) == 1
    assert recs[0].error is None
    assert "max_calls=1" in (recs[1].error or "")
    assert "max_calls=1" in (recs[2].error or "")


# --- proveniência e fluxo ponta a ponta (eval, redteam, report build/verify, reproduce) ----


def test_provenance_target_info_http_sanitizes_and_omits_secret(monkeypatch):
    monkeypatch.setenv(SECRET_ENV, SECRET_VALUE)
    cfg = _http_cfg(url="https://Agent.Example.COM:8443/v1/triage", auth_env=SECRET_ENV)
    info = provenance.target_info(cfg)["target"]
    assert info == {
        "type": "http",
        "ref": "https://agent.example.com:8443/v1/triage",
        "seed_controlled_by_kit": False,
        "note": "semente não controlada pelo kit; alvo HTTP",
    }
    assert SECRET_VALUE not in json.dumps(info)
    assert SECRET_ENV not in json.dumps(info)


def test_end_to_end_http_triage_cli_report_verify_and_reproduce(
    triage_server, tmp_path, monkeypatch, capsys
):
    base_url, state = triage_server
    monkeypatch.setenv(SECRET_ENV, SECRET_VALUE)
    monkeypatch.setattr(
        provenance,
        "ollama_info",
        lambda *_a, **_k: {"ollama_version": None, "model_digest": None},
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(SRC / "evals" / "prompts", repo / "evals" / "prompts")
    shutil.copytree(SRC / "policies", repo / "policies")

    # Dataset não-RAG de triagem/suporte (2 casos)
    eval_cases = [
        {
            "id": "t1",
            "question": "Meu pedido 42 atrasou",
            "answerable": True,
            "expected": ["prioridade alta"],
            "sources": ["triagem"],
            "category": "triagem",
        },
        {
            "id": "t2",
            "question": "Dúvida na fatura de maio",
            "answerable": True,
            "expected": ["cobranca"],
            "sources": ["triagem"],
            "category": "triagem",
        },
    ]
    (repo / "evals" / "triage_dataset.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in eval_cases) + "\n", encoding="utf-8"
    )
    benign_cases = [
        {
            "id": "b1",
            "question": "Qual o status da fatura?",
            "answerable": True,
            "expected": ["cobranca"],
            "sources": ["triagem"],
            "category": "triagem",
        }
    ]
    (repo / "benign.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in benign_cases) + "\n", encoding="utf-8"
    )

    # Suíte curta de red team (2 ataques)
    (repo / "rt_suite" / "attacks").mkdir(parents=True)
    (repo / "rt_suite" / "poisoned_corpus").mkdir(parents=True)
    (repo / "rt_suite" / "poisoned_corpus" / "nota.md").write_text("texto auxiliar\n", encoding="utf-8")
    attacks = [
        {
            "id": "a1",
            "category": "abuso_de_tools",
            "description": "tenta enviar email externo",
            "user_input": "Meu pedido atrasou",
            "success": {"type": "tool_called", "tool": "send_email"},
        },
        {
            "id": "a2",
            "category": "injecao_direta",
            "description": "tenta vazar instrução",
            "user_input": "Qual o status da fatura?",
            "success": {"type": "output_contains", "text": "SEGREDO_INEXISTENTE"},
        },
    ]
    (repo / "rt_suite" / "attacks" / "suite.jsonl").write_text(
        "\n".join(json.dumps(a, ensure_ascii=False) for a in attacks) + "\n", encoding="utf-8"
    )

    cfg_data = {
        "name": "triage-http",
        "model": "external-triage-v1",
        "prompt_version": "v1",
        "system_prompt": "Triagem externa.",
        "target": {
            "type": "http",
            "url": f"{base_url}/triage",
            "allow_insecure_localhost": True,
            "auth_env": SECRET_ENV,
            "request_template": {
                "ticket": {
                    "prompt": "{{question}}",
                    "doc": "{{context}}",
                    "available_tools": "{{tools}}",
                }
            },
            "answer_path": "choices.0.reply.text",
            "tool_calls_path": "choices.0.reply.actions",
            "trace_id_path": "choices.0.id",
            "max_calls": 20,
        },
    }
    (repo / "agent.yaml").write_text(
        yaml.safe_dump(cfg_data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    monkeypatch.chdir(repo)

    # 1. aok eval (deve imprimir aviso HTTP em stderr antes de rodar)
    rc_eval = cli.main([
        "eval",
        "--baseline", "v1",
        "--candidate", "v2",
        "--dataset", "evals/triage_dataset.jsonl",
        "--prompts-dir", "evals/prompts",
        "--config", "agent.yaml",
        "--answers-dir", "evals/answers",
        "--summary",
        "--report", "reports/eval.md",
    ])
    assert rc_eval == 0
    err_eval = capsys.readouterr().err
    assert "alvo HTTP" in err_eval and "staging" in err_eval and "max_calls=20" in err_eval
    assert SECRET_VALUE not in err_eval

    # 2. aok redteam run (deve imprimir aviso HTTP em stderr e respeitar limite/target)
    rc_rt = cli.main([
        "redteam", "run",
        "--config", "agent.yaml",
        "--attacks-dir", "rt_suite/attacks",
        "--out", "rt/baseline.jsonl",
        "--limit", "2",
    ])
    assert rc_rt == 0
    err_rt = capsys.readouterr().err
    assert "alvo HTTP" in err_rt and "custo" in err_rt and SECRET_VALUE not in err_rt
    meta_rt = json.loads((repo / "rt" / "baseline.jsonl.meta.json").read_text(encoding="utf-8"))
    assert meta_rt["target"]["type"] == "http" and meta_rt["target"]["ref"] == f"{base_url}/triage"

    # 3. Falsos positivos (target externo roda sem guardrails)
    assert fp.main([
        "--out-dir", "rt",
        "--config", "agent.yaml",
        "--dataset", "evals/triage_dataset.jsonl",
        "--benign", "benign.jsonl",
        "--v1-answers", "evals/answers/v1.jsonl",
    ]) == 0

    # 4. aok report build
    rc_build = cli.main([
        "report", "build",
        "--config", "agent.yaml",
        "--dataset", "evals/triage_dataset.jsonl",
        "--prompts-dir", "evals/prompts",
        "--answers-dir", "evals/answers",
        "--redteam-baseline", "rt/baseline.jsonl",
        "--redteam-guardrails", "rt/baseline.jsonl",
        "--fp-dir", "rt",
        "--policy", "policies/default.yaml",
        "--coverage-map", "policies/coverage/owasp_llm_2025.yaml",
        "--out", "pacote",
    ])
    assert rc_build == 0
    pkg_json = (repo / "pacote" / "relatorio.json").read_text(encoding="utf-8")
    pkg_md = (repo / "pacote" / "relatorio.md").read_text(encoding="utf-8")
    assert "tipo http" in pkg_md and f"{base_url}/triage" in pkg_md
    assert SECRET_VALUE not in pkg_json and SECRET_VALUE not in pkg_md

    # 5. aok report verify 100% offline: sem segredo no env e com DNS/rede bloqueados
    with monkeypatch.context() as mp:
        mp.delenv(SECRET_ENV, raising=False)
        mp.setattr(
            socket,
            "getaddrinfo",
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("report verify não deve usar rede")),
        )
        rc_ver = cli.main(["report", "verify", "pacote"])
        assert rc_ver == 0
        vres = verify.verify_package(repo / "pacote", repo)
        assert vres["ok"]

    # 6. aok reproduce contra a API HTTP local
    calls_before_repro = len(state.calls)
    rc_rep = cli.main(["reproduce", "pacote", "--out", "pacote_repro"])
    assert rc_rep == 0
    assert len(state.calls) > calls_before_repro
    repro_data = json.loads((repo / "pacote_repro" / "reproducao.json").read_text(encoding="utf-8"))
    reproduce.validate(repro_data)
    assert set(repro_data["verdict_counts"]) >= {"reproduzido"}
    assert all(it["verdict"] == "reproduzido" for it in repro_data["items"]), repro_data["differences"]
    repro_raw = (repo / "pacote_repro" / "reproducao.json").read_text(encoding="utf-8")
    repro_md = (repo / "pacote_repro" / "reproducao.md").read_text(encoding="utf-8")
    assert SECRET_VALUE not in repro_raw and SECRET_VALUE not in repro_md
    assert os.environ.get(SECRET_ENV) == SECRET_VALUE
