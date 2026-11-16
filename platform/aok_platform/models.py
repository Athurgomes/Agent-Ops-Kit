"""Tabelas da plataforma (plataforma.md seção 5): fase 2 + user/membership/session/download_log."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    TypeDecorator,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator):
    """Sempre devolve datetime com fuso UTC (o SQLite descarta o fuso)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Organization(Base):
    """Organização (empresa). Inativa: ninguém dela loga, sessões e tokens param, nada é apagado."""

    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)  # [a-z0-9-]{1,64}
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Area(Base):
    __tablename__ = "area"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("area.id"), nullable=True)


class Agent(Base):
    """O slug é único por organização (não global); a org do agente é a da sua área."""

    __tablename__ = "agent"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_agent_org_slug"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"), index=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"))
    slug: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentCredential(Base):
    __tablename__ = "agent_credential"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 hex
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ReportVersion(Base):
    """Versão publicada de um relatório. Imutável: sem update/delete (a API nem expõe rotas)."""

    __tablename__ = "report_version"
    __table_args__ = (
        UniqueConstraint("agent_id", "sha256", name="uq_report_agent_sha256"),
        UniqueConstraint("agent_id", "seq", name="uq_report_agent_seq"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agent.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # 1, 2, ... por agente
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    sha256: Mapped[str] = mapped_column(String(64))  # do relatorio.json, recalculado no servidor
    summary_json: Mapped[dict] = mapped_column(JSON)
    status_semaforo: Mapped[str] = mapped_column(String(10))
    audit_verify_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    audit_anchor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_cases: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_md: Mapped[str] = mapped_column(String(300))  # caminhos relativos a AOK_DATA_DIR
    file_html: Mapped[str] = mapped_column(String(300))
    file_json: Mapped[str] = mapped_column(String(300))


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    email: Mapped[str] = mapped_column(String(254), unique=True)  # sempre em minúsculas
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Membership(Base):
    """area_viewer exige area_id (vale para a área e sub-áreas); org_admin tem area_id nulo."""

    __tablename__ = "membership"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("area.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20))  # org_admin | area_viewer


class UserSession(Base):
    __tablename__ = "session"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 hex
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class DownloadLog(Base):
    __tablename__ = "download_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    report_version_id: Mapped[int] = mapped_column(ForeignKey("report_version.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    downloaded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    format: Mapped[str] = mapped_column(String(4))  # md | html | json


class AdminEvent(Base):
    """Escrita administrativa (quem mudou o quê). Nunca guarda segredo: só ação e alvo."""

    __tablename__ = "admin_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"), index=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    target_type: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PlatformOperator(Base):
    """Operador da plataforma: tabela separada de `user`, não pertence a nenhuma organização."""

    __tablename__ = "platform_operator"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # sempre em minúsculas
    password_hash: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class OperatorSession(Base):
    __tablename__ = "operator_session"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("platform_operator.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # SHA-256 hex
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class OperatorEvent(Base):
    """Trilha das ações do operador. Imutável pelo ORM; nunca guarda segredo."""

    __tablename__ = "operator_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("platform_operator.id"), index=True)
    action: Mapped[str] = mapped_column(String(40))
    target_org_id: Mapped[int | None] = mapped_column(ForeignKey("organization.id"), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


def _immutable(*_args) -> None:
    raise RuntimeError("registro imutável (report_version, admin_event): sem update nem delete")


event.listen(ReportVersion, "before_update", _immutable)
event.listen(ReportVersion, "before_delete", _immutable)
event.listen(AdminEvent, "before_update", _immutable)
event.listen(AdminEvent, "before_delete", _immutable)
event.listen(OperatorEvent, "before_update", _immutable)
event.listen(OperatorEvent, "before_delete", _immutable)
