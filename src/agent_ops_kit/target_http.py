"""Cliente HTTP seguro para auditar agentes externos (`target.type == "http"`).

Garantias de segurança na camada de transporte:
- Revalida URL (https por padrão, http só em loopback com allow_insecure_localhost=True).
- Anti-SSRF antes e depois de `socket.getaddrinfo` (todos os IPs resolvidos), conectando
  diretamente aos endereços validados (evita DNS rebinding sem quebrar SNI/TLS).
- Desabilita proxies de ambiente (`ProxyHandler({})`) e recusa redirects 3xx sem seguir.
- Lê o segredo de `os.environ.get(auth_env)` apenas no momento da chamada, nunca expondo em
  erros ou logs; respeita `timeout_s`, `max_response_bytes` (leitura em chunks) e `max_calls`.
"""

from __future__ import annotations

import errno
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agent_ops_kit.config import (
    TargetConfig,
    _is_valid_header_value,
    sanitize_url,
    validate_http_url,
)
from agent_ops_kit.target import ContractError, TargetError, validate_response

_BLOCKED_HOSTS = frozenset({
    "metadata",
    "metadata.google.internal",
    "metadata.google",
    "instance-data",
    "instance-data.ec2.internal",
})
_THIS_NETWORK = ipaddress.IPv4Network("0.0.0.0/8")
_ALIBABA_METADATA = ipaddress.IPv4Address("100.100.100.200")
_AWS_IPV6_METADATA = ipaddress.IPv6Address("fd00:ec2::254")
_PLACEHOLDER_RE = re.compile(r"\{\{(question|context|tools)\}\}")
_MISSING = object()
_CHUNK_SIZE = 65_536


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, require_loopback: bool) -> None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
        or (ip.is_reserved and not ip.is_loopback)
        or (isinstance(ip, ipaddress.IPv4Address) and ip in _THIS_NETWORK)
        or ip in (_AWS_IPV6_METADATA, _ALIBABA_METADATA)
    ):
        raise TargetError(f"endereço IP bloqueado por política anti-SSRF: {ip}")
    if require_loopback and not ip.is_loopback:
        raise TargetError(f"HTTP sem TLS exige endereço loopback; resolvido {ip}")


def _parse_ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    return ipaddress.ip_address(raw.split("%", 1)[0])


def validate_url_safety(
    url: str, *, allow_insecure_localhost: bool = False
) -> tuple[str, str, int, str]:
    """Valida URL e checa hostnames de metadados/IPs literais proibidos (offline)."""
    try:
        validate_http_url(url, allow_insecure_localhost=allow_insecure_localhost)
    except ValueError as exc:
        raise TargetError(str(exc)) from exc
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    if "%" in host:
        raise TargetError("host HTTP inválido")
    try:
        host_ascii = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise TargetError("host HTTP inválido") from None
    host_norm = host_ascii.rstrip(".").lower()
    if host_norm in _BLOCKED_HOSTS or host_norm.endswith(".metadata.google.internal"):
        raise TargetError(f"host de metadados bloqueado por política anti-SSRF: {host}")
    try:
        ip = _parse_ip(host_ascii)
    except ValueError:
        pass
    else:
        _check_ip(ip, require_loopback=(scheme == "http"))
    port = parsed.port or (443 if scheme == "https" else 80)
    host_fmt = f"[{host_ascii}]" if ":" in host_ascii else host_ascii
    netloc = f"{host_fmt}:{parsed.port}" if parsed.port is not None else host_fmt
    safe_url = urlunsplit((scheme, netloc, parsed.path, "", ""))
    return scheme, host_ascii, port, safe_url


def _resolve_and_check_ips(host: str, port: int, *, require_loopback: bool) -> list[tuple]:
    try:
        infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except OSError as exc:
        raise TargetError(f"falha ao resolver host HTTP {host!r}: {exc}") from exc
    if not infos:
        raise TargetError(f"nenhum endereço IP resolvido para {host!r}")
    for info in infos:
        sockaddr = info[4]
        try:
            ip = _parse_ip(str(sockaddr[0]))
        except ValueError as exc:
            raise TargetError(f"endereço IP inválido retornado pelo DNS: {sockaddr[0]!r}") from exc
        _check_ip(ip, require_loopback=require_loopback)
    return infos


