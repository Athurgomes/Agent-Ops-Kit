"""Operador da plataforma (/v1/ops): login próprio e visão multiempresa SÓ de metadados.

Desligado por padrão: as rotas só existem com AOK_OPS_ENABLED=true (senão 404, como se não existissem).
Regra de privacidade: o operador NÃO lê conteúdo de relatórios (nada de summary_json, ressalvas,
arquivos ou download) e nunca vê token, hash ou senha; a única senha que sai é a gerada na criação
ou no reset de um admin, devolvida uma vez. O operador não pertence a organização e a chave de
bootstrap não tem relação com ele.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (
    ORG_ADMIN,
    burn_password_check,
    cookie_secure,
    generate_password,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)
from .models import (
    AdminEvent,
    Agent,
    AgentCredential,
    Area,
    Membership,
    OperatorEvent,
    OperatorSession,
    Organization,
    PlatformOperator,
    ReportVersion,
    User,
    UserSession,
    utcnow,
)
from .sessions import LoginThrottle

OPS_COOKIE = "aok_ops_session"
OPS_COOKIE_PATH = "/v1/ops"
OPS_SESSION_TTL = 4 * 3600
SLUG = r"^[a-z0-9-]{1,64}$"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ops_enabled() -> bool:
    return os.environ.get("AOK_OPS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 254 or not _EMAIL.fullmatch(v):
        raise ValueError("e-mail inválido")
    return v


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(_In):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class OperatorOut(BaseModel):
    id: int
    email: str


class OrgIn(_In):
    slug: str = Field(pattern=SLUG)
    name: str = Field(min_length=1, max_length=200)


class OrgPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None


class AdminIn(_In):
    email: str = Field(max_length=254)


class OrgOut(BaseModel):
    id: int
    slug: str
    name: str
    active: bool
    created_at: datetime


class OrgListItem(OrgOut):
    areas_count: int
    agents_count: int
    users_count: int
    tokens_active_count: int
    reports_count: int
    last_report_at: datetime | None


class CreatedAdmin(BaseModel):  # a senha vai aqui UMA vez; não existe rota que a leia depois
    user_id: int
    email: str
    password: str


class AreaNodeOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    children: list[AreaNodeOut] = []


class AgentMeta(BaseModel):
    id: int
    slug: str
    name: str
    area_name: str
    active: bool
    tokens_active_count: int
    last_report_at: datetime | None
    latest_semaforo: str | None


class AccessMeta(BaseModel):
    role: str
    area_name: str | None


class UserMeta(BaseModel):
    id: int
    email: str
    active: bool
    access: list[AccessMeta]


class ReportMeta(BaseModel):  # só metadados: sem resumo, ressalvas, arquivos nem hashes
    id: int
    agent_slug: str
    seq: int
    status_semaforo: str
    generated_at: str | None
    published_at: datetime
    n_cases: int | None
    model: str | None


class OrgDetail(OrgOut):
    areas: list[AreaNodeOut]
    agents: list[AgentMeta]
    users: list[UserMeta]
    reports: list[ReportMeta]


class OrgEventOut(BaseModel):
    id: int
    at: datetime
    actor_user_id: int | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: int | None


class OperatorEventOut(BaseModel):
    id: int
    at: datetime
    operator_id: int
    operator_email: str
    action: str
    target_org_id: int | None
    target_org_slug: str | None
    target_type: str | None
    target_id: int | None


def _no_store(response: Response) -> None:
    """Respostas com senha gerada nunca podem ficar em cache (navegador, proxy ou histórico)."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _org_or_404(s: Session, org_id: int) -> Organization:
    org = s.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "organização não encontrada")
    return org


def _log(s: Session, op: PlatformOperator, action: str, org_id=None, target_type=None, target_id=None):
    s.add(
        OperatorEvent(
            operator_id=op.id,
            action=action,
            target_org_id=org_id,
            target_type=target_type,
            target_id=target_id,
        )
    )


