"""SQLAlchemy persistence models for the durable orchestration kernel."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Return a naive UTC timestamp for PostgreSQL TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class WorkflowModel(Base):
    __tablename__ = "workflows"

    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    blocked_from_phase: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cancellation_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancellation_requested_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime)
    active_phase_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class SessionModel(Base):
    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    authentication_source: Mapped[str] = mapped_column(String(32), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    opaque_token_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class WorkflowGrantModel(Base):
    __tablename__ = "workflow_grants"
    __table_args__ = (
        UniqueConstraint("workflow_id", "permission", name="uq_workflow_grant_permission"),
    )

    grant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    permission: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ContractSnapshotModel(Base):
    __tablename__ = "contract_snapshots"

    snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    capability_contracts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    connector_versions: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class PhaseRunModel(Base):
    __tablename__ = "phase_runs"
    __table_args__ = (
        UniqueConstraint("workflow_id", "generation", name="uq_phase_run_generation"),
        CheckConstraint("generation >= 1", name="positive_generation"),
    )

    phase_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase: Mapped[str] = mapped_column(String(32), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    contract_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("contract_snapshots.snapshot_id"), nullable=False
    )
    phase_exit_criteria: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    coordinator_owner: Mapped[str | None] = mapped_column(String(128))
    coordinator_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coordinator_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskTemplateModel(Base):
    __tablename__ = "task_templates"
    __table_args__ = (
        UniqueConstraint("phase_run_id", "local_id", name="uq_task_template_local_id"),
        CheckConstraint("max_attempts >= 1", name="positive_max_attempts"),
        CheckConstraint("timeout_seconds >= 1", name="positive_timeout"),
    )

    template_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    phase_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("phase_runs.phase_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    local_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connector_id: Mapped[str | None] = mapped_column(String(128))
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    required_dependencies: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    unresolved_inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class TemplateDispositionModel(Base):
    __tablename__ = "template_dispositions"

    disposition_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_templates.template_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    phase_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("phase_runs.phase_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    upstream_local_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class MaterializedTaskModel(Base):
    __tablename__ = "materialized_tasks"
    __table_args__ = (
        UniqueConstraint("template_id", name="uq_materialized_task_template"),
        UniqueConstraint("phase_run_id", "local_id", name="uq_materialized_task_local_id"),
        UniqueConstraint("operation_idempotency_key", name="uq_materialized_task_operation_key"),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        CheckConstraint("claim_epoch >= 0", name="nonnegative_claim_epoch"),
        Index(
            "ix_materialized_tasks_claimable",
            "status",
            "lease_expires_at",
            postgresql_where="status IN ('READY', 'RETRY_WAIT')",
        ),
    )

    task_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_templates.template_id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("phase_runs.phase_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    local_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    output_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connector_id: Mapped[str | None] = mapped_column(String(128))
    connector_version: Mapped[str | None] = mapped_column(String(64))
    target_environment: Mapped[str | None] = mapped_column(String(32))
    resolved_inputs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    resolved_input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    operation_idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    required_permission: Mapped[str] = mapped_column(String(64), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    validators: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_digest: Mapped[str | None] = mapped_column(String(64))
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_classification: Mapped[str | None] = mapped_column(String(64))
    disposition_reason: Mapped[str | None] = mapped_column(String(128))
    lease_owner: Mapped[str | None] = mapped_column(String(128))
    claim_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    active_attempt_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    recovery_owner: Mapped[str | None] = mapped_column(String(128))
    recovery_lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    reconcile_check_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reconcile_deadline: Mapped[datetime | None] = mapped_column(DateTime)
    retry_not_before: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    materialized_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class TaskAttemptModel(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt_number"),
        UniqueConstraint("task_id", "claim_epoch", name="uq_task_attempt_claim_epoch"),
        CheckConstraint("attempt_number >= 1", name="positive_attempt_number"),
        CheckConstraint("claim_epoch >= 1", name="positive_claim_epoch"),
    )

    attempt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("materialized_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("phase_runs.phase_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_owner: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    cancellation_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    dispatch_state: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String(256))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_digest: Mapped[str | None] = mapped_column(String(64))
    failure_classification: Mapped[str | None] = mapped_column(String(64))


class ApprovalModel(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materialized_tasks.task_id", ondelete="CASCADE")
    )
    subject: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    subject_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    requester_principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    decided_by_principal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    comment: Mapped[str | None] = mapped_column(Text)


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "sha256",
            "artifact_type",
            "version",
            name="uq_artifact_workflow_content_version",
        ),
    )

    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materialized_tasks.task_id", ondelete="SET NULL")
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    blob: Mapped[bytes | None]
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ConnectorHealthModel(Base):
    __tablename__ = "connector_health"

    health_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    connector_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    missing_permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)


class RecoveryEventModel(Base):
    __tablename__ = "recovery_events"

    recovery_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("materialized_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_attempts.attempt_id", ondelete="CASCADE"),
        nullable=False,
    )
    recovery_owner: Mapped[str] = mapped_column(String(128), nullable=False)
    claim_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    check_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class UnresolvedEffectModel(Base):
    __tablename__ = "unresolved_effects"

    unresolved_effect_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("materialized_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("task_attempts.attempt_id"), nullable=False
    )
    operation_idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    recovery_context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    required_follow_up: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AuditSequenceModel(Base):
    __tablename__ = "audit_sequences"

    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        primary_key=True,
    )
    next_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (UniqueConstraint("workflow_id", "sequence", name="uq_audit_event_sequence"),)

    audit_event_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    phase_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    task_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    attempt_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    operation_idempotency_key: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class BudgetLedgerModel(Base):
    __tablename__ = "budget_ledgers"
    __table_args__ = (
        UniqueConstraint("workflow_id", "scope", "unit", name="uq_budget_ledger_scope"),
        CheckConstraint("authorized_cap >= 0", name="nonnegative_cap"),
        CheckConstraint("reserved_amount >= 0", name="nonnegative_reserved"),
        CheckConstraint("settled_amount >= 0", name="nonnegative_settled"),
        CheckConstraint(
            "reserved_amount + settled_amount <= authorized_cap",
            name="within_authorized_cap",
        ),
    )

    ledger_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    authorized_cap: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    reserved_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )
    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=Decimal("0")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class BudgetEntryModel(Base):
    __tablename__ = "budget_entries"
    __table_args__ = (
        UniqueConstraint("reservation_id", "entry_kind", name="uq_budget_entry_reservation_kind"),
        CheckConstraint("amount >= 0", name="nonnegative_amount"),
    )

    entry_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    ledger_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("budget_ledgers.ledger_id", ondelete="CASCADE"),
        nullable=False,
    )
    reservation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    entry_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class EvidenceReferenceModel(Base):
    """Immutable locator and digest for evidence used by the Twin."""

    __tablename__ = "evidence_references"

    evidence_ref_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    evidence_type: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.artifact_id", ondelete="RESTRICT")
    )
    immutable_uri: Mapped[str | None] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    source_authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_authority_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    producer_operation_key: Mapped[str | None] = mapped_column(String(64))
    producer_attempt_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("task_attempts.attempt_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TwinAssetModel(Base):
    __tablename__ = "twin_assets"
    __table_args__ = (
        CheckConstraint("asset_version >= 1", name="positive_asset_version"),
        CheckConstraint("incarnation >= 1", name="positive_incarnation"),
        Index(
            "ix_twin_assets_native_identity",
            "source_authority_digest",
            "environment",
            "kind",
            "native_key",
            "asset_version",
            unique=True,
            postgresql_where="native_key IS NOT NULL",
        ),
        Index(
            "ix_twin_assets_locator_identity",
            "source_authority_digest",
            "environment",
            "kind",
            "canonical_locator_digest",
            "incarnation",
            "asset_version",
            unique=True,
            postgresql_where="native_key IS NULL",
        ),
    )

    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    asset_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_authority_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    native_key: Mapped[str | None] = mapped_column(String(512))
    canonical_locator: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    canonical_locator_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    incarnation: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_asset_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    platform_type: Mapped[str] = mapped_column(String(128), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    evidence_ref_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_references.evidence_ref_id", ondelete="RESTRICT"),
        nullable=False,
    )


class TwinRelationshipModel(Base):
    __tablename__ = "twin_relationships"
    __table_args__ = (
        CheckConstraint("relationship_version >= 1", name="positive_relationship_version"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        Index(
            "ix_twin_relationship_identity",
            "source_authority_digest",
            "environment",
            "kind",
            "from_asset_id",
            "to_asset_id",
            "relationship_version",
            unique=True,
        ),
        Index("ix_twin_relationship_from", "from_asset_id"),
        Index("ix_twin_relationship_to", "to_asset_id"),
    )

    relationship_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    relationship_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    from_asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    to_asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_authority_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    evidence_ref_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_references.evidence_ref_id", ondelete="RESTRICT"),
        nullable=False,
    )


class TwinObservationModel(Base):
    __tablename__ = "twin_observations"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="valid_confidence"),
        Index("ix_twin_observation_subject_kind", "subject_asset_id", "kind"),
    )

    observation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    subject_asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_authority: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_authority_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    evidence_ref_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_references.evidence_ref_id", ondelete="RESTRICT"),
        nullable=False,
    )


class TwinSnapshotModel(Base):
    __tablename__ = "twin_snapshots"

    twin_snapshot_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    capture_cutoff: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_authorities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class TwinSnapshotAssetModel(Base):
    __tablename__ = "twin_snapshot_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["asset_id", "asset_version"],
            ["twin_assets.asset_id", "twin_assets.asset_version"],
            ondelete="RESTRICT",
        ),
    )

    twin_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("twin_snapshots.twin_snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    asset_version: Mapped[int] = mapped_column(Integer, nullable=False)


class TwinSnapshotRelationshipModel(Base):
    __tablename__ = "twin_snapshot_relationships"
    __table_args__ = (
        ForeignKeyConstraint(
            ["relationship_id", "relationship_version"],
            [
                "twin_relationships.relationship_id",
                "twin_relationships.relationship_version",
            ],
            ondelete="RESTRICT",
        ),
    )

    twin_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("twin_snapshots.twin_snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    relationship_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    relationship_version: Mapped[int] = mapped_column(Integer, nullable=False)


class TwinSnapshotObservationModel(Base):
    __tablename__ = "twin_snapshot_observations"

    twin_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("twin_snapshots.twin_snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    observation_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("twin_observations.observation_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class TwinSnapshotEvidenceModel(Base):
    __tablename__ = "twin_snapshot_evidence"

    twin_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("twin_snapshots.twin_snapshot_id", ondelete="CASCADE"),
        primary_key=True,
    )
    evidence_ref_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_references.evidence_ref_id", ondelete="RESTRICT"),
        primary_key=True,
    )


class WorkflowTwinSnapshotModel(Base):
    __tablename__ = "workflow_twin_snapshots"

    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        primary_key=True,
    )
    twin_snapshot_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("twin_snapshots.twin_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    )
    pinned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class GatewayDispatchIntentModel(Base):
    __tablename__ = "gateway_dispatch_intents"
    __table_args__ = (
        UniqueConstraint("attempt_id", "action", name="uq_gateway_dispatch_attempt_action"),
    )

    intent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("phase_runs.phase_run_id", ondelete="CASCADE"),
        nullable=False,
    )
    task_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("materialized_tasks.task_id", ondelete="CASCADE"),
        nullable=False,
    )
    attempt_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_attempts.attempt_id", ondelete="CASCADE"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connector_id: Mapped[str | None] = mapped_column(String(128))
    connector_version: Mapped[str | None] = mapped_column(String(64))
    operation_idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_input_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    risk_decision: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    approval_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_ref_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_references.evidence_ref_id", ondelete="RESTRICT"),
    )
    result_digest: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class RepairEventModel(Base):
    """Append-only repair/verifier event used for budget reconstruction."""

    __tablename__ = "repair_events"

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    workflow_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workflows.workflow_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("materialized_tasks.task_id", ondelete="SET NULL")
    )
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    evidence_ref_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_references.evidence_ref_id", ondelete="RESTRICT"),
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("artifacts.artifact_id", ondelete="RESTRICT")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class OperatorConsoleRunModel(Base):
    """Durable operator-console run. Status survives process restart; row previews do not."""

    __tablename__ = "operator_console_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="status_known",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workflow_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    snapshot_artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, index=True
    )
