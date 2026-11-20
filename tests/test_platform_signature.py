"""Assinatura Ed25519 do relatorio.json na plataforma (ADR-029, parte da plataforma). Sem rede."""

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from aok_platform.app import create_app
from aok_platform.models import AdminEvent, ReportVersion
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_platform_reports import ADMIN, KEY, _make_agent, _package, _post

from agent_ops_kit import audit_sign
from agent_ops_kit.report import publish

_PUB = (serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def _keypair():
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return priv_pem, priv.public_key().public_bytes(*_PUB).decode()


def _signed(priv_pem, **kw):
    pkg = _package(**kw)
    pkg["signature"] = json.dumps(
        audit_sign.sign_bytes(pkg["files"]["relatorio.json"].encode("utf-8"), priv_pem)
    )
    return pkg


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("AOK_ADMIN_BOOTSTRAP_KEY", KEY)
    monkeypatch.setenv("AOK_COOKIE_SECURE", "false")  # o TestClient usa http
    app = create_app("sqlite:///:memory:", data_dir=tmp_path / "data")
    return TestClient(app), tmp_path / "data"


def _register(client, agent_id, pem):
    return client.post(
        f"/v1/admin/agents/{agent_id}/keys", json={"public_key_pem": pem}, headers=ADMIN
    )


def _agent_with_key(client, slug="rag-demo"):
    ag, token, _ = _make_agent(client, slug)
    priv, pub = _keypair()
    r = _register(client, ag["id"], pub)
    assert r.status_code == 201
    return ag, token, priv, r.json()


def test_assinatura_valida_201_e_guarda_signed_e_fingerprint(env):
    client, data = env
    _, token, priv, key = _agent_with_key(client)
    r = _post(client, token, _signed(priv))
    assert r.status_code == 201 and r.json()["signed"] is True
    with Session(client.app.state.engine) as s:
        row = s.scalars(select(ReportVersion)).one()
        assert (row.signed, row.key_fingerprint) == (True, key["fingerprint"])
        assert (data / row.file_json).with_name("relatorio.json.sig").is_file()


def test_assinatura_invalida_422(env):
    client, _ = env
    _, token, priv, _ = _agent_with_key(client)
    other = _package(mean=0.9)  # assinatura feita sobre outros bytes
    other["signature"] = _signed(priv)["signature"]
    r = _post(client, token, other)
    assert r.status_code == 422 and r.json()["detail"] == "assinatura ausente ou inválida"


def test_assinatura_ausente_com_chave_ativa_422(env):
    client, _ = env
    _, token, _, _ = _agent_with_key(client)
    assert _post(client, token, _package()).status_code == 422


def test_require_signature_sem_assinatura_422_e_com_assinatura_201(env):
    client, _ = env
    ag, token, _ = _make_agent(client)
    r = client.patch(f"/v1/admin/agents/{ag['id']}", json={"require_signature": True}, headers=ADMIN)
    assert r.json()["require_signature"] is True
    assert _post(client, token, _package()).status_code == 422
    priv, pub = _keypair()
    _register(client, ag["id"], pub)
    assert _post(client, token, _signed(priv)).status_code == 201


def test_chave_revogada_422(env):
    client, _ = env
    ag, token, priv, key = _agent_with_key(client)
    r = client.delete(f"/v1/admin/agents/{ag['id']}/keys/{key['key_id']}", headers=ADMIN)
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    assert _post(client, token, _signed(priv)).status_code == 422


def test_chave_de_outro_agente_422(env):
    client, _ = env
    _, token_a, _, _ = _agent_with_key(client, "agente-a")
    _, _, priv_b, _ = _agent_with_key(client, "agente-b")
    assert _post(client, token_a, _signed(priv_b, agent_id="agente-a")).status_code == 422


def test_sem_chave_cadastrada_aceita_como_nao_assinado(env):
    client, _ = env
    _, token, _ = _make_agent(client)
    r = _post(client, token, _package())
    assert r.status_code == 201 and r.json()["signed"] is False
    with Session(client.app.state.engine) as s:
        row = s.scalars(select(ReportVersion)).one()
        assert (row.signed, row.key_fingerprint) == (False, None)


def test_duplicado_assinado_continua_409(env):
    client, _ = env
    _, token, priv, _ = _agent_with_key(client)
    pkg = _signed(priv)
    assert _post(client, token, pkg).status_code == 201
    assert _post(client, token, pkg).status_code == 409


def test_leitura_expoe_signed_e_fingerprint(env):
    client, _ = env
    ag, token, priv, key = _agent_with_key(client)
    assert _post(client, token, _signed(priv)).status_code == 201
    u = client.post(
        "/v1/admin/users",
        json={"email": "a@x.io", "password": "senha-de-teste-12345"},
        headers=ADMIN,
    ).json()
    body = {"user_id": u["id"], "role": "area_viewer", "area_id": ag["area_id"]}
    assert client.post("/v1/admin/memberships", json=body, headers=ADMIN).status_code == 201
    login = client.post(
        "/v1/auth/login", json={"email": "a@x.io", "password": "senha-de-teste-12345"}
    )
    assert login.status_code == 200, login.text
    item = client.get(f"/v1/agents/{ag['id']}/reports").json()[0]
    assert (item["signed"], item["key_fingerprint"]) == (True, key["fingerprint"])
    detail = client.get(f"/v1/reports/{item['id']}").json()
    assert (detail["signed"], detail["key_fingerprint"]) == (True, key["fingerprint"])


def test_cadastro_recusa_chave_privada_e_pem_invalido_sem_ecoar(env):
    client, _ = env
    ag, _, _ = _make_agent(client)
    priv, _ = _keypair()
    rsa_pub = rsa.generate_private_key(65537, 2048).public_key().public_bytes(*_PUB).decode()
    broken = "-----BEGIN PUBLIC KEY-----\nAAAA\n-----END PUBLIC KEY-----\n"
    for bad in (priv.decode(), "lixo", "", broken, rsa_pub):
        r = _register(client, ag["id"], bad)
        assert r.status_code == 422
        assert r.json()["detail"] == "chave pública Ed25519 em PEM inválida"
        assert "PRIVATE" not in r.text


def test_cadastro_duplicado_409_e_listagem_sem_pem(env):
    client, _ = env
    ag, _, _ = _make_agent(client)
    _, pub = _keypair()
    assert _register(client, ag["id"], pub).status_code == 201
    assert _register(client, ag["id"], pub).status_code == 409
    rows = client.get(f"/v1/admin/agents/{ag['id']}/keys", headers=ADMIN).json()
    assert len(rows) == 1 and "public_key_pem" not in rows[0]
    with Session(client.app.state.engine) as s:
        assert "key.register" in set(s.scalars(select(AdminEvent.action)))


def test_so_admin_cadastra_lista_e_revoga(env):
    client, _ = env
    ag, token, _ = _make_agent(client)
    _, pub = _keypair()
    url = f"/v1/admin/agents/{ag['id']}/keys"
    for headers in ({}, {"Authorization": "Bearer errada"}, {"Authorization": f"Bearer {token}"}):
        body = {"public_key_pem": pub}
        assert client.post(url, json=body, headers=headers).status_code in (401, 403)
        assert client.get(url, headers=headers).status_code in (401, 403)
        assert client.delete(f"{url}/1", headers=headers).status_code in (401, 403)
    assert client.get(url, headers=ADMIN).json() == []


def _pack_dir(tmp_path, priv=None):
    pkg = _package()
    for name, text in pkg["files"].items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    if priv is not None:
        sig = audit_sign.sign_bytes((tmp_path / "relatorio.json").read_bytes(), priv)
        (tmp_path / publish.SIG_FILE).write_text(json.dumps(sig), encoding="utf-8")
    return tmp_path


def _capture_remote(monkeypatch, package_dir):
    sent = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"seq": 1}'

    class _Opener:
        def open(self, req, timeout=None):
            sent["body"] = json.loads(req.data)
            return _Resp()

    monkeypatch.setattr(publish.urllib.request, "build_opener", lambda *_: _Opener())
    publish.publish_remote(package_dir, "http://x.local", "rag-demo", "tok")
    return sent["body"]


