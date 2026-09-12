"""DE002C scoped artifact uniqueness to workflow ownership.

Revision ID: d2c8e4f1a7b3
Revises: 9c3045032ed2
Create Date: 2026-09-12 08:40:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d2c8e4f1a7b3"
down_revision: str | Sequence[str] | None = "9c3045032ed2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_artifact_content_version", "artifacts", type_="unique")
    op.create_unique_constraint(
        "uq_artifact_workflow_content_version",
        "artifacts",
        ["workflow_id", "sha256", "artifact_type", "version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifact_workflow_content_version", "artifacts", type_="unique")
    op.create_unique_constraint(
        "uq_artifact_content_version",
        "artifacts",
        ["sha256", "artifact_type", "version"],
    )
