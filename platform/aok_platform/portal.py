"""Leitura (fase 3): áreas, agentes, relatórios, download e histórico. Só com sessão de usuário."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import visible_area_ids
from .models import Agent, Area, DownloadLog, ReportVersion, User, utcnow

Format = Literal["md", "html", "json"]
_FORMATS = {
    "md": ("file_md", "text/markdown; charset=utf-8"),
    "html": ("file_html", "text/html; charset=utf-8"),
    "json": ("file_json", "application/json"),
}
# HTML do relatório é conteúdo estático: nada de script, rede ou frame.
HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"


class AreaNode(BaseModel):
    id: int
    name: str
    parent_id: int | None
    children: list[AreaNode] = []


class AgentItem(BaseModel):
    id: int
    area_id: int
    slug: str
    name: str
    active: bool


class ReportItem(BaseModel):
    id: int
    seq: int
    published_at: datetime
    generated_at: str | None
    status_semaforo: str


class ReportDetail(ReportItem):
    agent_id: int
    agent_slug: str
    agent_name: str
    area_id: int
    sha256: str
    audit_verify_ok: bool | None
    audit_anchor: str | None
    model: str | None
    prompt_sha256: str | None
    dataset_sha256: str | None
    seed: int | None
    n_cases: int | None
    summary: dict
    limitations: list[str] = []  # texto fixo de limitações do relatorio.json (sem texto de ataque)


class DownloadItem(BaseModel):
    id: int
    report_id: int
    seq: int
    agent_id: int
    agent_slug: str
    agent_name: str
    area_id: int
    area_name: str
    format: str
    downloaded_at: datetime  # quando o usuário baixou
    generated_at: str | None  # quando o relatório foi gerado (relatorio.json)
    user_email: str | None = None  # só na rota admin


def _generated_at(row: ReportVersion, data_dir: Path) -> str | None:
    summary = row.summary_json or {}
    if "generated_at" in summary:
        return summary["generated_at"]
    try:  # versão publicada antes de o resumo guardar o campo: lê do arquivo
        return json.loads((data_dir / row.file_json).read_text(encoding="utf-8")).get(
            "generated_at"
        )
    except (OSError, ValueError, AttributeError):
        return None


def _limitations(row: ReportVersion, data_dir: Path) -> list[str]:
    try:
        items = json.loads((data_dir / row.file_json).read_text(encoding="utf-8")).get("limitations")
    except (OSError, ValueError, AttributeError):
        return []
    return [x for x in items if isinstance(x, str)] if isinstance(items, list) else []


def _build_tree(areas: list[Area]) -> list[AreaNode]:
    nodes = {a.id: AreaNode(id=a.id, name=a.name, parent_id=a.parent_id) for a in areas}
    roots: list[AreaNode] = []
    for a in areas:  # quem tem o pai fora do alcance vira raiz (o pai não é revelado)
        node = nodes[a.id]
        if a.parent_id in nodes:
            nodes[a.parent_id].children.append(node)
        else:
            node.parent_id = None
            roots.append(node)
    return roots


def build_portal_router(get_session, current_user, current_org_admin, data_dir: Path) -> APIRouter:
    r = APIRouter(prefix="/v1")

    def agent_or_404(s: Session, user: User, agent_id: int) -> Agent:
        agent = s.get(Agent, agent_id)
        if agent is None or agent.area_id not in visible_area_ids(s, user):
            raise HTTPException(404, "agente não encontrado")
        return agent

    def report_or_404(s: Session, user: User, report_id: int) -> tuple[ReportVersion, Agent]:
        row = s.get(ReportVersion, report_id)
        if row is None:
            raise HTTPException(404, "relatório não encontrado")
        try:
            agent = agent_or_404(s, user, row.agent_id)
        except HTTPException:
            raise HTTPException(404, "relatório não encontrado") from None
        return row, agent

    def report_item(row: ReportVersion) -> ReportItem:
        return ReportItem(
            id=row.id,
            seq=row.seq,
            published_at=row.published_at,
            generated_at=_generated_at(row, data_dir),
            status_semaforo=row.status_semaforo,
        )

    @r.get("/areas", response_model=list[AreaNode])
    def list_areas(user: User = Depends(current_user), s: Session = Depends(get_session)):
        ids = visible_area_ids(s, user)
        areas = list(s.scalars(select(Area).where(Area.id.in_(ids)).order_by(Area.name, Area.id)))
        return _build_tree(areas)

    @r.get("/areas/{area_id}/agents", response_model=list[AgentItem])
    def list_agents(
        area_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)
    ):
        if area_id not in visible_area_ids(s, user):
            raise HTTPException(404, "área não encontrada")
        return list(s.scalars(select(Agent).where(Agent.area_id == area_id).order_by(Agent.name)))

    @r.get("/agents/{agent_id}/reports", response_model=list[ReportItem])
    def list_reports(
        agent_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)
    ):
        agent_or_404(s, user, agent_id)
        rows = s.scalars(
            select(ReportVersion)
            .where(ReportVersion.agent_id == agent_id)
            .order_by(ReportVersion.seq.desc())
        )
        return [report_item(x) for x in rows]

    @r.get("/reports/{report_id}", response_model=ReportDetail)
    def get_report(
        report_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)
    ):
        row, agent = report_or_404(s, user, report_id)
        return ReportDetail(
            **report_item(row).model_dump(),
            agent_id=agent.id,
            agent_slug=agent.slug,
            agent_name=agent.name,
            area_id=agent.area_id,
            sha256=row.sha256,
            audit_verify_ok=row.audit_verify_ok,
            audit_anchor=row.audit_anchor,
            model=row.model,
            prompt_sha256=row.prompt_sha256,
            dataset_sha256=row.dataset_sha256,
            seed=row.seed,
            n_cases=row.n_cases,
            summary=row.summary_json,
            limitations=_limitations(row, data_dir),
        )

    @r.get("/reports/{report_id}/download")
    def download(
        report_id: int,
        format: Format,
        user: User = Depends(current_user),
        s: Session = Depends(get_session),
    ):
        row, agent = report_or_404(s, user, report_id)
        column, media = _FORMATS[format]
        base = data_dir.resolve()
        path = (base / getattr(row, column)).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise HTTPException(404, "arquivo do relatório indisponível")
        content = path.read_bytes()  # lê antes de gravar o log: só registra o que foi servido
        s.add(
            DownloadLog(
                report_version_id=row.id, user_id=user.id, downloaded_at=utcnow(), format=format
            )
        )
        s.commit()
        headers = {
            "Content-Disposition": f'attachment; filename="{agent.slug}-{row.seq}.{format}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        }
        if format == "html":
            headers["Content-Security-Policy"] = HTML_CSP
        return Response(content, media_type=media, headers=headers)

    def downloads(
        s: Session,
        org_id: int,
        user_id: int | None,
        area_id: int | None,
        agent_id: int | None,
        limit: int,
        offset: int,
        with_email: bool,
    ) -> list[DownloadItem]:
        q = (
            select(DownloadLog, ReportVersion, Agent, Area, User)
            .join(ReportVersion, ReportVersion.id == DownloadLog.report_version_id)
            .join(Agent, Agent.id == ReportVersion.agent_id)
            .join(Area, Area.id == Agent.area_id)
            .join(User, User.id == DownloadLog.user_id)
            .where(Area.org_id == org_id)
            .order_by(DownloadLog.downloaded_at.desc(), DownloadLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if user_id is not None:
            q = q.where(DownloadLog.user_id == user_id)
        if area_id is not None:
            q = q.where(Agent.area_id == area_id)
        if agent_id is not None:
            q = q.where(Agent.id == agent_id)
        return [
            DownloadItem(
                id=dl.id,
                report_id=rv.id,
                seq=rv.seq,
                agent_id=ag.id,
                agent_slug=ag.slug,
                agent_name=ag.name,
                area_id=ar.id,
                area_name=ar.name,
                format=dl.format,
                downloaded_at=dl.downloaded_at,
                generated_at=_generated_at(rv, data_dir),
                user_email=us.email if with_email else None,
            )
            for dl, rv, ag, ar, us in s.execute(q)
        ]

    @r.get("/me/downloads", response_model=list[DownloadItem])
    def my_downloads(
        area_id: int | None = None,
        agent_id: int | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        user: User = Depends(current_user),
        s: Session = Depends(get_session),
    ):
        # sempre filtrado pelo próprio usuário: ninguém vê downloads de outras pessoas (LGPD)
        return downloads(
            s, user.org_id, user.id, area_id, agent_id, limit, offset, with_email=False
        )

    @r.get("/admin/downloads", response_model=list[DownloadItem])
    def all_downloads(
        area_id: int | None = None,
        agent_id: int | None = None,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        admin: User = Depends(current_org_admin),
        s: Session = Depends(get_session),
    ):
        return downloads(s, admin.org_id, None, area_id, agent_id, limit, offset, with_email=True)

    return r
