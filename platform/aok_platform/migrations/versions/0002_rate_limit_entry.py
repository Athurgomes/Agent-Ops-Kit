"""Cria a tabela compartilhada rate_limit_entry para limitadores de tentativas.

Revision ID: 0002_rate_limit_entry
Revises: 0001_initial_schema
Create Date: 2026-11-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_rate_limit_entry"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "rate_limit_entry" not in insp.get_table_names():
        op.create_table(
            "rate_limit_entry",
            sa.Column("bucket", sa.String(length=40), primary_key=True, nullable=False),
            sa.Column("key_hash", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.Column("window_start", sa.Float(), nullable=False),
            sa.Column("locked_until", sa.Float(), nullable=False),
            sa.Column("expires_at", sa.Float(), nullable=False),
        )
        insp = sa.inspect(conn)
    existing_ix = {ix.get("name") for ix in insp.get_indexes("rate_limit_entry")}
    if "ix_rate_limit_entry_expires_at" not in existing_ix:
        op.create_index(
            "ix_rate_limit_entry_expires_at",
            "rate_limit_entry",
            ["expires_at"],
            unique=False,
        )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "rate_limit_entry" in insp.get_table_names():
        existing_ix = {ix.get("name") for ix in insp.get_indexes("rate_limit_entry")}
        if "ix_rate_limit_entry_expires_at" in existing_ix:
            op.drop_index("ix_rate_limit_entry_expires_at", table_name="rate_limit_entry")
        op.drop_table("rate_limit_entry")
