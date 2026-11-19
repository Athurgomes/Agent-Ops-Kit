"""Esquema inicial completo (14 tabelas) e upgrade seguro de bancos legados.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-19
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _slugify(name: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:64]
    return slug or fallback


def _legacy_columns() -> dict[str, list[sa.Column]]:
    """Colunas esperadas por tabela na revisão 0001 para backfill de bancos legados."""
    return {
        "organization": [
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        ],
        "area": [
            sa.Column("org_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
        ],
        "agent": [
            sa.Column("org_id", sa.Integer(), nullable=True),
            sa.Column("area_id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=True),
        ],
    }


def _add_missing_legacy_columns(conn: sa.Connection, existing: set[str]) -> None:
    insp = sa.inspect(conn)
    for table_name, columns in _legacy_columns().items():
        if table_name not in existing:
            continue
        have = {c["name"] for c in insp.get_columns(table_name)}
        for col in columns:
            if col.name not in have:
                op.add_column(
                    table_name,
                    sa.Column(col.name, col.type, nullable=col.nullable),
                )


def _backfill_legacy_data(conn: sa.Connection) -> None:
    org = sa.table(
        "organization",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    rows = conn.execute(sa.select(org.c.id, org.c.name).where(org.c.slug.is_(None))).all()
    taken = {r[0] for r in conn.execute(sa.select(org.c.slug).where(org.c.slug.is_not(None)))}
    for oid, name in rows:
        slug = _slugify(name, f"org-{oid}")
        if slug in taken:
            slug = f"{slug[:55]}-{oid}"
        taken.add(slug)
        conn.execute(sa.update(org).where(org.c.id == oid).values(slug=slug))
    conn.execute(sa.update(org).where(org.c.active.is_(None)).values(active=True))
    conn.execute(sa.update(org).where(org.c.created_at.is_(None)).values(created_at=datetime.now(UTC)))
    conn.execute(
        sa.text(
            "UPDATE agent SET org_id = (SELECT area.org_id FROM area WHERE area.id = agent.area_id)"
            " WHERE org_id IS NULL"
        )
    )


def _has_unique_on(conn: sa.Connection, insp: sa.Inspector, table: str, cols: list[str]) -> bool:
    if any(list(uq.get("column_names") or []) == cols for uq in insp.get_unique_constraints(table)):
        return True
    if any(
        idx.get("unique") and list(idx.get("column_names") or []) == cols
        for idx in insp.get_indexes(table)
    ):
        return True
    if conn.dialect.name == "sqlite":
        safe_table = table.replace('"', '""')
        for row in conn.execute(sa.text(f'PRAGMA index_list("{safe_table}")')).fetchall():
            idx_name, is_unique = row[1], bool(row[2])
            if not is_unique:
                continue
            safe_idx = str(idx_name).replace('"', '""')
            idx_cols = [
                r[2] for r in conn.execute(sa.text(f'PRAGMA index_info("{safe_idx}")')).fetchall()
            ]
            if idx_cols == cols:
                return True
    return False


def _has_index_named(insp: sa.Inspector, table: str, name: str) -> bool:
    return any(idx.get("name") == name for idx in insp.get_indexes(table))


def _upgrade_legacy_organization(conn: sa.Connection) -> None:
    insp = sa.inspect(conn)
    if not _has_index_named(insp, "organization", "uq_organization_slug"):
        op.execute(
            sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_organization_slug ON organization (slug)")
        )


def _upgrade_legacy_agent_sqlite(conn: sa.Connection) -> None:
    insp = sa.inspect(conn)
    if _has_unique_on(conn, insp, "agent", ["slug"]):
        meta = sa.MetaData()
        agent_tbl = sa.Table("agent", meta, autoload_with=conn)
        agent_tbl.constraints = {
            c
            for c in agent_tbl.constraints
            if not (isinstance(c, sa.UniqueConstraint) and [col.name for col in c.columns] == ["slug"])
        }
        agent_tbl.indexes = {
            ix
            for ix in agent_tbl.indexes
            if not (ix.unique and [col.name for col in ix.columns] == ["slug"])
        }
        agent_tbl.c.slug.unique = False
        has_uq = any(
            isinstance(c, sa.UniqueConstraint)
            and [col.name for col in c.columns] == ["org_id", "slug"]
            for c in agent_tbl.constraints
        ) or any(
            ix.unique and [col.name for col in ix.columns] == ["org_id", "slug"]
            for ix in agent_tbl.indexes
        )
        has_fk_org = any(fk.column.table.name == "organization" for fk in agent_tbl.foreign_keys)
        has_ix_org = any(
            ix.name == "ix_agent_org_id" or [col.name for col in ix.columns] == ["org_id"]
            for ix in agent_tbl.indexes
        )
        null_org_count = conn.execute(
            sa.text("SELECT COUNT(*) FROM agent WHERE org_id IS NULL")
        ).scalar_one()

        with op.batch_alter_table("agent", recreate="always", copy_from=agent_tbl) as batch_op:
            if null_org_count == 0:
                batch_op.alter_column("org_id", existing_type=sa.Integer(), nullable=False)
            if not has_uq:
                batch_op.create_unique_constraint("uq_agent_org_slug", ["org_id", "slug"])
            if not has_fk_org:
                batch_op.create_foreign_key(
                    "fk_agent_org_id_organization", "organization", ["org_id"], ["id"]
                )
            if not has_ix_org:
                batch_op.create_index("ix_agent_org_id", ["org_id"], unique=False)
        return

    if not _has_unique_on(conn, insp, "agent", ["org_id", "slug"]):
        op.execute(
            sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_org_slug ON agent (org_id, slug)")
        )
    if not _has_index_named(insp, "agent", "ix_agent_org_id"):
        op.create_index("ix_agent_org_id", "agent", ["org_id"], unique=False)


def _upgrade_legacy_agent_postgres(conn: sa.Connection) -> None:
    op.execute(sa.text("ALTER TABLE agent DROP CONSTRAINT IF EXISTS agent_slug_key"))
    insp = sa.inspect(conn)
    if not _has_index_named(insp, "agent", "uq_agent_org_slug"):
        op.execute(
            sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_org_slug ON agent (org_id, slug)")
        )
    if not _has_index_named(insp, "agent", "ix_agent_org_id"):
        op.create_index("ix_agent_org_id", "agent", ["org_id"], unique=False)
    has_fk_org = any(
        fk.get("referred_table") == "organization" for fk in insp.get_foreign_keys("agent")
    )
    if not has_fk_org:
        op.create_foreign_key(
            "fk_agent_org_id_organization", "agent", "organization", ["org_id"], ["id"]
        )


def _create_missing_tables(existing: set[str]) -> None:
    if "organization" not in existing:
        op.create_table(
            "organization",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("slug", name="uq_organization_slug"),
        )

    if "area" not in existing:
        op.create_table(
            "area",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("parent_id", sa.Integer(), sa.ForeignKey("area.id"), nullable=True),
        )

    if "agent" not in existing:
        op.create_table(
            "agent",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
            sa.Column("area_id", sa.Integer(), sa.ForeignKey("area.id"), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.UniqueConstraint("org_id", "slug", name="uq_agent_org_slug"),
        )
        op.create_index("ix_agent_org_id", "agent", ["org_id"], unique=False)

    if "agent_credential" not in existing:
        op.create_table(
            "agent_credential",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agent.id"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_agent_credential_token_hash"),
        )
        op.create_index(
            "ix_agent_credential_agent_id", "agent_credential", ["agent_id"], unique=False
        )

    if "report_version" not in existing:
        op.create_table(
            "report_version",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agent.id"), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sha256", sa.String(length=64), nullable=False),
            sa.Column("summary_json", sa.JSON(), nullable=False),
            sa.Column("status_semaforo", sa.String(length=10), nullable=False),
            sa.Column("audit_verify_ok", sa.Boolean(), nullable=True),
            sa.Column("audit_anchor", sa.String(length=128), nullable=True),
            sa.Column("model", sa.String(length=200), nullable=True),
            sa.Column("prompt_sha256", sa.String(length=64), nullable=True),
            sa.Column("dataset_sha256", sa.String(length=64), nullable=True),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("n_cases", sa.Integer(), nullable=True),
            sa.Column("file_md", sa.String(length=300), nullable=False),
            sa.Column("file_html", sa.String(length=300), nullable=False),
            sa.Column("file_json", sa.String(length=300), nullable=False),
            sa.UniqueConstraint("agent_id", "sha256", name="uq_report_agent_sha256"),
            sa.UniqueConstraint("agent_id", "seq", name="uq_report_agent_seq"),
        )
        op.create_index("ix_report_version_agent_id", "report_version", ["agent_id"], unique=False)

    if "user" not in existing:
        op.create_table(
            "user",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
            sa.Column("email", sa.String(length=254), nullable=False),
            sa.Column("password_hash", sa.String(length=300), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("email", name="uq_user_email"),
        )

    if "membership" not in existing:
        op.create_table(
            "membership",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("area_id", sa.Integer(), sa.ForeignKey("area.id"), nullable=True),
            sa.Column("role", sa.String(length=20), nullable=False),
        )
        op.create_index("ix_membership_user_id", "membership", ["user_id"], unique=False)

    if "session" not in existing:
        op.create_table(
            "session",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_session_token_hash"),
        )
        op.create_index("ix_session_user_id", "session", ["user_id"], unique=False)

    if "password_reset" not in existing:
        op.create_table(
            "password_reset",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_password_reset_token_hash"),
        )
        op.create_index("ix_password_reset_user_id", "password_reset", ["user_id"], unique=False)

    if "download_log" not in existing:
        op.create_table(
            "download_log",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "report_version_id",
                sa.Integer(),
                sa.ForeignKey("report_version.id"),
                nullable=False,
            ),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("format", sa.String(length=4), nullable=False),
        )
        op.create_index(
            "ix_download_log_report_version_id",
            "download_log",
            ["report_version_id"],
            unique=False,
        )
        op.create_index("ix_download_log_user_id", "download_log", ["user_id"], unique=False)

    if "admin_event" not in existing:
        op.create_table(
            "admin_event",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("org_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=False),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("target_type", sa.String(length=20), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=True),
        )
        op.create_index("ix_admin_event_org_id", "admin_event", ["org_id"], unique=False)
        op.create_index("ix_admin_event_at", "admin_event", ["at"], unique=False)

    if "platform_operator" not in existing:
        op.create_table(
            "platform_operator",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("email", sa.String(length=254), nullable=False),
            sa.Column("password_hash", sa.String(length=300), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("email", name="uq_platform_operator_email"),
        )

    if "operator_session" not in existing:
        op.create_table(
            "operator_session",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column(
                "operator_id",
                sa.Integer(),
                sa.ForeignKey("platform_operator.id"),
                nullable=False,
            ),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_operator_session_token_hash"),
        )
        op.create_index(
            "ix_operator_session_operator_id", "operator_session", ["operator_id"], unique=False
        )

    if "operator_event" not in existing:
        op.create_table(
            "operator_event",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "operator_id",
                sa.Integer(),
                sa.ForeignKey("platform_operator.id"),
                nullable=False,
            ),
            sa.Column("action", sa.String(length=40), nullable=False),
            sa.Column("target_org_id", sa.Integer(), sa.ForeignKey("organization.id"), nullable=True),
            sa.Column("target_type", sa.String(length=20), nullable=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
        )
        op.create_index("ix_operator_event_at", "operator_event", ["at"], unique=False)
        op.create_index(
            "ix_operator_event_operator_id", "operator_event", ["operator_id"], unique=False
        )


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(sa.inspect(conn).get_table_names())

    if existing - {"alembic_version"}:
        _add_missing_legacy_columns(conn, existing)
        if "organization" in existing and "agent" in existing and "area" in existing:
            _backfill_legacy_data(conn)
        if "organization" in existing:
            _upgrade_legacy_organization(conn)
        if "agent" in existing:
            if conn.dialect.name == "sqlite":
                _upgrade_legacy_agent_sqlite(conn)
            elif conn.dialect.name == "postgresql":
                _upgrade_legacy_agent_postgres(conn)

    _create_missing_tables(existing)


def downgrade() -> None:
    for table in (
        "operator_event",
        "operator_session",
        "platform_operator",
        "admin_event",
        "download_log",
        "password_reset",
        "session",
        "membership",
        "user",
        "report_version",
        "agent_credential",
        "agent",
        "area",
        "organization",
    ):
        op.drop_table(table)
