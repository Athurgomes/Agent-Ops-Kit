"""Recuperação de senha por e-mail: desativada sem SMTP, anti-enumeração, token de uso único, limites."""

import hashlib
import json
import logging
import re
import socketserver
import threading
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform import mailer
from aok_platform.app import create_app
from aok_platform.auth import hash_password
from aok_platform.models import AdminEvent, Organization, PasswordReset, User, UserSession, utcnow
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

PWD = "senha-de-teste-123"
NEW = "senha-nova-bem-longa-9"
BASE = "https://farol.example"
LINK = re.compile(r"https://farol\.example/reset-password#token=([A-Za-z0-9_-]+)")


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch):
    monkeypatch.setattr("aok_platform.auth._SCRYPT", {"n": 2**4, "r": 8, "p": 1})  # só acelera o teste


def _mk_app(monkeypatch, tmp_path, enabled=True):
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", "chave-de-teste-nao-secreta")
    if enabled:
        monkeypatch.setenv("AOK_SMTP_HOST", "smtp.test")
        monkeypatch.setenv("AOK_PUBLIC_URL", BASE + "/")
    else:
        monkeypatch.delenv("AOK_SMTP_HOST", raising=False)
        monkeypatch.delenv("AOK_PUBLIC_URL", raising=False)
    return create_app("sqlite:///:memory:", data_dir=tmp_path / "data")


@pytest.fixture
def rec(monkeypatch, tmp_path):
    """App com recuperação ligada, mailer trocado por um coletor, e usuários de vários estados."""
    app = _mk_app(monkeypatch, tmp_path)
    mails = []
    monkeypatch.setattr(mailer, "send_mail", lambda to, subject, text, html=None: mails.append(
        {"to": to, "subject": subject, "text": text, "html": html}))
    with Session(app.state.engine) as s:
        org = s.scalars(select(Organization)).first()
        dead = Organization(name="Inativa", slug="inativa", active=False)
        s.add(dead)
        s.flush()
        pw = hash_password(PWD)
        s.add_all([
            User(org_id=org.id, email="ana@x.com", password_hash=pw, active=True),
            User(org_id=org.id, email="bob@x.com", password_hash=pw, active=False),
            User(org_id=dead.id, email="cy@x.com", password_hash=pw, active=True),
        ])
        s.commit()
    return app, TestClient(app), mails


def _login(app, email="ana@x.com", password=PWD):
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": email, "password": password}).status_code == 200
    return c


def _forgot(c, email, **kw):
    return c.post("/v1/auth/password/forgot", json={"email": email}, **kw)


def _token(mails, i=-1):
    return LINK.search(mails[i]["text"]).group(1)


# ---- desativado sem SMTP -----------------------------------------------------------------------------


def test_desativado_sem_smtp_ou_sem_url_publica(monkeypatch, tmp_path):
    app = _mk_app(monkeypatch, tmp_path, enabled=False)
    c = TestClient(app)
    assert c.get("/v1/auth/capabilities").json() == {"password_reset": False}
    assert _forgot(c, "ana@x.com").status_code == 404
    assert c.post("/v1/auth/password/reset", json={"token": "x", "new_password": NEW}).status_code == 404
    monkeypatch.setenv("AOK_SMTP_HOST", "smtp.test")  # SMTP sem AOK_PUBLIC_URL: continua desativado
    assert c.get("/v1/auth/capabilities").json() == {"password_reset": False}
    assert _forgot(c, "ana@x.com").status_code == 404
    monkeypatch.setenv("AOK_PUBLIC_URL", BASE)
    assert c.get("/v1/auth/capabilities").json() == {"password_reset": True}


def test_capabilities_ligado(rec):
    _, c, _ = rec
    assert c.get("/v1/auth/capabilities").json() == {"password_reset": True}


# ---- forgot: anti-enumeração ------------------------------------------------------------------------------