def _connect_pinned(
    infos: list[tuple], deadline: float, source_address: tuple[str, int] | None = None
) -> socket.socket:
    last_err: OSError | None = None
    for af, socktype, proto, _, sa in infos:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("tempo limite excedido ao conectar")
        sock: socket.socket | None = None
        try:
            sock = socket.socket(af, socktype, proto)
            sock.settimeout(remaining)
            if source_address is not None:
                sock.bind(source_address)
            sock.connect(sa)
            return sock
        except OSError as exc:
            last_err = exc
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    if last_err is not None:
        raise last_err
    raise OSError(errno.ENETUNREACH, "não foi possível conectar")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if fp is not None:
            fp.close()
        raise TargetError(f"redirect HTTP ({code}) recusado para target HTTP")


def _build_opener(infos: list[tuple], deadline: float, ssl_ctx: ssl.SSLContext):
    sock_ref: list[socket.socket] = []

    def _create_conn(_address, _timeout=None, source_address=None):
        return _connect_pinned(infos, deadline, source_address)

    class _PinnedMixin:
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._create_connection = _create_conn

        def connect(self):
            super().connect()
            sock_ref.append(self.sock)

    class _PinnedHTTPConnection(_PinnedMixin, http.client.HTTPConnection):
        pass

    class _PinnedHTTPSConnection(_PinnedMixin, http.client.HTTPSConnection):
        pass

    class _PinnedHTTPHandler(urllib.request.HTTPHandler):
        def http_open(self, req):
            return self.do_open(_PinnedHTTPConnection, req)

    class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, req):
            return self.do_open(_PinnedHTTPSConnection, req, context=self._context)

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _PinnedHTTPHandler(),
        _PinnedHTTPSHandler(context=ssl_ctx),
        _NoRedirectHandler(),
    )
    return opener, sock_ref


def _as_text(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False)


def render_request_body(template: dict[str, Any] | None, request: dict[str, Any]) -> bytes:
    """Monta o JSON da requisição substituindo placeholders em passada única."""
    values = {
        "question": request.get("question"),
        "context": request.get("context"),
        "tools": request.get("tools"),
    }
    if template is None:
        return json.dumps(values, ensure_ascii=False).encode("utf-8")

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, str):
            match = _PLACEHOLDER_RE.fullmatch(node)
            if match:
                return values[match.group(1)]
            return _PLACEHOLDER_RE.sub(lambda m: _as_text(values[m.group(1)]), node)
        return node

    return json.dumps(_walk(template), ensure_ascii=False).encode("utf-8")


