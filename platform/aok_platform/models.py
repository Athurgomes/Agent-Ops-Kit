"""Tabelas da fase 2 (plataforma.md seção 5). Sem user/membership/download_log."""

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
    __tablename__ = "organization"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Area(Base):
    __tablename__ = "area"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organization.id"))
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("area.id"), nullable=True)


class Agent(Base):
    __tablename__ = "agent"
    id: Mapped[int] = mapped_column(primary_key=True)
    area_id: Mapped[int] = mapped_column(ForeignKey("area.id"))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
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


def _immutable(*_args) -> None:
    raise RuntimeError("report_version é imutável: sem update nem delete")


event.listen(ReportVersion, "before_update", _immutable)
event.listen(ReportVersion, "before_delete", _immutable)
