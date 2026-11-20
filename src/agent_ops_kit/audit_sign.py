"""Assinatura digital criptográfica (Ed25519 PKI e HMAC-SHA256) da âncora de auditoria."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from agent_ops_kit import audit

SCHEMA_VERSION = 1
SUPPORTED_ALGORITHMS = ("ed25519", "hmac-sha256")
_RECEIPT_FIELDS = (
    "schema_version",
    "algorithm",
    "n_events",
    "last_hash",
    "signed_at_utc",
    "key_fingerprint",
    "signature_b64",
)


@dataclass
class SignatureVerifyResult:
    """Resultado da verificação criptográfica da assinatura de uma âncora."""

    ok: bool
    algorithm: str | None = None
    key_fingerprint: str | None = None
    n_events: int | None = None
    last_hash: str | None = None
    reason: str | None = None


def _public_pem_bytes(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _ed25519_fingerprint(public_key: Ed25519PublicKey) -> str:
    return hashlib.sha256(_public_pem_bytes(public_key)).hexdigest()


def _hmac_fingerprint(key_bytes: bytes) -> str:
    return hashlib.sha256(b"aok-hmac-v1:" + key_bytes).hexdigest()[:16]


def _normalize_hmac_key(hmac_key: str | bytes | None) -> bytes | None:
    if hmac_key is None:
        return None
    if isinstance(hmac_key, str):
        return hmac_key.encode("utf-8")
    if isinstance(hmac_key, (bytes, bytearray)):
        return bytes(hmac_key)
    raise ValueError("chave HMAC deve ser str ou bytes")


def build_anchor_payload(
    n_events: int,
    last_hash: str | None,
    signed_at_utc: str,
    schema_version: int = SCHEMA_VERSION,
) -> bytes:
    """Serializa em UTF-8 canônico o payload assinado da âncora de auditoria."""
    payload = {
        "schema_version": schema_version,
        "n_events": n_events,
        "last_hash": last_hash or audit.GENESIS_HASH,
        "signed_at_utc": signed_at_utc,
    }
    return audit.canonical(payload).encode("utf-8")


def generate_ed25519_keypair(
    private_path: str | Path,
    public_path: str | Path,
    overwrite: bool = False,
) -> dict[str, str]:
    """Gera par Ed25519 em PEM PKCS8 (sem passphrase) e devolve metadados seguros."""
    priv = Path(private_path)
    pub = Path(public_path)
    if priv.resolve() == pub.resolve():
        raise ValueError("os caminhos da chave privada e da chave pública devem ser diferentes")
    if not overwrite and (priv.exists() or pub.exists()):
        existing = priv if priv.exists() else pub
        raise FileExistsError(f"arquivo de chave já existe (use overwrite=True): {existing}")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = _public_pem_bytes(public_key)

    priv.parent.mkdir(parents=True, exist_ok=True)
    pub.parent.mkdir(parents=True, exist_ok=True)

    if os.name == "posix":
        flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
        fd = os.open(priv, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(private_bytes)
        finally:
            os.chmod(priv, 0o600)
    else:
        priv.write_bytes(private_bytes)

    pub.write_bytes(public_bytes)
    return {
        "algorithm": "ed25519",
        "key_fingerprint": hashlib.sha256(public_bytes).hexdigest(),
        "private_path": str(priv),
        "public_path": str(pub),
    }


SIGNING_KEY_FILE_ENV = "AOK_SIGNING_KEY_FILE"
SIGNING_KEY_PEM_ENV = "AOK_SIGNING_KEY_PEM"


def _load_private_key(pem: bytes) -> Ed25519PrivateKey:
    try:
        loaded = serialization.load_pem_private_key(pem, password=None)
        if isinstance(loaded, Ed25519PrivateKey):
            return loaded
    except (ValueError, TypeError, UnsupportedAlgorithm):
        pass
    raise ValueError("chave de assinatura inválida ou não suportada (esperada PEM Ed25519)")


def signing_key_from_env(environ: dict[str, str] | None = None) -> bytes | None:
    """PEM da chave privada de AOK_SIGNING_KEY_FILE (caminho) ou AOK_SIGNING_KEY_PEM (conteúdo); None se ausentes."""
    env = os.environ if environ is None else environ
    path = env.get(SIGNING_KEY_FILE_ENV)
    if path:
        try:
            return Path(path).read_bytes()
        except OSError:
            raise ValueError(f"não foi possível ler a chave de assinatura de {SIGNING_KEY_FILE_ENV}") from None
    pem = env.get(SIGNING_KEY_PEM_ENV)
    return pem.encode("utf-8") if pem and pem.strip() else None


def sign_bytes(data: bytes, private_pem: bytes) -> dict[str, str]:
    """Assina os bytes exatos com Ed25519 e devolve o recibo (conteúdo do arquivo .sig)."""
    key = _load_private_key(private_pem)
    return {
        "algorithm": "ed25519",
        "key_fingerprint": _ed25519_fingerprint(key.public_key()),
        "sig": base64.b64encode(key.sign(data)).decode("ascii"),
        "signed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def verify_bytes(data: bytes, receipt: Any, public_pem: bytes) -> SignatureVerifyResult:
    """Confere o recibo de `sign_bytes` contra os bytes e a chave pública (PEM)."""
    fp = receipt.get("key_fingerprint") if isinstance(receipt, dict) else None
    fp = fp if isinstance(fp, str) else None

    def bad(reason: str) -> SignatureVerifyResult:
        return SignatureVerifyResult(ok=False, algorithm="ed25519", key_fingerprint=fp, reason=reason)

    if not isinstance(receipt, dict) or receipt.get("algorithm") != "ed25519" or fp is None:
        return bad("recibo de assinatura inválido ou algoritmo não suportado")
    try:
        sig = base64.b64decode(str(receipt.get("sig", "")).encode("ascii"), validate=True)
        pub = serialization.load_pem_public_key(public_pem)
    except (ValueError, TypeError, UnsupportedAlgorithm, binascii.Error):
        return bad("assinatura ou chave pública ilegível")
    if not isinstance(pub, Ed25519PublicKey):
        return bad("chave pública fornecida não é Ed25519")
    if not hmac.compare_digest(_ed25519_fingerprint(pub), fp):
        return bad("a chave pública não corresponde ao fingerprint da assinatura")
    try:
        pub.verify(sig, data)
    except InvalidSignature:
        return bad("assinatura inválida: o conteúdo foi alterado ou a chave está errada")
    return SignatureVerifyResult(ok=True, algorithm="ed25519", key_fingerprint=fp)


def sign_anchor(
    audit_path: str | Path,
    *,
    private_key_path: str | Path | None = None,
    hmac_key: str | bytes | None = None,
    out_path: str | Path | None = None,
) -> dict[str, Any]:
    """Valida a cadeia do log e assina sua âncora com Ed25519 ou HMAC-SHA256."""
    hmac_bytes = _normalize_hmac_key(hmac_key)
    has_priv = private_key_path is not None and str(private_key_path) != ""
    has_hmac = hmac_bytes is not None and len(hmac_bytes) > 0

    if has_priv and has_hmac:
        raise ValueError("informe apenas private_key_path ou hmac_key, nunca ambos")
    if not has_priv and not has_hmac:
        raise ValueError("informe private_key_path ou hmac_key não vazio para assinar")

    res = audit.verify(audit_path)
    if not res.ok:
        where = f"na linha {res.first_bad_line}" if res.first_bad_line else "(âncora)"
        raise audit.AuditChainError(f"cadeia quebrada {where}: {res.reason}")

    last_hash = res.last_hash or audit.GENESIS_HASH
    signed_at_utc = datetime.now(UTC).isoformat(timespec="microseconds")
    payload_bytes = build_anchor_payload(res.n_lines, last_hash, signed_at_utc)

    if has_priv:
        priv_bytes = Path(private_key_path).read_bytes()  # type: ignore[arg-type]
        try:
            loaded = serialization.load_pem_private_key(priv_bytes, password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
            raise ValueError("chave privada PEM inválida, protegida por senha ou não suportada") from exc
        if not isinstance(loaded, Ed25519PrivateKey):
            raise ValueError("chave privada fornecida não é Ed25519")
        algorithm = "ed25519"
        key_fingerprint = _ed25519_fingerprint(loaded.public_key())
        sig_bytes = loaded.sign(payload_bytes)
    else:
        assert hmac_bytes is not None
        algorithm = "hmac-sha256"
        key_fingerprint = _hmac_fingerprint(hmac_bytes)
        sig_bytes = hmac.new(hmac_bytes, payload_bytes, hashlib.sha256).digest()

    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": algorithm,
        "n_events": res.n_lines,
        "last_hash": last_hash,
        "signed_at_utc": signed_at_utc,
        "key_fingerprint": key_fingerprint,
        "signature_b64": base64.b64encode(sig_bytes).decode("ascii"),
    }
    if out_path is not None:
        dest = Path(out_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def _load_receipt(receipt_or_path: dict[str, Any] | str | Path) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(receipt_or_path, dict):
        return receipt_or_path, None
    path = Path(receipt_or_path)
    if not path.is_file():
        return None, f"arquivo de assinatura não encontrado: {path}"
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, "não foi possível ler o arquivo de assinatura em UTF-8"
    try:
        obj = json.loads(raw)
    except (ValueError, RecursionError):
        return None, "recibo de assinatura não é JSON válido"
    if not isinstance(obj, dict):
        return None, "recibo de assinatura inválido (esperado objeto JSON)"
    return obj, None


def _validate_receipt_structure(receipt: dict[str, Any]) -> tuple[bytes | None, str | None]:
    for field in _RECEIPT_FIELDS:
        if field not in receipt:
            return None, f"campo obrigatório ausente no recibo de assinatura: {field}"

    ver = receipt["schema_version"]
    if isinstance(ver, bool) or not isinstance(ver, int) or ver != SCHEMA_VERSION:
        return None, "versão de esquema do recibo de assinatura não suportada"

    alg = receipt["algorithm"]
    n_events = receipt["n_events"]
    last_hash = receipt["last_hash"]
    signed_at = receipt["signed_at_utc"]
    fingerprint = receipt["key_fingerprint"]
    sig_b64 = receipt["signature_b64"]

    if (
        isinstance(n_events, bool)
        or not isinstance(n_events, int)
        or n_events < 0
        or not isinstance(alg, str)
        or not isinstance(last_hash, str)
        or not isinstance(signed_at, str)
        or not isinstance(fingerprint, str)
        or not isinstance(sig_b64, str)
    ):
        return None, "campo do recibo de assinatura com tipo inválido"

    if alg not in SUPPORTED_ALGORITHMS:
        return None, f"algoritmo de assinatura não suportado: {alg}"

    try:
        sig_ascii = sig_b64.encode("ascii")
        sig_bytes = base64.b64decode(sig_ascii, validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error):
        return None, "assinatura em Base64 inválida ou corrompida"

    if not sig_bytes:
        return None, "assinatura vazia no recibo"
    return sig_bytes, None


def verify_signature(
    audit_path: str | Path,
    receipt_or_path: dict[str, Any] | str | Path,
    *,
    public_key_path: str | Path | None = None,
    hmac_key: str | bytes | None = None,
) -> SignatureVerifyResult:
    """Valida a cadeia do log e verifica a assinatura criptográfica da âncora."""
    res = audit.verify(audit_path)
    actual_last_hash = res.last_hash or audit.GENESIS_HASH
    if not res.ok:
        where = f"na linha {res.first_bad_line}" if res.first_bad_line else "(âncora)"
        return SignatureVerifyResult(
            ok=False,
            n_events=res.n_lines,
            last_hash=res.last_hash,
            reason=f"cadeia de auditoria inválida {where}: {res.reason}",
        )

    receipt, load_err = _load_receipt(receipt_or_path)
    if load_err is not None or receipt is None:
        return SignatureVerifyResult(
            ok=False,
            n_events=res.n_lines,
            last_hash=actual_last_hash,
            reason=load_err or "recibo de assinatura inválido",
        )

    alg = receipt.get("algorithm") if isinstance(receipt.get("algorithm"), str) else None
    fp = receipt.get("key_fingerprint") if isinstance(receipt.get("key_fingerprint"), str) else None

    sig_bytes, struct_err = _validate_receipt_structure(receipt)
    if struct_err is not None or sig_bytes is None:
        return SignatureVerifyResult(
            ok=False,
            algorithm=alg,
            key_fingerprint=fp,
            n_events=res.n_lines,
            last_hash=actual_last_hash,
            reason=struct_err,
        )

    assert alg is not None and fp is not None
    if receipt["n_events"] != res.n_lines:
        return SignatureVerifyResult(
            ok=False,
            algorithm=alg,
            key_fingerprint=fp,
            n_events=res.n_lines,
            last_hash=actual_last_hash,
            reason=(
                f"número de eventos do log ({res.n_lines}) difere do assinado "
                f"({receipt['n_events']}): possível truncamento ou acréscimo após a assinatura"
            ),
        )
    if receipt["last_hash"] != actual_last_hash:
        return SignatureVerifyResult(
            ok=False,
            algorithm=alg,
            key_fingerprint=fp,
            n_events=res.n_lines,
            last_hash=actual_last_hash,
            reason="último hash do log difere do hash assinado: possível adulteração ou reescrita",
        )

    try:
        hmac_bytes = _normalize_hmac_key(hmac_key)
    except ValueError as exc:
        return SignatureVerifyResult(
            ok=False,
            algorithm=alg,
            key_fingerprint=fp,
            n_events=res.n_lines,
            last_hash=actual_last_hash,
            reason=str(exc),
        )

    has_pub = public_key_path is not None and str(public_key_path) != ""
    has_hmac = hmac_bytes is not None and len(hmac_bytes) > 0
    if has_pub and has_hmac:
        return SignatureVerifyResult(
            ok=False,
            algorithm=alg,
            key_fingerprint=fp,
            n_events=res.n_lines,
            last_hash=actual_last_hash,
            reason="informe apenas uma chave verificadora (chave pública ou chave HMAC)",
        )

    payload_bytes = build_anchor_payload(
        receipt["n_events"],
        receipt["last_hash"],
        receipt["signed_at_utc"],
        receipt["schema_version"],
    )

    if alg == "ed25519":
        if has_hmac:
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="algoritmo ed25519 incompatível com chave HMAC fornecida",
            )
        if not has_pub:
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="chave pública Ed25519 não informada para verificação",
            )
        pub_path = Path(public_key_path)  # type: ignore[arg-type]
        if not pub_path.is_file():
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason=f"chave pública não encontrada: {pub_path}",
            )
        try:
            loaded_pub = serialization.load_pem_public_key(pub_path.read_bytes())
        except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="chave pública PEM inválida ou não suportada",
            )
        if not isinstance(loaded_pub, Ed25519PublicKey):
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="chave pública fornecida não é Ed25519",
            )
        if not hmac.compare_digest(_ed25519_fingerprint(loaded_pub), fp):
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="assinatura Ed25519 inválida: fingerprint da chave pública não confere com o recibo",
            )
        try:
            loaded_pub.verify(sig_bytes, payload_bytes)
        except InvalidSignature:
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="assinatura Ed25519 inválida ou chave pública incorreta",
            )
    else:  # alg == "hmac-sha256"
        if has_pub:
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="algoritmo hmac-sha256 incompatível com chave pública Ed25519 fornecida",
            )
        if not has_hmac or hmac_bytes is None:
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="chave HMAC não informada ou vazia para verificação",
            )
        expected_sig = hmac.new(hmac_bytes, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(sig_bytes, expected_sig):
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="assinatura HMAC-SHA256 inválida ou chave incorreta",
            )
        if not hmac.compare_digest(_hmac_fingerprint(hmac_bytes), fp):
            return SignatureVerifyResult(
                ok=False,
                algorithm=alg,
                key_fingerprint=fp,
                n_events=res.n_lines,
                last_hash=actual_last_hash,
                reason="fingerprint da chave HMAC não confere com o recibo",
            )

    return SignatureVerifyResult(
        ok=True,
        algorithm=alg,
        key_fingerprint=fp,
        n_events=res.n_lines,
        last_hash=actual_last_hash,
        reason=None,
    )
