"""Assinatura Ed25519 do relatorio.json (ADR-029): sign_bytes/verify_bytes, report build e report verify."""

import base64
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_ops_kit import audit, audit_sign, cli  # noqa: F401  (audit antes de audit_sign: import circular)
from agent_ops_kit.report import verify

ROOT = Path(__file__).resolve().parent.parent
RES = "redteam/results_owasp"
BUILD_ARGS = [
    "report", "build", "--redteam-baseline", f"{RES}/baseline.jsonl",
    "--redteam-guardrails", f"{RES}/guardrails.jsonl", "--fp-dir", RES,
]
ENVS = (audit_sign.SIGNING_KEY_FILE_ENV, audit_sign.SIGNING_KEY_PEM_ENV)


def _build(out, monkeypatch, env=None):
    for k in ENVS:
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(ROOT)
    assert cli.main([*BUILD_ARGS, "--out", str(out)]) == 0


def _verify(pkg, *extra):
    return cli.main(["report", "verify", str(pkg), "--repo-root", str(ROOT), *extra])


def _status(pkg, **kw):
    res = verify.verify_package(pkg, ROOT, **kw)
    return {c["id"]: c for c in res["checks"]}["signature"]


@pytest.fixture(scope="module")
def keys(tmp_path_factory):
    d = tmp_path_factory.mktemp("keys")
    audit_sign.generate_ed25519_keypair(d / "k.pem", d / "k.pub")
    audit_sign.generate_ed25519_keypair(d / "o.pem", d / "o.pub")
    return d


@pytest.fixture(scope="module")
def pkgs(tmp_path_factory, keys):
    """Pacotes reais de results_owasp: sem chave, com chave por arquivo e com chave por PEM."""
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("pkgs")
    try:
        _build(base / "plain", mp)
        _build(base / "file", mp, {audit_sign.SIGNING_KEY_FILE_ENV: str(keys / "k.pem")})
        pem = (keys / "k.pem").read_text(encoding="utf-8")
        _build(base / "pem", mp, {audit_sign.SIGNING_KEY_PEM_ENV: pem})
    finally:
        mp.undo()
    return base


# --- sign_bytes / verify_bytes ---------------------------------------------------------------

def test_sign_verify_roundtrip(keys):
    data = b'{"a": 1}\n'
    rec = audit_sign.sign_bytes(data, (keys / "k.pem").read_bytes())
    assert set(rec) == {"algorithm", "key_fingerprint", "sig", "signed_at_utc"} and rec["algorithm"] == "ed25519"
    res = audit_sign.verify_bytes(data, rec, (keys / "k.pub").read_bytes())
    assert res.ok and res.key_fingerprint == rec["key_fingerprint"]


def test_altered_byte_is_invalid(keys):
    data = b"conteudo original"
    rec = audit_sign.sign_bytes(data, (keys / "k.pem").read_bytes())
    res = audit_sign.verify_bytes(b"conteudo originaL", rec, (keys / "k.pub").read_bytes())
    assert not res.ok and "inválida" in res.reason


def test_wrong_key_is_invalid(keys):
    rec = audit_sign.sign_bytes(b"x", (keys / "k.pem").read_bytes())
    assert not audit_sign.verify_bytes(b"x", rec, (keys / "o.pub").read_bytes()).ok


def test_corrupted_receipt_is_invalid(keys):
    pub = (keys / "k.pub").read_bytes()
    rec = audit_sign.sign_bytes(b"x", (keys / "k.pem").read_bytes())
    assert not audit_sign.verify_bytes(b"x", {**rec, "sig": "###"}, pub).ok
    assert not audit_sign.verify_bytes(b"x", {**rec, "algorithm": "rsa"}, pub).ok
    assert not audit_sign.verify_bytes(b"x", "lixo", pub).ok


def test_bad_private_key_error_is_generic():
    secret = b"-----BEGIN " + b"PRIVATE KEY-----\nSEGREDOSEGREDO\n-----END " + b"PRIVATE KEY-----\n"
    with pytest.raises(ValueError) as exc:
        audit_sign.sign_bytes(b"x", secret)
    assert "SEGREDO" not in str(exc.value) and "PRIVATE" not in str(exc.value)


def test_signing_key_from_env_file_pem_and_none(keys):
    pem = (keys / "k.pem").read_bytes()
    assert audit_sign.signing_key_from_env({}) is None
    assert audit_sign.signing_key_from_env({audit_sign.SIGNING_KEY_PEM_ENV: "  "}) is None
    assert audit_sign.signing_key_from_env({audit_sign.SIGNING_KEY_PEM_ENV: pem.decode()}) == pem
    assert audit_sign.signing_key_from_env({audit_sign.SIGNING_KEY_FILE_ENV: str(keys / "k.pem")}) == pem
    with pytest.raises(ValueError):
        audit_sign.signing_key_from_env({audit_sign.SIGNING_KEY_FILE_ENV: str(keys / "nao_existe.pem")})


# --- report build ----------------------------------------------------------------------------

