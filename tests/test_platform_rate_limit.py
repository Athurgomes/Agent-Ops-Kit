"""Testes do store compartilhado de rate limiting (multi-instância, privacidade, concorrência e poda)."""

from __future__ import annotations

import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform import mailer
from aok_platform.app import create_app
from aok_platform.auth import hash_password, hash_token
from aok_platform.db import make_engine
from aok_platform.migrate import run_migrations
from aok_platform.models import Organization, PlatformOperator, RateLimitEntry, User
from aok_platform.rate_limit import HourlyLimiter, LoginThrottle
from conftest import TEST_DB_URL, pg_schema_url
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

SAMPLE_CRED = "senha-de-teste-123"
NEW_CRED = "senha-nova-bem-longa-9"
BASE = "https://farol.example"
LINK = re.compile(r"https://farol\.example/reset-password#token=([A-Za-z0-9_-]+)")


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch):
    monkeypatch.setattr("aok_platform.auth._SCRYPT", {"n": 2**4, "r": 8, "p": 1})


def _setup_shared_apps(monkeypatch, tmp_path, *, ops=False, recovery=False):
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", "chave-teste-local")
    if ops:
        monkeypatch.setenv("AOK_OPS_ENABLED", "true")
    else:
        monkeypatch.delenv("AOK_OPS_ENABLED", raising=False)
    if recovery:
        monkeypatch.setenv("AOK_SMTP_HOST", "smtp.test")
        monkeypatch.setenv("AOK_PUBLIC_URL", BASE)
    else:
        monkeypatch.delenv("AOK_SMTP_HOST", raising=False)
        monkeypatch.delenv("AOK_PUBLIC_URL", raising=False)

    db_url = f"sqlite:///{tmp_path / 'shared.db'}"
    data_dir = tmp_path / "data"
    app_a = create_app(db_url, data_dir=data_dir)
    app_b = create_app(db_url, data_dir=data_dir)
    return app_a, app_b, db_url


def test_login_throttle_compartilhado_entre_instancias_e_destrava_apos_expiracao(monkeypatch, tmp_path):
    app_a, app_b, _ = _setup_shared_apps(monkeypatch, tmp_path)
    try:
        with Session(app_a.state.engine) as s:
            org = s.scalars(select(Organization)).one()
            s.add(User(org_id=org.id, email="ana@x.com", password_hash=hash_password(SAMPLE_CRED), active=True))
            s.commit()

        now = [10_000.0]
        app_a.state.throttle.clock = lambda: now[0]
        app_b.state.throttle.clock = lambda: now[0]

        ca = TestClient(app_a)
        cb = TestClient(app_b)
        bad = {"email": "ana@x.com", "password": "errada"}
        good = {"email": "ana@x.com", "password": SAMPLE_CRED}

        for _ in range(3):
            assert ca.post("/v1/auth/login", json=bad).status_code == 401
        for _ in range(2):
            assert cb.post("/v1/auth/login", json=bad).status_code == 401

        ra = ca.post("/v1/auth/login", json=good)
        rb = cb.post("/v1/auth/login", json=good)
        assert ra.status_code == 429 and int(ra.headers["retry-after"]) > 0
        assert rb.status_code == 429 and int(rb.headers["retry-after"]) > 0

        now[0] += 301.0
        assert cb.post("/v1/auth/login", json=good).status_code == 200
        assert ca.post("/v1/auth/login", json=bad).status_code == 401
        assert ca.post("/v1/auth/login", json=good).status_code == 200
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()


