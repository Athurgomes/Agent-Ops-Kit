"""POST /v1/reports (fase 2): publica o pacote com token de agente. A leitura está em portal.py."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent_ops_kit.audit_sign import verify_bytes
from agent_ops_kit.reproduce import (
    DIVERGENT,
    NOT_REPRODUCIBLE,
    SAME,
    VERDICTS,
    WITHIN,
)
from agent_ops_kit.reproduce import (
    SCHEMA_VERSION as REPRO_SCHEMA_VERSION,
)
from agent_ops_kit.reproduce import (
    validate as validate_reproduction,
)

from .auth import hash_token, org_is_active
from .models import Agent, AgentCredential, AgentPublicKey, ReportVersion, utcnow

MAX_BODY = 1024 * 1024  # 1 MiB no total
FILES = ("relatorio.md", "relatorio.html", "relatorio.json")  # mesmo conjunto de pacote.json
SIG_FILE = "relatorio.json.sig"  # conteúdo vem em `signature`; fora de FILES e de pacote.json
REPRO_FILE = "reproducao.json"  # opcional: saída do `aok reproduce` em `reproducao_json`
_HEX64 = re.compile(r"[0-9a-f]{64}")


class PackageIn(BaseModel):
    """Mesmo formato do pacote.json do motor + o conteúdo dos 3 arquivos. Campos extras: recusados."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    timestamp: str = Field(pattern=r"^\d{8}T\d{6}Z$")
    semaphore: Literal["green", "yellow", "red"]
    sha256: dict[str, str]
    files: dict[str, str]
    signature: str | None = Field(default=None, max_length=4096)  # opcional: conteúdo do .sig
    reproducao_json: str | None = None  # opcional: conteúdo do reproducao.json

    @field_validator("sha256", "files")
    @classmethod
    def _exact_files(cls, v: dict[str, str]) -> dict[str, str]:
        if set(v) != set(FILES):
            raise ValueError(f"chaves esperadas: {', '.join(FILES)}")
        return v

    @field_validator("sha256")
    @classmethod
    def _hex(cls, v: dict[str, str]) -> dict[str, str]:
        if not all(_HEX64.fullmatch(h) for h in v.values()):
            raise ValueError("sha256 deve ter 64 caracteres hexadecimais minúsculos")
        return v


class ReportOut(BaseModel):
    seq: int
    sha256: str
    published_at: datetime
    status_semaforo: str
    signed: bool
    verified: bool
    verification_status: str | None
    has_reproducao: bool


def _agent_from_token(authorization: str | None, s: Session) -> Agent:
    scheme, _, given = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not given.strip():
        raise HTTPException(401, "token ausente ou inválido", {"WWW-Authenticate": "Bearer"})
    cred = s.scalar(
        select(AgentCredential).where(AgentCredential.token_hash == hash_token(given.strip()))
    )
    if cred is None or cred.revoked_at is not None:
        raise HTTPException(401, "token ausente ou inválido", {"WWW-Authenticate": "Bearer"})
    agent = s.get(Agent, cred.agent_id)
    if agent is not None and not org_is_active(s, agent.org_id):
        raise HTTPException(401, "token ausente ou inválido", {"WWW-Authenticate": "Bearer"})
    if agent is None or not agent.active:
        raise HTTPException(403, "agente inativo")
    cred.last_used_at = utcnow()
    s.commit()
    return agent


def _pick(d, *path):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _summarize(js: dict) -> dict:
    """Resumo do relatorio.json calculado no servidor (nada vindo do cliente além do arquivo)."""
    ev, rt, au = js.get("eval") or {}, js.get("redteam") or {}, js.get("audit")
    return {
        "generated_at": js.get("generated_at"),
        "semaphore": js["semaphore"],
        "agent": js.get("agent"),
        "eval": {
            k: ev.get(k)
            for k in (
                "baseline",
                "candidate",
                "n_cases",
                "mean_baseline",
                "mean_candidate",
                "mean_diff",
                "ci95_low",
                "ci95_high",
                "p_value",
                "regression",
            )
        },
        "redteam": {
            "asr_baseline": _pick(rt, "asr", "baseline", "total"),
            "asr_guardrails": _pick(rt, "asr", "guardrails", "total"),
            "false_positives": rt.get("false_positives"),
        },
        "audit": au,
    }


