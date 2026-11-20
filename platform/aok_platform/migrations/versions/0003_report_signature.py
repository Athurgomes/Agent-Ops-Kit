"""Assinatura do relatório: chaves públicas por agente, require_signature e signed/key_fingerprint.

Revision ID: 0003_report_signature
Revises: 0002_rate_limit_entry
Create Date: 2026-11-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_report_signature"
down_revision: str | None = "0002_rate_limit_entry"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _cols(insp, table: str) -> set[str]:
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "agent_public_keys" not in insp.get_table_names():
        op.create_table(
            "agent_public_keys",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agent.id"), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("public_key_pem", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("agent_id", "fingerprint", name="uq_agent_key_fingerprint"),
        )
        op.create_index("ix_agent_public_keys_agent_id", "agent_public_keys", ["agent_id"])
    if "require_signature" not in _cols(insp, "agent"):
        op.add_column(
            "agent",
            sa.Column(
                "require_signature", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    report_cols = _cols(insp, "report_version")
    if "signed" not in report_cols:
        op.add_column(
            "report_version",
            sa.Column("signed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "key_fingerprint" not in report_cols:
        op.add_column(
            "report_version", sa.Column("key_fingerprint", sa.String(length=64), nullable=True)
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "key_fingerprint" in _cols(insp, "report_version"):
        with op.batch_alter_table("report_version") as batch:
            batch.drop_column("key_fingerprint")
            batch.drop_column("signed")
    if "require_signature" in _cols(insp, "agent"):
        with op.batch_alter_table("agent") as batch:
            batch.drop_column("require_signature")
    if "agent_public_keys" in insp.get_table_names():
        op.drop_index("ix_agent_public_keys_agent_id", table_name="agent_public_keys")
        op.drop_table("agent_public_keys")