def test_publish_remote_envia_signature_e_a_plataforma_aceita(env, monkeypatch, tmp_path):
    client, _ = env
    _, token, priv, _ = _agent_with_key(client)
    body = _capture_remote(monkeypatch, _pack_dir(tmp_path, priv))
    assert set(body) == {"agent_id", "timestamp", "semaphore", "sha256", "files", "signature"}
    r = _post(client, token, body)
    assert r.status_code == 201 and r.json()["signed"] is True


def test_publish_remote_sem_sig_nao_envia_campo(monkeypatch, tmp_path):
    assert "signature" not in _capture_remote(monkeypatch, _pack_dir(tmp_path))


def test_publish_local_copia_sig_quando_existe(tmp_path):
    priv, _ = _keypair()
    (tmp_path / "src_a").mkdir()
    (tmp_path / "src_b").mkdir()
    src = _pack_dir(tmp_path / "src_a", priv)
    dest, _ = publish.publish(src, tmp_path / "root", "rag-demo")
    assert (dest / publish.SIG_FILE).is_file()
    dest2, _ = publish.publish(_pack_dir(tmp_path / "src_b"), tmp_path / "root", "rag-demo-2")
    assert not (dest2 / publish.SIG_FILE).exists()
    assert set(json.loads((dest / "pacote.json").read_text())["sha256"]) == set(publish.FILES)