def test_forgot_responde_sempre_igual_e_so_envia_quando_devido(rec):
    _app, c, mails = rec
    cases = ["ana@x.com", "ninguem@x.com", "bob@x.com", "cy@x.com", "isto nao e e-mail", "  ANA@x.com "]
    resp = [_forgot(c, e) for e in cases]
    assert {r.status_code for r in resp} == {202}
    assert len({r.text for r in resp}) == 1  # corpo idêntico em todos os casos
    assert [m["to"] for m in mails] == ["ana@x.com", "ana@x.com"]  # só o usuário ativo de org ativa (2 pedidos dela)
    assert resp[0].json() == {"status": "accepted", "detail": "If the email belongs to an active account, a reset link has been sent."}
    assert "set-cookie" not in resp[0].headers


def test_email_tem_so_o_link_com_token_no_fragmento_e_usa_a_url_configurada(rec):
    app, c, mails = rec
    _forgot(c, "ana@x.com", headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example", "Origin": "https://evil.example"})
    m = mails[0]
    assert m["subject"] == "Reset your Farol password"
    for body in (m["text"], m["html"]):
        assert f"{BASE}/reset-password#token=" in body and "evil" not in body and "?token" not in body
    assert "valid for 30 minutes" in m["text"] and "If you didn't request this, ignore it" in m["text"]
    assert "<script" not in m["html"] and PWD not in m["text"] and "Org" not in m["text"]
    token = _token(mails)
    assert len(token) >= 40
    with Session(app.state.engine) as s:
        rows = list(s.scalars(select(PasswordReset)))
        assert len(rows) == 1 and rows[0].token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in json.dumps([r.token_hash for r in rows])  # só o hash no banco
        assert 29 * 60 < (rows[0].expires_at - rows[0].created_at).total_seconds() <= 30 * 60
        assert {c.name for c in PasswordReset.__table__.columns} == {"id", "user_id", "token_hash", "created_at", "expires_at", "used_at"}  # sem IP


# ---- reset ------------------------------------------------------------------------------------------------


def test_reset_ok_troca_senha_revoga_sessoes_e_nao_loga(rec):
    app, c, mails = rec
    old_session = _login(app)
    _forgot(c, "ana@x.com")
    r = c.post("/v1/auth/password/reset", json={"token": _token(mails), "new_password": NEW})
    assert r.status_code == 204 and r.content == b"" and "set-cookie" not in r.headers  # sem login automático
    assert old_session.get("/v1/auth/me").status_code == 401  # todas as sessões caem
    assert TestClient(app).post("/v1/auth/login", json={"email": "ana@x.com", "password": PWD}).status_code == 401
    assert _login(app, password=NEW).get("/v1/auth/me").status_code == 200
    assert mails[-1]["subject"] == "Your Farol password was changed" and mails[-1]["to"] == "ana@x.com"
    assert NEW not in mails[-1]["text"]
    with Session(app.state.engine) as s:  # a sessão antiga foi revogada no banco; só a nova (pós-reset) está ativa
        ana = s.scalar(select(User.id).where(User.email == "ana@x.com"))
        rows = list(s.scalars(select(UserSession).where(UserSession.user_id == ana).order_by(UserSession.id)))
        assert rows[0].revoked_at is not None and all(r.revoked_at is None for r in rows[1:])


def test_segundo_uso_do_token_falha_e_o_evento_nao_tem_segredo(rec):
    app, c, mails = rec
    _forgot(c, "ana@x.com")
    token = _token(mails)
    assert c.post("/v1/auth/password/reset", json={"token": token, "new_password": NEW}).status_code == 204
    again = c.post("/v1/auth/password/reset", json={"token": token, "new_password": "outra-senha-longa-1"})
    assert again.status_code == 400 and again.json() == {"detail": "invalid or expired token"}
    assert _login(app, password=NEW)  # a senha do 2º uso nunca valeu
    with Session(app.state.engine) as s:
        ana = s.scalar(select(User).where(User.email == "ana@x.com"))
        ev = list(s.scalars(select(AdminEvent).where(AdminEvent.action == "user.password_reset")))
        assert len(ev) == 1 and ev[0].actor_user_id == ana.id and (ev[0].target_type, ev[0].target_id) == ("user", ana.id)
        assert ev[0].org_id == ana.org_id
        blob = json.dumps({k: str(v) for k, v in vars(ev[0]).items() if not k.startswith("_")})
        assert token not in blob and NEW not in blob


@pytest.mark.parametrize("motivo", ["expirado", "usado", "invalido", "usuario_inativo", "org_inativa"])
def test_falhas_do_reset_sao_todas_iguais(rec, motivo):
    app, c, mails = rec
    _forgot(c, "ana@x.com")
    token = _token(mails)
    with Session(app.state.engine) as s:
        pr = PasswordReset.__table__
        if motivo == "expirado":
            s.execute(update(pr).values(expires_at=utcnow().replace(year=2000)))
        elif motivo == "usado":
            s.execute(update(pr).values(used_at=utcnow()))
        elif motivo == "invalido":
            token = "token-que-nunca-existiu-" + "x" * 20
        elif motivo == "usuario_inativo":
            s.execute(update(User).where(User.email == "ana@x.com").values(active=False))
        elif motivo == "org_inativa":
            s.execute(update(Organization).values(active=False))
        s.commit()
    r = c.post("/v1/auth/password/reset", json={"token": token, "new_password": NEW})
    assert r.status_code == 400 and r.json() == {"detail": "invalid or expired token"}
    assert TestClient(app).post("/v1/auth/login", json={"email": "ana@x.com", "password": NEW}).status_code == 401


def test_novo_pedido_invalida_o_anterior(rec):
    _app, c, mails = rec
    _forgot(c, "ana@x.com")
    _forgot(c, "ana@x.com")
    first, second = _token(mails, 0), _token(mails, 1)
    assert first != second
    assert c.post("/v1/auth/password/reset", json={"token": first, "new_password": NEW}).status_code == 400
    assert c.post("/v1/auth/password/reset", json={"token": second, "new_password": NEW}).status_code == 204


def test_reset_invalida_outros_tokens_pendentes(rec):
    app, c, mails = rec
    _forgot(c, "ana@x.com")
    token = _token(mails)
    with Session(app.state.engine) as s:  # um 2º token pendente do mesmo usuário (ex.: criado por fora)
        s.add(PasswordReset(user_id=s.scalar(select(User.id).where(User.email == "ana@x.com")),
                            token_hash=hashlib.sha256(b"outro").hexdigest(), created_at=utcnow(),
                            expires_at=utcnow().replace(year=2100)))
        s.commit()
    assert c.post("/v1/auth/password/reset", json={"token": token, "new_password": NEW}).status_code == 204
    assert c.post("/v1/auth/password/reset", json={"token": "outro", "new_password": NEW}).status_code == 400


def test_senha_curta_e_recusada_e_o_token_continua_valido(rec):
    _app, c, mails = rec
    _forgot(c, "ana@x.com")
    token = _token(mails)
    assert c.post("/v1/auth/password/reset", json={"token": token, "new_password": "curta"}).status_code == 422
    assert c.post("/v1/auth/password/reset", json={"token": token, "new_password": NEW}).status_code == 204


# ---- limites ----------------------------------------------------------------------------------------------


def test_limite_por_email_responde_igual_mas_nao_envia(rec):
    app, c, mails = rec
    resp = [_forgot(c, "ana@x.com") for _ in range(5)]
    assert {r.status_code for r in resp} == {202} and len({r.text for r in resp}) == 1
    assert len(mails) == 3  # 3 por hora por e-mail
    lim = app.state.recovery_limiters["email"]
    real = lim.clock
    lim.clock = lambda: real() + 3601  # passou 1 hora: a janela reinicia
    _forgot(c, "ana@x.com")
    assert len(mails) == 4


def test_limite_por_ip(rec):
    app, c, mails = rec
    with Session(app.state.engine) as s:
        org = s.scalars(select(Organization)).first()
        s.add_all([User(org_id=org.id, email=f"u{i}@x.com", password_hash="x", active=True) for i in range(12)])
        s.commit()
    codes = {_forgot(c, f"u{i}@x.com").status_code for i in range(12)}
    assert codes == {202} and len(mails) == 10  # 10 por IP por hora; o resto responde igual sem enviar


def test_tentativas_invalidas_de_reset_sao_limitadas(rec):
    _app, c, mails = rec
    _forgot(c, "ana@x.com")
    good = _token(mails)
    for _ in range(10):
        assert c.post("/v1/auth/password/reset", json={"token": "errado-errado", "new_password": NEW}).status_code == 400
    assert c.post("/v1/auth/password/reset", json={"token": "errado-errado", "new_password": NEW}).status_code == 429
    # Token válido do mesmo IP continua passando (evita DoS em NAT/IP compartilhado).
    assert c.post("/v1/auth/password/reset", json={"token": good, "new_password": NEW}).status_code == 204
    # Reuso posterior desse token já consumido volta a ser barrado pelo limite do IP.
    assert c.post("/v1/auth/password/reset", json={"token": good, "new_password": NEW}).status_code == 429


# ---- SMTP com falha, log e servidor SMTP de verdade ----------------------------------------------------


def test_falha_de_smtp_nao_vaza_nem_quebra_o_202_e_o_log_e_mascarado(rec, monkeypatch, caplog):
    app, c, _mails = rec

    def boom(to, subject, text, html=None):
        raise OSError(f"connection refused while sending to {to}: {text}")

    monkeypatch.setattr(mailer, "send_mail", boom)
    with caplog.at_level(logging.DEBUG):
        r = _forgot(c, "ana@x.com")
    assert r.status_code == 202 and r.json()["status"] == "accepted" and "refused" not in r.text
    log = caplog.text
    assert "a***@x***.com" in log and "OSError" in log
    assert "ana@x.com" not in log and "reset-password" not in log
    with Session(app.state.engine) as s:  # o token foi criado, mas ninguém o recebeu
        token_hash = s.scalar(select(PasswordReset.token_hash))
    assert token_hash and token_hash not in log


class _Smtp(socketserver.StreamRequestHandler):
    """Servidor SMTP mínimo (EHLO, MAIL, RCPT, DATA, QUIT) só para o teste."""

    def handle(self):
        w = lambda line: self.wfile.write((line + "\r\n").encode())
        w("220 test ESMTP")
        data, in_data = [], False
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode(errors="replace").rstrip("\r\n")
            if in_data:
                if text == ".":
                    in_data = False
                    self.server.messages.append("\n".join(data))
                    w("250 queued")
                else:
                    data.append(text)
                continue
            cmd = text.upper()
            if cmd.startswith(("EHLO", "HELO")):
                w("250 test")
            elif cmd.startswith(("MAIL", "RCPT", "RSET", "NOOP")):
                w("250 ok")
            elif cmd.startswith("DATA"):
                in_data = True
                w("354 go")
            elif cmd.startswith("QUIT"):
                w("221 bye")
                return
            else:
                w("502 no")


def test_envio_real_por_smtp(monkeypatch, tmp_path):
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Smtp)
    srv.messages = []
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        app = _mk_app(monkeypatch, tmp_path)  # sem trocar o mailer: usa smtplib de verdade
        monkeypatch.setenv("AOK_SMTP_HOST", "127.0.0.1")
        monkeypatch.setenv("AOK_SMTP_PORT", str(srv.server_address[1]))
        monkeypatch.setenv("AOK_SMTP_STARTTLS", "false")
        monkeypatch.setenv("AOK_SMTP_FROM", "farol@farol.example")
        with Session(app.state.engine) as s:
            s.add(User(org_id=s.scalars(select(Organization)).first().id, email="ana@x.com",
                       password_hash=hash_password(PWD), active=True))
            s.commit()
        c = TestClient(app)
        assert _forgot(c, "ana@x.com").status_code == 202
        for _ in range(50):
            if srv.messages:
                break
            time.sleep(0.05)
        assert len(srv.messages) == 1
        raw = srv.messages[0]
        assert "To: ana@x.com" in raw and "From: farol@farol.example" in raw
        assert f"{BASE}/reset-password#token=" in raw.replace("=\n", "")  # (quoted-printable pode quebrar linha)
    finally:
        srv.shutdown()
        srv.server_close()