def _facts(js: dict) -> dict:
    """Colunas derivadas do relatorio.json; o manifesto é o da variante candidata."""
    ev = js.get("eval") or {}
    au = js.get("audit") if isinstance(js.get("audit"), dict) else None
    man = _pick(ev, "manifest", ev.get("candidate")) or {}
    return {
        "status_semaforo": js["semaphore"]["color"],
        "audit_verify_ok": None if au is None else bool(au.get("ok")),
        "audit_anchor": None if au is None else au.get("anchor"),
        "model": _pick(js, "agent", "model"),
        "prompt_sha256": man.get("prompt_sha256"),
        "dataset_sha256": man.get("dataset_sha256"),
        "seed": ev.get("seed"),
        "n_cases": ev.get("n_cases"),
    }


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: MoveFileExW concorrente no mesmo destino pode retornar Access Denied
                if os.name != "nt" or attempt == 9:
                    raise
                time.sleep(0.002 * (attempt + 1))
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _check_signature(signature: str | None, raw: bytes, agent: Agent, s: Session) -> str | None:
    """Devolve o fingerprint se a assinatura vale; None se o relatório fica "não assinado"; 422 se recusa."""
    bad = HTTPException(422, "assinatura ausente ou inválida")  # mensagem única, sem detalhes
    keys = list(s.scalars(select(AgentPublicKey).where(AgentPublicKey.agent_id == agent.id)))
    active = {k.fingerprint: k for k in keys if k.revoked_at is None}
    try:
        receipt = json.loads(signature) if signature else None
    except ValueError:
        receipt = None
    if not isinstance(receipt, dict):  # ausente (ou ilegível)
        if active or agent.require_signature:
            raise bad
        return None
    fp = receipt.get("key_fingerprint")
    key = active.get(fp) if isinstance(fp, str) else None
    if key is not None:
        if verify_bytes(raw, receipt, key.public_key_pem.encode("ascii")).ok:
            return key.fingerprint
        raise bad
    if keys or agent.require_signature:  # chave revogada, de outro agente ou desconhecida
        raise bad
    return None  # agente sem chave cadastrada: vale como antes, "não assinado"


def _check_verification(
    reproducao_json: str | None, report_digest: str, agent: Agent
) -> tuple[bool, str | None, bytes | None]:
    """Valida reproducao.json opcional e extrai (verified, verification_status, raw_bytes)."""
    if reproducao_json is None:
        if agent.require_verification:
            raise HTTPException(
                422, "este agente exige anexo reproducao.json válido (verificação obrigatória)"
            )
        return False, None, None
    try:
        parsed = json.loads(reproducao_json)
    except ValueError as exc:
        raise HTTPException(422, "reproducao.json inválido: JSON malformado") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(422, "reproducao.json inválido: objeto JSON esperado")
    try:
        repro = validate_reproduction(parsed)
    except ValidationError as exc:
        raise HTTPException(422, "reproducao.json inválido: esquema incompatível") from exc
    if repro.schema_version != REPRO_SCHEMA_VERSION or repro.kind != "reproducao":
        raise HTTPException(422, "reproducao.json inválido: versão ou tipo incompatível")
    if not repro.verification.ok:
        raise HTTPException(422, "reproducao.json inválido: verificação offline falhou")
    if repro.original.report_sha256 != report_digest:
        raise HTTPException(
            422, "reproducao.json não corresponde ao relatorio.json deste pacote (sha256 divergente)"
        )
    if not repro.items:
        raise HTTPException(422, "reproducao.json inválido: nenhum item verificado")
    if not all(item.verdict in VERDICTS for item in repro.items):
        raise HTTPException(422, "reproducao.json inválido: veredito desconhecido")
    expected_counts = {v: sum(item.verdict == v for item in repro.items) for v in VERDICTS}
    if repro.verdict_counts != expected_counts:
        raise HTTPException(422, "reproducao.json inválido: contagem de vereditos inconsistente")
    if expected_counts[DIVERGENT] > 0:
        verified, status = False, DIVERGENT
    elif expected_counts[NOT_REPRODUCIBLE] > 0:
        verified, status = False, NOT_REPRODUCIBLE
    elif expected_counts[WITHIN] > 0:
        verified, status = True, WITHIN
    else:
        verified, status = True, SAME
    if agent.require_verification and not verified:
        raise HTTPException(
            422,
            f"este agente exige verificação aprovada; o veredito do reproducao.json foi '{status}'",
        )
    return verified, status, reproducao_json.encode("utf-8")