def extract_dot_path(data: Any, path: str) -> Any:
    """Extrai valor por caminho pontilhado (com índices de lista, ex.: choices.0.message.content)."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return _MISSING
        else:
            return _MISSING
    return cur


def parse_http_response(body_bytes: bytes, target_cfg: TargetConfig) -> dict:
    """Decodifica JSON, extrai campos configurados e aplica `validate_response`."""
    try:
        text = body_bytes.decode("utf-8")
        data = json.loads(text)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ContractError(f"resposta HTTP não é JSON UTF-8 válido: {exc}") from exc
    if not isinstance(data, (dict, list)):
        raise ContractError(f"resposta JSON deve ser objeto ou lista, veio {type(data).__name__}")
    answer = extract_dot_path(data, target_cfg.answer_path)
    if answer is _MISSING:
        raise ContractError(f"caminho answer_path {target_cfg.answer_path!r} não encontrado na resposta HTTP")
    tool_calls = None
    if target_cfg.tool_calls_path is not None:
        raw_tc = extract_dot_path(data, target_cfg.tool_calls_path)
        tool_calls = None if raw_tc is _MISSING else raw_tc
    trace_id = None
    if target_cfg.trace_id_path is not None:
        raw_tid = extract_dot_path(data, target_cfg.trace_id_path)
        trace_id = None if raw_tid is _MISSING else raw_tid
    return validate_response({"answer": answer, "tool_calls": tool_calls, "trace_id": trace_id})


def _build_headers(target_cfg: TargetConfig) -> dict[str, str]:
    headers: dict[str, str] = {}
    lower_keys: dict[str, str] = {}
    for k, v in target_cfg.headers.items():
        lk = k.lower()
        if lk in lower_keys:
            headers.pop(lower_keys[lk], None)
        lower_keys[lk] = k
        headers[k] = v
    if "content-type" not in lower_keys:
        headers["Content-Type"] = "application/json"
    if "accept" not in lower_keys:
        headers["Accept"] = "application/json"
    if target_cfg.auth_env:
        secret = os.environ.get(target_cfg.auth_env, "")
        if not secret.strip():
            raise TargetError(
                f"variável de ambiente {target_cfg.auth_env} ausente ou vazia para autenticação HTTP"
            )
        header_val = f"{target_cfg.auth_prefix}{secret}"
        if not _is_valid_header_value(secret) or not _is_valid_header_value(header_val):
            raise TargetError(
                f"valor da variável {target_cfg.auth_env} contém caractere inválido para cabeçalho HTTP"
            )
        headers[target_cfg.auth_header] = header_val
    return headers


def _read_bounded(
    resp: Any,
    max_bytes: int,
    deadline: float,
    timeout_s: float,
    sock: socket.socket | None = None,
) -> bytes:
    content_len = resp.headers.get("Content-Length") if resp.headers else None
    if content_len is not None:
        try:
            if int(content_len) > max_bytes:
                raise ContractError(
                    f"resposta HTTP excedeu o limite max_response_bytes ({max_bytes} bytes)"
                )
        except ValueError:
            pass
    read_fn = getattr(resp, "read1", resp.read)
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TargetError(f"tempo limite de {timeout_s}s excedido ao ler resposta HTTP")
        if sock is not None:
            try:
                sock.settimeout(remaining)
            except OSError:
                pass
        to_read = min(_CHUNK_SIZE, max_bytes - total + 1)
        chunk = read_fn(to_read)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ContractError(
                f"resposta HTTP excedeu o limite max_response_bytes ({max_bytes} bytes)"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def make_http_caller(target_cfg: TargetConfig) -> Callable[[dict], dict]:
    """Cria função chamável `fn(request)` para `TargetConfig(type='http')`."""
    if not target_cfg.url:
        raise TargetError("target.url é obrigatório para target.type='http'")
    validate_url_safety(
        target_cfg.url, allow_insecure_localhost=target_cfg.allow_insecure_localhost
    )
    lock = threading.Lock()
    call_count = 0
    ssl_ctx = ssl.create_default_context()

    def call_http(request: dict[str, Any]) -> dict:
        nonlocal call_count
        with lock:
            if target_cfg.max_calls is not None and call_count >= target_cfg.max_calls:
                raise TargetError(
                    f"limite de chamadas (max_calls={target_cfg.max_calls}) excedido"
                )
            call_count += 1

        scheme, host, port, safe_url = validate_url_safety(
            target_cfg.url or "",
            allow_insecure_localhost=target_cfg.allow_insecure_localhost,
        )
        headers = _build_headers(target_cfg)
        body = render_request_body(target_cfg.request_template, request)
        infos = _resolve_and_check_ips(host, port, require_loopback=(scheme == "http"))
        deadline = time.monotonic() + target_cfg.timeout_s
        opener, sock_ref = _build_opener(infos, deadline, ssl_ctx)
        req = urllib.request.Request(safe_url, data=body, headers=headers, method="POST")

        try:
            with opener.open(req, timeout=target_cfg.timeout_s) as resp:
                raw_bytes = _read_bounded(
                    resp,
                    target_cfg.max_response_bytes,
                    deadline,
                    target_cfg.timeout_s,
                    sock=sock_ref[-1] if sock_ref else None,
                )
        except (TargetError, ContractError):
            raise
        except urllib.error.HTTPError as exc:
            try:
                exc.close()
            except OSError:
                pass
            if 300 <= exc.code < 400:
                raise TargetError(f"redirect HTTP ({exc.code}) recusado para target HTTP") from None
            raise TargetError(f"alvo HTTP respondeu status {exc.code}") from None
        except TimeoutError as exc:
            raise TargetError(
                f"tempo limite de {target_cfg.timeout_s}s excedido na chamada HTTP"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TargetError(
                    f"tempo limite de {target_cfg.timeout_s}s excedido na chamada HTTP"
                ) from None
            raise TargetError(f"falha na chamada HTTP: {exc.reason}") from None
        except (http.client.HTTPException, OSError) as exc:
            raise TargetError(f"falha na chamada HTTP: {exc}") from None

        return parse_http_response(raw_bytes, target_cfg)

    return call_http


def http_target_warning(target_cfg: TargetConfig) -> str:
    """Aviso curto em português para imprimir em stderr antes de auditar um alvo HTTP."""
    limit_txt = (
        f"respeita max_calls={target_cfg.max_calls}"
        if target_cfg.max_calls is not None
        else "sem limite max_calls definido"
    )
    return (
        f"Aviso: alvo HTTP ({sanitize_url(target_cfg.url or '')}): use apenas ambiente de "
        f"staging sem efeitos reais; chamadas geram custo na API do cliente ({limit_txt})."
    )
