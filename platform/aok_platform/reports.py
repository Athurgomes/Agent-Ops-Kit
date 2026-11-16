"""POST /v1/reports (fase 2): publica o pacote com token de agente. Sem rota de leitura (fase 3)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import hash_token
from .models import Agent, AgentCredential, ReportVersion, utcnow

MAX_BODY = 1024 * 1024  # 1 MiB no total
FILES = ("relatorio.md", "relatorio.html", "relatorio.json")  # mesmo conjunto de pacote.json
_HEX64 = re.compile(r"[0-9a-f]{64}")


class PackageIn(BaseModel):
    """Mesmo formato do pacote.json do motor + o conteúdo dos 3 arquivos. Campos extras: recusados."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    timestamp: str = Field(pattern=r"^\d{8}T\d{6}Z$")
    semaphore: Literal["green", "yellow", "red"]
    sha256: dict[str, str]
    files: dict[str, str]

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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


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
    digest = hashlib.sha256(raw["relatorio.json"]).hexdigest()

    def duplicate() -> HTTPException:
        return HTTPException(409, "relatório já publicado para este agente")

    exists = select(ReportVersion.id).where(
        ReportVersion.agent_id == agent.id, ReportVersion.sha256 == digest
    )
    if s.scalar(exists) is not None:
        raise duplicate()

    rel = Path(agent.slug) / digest
    folder = data_dir / rel
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for name in FILES:
            _write_atomic(folder / name, raw[name])
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
        )

    return r
