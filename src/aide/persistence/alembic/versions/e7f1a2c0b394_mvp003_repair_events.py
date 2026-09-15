"""mvp003 repair events

Revision ID: e7f1a2c0b394
Revises: c4b82e1a9f07
Create Date: 2026-09-14 21:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7f1a2c0b394"
down_revision: str | Sequence[str] | None = "c4b82e1a9f07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repair_events",
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("event_kind", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("evidence_ref_id", sa.UUID(), nullable=True),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["artifacts.artifact_id"],
            name=op.f("fk_repair_events_artifact_id_artifacts"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_ref_id"],
            ["evidence_references.evidence_ref_id"],
            name=op.f("fk_repair_events_evidence_ref_id_evidence_references"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["materialized_tasks.task_id"],
            name=op.f("fk_repair_events_task_id_materialized_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.workflow_id"],
            name=op.f("fk_repair_events_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_repair_events")),
    )
    op.create_index(
        op.f("ix_repair_events_workflow_id"),
        "repair_events",
        ["workflow_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_repair_events_workflow_id"), table_name="repair_events")
    op.drop_table("repair_events")
