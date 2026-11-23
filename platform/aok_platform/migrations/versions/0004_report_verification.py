"""Verificação do relatório via reproducao.json: require_verification, verified e download.

Revision ID: 0004_report_verification
Revises: 0003_report_signature
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_report_verification"
down_revision: str | None = "0003_report_signature"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _cols(insp, table: str) -> dict[str, dict]:
    return {c["name"]: c for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "require_verification" not in _cols(insp, "agent"):
        op.add_column(
            "agent",
            sa.Column(
                "require_verification", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    report_cols = _cols(insp, "report_version")
    if "verified" not in report_cols:
        op.add_column(
            "report_version",
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "verification_status" not in report_cols:
        op.add_column(
            "report_version",
            sa.Column("verification_status", sa.String(length=32), nullable=True),
        )
    if "file_reproducao" not in report_cols:
        op.add_column(
            "report_version",
            sa.Column("file_reproducao", sa.String(length=512), nullable=True),
        )
    fmt_col = _cols(insp, "download_log").get("format")
    if fmt_col is not None and getattr(fmt_col["type"], "length", None) != 16:
        with op.batch_alter_table("download_log") as batch:
            batch.alter_column(
                "format",
                existing_type=sa.String(length=4),
                type_=sa.String(length=16),
                existing_nullable=False,
            )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    fmt_col = _cols(insp, "download_log").get("format")
    if fmt_col is not None and getattr(fmt_col["type"], "length", None) != 4:
        with op.batch_alter_table("download_log") as batch:
            batch.alter_column(
                "format",
                existing_type=sa.String(length=16),
                type_=sa.String(length=4),
                existing_nullable=False,
            )
    report_cols = _cols(insp, "report_version")
    drop_report = [
        c for c in ("file_reproducao", "verification_status", "verified") if c in report_cols
    ]
    if drop_report:
        with op.batch_alter_table("report_version") as batch:
            for col in drop_report:
                batch.drop_column(col)
    if "require_verification" in _cols(insp, "agent"):
        with op.batch_alter_table("agent") as batch:
            batch.drop_column("require_verification")