def test_isolamento_de_buckets_entre_login_e_ops_login(monkeypatch, tmp_path):
    app_a, app_b, _ = _setup_shared_apps(monkeypatch, tmp_path, ops=True)
    try:
        with Session(app_a.state.engine) as s:
            org = s.scalars(select(Organization)).one()
            pw = hash_password(SAMPLE_CRED)
            s.add(User(org_id=org.id, email="mesmo@x.com", password_hash=pw, active=True))
            s.add(User(org_id=org.id, email="outro@x.com", password_hash=pw, active=True))
            s.add(PlatformOperator(email="mesmo@x.com", password_hash=pw, active=True))
            s.add(PlatformOperator(email="outro@x.com", password_hash=pw, active=True))
            s.commit()

        ca = TestClient(app_a)
        cb = TestClient(app_b)

        # Trava bucket "login" para mesmo@x.com na instância A
        for _ in range(5):
            assert ca.post("/v1/auth/login", json={"email": "mesmo@x.com", "password": "errada"}).status_code == 401
        assert cb.post("/v1/auth/login", json={"email": "mesmo@x.com", "password": SAMPLE_CRED}).status_code == 429
        # Bucket "ops_login" para o mesmo e-mail continua livre na B
        assert cb.post("/v1/ops/auth/login", json={"email": "mesmo@x.com", "password": SAMPLE_CRED}).status_code == 200

        # Trava bucket "ops_login" para outro@x.com na B; bucket "login" para outro@x.com continua livre na A
        for _ in range(5):
            assert cb.post("/v1/ops/auth/login", json={"email": "outro@x.com", "password": "errada"}).status_code == 401
        assert ca.post("/v1/ops/auth/login", json={"email": "outro@x.com", "password": SAMPLE_CRED}).status_code == 429
        assert ca.post("/v1/auth/login", json={"email": "outro@x.com", "password": SAMPLE_CRED}).status_code == 200
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()


