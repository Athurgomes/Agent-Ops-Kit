"""API FastAPI: cadastro, tokens, publicação (fase 2); usuários, login e leitura (fase 3)."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import (
    AREA_VIEWER,
    MIN_PASSWORD,
    ORG_ADMIN,
    Actor,
    hash_password,
    hash_token,
    make_dependencies,
    new_token,
)
from .db import init_db, make_engine, session_dependency
from .models import (
    AdminEvent,
    Agent,
    AgentCredential,
    Area,
    Membership,
    ReportVersion,
    User,
    UserSession,
    utcnow,
)
from .portal import build_portal_router
from .reports import build_reports_router
from .sessions import LoginThrottle, build_auth_router

SLUG = r"^[a-z0-9-]{1,64}$"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def _email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.fullmatch(v):
        raise ValueError("e-mail inválido")
    return v


class UserIn(_In):
    email: str
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)

    @field_validator("email")
    @classmethod
    def _norm(cls, v):
        return _email(v)


class UserPatch(_In):
    email: str | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD, max_length=256)
    active: bool | None = None

    @field_validator("email")
    @classmethod
    def _norm(cls, v):
        return None if v is None else _email(v)


class UserOut(BaseModel):  # nunca inclui senha nem hash
    id: int
    org_id: int
    email: str
    active: bool
    created_at: datetime


class MembershipIn(_In):
    user_id: int
    role: Literal["org_admin", "area_viewer"]
    area_id: int | None = None  # obrigatório para area_viewer; org_admin vale para a organização


class MembershipOut(BaseModel):
    id: int
    user_id: int
    area_id: int | None
    role: str


class AreaListItem(BaseModel):
    id: int
    name: str
    parent_id: int | None
    agent_count: int  # agentes diretamente nesta área (inclui inativos)


class AgentListItem(BaseModel):
    id: int
    slug: str
    name: str
    area_id: int
    area_name: str
    active: bool
    tokens_active_count: int
    last_report_at: datetime | None


class TokenMeta(BaseModel):  # só metadados: nunca o token nem o hash
    token_id: int
    created_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None


class MembershipBrief(BaseModel):
    id: int
    area_id: int | None
    area_name: str | None
    role: str


class UserListItem(BaseModel):  # nunca inclui senha nem hash
    id: int
    email: str
    active: bool
    created_at: datetime
    memberships: list[MembershipBrief]


class MembershipListItem(BaseModel):
    id: int
    user_id: int
    user_email: str
    area_id: int | None
    area_name: str | None
    role: str


class EventOut(BaseModel):
    id: int
    at: datetime
    actor_user_id: int | None  # nulo = chave de bootstrap
    actor_email: str | None
    action: str
    target_type: str
    target_id: int | None


# ---- helpers com escopo na organização do ator --------------------------------------------------


def _area_or_404(s: Session, area_id: int, org_id: int) -> Area:
    area = s.get(Area, area_id)
    if area is None or area.org_id != org_id:
        raise HTTPException(404, "área não encontrada")
    return area


def _agent_or_404(s: Session, agent_id: int, org_id: int) -> Agent:
    agent = s.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agente não encontrado")
    _area_or_404(s, agent.area_id, org_id)  # o agente pertence à organização pela área
    return agent


def _user_or_404(s: Session, user_id: int, org_id: int) -> User:
    user = s.get(User, user_id)
    if user is None or user.org_id != org_id:
        raise HTTPException(404, "usuário não encontrado")
    return user


def _log(s: Session, actor: Actor, action: str, target_type: str, target_id: int | None) -> None:
    """Registra a escrita admin na mesma transação da mudança. Sem segredos: só ação e alvo."""
    s.add(
        AdminEvent(
            org_id=actor.org_id,
            actor_user_id=actor.user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
        )
    )


def _revoke_sessions(s: Session, user_id: int) -> None:
    now = utcnow()
    for row in s.scalars(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ):
        row.revoked_at = now


def build_admin_router(get_session, require_admin, current_org_admin) -> APIRouter:
    r = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_admin)])

    # ---- listagens (somente leitura, escopo na organização) ------------------------------------

    @r.get("/areas", response_model=list[AreaListItem])
    def list_areas(actor: Actor = Depends(require_admin), s: Session = Depends(get_session)):
        counts = dict(
            s.execute(
                select(Agent.area_id, func.count(Agent.id))
                .join(Area, Area.id == Agent.area_id)
                .where(Area.org_id == actor.org_id)
                .group_by(Agent.area_id)
            ).all()
        )
        areas = s.scalars(
            select(Area).where(Area.org_id == actor.org_id).order_by(Area.name, Area.id)
        )
        return [
            AreaListItem(id=a.id, name=a.name, parent_id=a.parent_id, agent_count=counts.get(a.id, 0))
            for a in areas
        ]

    @r.get("/agents", response_model=list[AgentListItem])
    def list_agents(actor: Actor = Depends(require_admin), s: Session = Depends(get_session)):
        rows = s.execute(
            select(Agent, Area.name)
            .join(Area, Area.id == Agent.area_id)
            .where(Area.org_id == actor.org_id)
            .order_by(Agent.name, Agent.id)
        ).all()
        tokens = dict(
            s.execute(
                select(AgentCredential.agent_id, func.count(AgentCredential.id))
                .where(AgentCredential.revoked_at.is_(None))
                .group_by(AgentCredential.agent_id)
            ).all()
        )
        last = dict(
            s.execute(
                select(ReportVersion.agent_id, func.max(ReportVersion.published_at)).group_by(
                    ReportVersion.agent_id
                )
            ).all()
        )
        return [
            AgentListItem(
                id=a.id,
                slug=a.slug,
                name=a.name,
                area_id=a.area_id,
                area_name=area_name,
                active=a.active,
                tokens_active_count=tokens.get(a.id, 0),
                last_report_at=last.get(a.id),
            )
            for a, area_name in rows
        ]

    @r.get("/agents/{agent_id}/tokens", response_model=list[TokenMeta])
    def list_tokens(
        agent_id: int, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        _agent_or_404(s, agent_id, actor.org_id)
        rows = s.scalars(
            select(AgentCredential)
            .where(AgentCredential.agent_id == agent_id)
            .order_by(AgentCredential.id.desc())
        )
        return [
            TokenMeta(
                token_id=c.id,
                created_at=c.created_at,
                revoked_at=c.revoked_at,
                last_used_at=c.last_used_at,
            )
            for c in rows
        ]

    @r.get("/users", response_model=list[UserListItem])
    def list_users(actor: Actor = Depends(require_admin), s: Session = Depends(get_session)):
        users = list(
            s.scalars(select(User).where(User.org_id == actor.org_id).order_by(User.email, User.id))
        )
        area_names = dict(
            s.execute(select(Area.id, Area.name).where(Area.org_id == actor.org_id)).all()
        )
        by_user: dict[int, list[MembershipBrief]] = {}
        for m in s.scalars(
            select(Membership)
            .where(Membership.user_id.in_([u.id for u in users]))
            .order_by(Membership.id)
        ):
            by_user.setdefault(m.user_id, []).append(
                MembershipBrief(
                    id=m.id, area_id=m.area_id, area_name=area_names.get(m.area_id), role=m.role
                )
            )
        return [
            UserListItem(
                id=u.id,
                email=u.email,
                active=u.active,
                created_at=u.created_at,
                memberships=by_user.get(u.id, []),
            )
            for u in users
        ]

    @r.get("/memberships", response_model=list[MembershipListItem])
    def list_memberships(actor: Actor = Depends(require_admin), s: Session = Depends(get_session)):
        area_names = dict(
            s.execute(select(Area.id, Area.name).where(Area.org_id == actor.org_id)).all()
        )
        rows = s.execute(
            select(Membership, User.email)
            .join(User, User.id == Membership.user_id)
            .where(User.org_id == actor.org_id)
            .order_by(Membership.id)
        ).all()
        return [
            MembershipListItem(
                id=m.id,
                user_id=m.user_id,
                user_email=email,
                area_id=m.area_id,
                area_name=area_names.get(m.area_id),
                role=m.role,
            )
            for m, email in rows
        ]

    @r.get("/events", response_model=list[EventOut])
    def list_events(  # só sessão de org_admin: a chave de bootstrap não lê o registro de auditoria
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        admin: User = Depends(current_org_admin),
        s: Session = Depends(get_session),
    ):
        rows = s.execute(
            select(AdminEvent, User.email)
            .outerjoin(User, User.id == AdminEvent.actor_user_id)
            .where(AdminEvent.org_id == admin.org_id)
            .order_by(AdminEvent.at.desc(), AdminEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [
            EventOut(
                id=e.id,
                at=e.at,
                actor_user_id=e.actor_user_id,
                actor_email=email,
                action=e.action,
                target_type=e.target_type,
                target_id=e.target_id,
            )
            for e, email in rows
        ]

    # ---- escrita ---------------------------------------------------------------------------------

    @r.post("/areas", status_code=201, response_model=AreaOut)
    def create_area(
        body: AreaIn, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        if body.parent_id is not None:
            _area_or_404(s, body.parent_id, actor.org_id)
        area = Area(org_id=actor.org_id, name=body.name, parent_id=body.parent_id)
        s.add(area)
        s.flush()
        _log(s, actor, "area.create", "area", area.id)
        s.commit()
        return area

    @r.patch("/areas/{area_id}", response_model=AreaOut)
    def patch_area(
        area_id: int,
        body: AreaPatch,
        actor: Actor = Depends(require_admin),
        s: Session = Depends(get_session),
    ):
        area = _area_or_404(s, area_id, actor.org_id)
        if body.name is not None:
            area.name = body.name
        if "parent_id" in body.model_fields_set:
            cur = body.parent_id
            while cur is not None:  # impede ciclo: o novo pai não pode ser a área nem descendente
                if cur == area.id:
                    raise HTTPException(422, "parent_id criaria um ciclo")
                cur = _area_or_404(s, cur, actor.org_id).parent_id
            area.parent_id = body.parent_id
        _log(s, actor, "area.update", "area", area.id)
        s.commit()
        return area

    @r.post("/agents", status_code=201, response_model=AgentOut)
    def create_agent(
        body: AgentIn, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        _area_or_404(s, body.area_id, actor.org_id)
        agent = Agent(area_id=body.area_id, slug=body.slug, name=body.name, active=True)
        s.add(agent)
        try:
            s.flush()
            _log(s, actor, "agent.create", "agent", agent.id)
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            raise HTTPException(409, "slug de agente já existe") from exc
        return agent

    @r.patch("/agents/{agent_id}", response_model=AgentOut)
    def patch_agent(
        agent_id: int,
        body: AgentPatch,
        actor: Actor = Depends(require_admin),
        s: Session = Depends(get_session),
    ):
        agent = _agent_or_404(s, agent_id, actor.org_id)
        data = body.model_dump(exclude_none=True)
        if "area_id" in data:
            _area_or_404(s, data["area_id"], actor.org_id)
        was_active = agent.active
        for k, v in data.items():
            setattr(agent, k, v)
        if data.keys() & {"name", "area_id"}:
            _log(s, actor, "agent.update", "agent", agent.id)
        if "active" in data and data["active"] != was_active:
            _log(s, actor, "agent.activate" if data["active"] else "agent.deactivate", "agent", agent.id)
        s.commit()
        return agent

    @r.post("/agents/{agent_id}/tokens", status_code=201, response_model=TokenOut)
    def issue_token(
        agent_id: int, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        _agent_or_404(s, agent_id, actor.org_id)
        token = new_token()
        cred = AgentCredential(agent_id=agent_id, token_hash=hash_token(token))
        s.add(cred)
        s.flush()
        _log(s, actor, "token.issue", "agent_token", cred.id)  # o token em si nunca vai ao registro
        s.commit()
        return TokenOut(token_id=cred.id, token=token, created_at=cred.created_at)

    @r.delete("/agents/{agent_id}/tokens/{token_id}", response_model=TokenOut)
    def revoke_token(
        agent_id: int,
        token_id: int,
        actor: Actor = Depends(require_admin),
        s: Session = Depends(get_session),
    ):
        _agent_or_404(s, agent_id, actor.org_id)
        cred = s.get(AgentCredential, token_id)
        if cred is None or cred.agent_id != agent_id:
            raise HTTPException(404, "token não encontrado")
        if cred.revoked_at is None:  # revogar de novo preserva a data original
            cred.revoked_at = utcnow()
            _log(s, actor, "token.revoke", "agent_token", cred.id)
            s.commit()
        return TokenOut(token_id=cred.id, created_at=cred.created_at, revoked_at=cred.revoked_at)

    @r.post("/users", status_code=201, response_model=UserOut)
    def create_user(
        body: UserIn, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        user = User(
            org_id=actor.org_id,
            email=body.email,
            password_hash=hash_password(body.password),
            active=True,
        )
        s.add(user)
        try:
            s.flush()
            _log(s, actor, "user.create", "user", user.id)
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            raise HTTPException(409, "e-mail já cadastrado") from exc
        return user

    @r.patch("/users/{user_id}", response_model=UserOut)
    def patch_user(
        user_id: int,
        body: UserPatch,
        actor: Actor = Depends(require_admin),
        s: Session = Depends(get_session),
    ):
        user = _user_or_404(s, user_id, actor.org_id)
        was_active = user.active
        if body.email is not None:
            user.email = body.email
            _log(s, actor, "user.update", "user", user.id)
        if body.active is not None:
            user.active = body.active
            if body.active != was_active:
                _log(s, actor, "user.activate" if body.active else "user.deactivate", "user", user.id)
        if body.password is not None:
            user.password_hash = hash_password(body.password)
            _log(s, actor, "user.password_change", "user", user.id)  # a senha nunca é registrada
        if body.password is not None or body.active is False:
            _revoke_sessions(s, user.id)  # trocar a senha ou desativar encerra as sessões
        try:
            s.commit()
        except IntegrityError as exc:
            s.rollback()
            raise HTTPException(409, "e-mail já cadastrado") from exc
        return user

    @r.post("/memberships", status_code=201, response_model=MembershipOut)
    def create_membership(
        body: MembershipIn, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        _user_or_404(s, body.user_id, actor.org_id)
        if body.role == AREA_VIEWER:
            if body.area_id is None:
                raise HTTPException(422, "area_viewer exige area_id")
            _area_or_404(s, body.area_id, actor.org_id)
        elif body.area_id is not None:
            raise HTTPException(422, f"{ORG_ADMIN} não tem area_id")
        dup = select(Membership.id).where(
            Membership.user_id == body.user_id,
            Membership.role == body.role,
            Membership.area_id.is_(None)
            if body.area_id is None
            else Membership.area_id == body.area_id,
        )
        if s.scalar(dup) is not None:
            raise HTTPException(409, "vínculo já existe")
        m = Membership(user_id=body.user_id, area_id=body.area_id, role=body.role)
        s.add(m)
        s.flush()
        _log(s, actor, "membership.create", "membership", m.id)
        s.commit()
        return m

    @r.delete("/memberships/{membership_id}", status_code=204)
    def delete_membership(
        membership_id: int, actor: Actor = Depends(require_admin), s: Session = Depends(get_session)
    ):
        m = s.get(Membership, membership_id)
        if m is None:
            raise HTTPException(404, "vínculo não encontrado")
        _user_or_404(s, m.user_id, actor.org_id)  # vínculo de outra organização: 404
        _log(s, actor, "membership.delete", "membership", m.id)
        s.delete(m)
        s.commit()
        return Response(status_code=204)

    return r


PORTAL_CSP = (
    "default-src 'self'; img-src 'self' data:; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def default_portal_dir() -> Path:
    """AOK_PORTAL_DIR ou platform/portal/dist (checkout do repositório)."""
    env = os.environ.get("AOK_PORTAL_DIR")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "portal" / "dist"


def mount_portal(app: FastAPI, dist: Path) -> None:
    """Serve o portal (SPA) em `/` via o 404 do roteador; só se `dist/index.html` existir.

    As rotas da API (e seus 401/404/405) não mudam: só GET/HEAD fora de /v1 cai aqui.
    """
    index = dist / "index.html"
    if not index.is_file():
        return
    base = dist.resolve()

    async def portal(request: Request, exc: StarletteHTTPException):
        path = request.url.path.lstrip("/")
        if request.method not in ("GET", "HEAD") or path == "v1" or path.startswith("v1/"):
            return await http_exception_handler(request, exc)
        target = (base / path).resolve()
        if path and target.is_relative_to(base) and target.is_file():
            hashed = path.startswith("assets/")  # nomes com hash do Vite: cache longo
            cache = "public, max-age=31536000, immutable" if hashed else "no-cache"
            return FileResponse(target, headers={"Cache-Control": cache})
        return FileResponse(
            index,
            headers={
                "Cache-Control": "no-cache",
                "Content-Security-Policy": PORTAL_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    app.add_exception_handler(404, portal)


def create_app(database_url: str | None = None, data_dir: str | Path | None = None) -> FastAPI:
    engine = make_engine(database_url)
    init_db(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    app = FastAPI(title="agent-ops-kit platform", version="0.1.0")
    app.state.engine = engine
    app.state.session_factory = factory
    data = Path(data_dir or os.environ.get("AOK_DATA_DIR") or "./aok_data")
    get_session = session_dependency(factory)
    current_user, current_org_admin, require_admin = make_dependencies(get_session)
    app.state.throttle = LoginThrottle()
    app.include_router(build_admin_router(get_session, require_admin, current_org_admin))
    app.include_router(build_reports_router(get_session, data))
    app.include_router(build_auth_router(get_session, current_user, app.state.throttle))
    app.include_router(build_portal_router(get_session, current_user, current_org_admin, data))
    mount_portal(app, default_portal_dir())
    return app