def _store(pkg: PackageIn, agent: Agent, s: Session, data_dir: Path) -> ReportVersion:
    """Valida, grava arquivos (atômico) e a linha. Uma pasta por (agente, sha256): sem corrida."""
    raw = {name: pkg.files[name].encode("utf-8") for name in FILES}
    for name in FILES:
        if hashlib.sha256(raw[name]).hexdigest() != pkg.sha256[name]:
            raise HTTPException(422, f"sha256 divergente em {name}")
    try:
        js = json.loads(raw["relatorio.json"])
        facts, summary = _facts(js), _summarize(js)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "relatorio.json inválido") from exc
    if facts["status_semaforo"] != pkg.semaphore:
        raise HTTPException(422, "semáforo declarado diverge do relatorio.json")
    key_fp = _check_signature(pkg.signature, raw["relatorio.json"], agent, s)
    digest = hashlib.sha256(raw["relatorio.json"]).hexdigest()
    verified, verification_status, repro_bytes = _check_verification(
        pkg.reproducao_json, digest, agent
    )

    def duplicate() -> HTTPException:
        return HTTPException(409, "relatório já publicado para este agente")

    exists = select(ReportVersion.id).where(
        ReportVersion.agent_id == agent.id, ReportVersion.sha256 == digest
    )
    if s.scalar(exists) is not None:
        raise duplicate()

    rel = Path(str(agent.org_id)) / agent.slug / digest  # <org_id>/<slug>/<sha256>: sem colisão entre orgs
    folder = data_dir / rel
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for name in FILES:
            _write_atomic(folder / name, raw[name])
        if key_fp is not None:
            _write_atomic(folder / SIG_FILE, pkg.signature.encode("utf-8"))
        repro_rel: str | None = None
        if repro_bytes is not None:
            _write_atomic(folder / REPRO_FILE, repro_bytes)
            repro_rel = (rel / REPRO_FILE).as_posix()
        _write_atomic(  # mesmo formato do pacote.json do motor
            folder / "pacote.json",
            json.dumps(
                {
                    "agent_id": agent.slug,
                    "timestamp": pkg.timestamp,
                    "semaphore": pkg.semaphore,
                    "sha256": pkg.sha256,
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            + b"\n",
        )
        for _ in range(3):  # seq concorrente: a unicidade (agent_id, seq) barra e tentamos de novo
            seq = (
                s.scalar(
                    select(func.max(ReportVersion.seq)).where(ReportVersion.agent_id == agent.id)
                )
                or 0
            ) + 1
            row = ReportVersion(
                agent_id=agent.id,
                seq=seq,
                sha256=digest,
                summary_json=summary,
                **facts,
                signed=key_fp is not None,
                key_fingerprint=key_fp,
                verified=verified,
                verification_status=verification_status,
                file_reproducao=repro_rel,
                file_md=(rel / FILES[0]).as_posix(),
                file_html=(rel / FILES[1]).as_posix(),
                file_json=(rel / FILES[2]).as_posix(),
            )
            s.add(row)
            try:
                s.commit()
                return row
            except IntegrityError:
                s.rollback()
                if s.scalar(exists) is not None:
                    raise duplicate() from None
        raise HTTPException(503, "não foi possível reservar a sequência; tente de novo")
    except BaseException:
        s.rollback()
        if s.scalar(exists) is None:  # só apaga se nenhuma linha usa a pasta
            shutil.rmtree(folder, ignore_errors=True)
        raise


def build_reports_router(get_session, data_dir: Path) -> APIRouter:
    r = APIRouter(prefix="/v1")

    @r.post("/reports", status_code=201, response_model=ReportOut)
    async def publish_report(request: Request, s: Session = Depends(get_session)):
        agent = await run_in_threadpool(_agent_from_token, request.headers.get("authorization"), s)
        try:
            if int(request.headers.get("content-length") or 0) > MAX_BODY:
                raise HTTPException(413, "corpo acima de 1 MiB")
        except ValueError:
            raise HTTPException(400, "Content-Length inválido") from None
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BODY:
                raise HTTPException(413, "corpo acima de 1 MiB")
        try:
            pkg = PackageIn.model_validate_json(bytes(body))
        except ValidationError as exc:
            msgs = [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()]
            raise HTTPException(422, "pacote inválido: " + "; ".join(msgs)) from None
        if pkg.agent_id != agent.slug:
            raise HTTPException(403, "agent_id do corpo não corresponde ao agente do token")
        row = await run_in_threadpool(_store, pkg, agent, s, data_dir)
        return ReportOut(
            seq=row.seq,
            sha256=row.sha256,
            published_at=row.published_at,
            status_semaforo=row.status_semaforo,
            signed=row.signed,
            verified=row.verified,
            verification_status=row.verification_status,
            has_reproducao=row.file_reproducao is not None,
        )

    return r
