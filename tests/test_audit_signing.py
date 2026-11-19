"""Testes da assinatura digital (Ed25519 e HMAC-SHA256) da âncora de auditoria."""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

import pytest

from agent_ops_kit import audit, audit_sign, cli
from agent_ops_kit.audit import AuditChainError, AuditLog
from agent_ops_kit.report import build, render

ROOT = Path(__file__).resolve().parent.parent
HMAC_SECRET = "segredo-super-forte-teste-hmac-r1-2026"
BANNED_REPORT_WORDS = re.compile(r"\b(seguro|segura|robust[oa]s?|eficaz(es)?)\b", re.IGNORECASE)


def _make_log(tmp_path: Path, n: int = 4, name: str = "audit.jsonl") -> Path:
    p = tmp_path / name
    log = AuditLog(p)
    for i in range(n):
        log.append("question" if i % 2 == 0 else "answer", {"i": i})
    return p


def _write_rt_dir(tmp_path: Path) -> Path:
    d = tmp_path / "rt"
    d.mkdir(exist_ok=True)
    for fname, rows in (
        (
            "baseline.jsonl",
            [
                {
                    "case_id": "a1",
                    "category": "injecao_direta",
                    "success": True,
                    "blocked_by": [],
                    "final_answer": "x",
                    "raw_answer": "x",
                }
            ],
        ),
        (
            "guardrails.jsonl",
            [
                {
                    "case_id": "a1",
                    "category": "injecao_direta",
                    "success": False,
                    "blocked_by": ["input"],
                    "final_answer": "x",
                    "raw_answer": "x",
                }
            ],
        ),
        (
            "fp_dataset.jsonl",
            [
                {
                    "case_id": "q1",
                    "blocked": False,
                    "blocked_by": [],
                    "reasons": [],
                    "answer": "x",
                    "raw_answer": "x",
                    "score": 1.0,
                    "error": None,
                }
            ],
        ),
        (
            "fp_benign.jsonl",
            [
                {
                    "case_id": "b1",
                    "blocked": False,
                    "blocked_by": [],
                    "reasons": [],
                    "answer": "x",
                    "raw_answer": "x",
                    "score": 1.0,
                    "error": None,
                }
            ],
        ),
    ):
        (d / fname).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return d


def test_reexports_in_audit_module():
    assert audit.SignatureVerifyResult is audit_sign.SignatureVerifyResult
    assert audit.generate_ed25519_keypair is audit_sign.generate_ed25519_keypair
    assert audit.sign_anchor is audit_sign.sign_anchor
    assert audit.verify_signature is audit_sign.verify_signature


def test_generate_ed25519_keypair_and_no_overwrite(tmp_path):
    priv = tmp_path / "keys" / "audit.key"
    pub = tmp_path / "keys" / "audit.pub"
    info = audit_sign.generate_ed25519_keypair(priv, pub)

    assert info["algorithm"] == "ed25519"
    assert len(info["key_fingerprint"]) == 64
    assert info["private_path"] == str(priv)
    assert info["public_path"] == str(pub)
    assert priv.is_file() and pub.is_file()
    priv_text = priv.read_text(encoding="utf-8")
    pub_text = pub.read_text(encoding="utf-8")
    assert "PUBLIC KEY" in pub_text
    assert "PRIVATE KEY" in priv_text
    assert priv_text not in json.dumps(info)

    with pytest.raises(FileExistsError):
        audit_sign.generate_ed25519_keypair(priv, pub)

    info2 = audit_sign.generate_ed25519_keypair(priv, pub, overwrite=True)
    assert info2["key_fingerprint"] != info["key_fingerprint"]

    with pytest.raises(ValueError):
        audit_sign.generate_ed25519_keypair(priv, priv, overwrite=True)