def _operator_from_request(request: Request, s: Session) -> PlatformOperator | None:
    """Só o cookie do operador conta: sessão de usuário, org_admin ou bootstrap não valem aqui."""
    token = request.cookies.get(OPS_COOKIE)
    if not token:
        return None
    row = s.scalar(select(OperatorSession).where(OperatorSession.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= utcnow():
        return None
    op = s.get(PlatformOperator, row.operator_id)
    return op if op is not None and op.active else None


def _org_stats(s: Session, org_ids: list[int]) -> dict[int, dict]:
    if not org_ids:
        return {}

    def counts(q):
        return dict(s.execute(q).all())

    areas = counts(
        select(Area.org_id, func.count(Area.id))
        .where(Area.org_id.in_(org_ids))
        .group_by(Area.org_id)
    )
    agents = counts(
        select(Agent.org_id, func.count(Agent.id))
        .where(Agent.org_id.in_(org_ids))
        .group_by(Agent.org_id)
    )
    users = counts(
        select(User.org_id, func.count(User.id))
        .where(User.org_id.in_(org_ids))
        .group_by(User.org_id)
    )
    tokens = counts(
        select(Agent.org_id, func.count(AgentCredential.id))
        .join(Agent, Agent.id == AgentCredential.agent_id)
        .where(Agent.org_id.in_(org_ids), AgentCredential.revoked_at.is_(None))
        .group_by(Agent.org_id)
    )
    reports = {
        org: (n, last)
        for org, n, last in s.execute(
            select(Agent.org_id, func.count(ReportVersion.id), func.max(ReportVersion.published_at))
            .join(Agent, Agent.id == ReportVersion.agent_id)
            .where(Agent.org_id.in_(org_ids))
            .group_by(Agent.org_id)
        ).all()
    }
    return {
        i: {
            "areas_count": areas.get(i, 0),
            "agents_count": agents.get(i, 0),
            "users_count": users.get(i, 0),
            "tokens_active_count": tokens.get(i, 0),
            "reports_count": reports.get(i, (0, None))[0],
            "last_report_at": reports.get(i, (0, None))[1],
        }
        for i in org_ids
    }


def build_ops_router(get_session, throttle: LoginThrottle) -> APIRouter:
    r = APIRouter(prefix="/v1/ops")

    def current_operator(request: Request, s: Session = Depends(get_session)) -> PlatformOperator:
        op = _operator_from_request(request, s)
        if op is None:
            raise HTTPException(401, "não autenticado")
        return op

    # ---- autenticação (separada da de usuários) -----------------------------------------------

    @r.post("/auth/login", response_model=OperatorOut)
    def login(body: LoginIn, response: Response, s: Session = Depends(get_session)):
        email = body.email.strip().lower()
        wait = throttle.retry_after(email)
        if wait:
            raise HTTPException(
                429, "muitas tentativas; tente novamente mais tarde", {"Retry-After": str(wait)}
            )
        op = s.scalar(select(PlatformOperator).where(PlatformOperator.email == email))
        if op is None or not op.active:
            burn_password_check(body.password)  # mesmo tempo nos três casos
            good = False
        else:
            good = verify_password(body.password, op.password_hash)
        if not good:
            throttle.fail(email)
            raise HTTPException(401, "e-mail ou senha inválidos")
        throttle.ok(email)
        token = new_token()
        now = utcnow()
        s.add(
            OperatorSession(
                operator_id=op.id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + timedelta(seconds=OPS_SESSION_TTL),
            )
        )
        _log(s, op, "auth.login")
        s.commit()
        response.set_cookie(
            OPS_COOKIE,
            token,
            max_age=OPS_SESSION_TTL,
            httponly=True,
            samesite="strict",
            secure=cookie_secure(),
            path=OPS_COOKIE_PATH,
        )
        return OperatorOut(id=op.id, email=op.email)

    @r.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response, s: Session = Depends(get_session)):
        token = request.cookies.get(OPS_COOKIE)
        if token:
            row = s.scalar(select(OperatorSession).where(OperatorSession.token_hash == hash_token(token)))
            if row is not None and row.revoked_at is None:
                row.revoked_at = utcnow()
                s.commit()
        response.delete_cookie(
            OPS_COOKIE, path=OPS_COOKIE_PATH, httponly=True, samesite="strict", secure=cookie_secure()
        )

    @r.get("/auth/me", response_model=OperatorOut)
    def me(op: PlatformOperator = Depends(current_operator)):
        return OperatorOut(id=op.id, email=op.email)

    # ---- organizações ------------------------------------------------------------------------

    @r.get("/organizations", response_model=list[OrgListItem])
    def list_orgs(
        response: Response,
        limit: int | None = Query(default=None, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        total = s.scalar(select(func.count(Organization.id))) or 0
        response.headers["X-Total-Count"] = str(total)
        stmt = select(Organization).order_by(func.lower(Organization.name), Organization.name, Organization.id)
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        orgs = list(s.scalars(stmt))
        if not orgs:
            return []
        stats = _org_stats(s, [o.id for o in orgs])
        return [
            OrgListItem(id=o.id, slug=o.slug, name=o.name, active=o.active, created_at=o.created_at, **stats[o.id])
            for o in orgs
        ]

    @r.post("/organizations", status_code=201, response_model=OrgOut)
    def create_org(
        body: OrgIn, op: PlatformOperator = Depends(current_operator), s: Session = Depends(get_session)
    ):
        org = Organization(slug=body.slug, name=body.name.strip(), active=True)
        s.add(org)
        try:
            s.flush()
        except IntegrityError as exc:
            s.rollback()
            raise HTTPException(409, "slug de organização já existe") from exc
        _log(s, op, "org.create", org.id, "organization", org.id)
        s.commit()
        return org

    @r.patch("/organizations/{org_id}", response_model=OrgOut)
    def patch_org(
        org_id: int,
        body: OrgPatch,
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        org = _org_or_404(s, org_id)
        if body.name is not None and body.name.strip() != org.name:
            org.name = body.name.strip()
            _log(s, op, "org.update", org.id, "organization", org.id)
        if body.active is not None and body.active != org.active:
            org.active = body.active
            _log(s, op, "org.activate" if body.active else "org.deactivate", org.id, "organization", org.id)
        s.commit()
        return org

    @r.post("/organizations/{org_id}/admins", status_code=201, response_model=CreatedAdmin)
    def create_admin(
        org_id: int,
        body: AdminIn,
        response: Response,
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        org = _org_or_404(s, org_id)
        try:
            email = normalize_email(body.email)
        except ValueError as exc:
            raise HTTPException(422, "e-mail inválido") from exc
        password = generate_password()  # gerada aqui; só o hash fica no banco
        user = User(org_id=org.id, email=email, password_hash=hash_password(password), active=True)
        s.add(user)
        try:
            s.flush()
        except IntegrityError as exc:
            s.rollback()
            raise HTTPException(409, "e-mail já cadastrado") from exc
        s.add(Membership(user_id=user.id, area_id=None, role=ORG_ADMIN))
        _log(s, op, "org.admin_create", org.id, "user", user.id)
        s.commit()
        _no_store(response)
        return CreatedAdmin(user_id=user.id, email=email, password=password)

    @r.post("/organizations/{org_id}/admins/{user_id}/reset-password", response_model=CreatedAdmin)
    def reset_admin_password(
        org_id: int,
        user_id: int,
        response: Response,
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        org = _org_or_404(s, org_id)
        user = s.get(User, user_id)
        is_admin = user is not None and s.scalar(
            select(Membership.id).where(Membership.user_id == user.id, Membership.role == ORG_ADMIN).limit(1)
        )
        if user is None or user.org_id != org.id or not is_admin:
            raise HTTPException(404, "administrador não encontrado")
        password = generate_password()
        user.password_hash = hash_password(password)
        now = utcnow()
        for row in s.scalars(
            select(UserSession).where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        ):
            row.revoked_at = now  # recuperação sem e-mail: a senha antiga e as sessões param de valer
        _log(s, op, "org.admin_password_reset", org.id, "user", user.id)
        s.commit()
        _no_store(response)
        return CreatedAdmin(user_id=user.id, email=user.email, password=password)

    @r.get("/organizations/{org_id}", response_model=OrgDetail)
    def org_detail(
        org_id: int,
        response: Response,
        limit: int = Query(200, ge=1, le=500),
        offset: int = Query(0, ge=0),
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        org = _org_or_404(s, org_id)
        areas = list(s.scalars(select(Area).where(Area.org_id == org.id).order_by(Area.name, Area.id)))
        nodes = {a.id: AreaNodeOut(id=a.id, name=a.name, parent_id=a.parent_id) for a in areas}
        roots: list[AreaNodeOut] = []
        for a in areas:
            parent = nodes.get(a.parent_id) if a.parent_id is not None else None
            (parent.children if parent else roots).append(nodes[a.id])
        area_name = {a.id: a.name for a in areas}

        agents = list(s.scalars(select(Agent).where(Agent.org_id == org.id).order_by(Agent.name, Agent.id)))
        agent_ids = [a.id for a in agents]
        if agent_ids:
            tokens = dict(
                s.execute(
                    select(AgentCredential.agent_id, func.count(AgentCredential.id))
                    .where(AgentCredential.agent_id.in_(agent_ids), AgentCredential.revoked_at.is_(None))
                    .group_by(AgentCredential.agent_id)
                ).all()
            )
            # Último relatório de cada agente: consulta própria, só as colunas necessárias (sem summary_json).
            newest = (
                select(ReportVersion.agent_id, func.max(ReportVersion.seq).label("seq"))
                .where(ReportVersion.agent_id.in_(agent_ids))
                .group_by(ReportVersion.agent_id)
                .subquery()
            )
            latest = {
                agent_id: (semaforo, published)
                for agent_id, semaforo, published in s.execute(
                    select(ReportVersion.agent_id, ReportVersion.status_semaforo, ReportVersion.published_at).join(
                        newest, (newest.c.agent_id == ReportVersion.agent_id) & (newest.c.seq == ReportVersion.seq)
                    )
                ).all()
            }
        else:
            tokens = {}
            latest = {}
        slug_of = {a.id: a.slug for a in agents}
        agent_meta = [
            AgentMeta(
                id=a.id,
                slug=a.slug,
                name=a.name,
                area_name=area_name.get(a.area_id, ""),
                active=a.active,
                tokens_active_count=tokens.get(a.id, 0),
                last_report_at=latest[a.id][1] if a.id in latest else None,
                latest_semaforo=latest[a.id][0] if a.id in latest else None,
            )
            for a in agents
        ]

        users = list(s.scalars(select(User).where(User.org_id == org.id).order_by(User.email, User.id)))
        access: dict[int, list[AccessMeta]] = {}
        if users:
            for m in s.scalars(
                select(Membership).where(Membership.user_id.in_([u.id for u in users])).order_by(Membership.id)
            ):
                access.setdefault(m.user_id, []).append(AccessMeta(role=m.role, area_name=area_name.get(m.area_id)))
        user_meta = [
            UserMeta(id=u.id, email=u.email, active=u.active, access=access.get(u.id, [])) for u in users
        ]

        if agent_ids:
            total_reports = (
                s.scalar(select(func.count(ReportVersion.id)).where(ReportVersion.agent_id.in_(agent_ids)))
                or 0
            )
            # Versões: LIMIT/OFFSET no SQL; a data de geração é extraída do JSON no banco (não carrega o resumo inteiro).
            generated = ReportVersion.summary_json["generated_at"].as_string()
            report_rows = s.execute(
                select(
                    ReportVersion.id,
                    ReportVersion.agent_id,
                    ReportVersion.seq,
                    ReportVersion.status_semaforo,
                    generated,
                    ReportVersion.published_at,
                    ReportVersion.n_cases,
                    ReportVersion.model,
                )
                .where(ReportVersion.agent_id.in_(agent_ids))
                .order_by(ReportVersion.published_at.desc(), ReportVersion.id.desc())
                .offset(offset)
                .limit(limit)
            ).all()
            reports = [
                ReportMeta(
                    id=rid,
                    agent_slug=slug_of[agent_id],
                    seq=seq,
                    status_semaforo=semaforo,
                    generated_at=gen,
                    published_at=published,
                    n_cases=n_cases,
                    model=model,
                )
                for rid, agent_id, seq, semaforo, gen, published, n_cases, model in report_rows
            ]
        else:
            total_reports = 0
            reports = []
        response.headers["X-Total-Count"] = str(total_reports)
        return OrgDetail(
            id=org.id,
            slug=org.slug,
            name=org.name,
            active=org.active,
            created_at=org.created_at,
            areas=roots,
            agents=agent_meta,
            users=user_meta,
            reports=reports,
        )

    # ---- trilhas (somente leitura) -------------------------------------------------------------

    @r.get("/organizations/{org_id}/events", response_model=list[OrgEventOut])
    def org_events(
        org_id: int,
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        org = _org_or_404(s, org_id)
        rows = s.execute(
            select(AdminEvent, User.email)
            .outerjoin(User, User.id == AdminEvent.actor_user_id)
            .where(AdminEvent.org_id == org.id)
            .order_by(AdminEvent.at.desc(), AdminEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [
            OrgEventOut(
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

    @r.get("/events", response_model=list[OperatorEventOut])
    def operator_events(
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        op: PlatformOperator = Depends(current_operator),
        s: Session = Depends(get_session),
    ):
        rows = s.execute(
            select(OperatorEvent, PlatformOperator.email, Organization.slug)
            .join(PlatformOperator, PlatformOperator.id == OperatorEvent.operator_id)
            .outerjoin(Organization, Organization.id == OperatorEvent.target_org_id)
            .order_by(OperatorEvent.at.desc(), OperatorEvent.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return [
            OperatorEventOut(
                id=e.id,
                at=e.at,
                operator_id=e.operator_id,
                operator_email=email,
                action=e.action,
                target_org_id=e.target_org_id,
                target_org_slug=slug,
                target_type=e.target_type,
                target_id=e.target_id,
            )
            for e, email, slug in rows
        ]

    return r
