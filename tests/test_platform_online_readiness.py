"""Online readiness checks: /v1/health, docs toggle, security headers/HSTS, and trusted proxy IPs."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform import mailer
from aok_platform.app import _env_bool, create_app
from aok_platform.auth import hash_password
from aok_platform.models import Organization, User
from aok_platform.recovery import client_ip
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers


def _fake_request(
    host: str | None = "127.0.0.1",
    xff: str | list[str] | None = None,
) -> SimpleNamespace:
    raw: list[tuple[bytes, bytes]] = []
    if isinstance(xff, list):
        raw = [(b"x-forwarded-for", v.encode("latin-1")) for v in xff]
    elif xff is not None:
        raw = [(b"x-forwarded-for", xff.encode("latin-1"))]
    client = SimpleNamespace(host=host, port=50000) if host is not None else None
    return SimpleNamespace(client=client, headers=Headers(raw=raw))


def _dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>portal</title>", encoding="utf-8")
    return d


# ---- _env_bool and /v1/health -------------------------------------------------------------------


def test_env_bool_parses_variants_and_defaults(monkeypatch):
    monkeypatch.delenv("AOK_TEST_FLAG", raising=False)
    assert _env_bool("AOK_TEST_FLAG", True) is True
    assert _env_bool("AOK_TEST_FLAG", False) is False

    for raw in ("", "   ", "unexpected"):
        monkeypatch.setenv("AOK_TEST_FLAG", raw)
        assert _env_bool("AOK_TEST_FLAG", True) is True
        assert _env_bool("AOK_TEST_FLAG", False) is False

    for raw in ("true", "TRUE", " 1 ", "Yes", "on"):
        monkeypatch.setenv("AOK_TEST_FLAG", raw)
        assert _env_bool("AOK_TEST_FLAG", False) is True

    for raw in ("false", "FALSE", " 0 ", "No", "off"):
        monkeypatch.setenv("AOK_TEST_FLAG", raw)
        assert _env_bool("AOK_TEST_FLAG", True) is False


def test_health_ok_and_creates_data_dir(tmp_path):
    data_dir = tmp_path / "nested" / "data"
    app = create_app("sqlite:///:memory:", data_dir=data_dir)
    c = TestClient(app)

    r = c.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
    assert r.headers["cache-control"] == "no-store"
    assert data_dir.is_dir()


def test_health_returns_503_without_leaking_db_details(monkeypatch, tmp_path):
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    c = TestClient(app)

    def broken_factory():
        raise RuntimeError("postgresql://aok:super-secret@db.internal:5432/aok connection refused")

    monkeypatch.setattr(app.state, "session_factory", broken_factory)
    r = c.get("/v1/health")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable"}
    assert r.headers["cache-control"] == "no-store"
    assert "super-secret" not in r.text
    assert "postgresql://" not in r.text
    assert "Traceback" not in r.text


def test_health_returns_503_when_execute_or_data_dir_fails(monkeypatch, tmp_path):
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    c = TestClient(app)

    class BrokenSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, *_args, **_kwargs):
            raise OSError("sqlite:///secret/path.db failed")

    monkeypatch.setattr(app.state, "session_factory", BrokenSession)
    r = c.get("/v1/health")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable"}
    assert r.headers["cache-control"] == "no-store"
    assert "secret" not in r.text

    not_a_dir = tmp_path / "file_not_dir"
    not_a_dir.write_text("occupied", encoding="utf-8")
    app_bad_dir = create_app("sqlite:///:memory:", data_dir=not_a_dir)
    r2 = TestClient(app_bad_dir).get("/v1/health")
    assert r2.status_code == 503
    assert r2.json() == {"status": "unavailable"}
    assert r2.headers["cache-control"] == "no-store"
    assert "file_not_dir" not in r2.text


# ---- docs toggle and security headers -----------------------------------------------------------


def test_docs_enabled_by_default_and_disabled_with_env(monkeypatch, tmp_path):
    monkeypatch.delenv("AOK_DOCS_ENABLED", raising=False)
    monkeypatch.setenv("AOK_PORTAL_DIR", str(tmp_path / "no-dist"))
    c_default = TestClient(create_app("sqlite:///:memory:", data_dir=tmp_path / "d1"))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c_default.get(path).status_code == 200

    monkeypatch.setenv("AOK_DOCS_ENABLED", "false")
    c_off = TestClient(create_app("sqlite:///:memory:", data_dir=tmp_path / "d2"))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c_off.get(path).status_code == 404
    assert c_off.get("/v1/health").status_code == 200

    # Also returns 404 when the SPA portal is mounted.
    monkeypatch.setenv("AOK_PORTAL_DIR", str(_dist(tmp_path)))
    c_spa = TestClient(create_app("sqlite:///:memory:", data_dir=tmp_path / "d3"))
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c_spa.get(path).status_code == 404
    assert c_spa.get("/").status_code == 200
    assert c_spa.get("/v1/health").status_code == 200


def test_security_headers_and_optional_hsts(monkeypatch, tmp_path):
    monkeypatch.delenv("AOK_HSTS_ENABLED", raising=False)
    monkeypatch.setenv("AOK_PORTAL_DIR", str(_dist(tmp_path)))
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    c = TestClient(app)

    for path in ("/v1/health", "/v1/auth/capabilities", "/v1/areas"):
        r = c.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "strict-transport-security" not in r.headers

    spa = c.get("/")
    assert spa.status_code == 200
    assert "default-src 'self'" in spa.headers["content-security-policy"]
    assert spa.headers["x-content-type-options"] == "nosniff"
    assert spa.headers["x-frame-options"] == "DENY"
    assert spa.headers["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in spa.headers

    monkeypatch.setenv("AOK_HSTS_ENABLED", "true")
    r_hsts = c.get("/v1/health")
    assert r_hsts.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert c.get("/v1/areas").headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )


# ---- client_ip and trusted proxy rate limiting --------------------------------------------------


def test_client_ip_without_and_with_trusted_proxies(monkeypatch, caplog):
    monkeypatch.delenv("AOK_TRUSTED_PROXIES", raising=False)
    assert client_ip(_fake_request("127.0.0.1", "198.51.100.7")) == "127.0.0.1"
    assert client_ip(_fake_request(None, "198.51.100.7")) == "unknown"

    monkeypatch.setenv("AOK_TRUSTED_PROXIES", "127.0.0.1")
    assert client_ip(_fake_request("127.0.0.1", "1.2.3.4, 198.51.100.7")) == "198.51.100.7"
    assert client_ip(_fake_request("198.51.100.99", "203.0.113.5")) == "198.51.100.99"
    assert client_ip(_fake_request("testclient", "203.0.113.5")) == "testclient"
    assert client_ip(_fake_request("127.0.0.1", "invalid, not-an-ip")) == "127.0.0.1"

    monkeypatch.setenv("AOK_TRUSTED_PROXIES", "127.0.0.1, 10.0.0.0/8, ::1/128")
    assert (
        client_ip(_fake_request("127.0.0.1", "1.2.3.4, 198.51.100.7, 10.0.0.5"))
        == "198.51.100.7"
    )
    assert client_ip(_fake_request("127.0.0.1", "10.0.0.1, 10.0.0.2")) == "10.0.0.1"
    assert client_ip(_fake_request("::1", ["1.2.3.4", "2001:0db8::1"])) == "2001:db8::1"

    monkeypatch.setenv("AOK_TRUSTED_PROXIES", "not-a-cidr, 127.0.0.1, 999.999.999.999")
    with caplog.at_level(logging.WARNING, logger="aok_platform.recovery"):
        resolved = client_ip(_fake_request("127.0.0.1", "198.51.100.7"))
    assert resolved == "198.51.100.7"
    assert "not-a-cidr" in caplog.text


def test_recovery_rate_limit_honors_trusted_proxies_and_ignores_spoofing(monkeypatch, tmp_path):
    monkeypatch.setattr("aok_platform.auth._SCRYPT", {"n": 2**4, "r": 8, "p": 1})
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    monkeypatch.setenv("AOK_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("AOK_PUBLIC_URL", "https://farol.example")
    monkeypatch.setenv("AOK_TRUSTED_PROXIES", "127.0.0.1")

    mails = []
    monkeypatch.setattr(
        mailer,
        "send_mail",
        lambda to, subject, text, html=None: mails.append({"to": to, "subject": subject}),
    )

    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    with Session(app.state.engine) as s:
        org = s.scalars(select(Organization)).first()
        pw = hash_password("senha-de-teste-123")
        s.add_all(
            [
                User(org_id=org.id, email=f"u{i}@x.com", password_hash=pw, active=True)
                for i in range(12)
            ]
        )
        s.commit()

    proxy_client = TestClient(app, client=("127.0.0.1", 50000))

    # 10 forgot requests with different spoofed left IPs but same real client IP (198.51.100.7).
    for i in range(10):
        r = proxy_client.post(
            "/v1/auth/password/forgot",
            json={"email": f"u{i}@x.com"},
            headers={"X-Forwarded-For": f"203.0.113.{i + 1}, 198.51.100.7"},
        )
        assert r.status_code == 202
    assert len(mails) == 10

    # 11th request for 198.51.100.7 is blocked by IP limiter (202 without sending mail).
    r_blocked = proxy_client.post(
        "/v1/auth/password/forgot",
        json={"email": "u10@x.com"},
        headers={"X-Forwarded-For": "203.0.113.99, 198.51.100.7"},
    )
    assert r_blocked.status_code == 202
    assert len(mails) == 10

    # Different real client IP behind the same trusted proxy still succeeds.
    r_other = proxy_client.post(
        "/v1/auth/password/forgot",
        json={"email": "u11@x.com"},
        headers={"X-Forwarded-For": "198.51.100.8"},
    )
    assert r_other.status_code == 202
    assert len(mails) == 11

    # Reset failure rate limit tracks the extracted client IP, not the proxy IP.
    for _ in range(10):
        r_fail = proxy_client.post(
            "/v1/auth/password/reset",
            json={"token": "bad-token-value", "new_password": "nova-senha-bem-longa-9"},
            headers={"X-Forwarded-For": "1.2.3.4, 198.51.100.7"},
        )
        assert r_fail.status_code == 400
    assert (
        proxy_client.post(
            "/v1/auth/password/reset",
            json={"token": "bad-token-value", "new_password": "nova-senha-bem-longa-9"},
            headers={"X-Forwarded-For": "198.51.100.7"},
        ).status_code
        == 429
    )
    assert (
        proxy_client.post(
            "/v1/auth/password/reset",
            json={"token": "bad-token-value", "new_password": "nova-senha-bem-longa-9"},
            headers={"X-Forwarded-For": "198.51.100.8"},
        ).status_code
        == 400
    )

    # Without AOK_TRUSTED_PROXIES, X-Forwarded-For is ignored and the proxy peer IP is used.
    monkeypatch.delenv("AOK_TRUSTED_PROXIES", raising=False)
    for i in range(10):
        assert (
            proxy_client.post(
                "/v1/auth/password/reset",
                json={"token": "bad-token-value", "new_password": "nova-senha-bem-longa-9"},
                headers={"X-Forwarded-For": f"198.51.100.{20 + i}"},
            ).status_code
            == 400
        )
    assert (
        proxy_client.post(
            "/v1/auth/password/reset",
            json={"token": "bad-token-value", "new_password": "nova-senha-bem-longa-9"},
            headers={"X-Forwarded-For": "198.51.100.99"},
        ).status_code
        == 429
    )