def test_sign_and_verify_ed25519_including_empty_log(tmp_path):
    priv = tmp_path / "ed.key"
    pub = tmp_path / "ed.pub"
    info = audit_sign.generate_ed25519_keypair(priv, pub)

    log_path = _make_log(tmp_path, 4)
    sig_path = tmp_path / "anchor.sig.json"
    receipt = audit_sign.sign_anchor(log_path, private_key_path=priv, out_path=sig_path)

    assert sig_path.is_file()
    assert receipt["schema_version"] == 1
    assert receipt["algorithm"] == "ed25519"
    assert receipt["n_events"] == 4
    assert receipt["key_fingerprint"] == info["key_fingerprint"]
    assert receipt["last_hash"] == audit.anchor(log_path)

    res = audit_sign.verify_signature(log_path, sig_path, public_key_path=pub)
    assert res.ok
    assert res.algorithm == "ed25519"
    assert res.key_fingerprint == info["key_fingerprint"]
    assert res.n_events == 4
    assert res.last_hash == receipt["last_hash"]
    assert res.reason is None

    empty_log = tmp_path / "empty.jsonl"
    empty_log.write_text("", encoding="utf-8")
    empty_receipt = audit_sign.sign_anchor(empty_log, private_key_path=priv)
    assert empty_receipt["n_events"] == 0
    assert empty_receipt["last_hash"] == audit.GENESIS_HASH
    empty_res = audit_sign.verify_signature(empty_log, empty_receipt, public_key_path=pub)
    assert empty_res.ok and empty_res.n_events == 0 and empty_res.last_hash == audit.GENESIS_HASH


def test_sign_and_verify_hmac_sha256_and_validation_errors(tmp_path):
    log_path = _make_log(tmp_path, 3)
    sig_path = tmp_path / "hmac.sig.json"
    receipt = audit_sign.sign_anchor(log_path, hmac_key=HMAC_SECRET, out_path=sig_path)

    assert receipt["algorithm"] == "hmac-sha256"
    assert len(receipt["key_fingerprint"]) == 16
    assert HMAC_SECRET not in sig_path.read_text(encoding="utf-8")

    res = audit_sign.verify_signature(log_path, sig_path, hmac_key=HMAC_SECRET.encode("utf-8"))
    assert res.ok and res.algorithm == "hmac-sha256" and res.n_events == 3

    with pytest.raises(ValueError):
        audit_sign.sign_anchor(log_path)
    with pytest.raises(ValueError):
        audit_sign.sign_anchor(log_path, hmac_key="")
    priv = tmp_path / "k.key"
    audit_sign.generate_ed25519_keypair(priv, tmp_path / "k.pub")
    with pytest.raises(ValueError):
        audit_sign.sign_anchor(log_path, private_key_path=priv, hmac_key=HMAC_SECRET)


