"""mvp002 governed tool gateway dispatch intents

Revision ID: c4b82e1a9f07
Revises: fe88c7293a96
Create Date: 2026-09-14 16:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4b82e1a9f07"
down_revision: str | Sequence[str] | None = "fe88c7293a96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gateway_dispatch_intents",
        sa.Column("intent_id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("phase_run_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("attempt_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("capability_id", sa.String(length=128), nullable=False),
        sa.Column("connector_id", sa.String(length=128), nullable=True),
        sa.Column("connector_version", sa.String(length=64), nullable=True),
        sa.Column("operation_idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("resolved_input_digest", sa.String(length=64), nullable=False),
        sa.Column("policy_decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("risk_decision", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("evidence_ref_id", sa.UUID(), nullable=True),
        sa.Column("result_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["task_attempts.attempt_id"],
            name=op.f("fk_gateway_dispatch_intents_attempt_id_task_attempts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_ref_id"],
            ["evidence_references.evidence_ref_id"],
            name=op.f("fk_gateway_dispatch_intents_evidence_ref_id_evidence_references"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["phase_run_id"],
            ["phase_runs.phase_run_id"],
            name=op.f("fk_gateway_dispatch_intents_phase_run_id_phase_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["materialized_tasks.task_id"],
            name=op.f("fk_gateway_dispatch_intents_task_id_materialized_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.workflow_id"],
            name=op.f("fk_gateway_dispatch_intents_workflow_id_workflows"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("intent_id", name=op.f("pk_gateway_dispatch_intents")),
        sa.UniqueConstraint(
            "attempt_id",
            "action",
            name="uq_gateway_dispatch_attempt_action",
        ),
    )


def downgrade() -> None:
    op.drop_table("gateway_dispatch_intents")