def test_without_key_does_not_sign_and_verifies_yellow(pkgs, capsys):
    plain = pkgs / "plain"
    assert not (plain / "relatorio.json.sig").exists()
    assert json.loads((plain / "relatorio.json").read_text(encoding="utf-8"))["semaphore"]["color"] == "yellow"
    assert _verify(plain) == 0
    out = capsys.readouterr().out
    assert "ÍNTEGRO" in out and "não assinado" in out and "FALHA" not in out


def test_without_key_package_is_identical_to_previous_behavior(pkgs, tmp_path, monkeypatch):
    again = tmp_path / "again"
    _build(again, monkeypatch)
    assert sorted(p.name for p in again.iterdir()) == ["relatorio.html", "relatorio.json", "relatorio.md"]
    a = json.loads((pkgs / "plain" / "relatorio.json").read_text(encoding="utf-8"))
    b = json.loads(again.joinpath("relatorio.json").read_text(encoding="utf-8"))
    for k in ("semaphore", "indicators", "eval", "redteam", "hashes", "findings", "policy"):
        assert a[k] == b[k]
    assert "signature" not in a and "sig" not in a


@pytest.mark.parametrize("name", ["file", "pem"])
def test_signed_build_and_verify(pkgs, keys, name, capsys):
    pkg = pkgs / name
    rec = json.loads((pkg / "relatorio.json.sig").read_text(encoding="utf-8"))
    assert rec["algorithm"] == "ed25519" and rec["key_fingerprint"] and rec["signed_at_utc"]
    assert base64.b64decode(rec["sig"], validate=True)
    assert "sig" not in json.loads((pkg / "relatorio.json").read_text(encoding="utf-8"))
    assert _verify(pkg, "--public-key", str(keys / "k.pub"), "--require-signature") == 0
    assert "assinatura Ed25519 válida" in capsys.readouterr().out


def test_signed_without_public_key_is_not_verifiable_with_fingerprint(pkgs, capsys):
    st = _status(pkgs / "file")
    assert st["status"] == "nao_verificavel"
    rec = json.loads((pkgs / "file" / "relatorio.json.sig").read_text(encoding="utf-8"))
    assert rec["key_fingerprint"] in st["detail"]
    assert _verify(pkgs / "file") == 1
    assert "NÃO VERIFICÁVEL" in capsys.readouterr().out


def test_wrong_public_key_fails(pkgs, keys):
    assert _status(pkgs / "file", public_key=keys / "o.pub")["status"] == "falha"
    assert _verify(pkgs / "file", "--public-key", str(keys / "o.pub")) == 1


def test_altered_package_fails_signature(pkgs, keys, tmp_path):
    pkg = tmp_path / "pk"
    shutil.copytree(pkgs / "file", pkg)
    raw = (pkg / "relatorio.json").read_bytes()
    (pkg / "relatorio.json").write_bytes(raw.replace(b"yellow", b"green", 1))
    assert _status(pkg, public_key=keys / "k.pub")["status"] == "falha"
    assert _verify(pkg, "--public-key", str(keys / "k.pub")) == 1


def test_require_signature_fails_when_unsigned(pkgs, capsys):
    assert _status(pkgs / "plain", require_signature=True)["status"] == "falha"
    assert _verify(pkgs / "plain", "--require-signature") == 1
    assert "sem assinatura" in capsys.readouterr().out


def test_invalid_key_in_env_fails_build_generic(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv(audit_sign.SIGNING_KEY_FILE_ENV, raising=False)
    monkeypatch.setenv(audit_sign.SIGNING_KEY_PEM_ENV, "SEGREDOQUALQUER")
    assert cli.main([*BUILD_ARGS, "--out", str(tmp_path / "x")]) == 2
    err = capsys.readouterr().err
    assert "inválida" in err and "SEGREDOQUALQUER" not in err


def test_stale_sig_removed_when_rebuilding_without_key(pkgs, tmp_path, monkeypatch):
    out = tmp_path / "re"
    shutil.copytree(pkgs / "file", out)
    _build(out, monkeypatch)
    assert not (out / "relatorio.json.sig").exists()


def test_no_private_key_in_outputs(pkgs, keys, capsys):
    pem = (keys / "k.pem").read_text(encoding="utf-8")
    body = "".join(pem.splitlines()[1:-1])
    _verify(pkgs / "pem", "--public-key", str(keys / "k.pub"))
    shown = capsys.readouterr()
    for p in (pkgs / "pem").iterdir():
        text = p.read_text(encoding="utf-8")
        assert body not in text and "PRIVATE KEY" not in text
    assert body not in shown.out + shown.err and "PRIVATE KEY" not in shown.out + shown.err


# --- varredura: nenhuma chave privada versionada ---------------------------------------------

def test_no_private_key_committed():
    try:
        files = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.split(b"\0")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git indisponível")
    pattern = re.compile(rb"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")
    # Única exceção: resposta do modelo no red team (OWASP LLM02), texto fictício de chave (corpo
    # sequencial sem valor criptográfico), evidência fixada por hash que não pode ser editada.
    allowed = {"redteam/results_owasp/baseline.jsonl"}
    hits = []
    for rel in filter(None, files):
        name = rel.decode("utf-8")
        path = ROOT / name
        if name not in allowed and path.is_file() and pattern.search(path.read_bytes()):
            hits.append(name)
    assert hits == [], f"chave privada versionada em: {hits}"