def test_sign_refuses_broken_chain(tmp_path):
    log_path = _make_log(tmp_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"i":1', '"i":99')
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(AuditChainError, match="linha 2"):
        audit_sign.sign_anchor(log_path, hmac_key=HMAC_SECRET)


def test_verify_detects_tamper_truncation_append_and_bad_receipts(tmp_path):
    priv = tmp_path / "ed.key"
    pub = tmp_path / "ed.pub"
    audit_sign.generate_ed25519_keypair(priv, pub)
    other_pub = tmp_path / "other.pub"
    audit_sign.generate_ed25519_keypair(tmp_path / "other.key", other_pub)

    # 1. Adulteração de 1 linha do log
    log_tampered = _make_log(tmp_path, 4, "tampered.jsonl")
    sig_tampered = tmp_path / "tampered.sig.json"
    audit_sign.sign_anchor(log_tampered, private_key_path=priv, out_path=sig_tampered)
    lines = log_tampered.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace('"i":2', '"i":777')
    log_tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = audit_sign.verify_signature(log_tampered, sig_tampered, public_key_path=pub)
    assert not res.ok and "linha 3" in (res.reason or "")

    # 2. Truncamento do fim após assinatura
    log_trunc = _make_log(tmp_path, 5, "trunc.jsonl")
    sig_trunc = tmp_path / "trunc.sig.json"
    audit_sign.sign_anchor(log_trunc, private_key_path=priv, out_path=sig_trunc)
    kept = log_trunc.read_text(encoding="utf-8").splitlines()[:3]
    log_trunc.write_text("\n".join(kept) + "\n", encoding="utf-8")
    assert audit.verify(log_trunc).ok
    res = audit_sign.verify_signature(log_trunc, sig_trunc, public_key_path=pub)
    assert not res.ok and "truncamento" in (res.reason or "")

    # 3. Acréscimo de evento após assinatura
    log_app = _make_log(tmp_path, 3, "append.jsonl")
    sig_app = tmp_path / "append.sig.json"
    audit_sign.sign_anchor(log_app, private_key_path=priv, out_path=sig_app)
    AuditLog(log_app).append("extra", {"x": 1})
    res = audit_sign.verify_signature(log_app, sig_app, public_key_path=pub)
    assert not res.ok and "acréscimo" in (res.reason or "")

    # 4. Adulteração de signature_b64, chave errada, algoritmo incompatível, JSON/Base64 corrompidos
    log_ok = _make_log(tmp_path, 3, "ok.jsonl")
    receipt_ed = audit_sign.sign_anchor(log_ok, private_key_path=priv)
    receipt_hmac = audit_sign.sign_anchor(log_ok, hmac_key=HMAC_SECRET)

    raw_sig = bytearray(base64.b64decode(receipt_ed["signature_b64"]))
    raw_sig[0] ^= 0xFF
    bad_sig_receipt = {**receipt_ed, "signature_b64": base64.b64encode(bytes(raw_sig)).decode("ascii")}
    res = audit_sign.verify_signature(log_ok, bad_sig_receipt, public_key_path=pub)
    assert not res.ok and "inválida" in (res.reason or "")

    res = audit_sign.verify_signature(log_ok, receipt_ed, public_key_path=other_pub)
    assert not res.ok and "inválida" in (res.reason or "")

    res = audit_sign.verify_signature(log_ok, receipt_hmac, hmac_key="outra-chave-errada")
    assert not res.ok and "outra-chave-errada" not in (res.reason or "")

    # Algoritmo incompatível / desconhecido
    res = audit_sign.verify_signature(log_ok, receipt_ed, hmac_key=HMAC_SECRET)
    assert not res.ok and "incompatível" in (res.reason or "")
    res = audit_sign.verify_signature(log_ok, receipt_hmac, public_key_path=pub)
    assert not res.ok and "incompatível" in (res.reason or "")
    res = audit_sign.verify_signature(log_ok, {**receipt_ed, "algorithm": "rsa-sha1"}, public_key_path=pub)
    assert not res.ok and "não suportado" in (res.reason or "")

    # JSON e Base64 corrompidos + assinatura ausente
    bad_json = tmp_path / "bad.sig.json"
    bad_json.write_text("{json quebrado", encoding="utf-8")
    res = audit_sign.verify_signature(log_ok, bad_json, public_key_path=pub)
    assert not res.ok and "JSON" in (res.reason or "")

    bad_b64 = {**receipt_ed, "signature_b64": "%%%nao-e-base64%%%"}
    res = audit_sign.verify_signature(log_ok, bad_b64, public_key_path=pub)
    assert not res.ok and "Base64" in (res.reason or "")

    res = audit_sign.verify_signature(log_ok, tmp_path / "inexistente.sig.json", public_key_path=pub)
    assert not res.ok and "não encontrado" in (res.reason or "")

    # key_fingerprint esvaziado deve falhar tanto para Ed25519 quanto para HMAC-SHA256
    res_empty_fp_ed = audit_sign.verify_signature(
        log_ok, {**receipt_ed, "key_fingerprint": ""}, public_key_path=pub
    )
    assert not res_empty_fp_ed.ok and "fingerprint" in (res_empty_fp_ed.reason or "")
    res_empty_fp_hmac = audit_sign.verify_signature(
        log_ok, {**receipt_hmac, "key_fingerprint": ""}, hmac_key=HMAC_SECRET
    )
    assert not res_empty_fp_hmac.ok and "fingerprint" in (res_empty_fp_hmac.reason or "")


def test_cli_audit_keygen_sign_verify_ed25519_and_hmac(tmp_path, monkeypatch, capsys):
    priv = tmp_path / "cli.key"
    pub = tmp_path / "cli.pub"
    log_path = _make_log(tmp_path, 4)
    sig_ed = tmp_path / "ed.sig.json"
    sig_hmac = tmp_path / "hmac.sig.json"

    assert cli.main(["audit", "keygen", "--private-out", str(priv), "--public-out", str(pub)]) == 0
    out_kg = capsys.readouterr().out
    assert "Fingerprint:" in out_kg and priv.read_text(encoding="utf-8") not in out_kg
    assert cli.main(["audit", "keygen", "--private-out", str(priv), "--public-out", str(pub)]) == 2
    capsys.readouterr()

    assert (
        cli.main(["audit", "sign", str(log_path), "--out", str(sig_ed), "--private-key", str(priv)])
        == 0
    )
    assert "ed25519" in capsys.readouterr().out
    assert (
        cli.main(
            [
                "audit",
                "verify",
                str(log_path),
                "--signature",
                str(sig_ed),
                "--public-key",
                str(pub),
            ]
        )
        == 0
    )
    assert "Assinatura válida (ed25519" in capsys.readouterr().out

    # HMAC via variável de ambiente (falha se ausente; nunca vaza em stdout ou arquivo)
    monkeypatch.delenv("AOK_AUDIT_HMAC_KEY", raising=False)
    assert (
        cli.main(
            [
                "audit",
                "sign",
                str(log_path),
                "--out",
                str(sig_hmac),
                "--hmac-key-env",
                "AOK_AUDIT_HMAC_KEY",
            ]
        )
        == 2
    )
    assert "AOK_AUDIT_HMAC_KEY" in capsys.readouterr().err

    monkeypatch.setenv("AOK_AUDIT_HMAC_KEY", HMAC_SECRET)
    assert (
        cli.main(
            [
                "audit",
                "sign",
                str(log_path),
                "--out",
                str(sig_hmac),
                "--hmac-key-env",
                "AOK_AUDIT_HMAC_KEY",
            ]
        )
        == 0
    )
    out_sign = capsys.readouterr().out
    assert HMAC_SECRET not in out_sign
    assert HMAC_SECRET not in sig_hmac.read_text(encoding="utf-8")
    assert (
        cli.main(
            [
                "audit",
                "verify",
                str(log_path),
                "--signature",
                str(sig_hmac),
                "--hmac-key-env",
                "AOK_AUDIT_HMAC_KEY",
            ]
        )
        == 0
    )
    assert "Assinatura válida (hmac-sha256" in capsys.readouterr().out

    # Adulteração após assinatura falha na CLI
    AuditLog(log_path).append("extra")
    assert (
        cli.main(
            [
                "audit",
                "verify",
                str(log_path),
                "--signature",
                str(sig_ed),
                "--public-key",
                str(pub),
            ]
        )
        == 1
    )
    assert "Assinatura INVÁLIDA" in capsys.readouterr().out


def test_report_integration_valid_and_tampered_signature(tmp_path, monkeypatch):
    rt_dir = _write_rt_dir(tmp_path)
    priv = tmp_path / "r.key"
    pub = tmp_path / "r.pub"
    audit_sign.generate_ed25519_keypair(priv, pub)

    log_path = _make_log(tmp_path, 2)
    sig_ed = tmp_path / "r.sig.json"
    receipt = audit_sign.sign_anchor(log_path, private_key_path=priv, out_path=sig_ed)

    out_ok = tmp_path / "out_ok"
    assert (
        cli.main(
            [
                "report",
                "build",
                "--out",
                str(out_ok),
                "--dataset",
                str(ROOT / "evals/dataset.jsonl"),
                "--prompts-dir",
                str(ROOT / "evals/prompts"),
                "--config",
                str(ROOT / "examples/rag_agent/agent.yaml"),
                "--answers-dir",
                str(ROOT / "evals/answers"),
                "--redteam-baseline",
                str(rt_dir / "baseline.jsonl"),
                "--redteam-guardrails",
                str(rt_dir / "guardrails.jsonl"),
                "--fp-dir",
                str(rt_dir),
                "--audit",
                str(log_path),
                "--audit-signature",
                str(sig_ed),
                "--audit-public-key",
                str(pub),
            ]
        )
        == 0
    )
    data_ok = json.loads((out_ok / "relatorio.json").read_text(encoding="utf-8"))
    sig_meta = data_ok["audit"]["signature"]
    assert sig_meta == {
        "checked": True,
        "ok": True,
        "algorithm": "ed25519",
        "key_fingerprint": receipt["key_fingerprint"],
        "signed_at_utc": receipt["signed_at_utc"],
        "reason": None,
    }
    assert "audit_invalid" not in data_ok["semaphore"]["triggered"]
    md_ok = (out_ok / "relatorio.md").read_text(encoding="utf-8")
    html_ok = (out_ok / "relatorio.html").read_text(encoding="utf-8")
    for needle in ("ed25519", receipt["key_fingerprint"], "RFC 3161 TSA", "não-repúdio", ".sig.json"):
        assert needle in md_ok and needle in html_ok

    # HMAC no build_data (também testa nota honesta sem não-repúdio)
    sig_hmac = tmp_path / "r_hmac.sig.json"
    receipt_hmac = audit_sign.sign_anchor(log_path, hmac_key=HMAC_SECRET, out_path=sig_hmac)
    monkeypatch.setenv("AOK_AUDIT_HMAC_KEY", HMAC_SECRET)
    out_hmac = tmp_path / "out_hmac"
    assert (
        cli.main(
            [
                "check",
                "--out",
                str(out_hmac),
                "--dataset",
                str(ROOT / "evals/dataset.jsonl"),
                "--prompts-dir",
                str(ROOT / "evals/prompts"),
                "--config",
                str(ROOT / "examples/rag_agent/agent.yaml"),
                "--answers-dir",
                str(ROOT / "evals/answers"),
                "--redteam-baseline",
                str(rt_dir / "baseline.jsonl"),
                "--redteam-guardrails",
                str(rt_dir / "guardrails.jsonl"),
                "--fp-dir",
                str(rt_dir),
                "--audit",
                str(log_path),
                "--audit-signature",
                str(sig_hmac),
                "--audit-hmac-key-env",
                "AOK_AUDIT_HMAC_KEY",
            ]
        )
        == 0
    )
    md_hmac = (out_hmac / "relatorio.md").read_text(encoding="utf-8")
    assert "hmac-sha256" in md_hmac
    assert receipt_hmac["key_fingerprint"] in md_hmac
    assert "sem não-repúdio" in md_hmac
    assert "RFC 3161 TSA" in md_hmac
    assert HMAC_SECRET not in md_hmac

    # Assinatura adulterada -> vermelho / audit_invalid
    bad_sig = tmp_path / "bad.sig.json"
    bad_receipt = {**receipt, "signature_b64": base64.b64encode(b"\x00" * 64).decode("ascii")}
    bad_sig.write_text(json.dumps(bad_receipt), encoding="utf-8")
    data_bad = build.build_data(
        config=str(ROOT / "examples/rag_agent/agent.yaml"),
        dataset=str(ROOT / "evals/dataset.jsonl"),
        prompts_dir=str(ROOT / "evals/prompts"),
        answers_dir=str(ROOT / "evals/answers"),
        baseline="v1",
        candidate="v2",
        seed=42,
        redteam_baseline=str(rt_dir / "baseline.jsonl"),
        redteam_guardrails=str(rt_dir / "guardrails.jsonl"),
        fp_dir=str(rt_dir),
        audit_path=str(log_path),
        audit_signature=str(bad_sig),
        audit_public_key=str(pub),
    )
    assert data_bad["audit"]["signature"]["ok"] is False
    assert data_bad["semaphore"]["color"] == "red"
    assert "audit_invalid" in data_bad["semaphore"]["triggered"]
    md_bad = render.to_markdown(render.build_blocks(data_bad))
    assert "inválida" in md_bad and "RFC 3161 TSA" in md_bad

    # Garante que nenhuma palavra banida vaza nos relatórios com assinatura (Ed25519 / HMAC / inválida)
    for text in (md_ok, html_ok, md_hmac, md_bad):
        assert not BANNED_REPORT_WORDS.search(text)

    # Flags inválidas na CLI saem com código 2 sem traceback
    base_pkg_args = [
        "--out",
        str(tmp_path / "err_out"),
        "--dataset",
        str(ROOT / "evals/dataset.jsonl"),
        "--prompts-dir",
        str(ROOT / "evals/prompts"),
        "--config",
        str(ROOT / "examples/rag_agent/agent.yaml"),
        "--answers-dir",
        str(ROOT / "evals/answers"),
        "--redteam-baseline",
        str(rt_dir / "baseline.jsonl"),
        "--redteam-guardrails",
        str(rt_dir / "guardrails.jsonl"),
        "--fp-dir",
        str(rt_dir),
    ]
    for bad_flags in (
        ["--audit-signature", str(sig_ed), "--audit-public-key", str(pub)],
        ["--audit", str(log_path), "--audit-signature", str(sig_ed)],
        ["--audit", str(log_path), "--audit-public-key", str(pub)],
        ["--audit", str(log_path), "--audit-hmac-key-env", "AOK_AUDIT_HMAC_KEY"],
        [
            "--audit",
            str(log_path),
            "--audit-signature",
            str(sig_ed),
            "--audit-public-key",
            str(pub),
            "--audit-hmac-key-env",
            "AOK_AUDIT_HMAC_KEY",
        ],
    ):
        assert cli.main(["report", "build", *base_pkg_args, *bad_flags]) == 2
        assert cli.main(["check", *base_pkg_args, *bad_flags]) == 2

    # API Python (_audit_section / build_data) com assinatura sem chave verificadora -> audit_invalid (vermelho)
    au_no_key = build._audit_section(str(log_path), signature_path=str(sig_ed))
    assert au_no_key is not None
    assert au_no_key["signature"] == {
        "checked": True,
        "ok": False,
        "algorithm": None,
        "key_fingerprint": None,
        "signed_at_utc": None,
        "reason": "chave de verificação da assinatura não informada",
    }
    data_no_key = build.build_data(
        config=str(ROOT / "examples/rag_agent/agent.yaml"),
        dataset=str(ROOT / "evals/dataset.jsonl"),
        prompts_dir=str(ROOT / "evals/prompts"),
        answers_dir=str(ROOT / "evals/answers"),
        baseline="v1",
        candidate="v2",
        seed=42,
        redteam_baseline=str(rt_dir / "baseline.jsonl"),
        redteam_guardrails=str(rt_dir / "guardrails.jsonl"),
        fp_dir=str(rt_dir),
        audit_path=str(log_path),
        audit_signature=str(sig_ed),
    )
    assert data_no_key["semaphore"]["color"] == "red"
    assert "audit_invalid" in data_no_key["semaphore"]["triggered"]
    md_no_key = render.to_markdown(render.build_blocks(data_no_key))
    html_no_key = render.to_html(render.build_blocks(data_no_key), "t")
    assert "chave de verificação da assinatura não informada" in md_no_key
    assert "chave de verificação da assinatura não informada" in html_no_key
    assert not BANNED_REPORT_WORDS.search(md_no_key)
    assert not BANNED_REPORT_WORDS.search(html_no_key)


def test_verify_signature_bad_pem_private_as_public_missing_and_non_ed25519(tmp_path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    priv = tmp_path / "k.key"
    pub = tmp_path / "k.pub"
    audit_sign.generate_ed25519_keypair(priv, pub)
    log_path = _make_log(tmp_path, 2)
    sig_path = tmp_path / "k.sig.json"
    audit_sign.sign_anchor(log_path, private_key_path=priv, out_path=sig_path)

    bad_pem = tmp_path / "bad.pub"
    bad_pem.write_text("nao e um pem valido", encoding="utf-8")
    res_bad = audit_sign.verify_signature(log_path, sig_path, public_key_path=bad_pem)
    assert not res_bad.ok and "PEM" in (res_bad.reason or "")

    # Chave privada passada no lugar da pública
    res_priv_as_pub = audit_sign.verify_signature(log_path, sig_path, public_key_path=priv)
    assert not res_priv_as_pub.ok and "PEM" in (res_priv_as_pub.reason or "")
    assert priv.read_text(encoding="utf-8") not in (res_priv_as_pub.reason or "")

    # Arquivo público ausente
    res_missing = audit_sign.verify_signature(
        log_path, sig_path, public_key_path=tmp_path / "ausente.pub"
    )
    assert not res_missing.ok and "não encontrada" in (res_missing.reason or "")

    # Chave RSA (não Ed25519)
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_priv = tmp_path / "rsa.key"
    rsa_pub = tmp_path / "rsa.pub"
    rsa_priv.write_bytes(
        rsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    rsa_pub.write_bytes(
        rsa_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    res_rsa_pub = audit_sign.verify_signature(log_path, sig_path, public_key_path=rsa_pub)
    assert not res_rsa_pub.ok and "Ed25519" in (res_rsa_pub.reason or "")
    with pytest.raises(ValueError, match="Ed25519"):
        audit_sign.sign_anchor(log_path, private_key_path=rsa_priv)


def test_cli_audit_verify_rejects_invalid_flag_combinations(tmp_path, capsys):
    priv = tmp_path / "c.key"
    pub = tmp_path / "c.pub"
    audit_sign.generate_ed25519_keypair(priv, pub)
    log_path = _make_log(tmp_path, 2)
    sig_path = tmp_path / "c.sig.json"
    audit_sign.sign_anchor(log_path, private_key_path=priv, out_path=sig_path)

    assert cli.main(["audit", "verify", str(log_path), "--signature", str(sig_path)]) == 2
    assert "--signature exige" in capsys.readouterr().err

    assert cli.main(["audit", "verify", str(log_path), "--public-key", str(pub)]) == 2
    assert "exige --signature" in capsys.readouterr().err

    assert cli.main(["audit", "verify", str(log_path), "--hmac-key-env", "AOK_AUDIT_HMAC_KEY"]) == 2
    assert "exige --signature" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc_info:
        cli.main(
            [
                "audit",
                "verify",
                str(log_path),
                "--signature",
                str(sig_path),
                "--public-key",
                str(pub),
                "--hmac-key-env",
                "AOK_AUDIT_HMAC_KEY",
            ]
        )
    assert exc_info.value.code != 0
    capsys.readouterr()


def test_ed25519_private_key_permissions_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("permissões POSIX 0o600 aplicam-se apenas a sistemas POSIX")
    priv = tmp_path / "p.key"
    pub = tmp_path / "p.pub"
    audit_sign.generate_ed25519_keypair(priv, pub)
    assert (priv.stat().st_mode & 0o777) == 0o600