def test_recovery_limiters_somam_entre_instancias(monkeypatch, tmp_path):
    app_a, app_b, _ = _setup_shared_apps(monkeypatch, tmp_path, recovery=True)
    mails = []
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, text, html=None: mails.append({"to": to, "text": text}))
    monkeypatch.setenv("AOK_TRUSTED_PROXIES", "127.0.0.1")
    try:
        with Session(app_a.state.engine) as s:
            org = s.scalars(select(Organization)).one()
            pw = hash_password(SAMPLE_CRED)
            s.add(User(org_id=org.id, email="ana@x.com", password_hash=pw, active=True))
            s.add_all([User(org_id=org.id, email=f"u{i}@x.com", password_hash=pw, active=True) for i in range(12)])
            s.commit()

        ca = TestClient(app_a, client=("127.0.0.1", 50001))
        cb = TestClient(app_b, client=("127.0.0.1", 50002))

        # Limite por e-mail (3/h): 2 na A + 1 na B enviam; 4º na B não envia
        assert ca.post("/v1/auth/password/forgot", json={"email": "ana@x.com"}, headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 202
        assert ca.post("/v1/auth/password/forgot", json={"email": "ana@x.com"}, headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 202
        assert cb.post("/v1/auth/password/forgot", json={"email": "ana@x.com"}, headers={"X-Forwarded-For": "198.51.100.3"}).status_code == 202
        assert cb.post("/v1/auth/password/forgot", json={"email": "ana@x.com"}, headers={"X-Forwarded-For": "198.51.100.4"}).status_code == 202
        assert len(mails) == 3

        good_tok = LINK.search(mails[-1]["text"]).group(1)

        # Limite por IP (10/h): 6 na A + 4 na B para o mesmo IP; 11º na A não envia
        mails.clear()
        ip_hdr = {"X-Forwarded-For": "203.0.113.50"}
        for i in range(6):
            assert ca.post("/v1/auth/password/forgot", json={"email": f"u{i}@x.com"}, headers=ip_hdr).status_code == 202
        for i in range(6, 10):
            assert cb.post("/v1/auth/password/forgot", json={"email": f"u{i}@x.com"}, headers=ip_hdr).status_code == 202
        assert ca.post("/v1/auth/password/forgot", json={"email": "u10@x.com"}, headers=ip_hdr).status_code == 202
        assert len(mails) == 10

        # Limite de falhas do /reset (10/h): 6 na A + 4 na B -> 400; 11ª na B -> 429; token válido na A passa
        reset_hdr = {"X-Forwarded-For": "203.0.113.99"}
        for _ in range(6):
            assert ca.post("/v1/auth/password/reset", json={"token": "errado", "new_password": NEW_CRED}, headers=reset_hdr).status_code == 400
        for _ in range(4):
            assert cb.post("/v1/auth/password/reset", json={"token": "errado", "new_password": NEW_CRED}, headers=reset_hdr).status_code == 400
        assert cb.post("/v1/auth/password/reset", json={"token": "errado", "new_password": NEW_CRED}, headers=reset_hdr).status_code == 429
        assert ca.post("/v1/auth/password/reset", json={"token": good_tok, "new_password": NEW_CRED}, headers=reset_hdr).status_code == 204
        assert cb.post("/v1/auth/password/reset", json={"token": good_tok, "new_password": NEW_CRED}, headers=reset_hdr).status_code == 429
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()


def test_privacidade_rate_limit_entry_apenas_hash_sha256(monkeypatch, tmp_path):
    app_a, app_b, _ = _setup_shared_apps(monkeypatch, tmp_path, ops=True, recovery=True)
    monkeypatch.setattr(mailer, "send_mail", lambda *args, **kwargs: None)
    monkeypatch.setenv("AOK_TRUSTED_PROXIES", "127.0.0.1")
    try:
        c = TestClient(app_a, client=("127.0.0.1", 50001))
        user_email = "privado@exemplo.test"
        op_email = "operador@exemplo.test"
        ip_forgot = "203.0.113.77"
        ip_reset = "203.0.113.88"

        c.post("/v1/auth/login", json={"email": user_email, "password": "errada"})
        c.post("/v1/ops/auth/login", json={"email": op_email, "password": "errada"})
        c.post("/v1/auth/password/forgot", json={"email": user_email}, headers={"X-Forwarded-For": ip_forgot})
        c.post("/v1/auth/password/reset", json={"token": "errado", "new_password": NEW_CRED}, headers={"X-Forwarded-For": ip_reset})

        with Session(app_a.state.engine) as s:
            rows = list(s.scalars(select(RateLimitEntry)))
            raw_dump = s.execute(text("SELECT bucket, key_hash, count, window_start, locked_until, expires_at FROM rate_limit_entry")).all()

        assert {(r.bucket, r.key_hash) for r in rows} == {
            ("login", hash_token(user_email)),
            ("ops_login", hash_token(op_email)),
            ("forgot_email", hash_token(user_email)),
            ("forgot_ip", hash_token(ip_forgot)),
            ("reset_fail", hash_token(ip_reset)),
        }
        for r in rows:
            assert re.fullmatch(r"[0-9a-f]{64}", r.key_hash)
        serialized = repr(raw_dump)
        for sensitive in (user_email, op_email, ip_forgot, ip_reset, "privado", "operador", "203.0.113"):
            assert sensitive not in serialized
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()


def test_concorrencia_threads_deterministica(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'concurrent.db'}"
    eng_a = make_engine(db_url)
    eng_b = make_engine(db_url)
    try:
        run_migrations(eng_a)
        fac_a = sessionmaker(eng_a, expire_on_commit=False)
        fac_b = sessionmaker(eng_b, expire_on_commit=False)

        t_a = LoginThrottle(max_failures=12, lock_seconds=300, factory=fac_a, bucket="login")
        t_b = LoginThrottle(max_failures=12, lock_seconds=300, factory=fac_b, bucket="login")

        barrier = threading.Barrier(12)

        def worker_fail(idx: int):
            barrier.wait()
            (t_a if idx % 2 == 0 else t_b).fail("corrida@x.com")

        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(worker_fail, range(12)))

        assert t_a.retry_after("corrida@x.com") > 0
        assert t_b.retry_after("corrida@x.com") > 0

        h_a = HourlyLimiter(20, factory=fac_a, bucket="forgot_ip")
        h_b = HourlyLimiter(20, factory=fac_b, bucket="forgot_ip")
        barrier2 = threading.Barrier(24)

        def worker_hit(idx: int) -> bool:
            barrier2.wait()
            return (h_a if idx % 2 == 0 else h_b).hit("198.51.100.10")

        with ThreadPoolExecutor(max_workers=24) as pool:
            results = list(pool.map(worker_hit, range(24)))

        assert results.count(True) == 20
        assert results.count(False) == 4
        with Session(eng_a) as s:
            row = s.scalar(
                select(RateLimitEntry).where(
                    RateLimitEntry.bucket == "forgot_ip",
                    RateLimitEntry.key_hash == hash_token("198.51.100.10"),
                )
            )
            assert row is not None and row.count == 24
    finally:
        eng_a.dispose()
        eng_b.dispose()


def test_poda_automatica_de_entradas_vencidas(monkeypatch, tmp_path):
    app_a, app_b, _ = _setup_shared_apps(monkeypatch, tmp_path)
    try:
        now = [1000.0]
        throttle = app_a.state.throttle
        throttle.clock = lambda: now[0]
        limiter = app_a.state.recovery_limiters["email"]
        limiter.clock = lambda: now[0]

        for i in range(3):
            throttle.fail(f"old{i}@x.com")
        for i in range(2):
            limiter.hit(f"old{i}@x.com")

        now[0] = 5000.0  # todas as entradas acima expiraram (300s e 3600s)
        throttle.fail("ativo@x.com")
        limiter.hit("ativo@x.com")

        # Dispara a poda automática periódica padrão (64 escritas)
        for i in range(throttle.prune_every):
            throttle.fail(f"novo{i}@x.com")
        for i in range(limiter.prune_every):
            limiter.hit(f"novo{i}@x.com")

        with Session(app_a.state.engine) as s:
            login_keys = {
                r.key_hash
                for r in s.scalars(select(RateLimitEntry).where(RateLimitEntry.bucket == "login"))
            }
            email_keys = {
                r.key_hash
                for r in s.scalars(select(RateLimitEntry).where(RateLimitEntry.bucket == "forgot_email"))
            }

        for i in range(3):
            assert hash_token(f"old{i}@x.com") not in login_keys
        for i in range(2):
            assert hash_token(f"old{i}@x.com") not in email_keys
        assert hash_token("ativo@x.com") in login_keys
        assert hash_token("ativo@x.com") in email_keys
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()


def test_fallback_em_memoria_sem_factory():
    now = [100.0]
    t = LoginThrottle(max_failures=2, lock_seconds=60, clock=lambda: now[0])
    t.fail("a@b.com")
    assert t.retry_after("a@b.com") == 0
    t.fail("a@b.com")
    assert t.retry_after("a@b.com") > 0
    now[0] += 61.0
    assert t.retry_after("a@b.com") == 0
    t.fail("a@b.com")
    t.ok("a@b.com")
    assert t.retry_after("a@b.com") == 0

    h = HourlyLimiter(2, window=10.0, clock=lambda: now[0])
    assert h.hit("k") is True
    assert h.hit("k") is True
    assert h.exceeded("k") is True
    assert h.hit("k") is False
    now[0] += 11.0
    assert h.exceeded("k") is False
    assert h.hit("k") is True


@pytest.mark.skipif(not TEST_DB_URL, reason="defina AOK_TEST_DATABASE_URL (Postgres) para rodar")
def test_postgres_concorrencia_e_multi_instancia(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    schema = f"t_rl_{uuid.uuid4().hex[:10]}"
    admin = create_engine(TEST_DB_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = pg_schema_url(schema)
    app_a = create_app(url, data_dir=tmp_path / "da")
    app_b = create_app(url, data_dir=tmp_path / "db")
    try:
        with Session(app_a.state.engine) as s:
            org = s.scalars(select(Organization)).one()
            s.add(User(org_id=org.id, email="pg@x.com", password_hash=hash_password(SAMPLE_CRED), active=True))
            s.commit()

        ca = TestClient(app_a)
        cb = TestClient(app_b)
        for _ in range(3):
            assert ca.post("/v1/auth/login", json={"email": "pg@x.com", "password": "errada"}).status_code == 401
        for _ in range(2):
            assert cb.post("/v1/auth/login", json={"email": "pg@x.com", "password": "errada"}).status_code == 401
        assert cb.post("/v1/auth/login", json={"email": "pg@x.com", "password": SAMPLE_CRED}).status_code == 429

        h_a = HourlyLimiter(16, factory=app_a.state.session_factory, bucket="pg_race")
        h_b = HourlyLimiter(16, factory=app_b.state.session_factory, bucket="pg_race")
        barrier = threading.Barrier(20)

        def worker(idx: int) -> bool:
            barrier.wait()
            return (h_a if idx % 2 == 0 else h_b).hit("198.51.100.77")

        with ThreadPoolExecutor(max_workers=20) as pool:
            res = list(pool.map(worker, range(20)))
        assert res.count(True) == 16 and res.count(False) == 4
    finally:
        app_a.state.engine.dispose()
        app_b.state.engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
