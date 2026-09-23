"""operator console runs

Revision ID: b7e4c1a09d55
Revises: e7f1a2c0b394
Create Date: 2026-09-23 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e4c1a09d55"
down_revision: str | Sequence[str] | None = "e7f1a2c0b394"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_console_runs",
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("workflow_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_artifact_id", sa.UUID(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name=op.f("ck_operator_console_runs_status_known"),
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_operator_console_runs")),
    )
    op.create_index(
        op.f("ix_operator_console_runs_created_at"),
        "operator_console_runs",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_operator_console_runs_created_at"), table_name="operator_console_runs")
    op.drop_table("operator_console_runs")
