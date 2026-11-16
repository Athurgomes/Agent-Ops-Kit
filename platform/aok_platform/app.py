"""API FastAPI (fase 2): cadastro de áreas/agentes e emissão/revogação de tokens."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .auth import hash_token, new_token, require_admin
from .db import init_db, make_engine, session_dependency
from .models import Agent, AgentCredential, Area, Organization, utcnow

SLUG = r"^[a-z0-9-]{1,64}$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AreaIn(_In):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None


class AreaPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent_id: int | None = None  # null explícito = vira macro-área


class AreaOut(BaseModel):
    id: int
    name: str
    parent_id: int | None


class AgentIn(_In):
    area_id: int
    slug: str = Field(pattern=SLUG)
    name: str = Field(min_length=1, max_length=200)


class AgentPatch(_In):  # slug é imutável: é o agent_id usado nos pacotes
    name: str | None = Field(default=None, min_length=1, max_length=200)
    area_id: int | None = None
    active: bool | None = None


class AgentOut(BaseModel):
    id: int
    area_id: int
    slug: str
    name: str
    active: bool


class TokenOut(BaseModel):
    token_id: int
    token: str | None = None  # só na emissão
    created_at: datetime
    revoked_at: datetime | None = None


def _area_or_404(s: Session, area_id: int) -> Area:
    area = s.get(Area, area_id)
    if area is None:
        raise HTTPException(404, "área não encontrada")
    return area


def _agent_or_404(s: Session, agent_id: int) -> Agent:
    agent = s.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agente não encontrado")
    return agent


def build_admin_router(get_session) -> APIRouter:
    r = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_admin)])

    @r.post("/areas", status_code=201, response_model=AreaOut)
    def create_area(body: AreaIn, s: Session = Depends(get_session)):
        if body.parent_id is not None:
            _area_or_404(s, body.parent_id)
        org_id = s.scalar(select(Organization.id).order_by(Organization.id).limit(1))
        area = Area(org_id=org_id, name=body.name, parent_id=body.parent_id)
        s.add(area)
        s.commit()
        return area

    @r.patch("/areas/{area_id}", response_model=AreaOut)
    def patch_area(area_id: int, body: AreaPatch, s: Session = Depends(get_session)):
        area = _area_or_404(s, area_id)
        if body.name is not None:
            area.name = body.name
        if "parent_id" in body.model_fields_set:
            cur = body.parent_id
            while cur is not None:  # impede ciclo: o novo pai não pode ser a área nem descendente
                if cur == area.id:
                    raise HTTPException(422, "parent_id criaria um ciclo")
                cur = _area_or_404(s, cur).parent_id
            area.parent_id = body.parent_id
        s.commit()
        return area

    @r.post("/agents", status_code=201, response_model=AgentOut)
    def create_agent(body: AgentIn, s: Session = Depends(get_session)):
        _area_or_404(s, body.area_id)
        agent = Agent(area_id=body.area_id, slug=body.slug, name=body.name, active=True)
        s.add(agent)
        try:
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            raise HTTPException(409, "slug de agente já existe") from exc
        return agent

    @r.patch("/agents/{agent_id}", response_model=AgentOut)
    def patch_agent(agent_id: int, body: AgentPatch, s: Session = Depends(get_session)):
        agent = _agent_or_404(s, agent_id)
        data = body.model_dump(exclude_none=True)
        if "area_id" in data:
            _area_or_404(s, data["area_id"])
        for k, v in data.items():
            setattr(agent, k, v)
        s.commit()
        return agent

    @r.post("/agents/{agent_id}/tokens", status_code=201, response_model=TokenOut)
    def issue_token(agent_id: int, s: Session = Depends(get_session)):
        _agent_or_404(s, agent_id)
        token = new_token()
        cred = AgentCredential(agent_id=agent_id, token_hash=hash_token(token))
        s.add(cred)
        s.commit()
        return TokenOut(token_id=cred.id, token=token, created_at=cred.created_at)

    @r.delete("/agents/{agent_id}/tokens/{token_id}", response_model=TokenOut)
    def revoke_token(agent_id: int, token_id: int, s: Session = Depends(get_session)):
        cred = s.get(AgentCredential, token_id)
        if cred is None or cred.agent_id != agent_id:
            raise HTTPException(404, "token não encontrado")
        if cred.revoked_at is None:  # revogar de novo preserva a data original
            cred.revoked_at = utcnow()
            s.commit()
        return TokenOut(token_id=cred.id, created_at=cred.created_at, revoked_at=cred.revoked_at)

    return r


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url)
    init_db(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(title="agent-ops-kit platform", version="0.1.0")
    app.state.engine = engine
    app.state.session_factory = factory
    app.include_router(build_admin_router(session_dependency(factory)))
    return app
