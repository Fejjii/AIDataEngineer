from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from aide.auth.grants import GrantAuthorizer
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.domain.approvals import ApprovalRecord, ApprovalStatus, ApprovalSubject
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.enums import TargetEnv
from aide.domain.identity import compute_operation_idempotency_key, compute_resolved_input_digest
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef, Role
from aide.domain.sql import SqlClassification
from aide.policy.request import PolicyRequest


class QueryInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    statement: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def digest64(label: str = "x") -> str:
    return compute_resolved_input_digest(QueryInput(statement=label))


def principal(*, roles: frozenset[Role] | None = None) -> PrincipalRef:
    session_id = uuid4()
    return PrincipalRef(
        principal_id=uuid4(),
        authentication_source="LOCAL_SESSION",
        roles=roles or frozenset({Role.OPERATOR, Role.APPROVER}),
        session_id=session_id,
    )


def grants_for(
    actor: PrincipalRef,
    requested: frozenset[PermissionLevel],
    *,
    env: TargetEnv = TargetEnv.DEV,
    now: datetime | None = None,
) -> object:
    return GrantAuthorizer().authorize(
        actor,
        requested,
        target_environment=env,
        decided_at=now or utcnow(),
    )


def health(
    connector_id: str,
    *,
    status: str = "AVAILABLE",
    now: datetime | None = None,
    missing: frozenset[PermissionLevel] = frozenset(),
    reasons: tuple[str, ...] = (),
) -> ConnectorHealthSnapshot:
    moment = now or utcnow()
    return ConnectorHealthSnapshot(
        connector_id=connector_id,
        status=status,  # type: ignore[arg-type]
        checked_at=moment,
        expires_at=moment + timedelta(minutes=5),
        missing_permissions=missing,
        reason_codes=reasons,
    )


def read_sql(
    *,
    objects: tuple[tuple[str, ...], ...] = (("RAW", "SALES", "ORDERS"),),
    parse_ok: bool = True,
    read_only: bool = True,
    destructive: bool = False,
    multi: bool = False,
    dynamic: bool = False,
    unsafe: tuple[str, ...] = (),
    unknown: tuple[str, ...] = (),
    stages: tuple[str, ...] = (),
    functions: tuple[str, ...] = ("COUNT",),
) -> SqlClassification:
    from aide.domain.sql import AssetKind, AssetRef

    assets = tuple(
        AssetRef(connector_id="snowflake_ro", address=addr, kind=AssetKind.TABLE)
        for addr in objects
    )
    return SqlClassification(
        statement_types=("SELECT",),
        objects_read=assets if read_only else (),
        objects_written=() if read_only else assets,
        functions=functions,
        table_functions=(),
        stages_or_urls=stages,
        unsafe_constructs=unsafe,
        unknown_ast_nodes=unknown,
        is_read_only=read_only,
        is_destructive=destructive,
        is_multi_statement=multi,
        has_dynamic_sql=dynamic,
        parse_ok=parse_ok,
        parse_error=None if parse_ok else "boom",
        normalized_sql="SELECT 1",
    )


def policy_request(
    *,
    capability_id: str = "execute_query",
    connector: ConnectorSpec | None = SNOWFLAKE_RO,
    requested: frozenset[PermissionLevel] | None = None,
    grants: frozenset[PermissionLevel] | None = None,
    sql: SqlClassification | None = None,
    provenance: tuple[ArtifactProvenance, ...] = (),
    approvals: tuple[ApprovalRecord, ...] = (),
    capability_known: bool = True,
    connector_registered: bool = True,
    advertises: bool | None = None,
    env: TargetEnv = TargetEnv.DEV,
    now: datetime | None = None,
    health_snapshot: ConnectorHealthSnapshot | None = None,
    extra: dict[str, object] | None = None,
) -> PolicyRequest:
    moment = now or utcnow()
    actor = principal()
    requested_grants = requested or frozenset(
        {PermissionLevel.READ, PermissionLevel.DEVELOPMENT_WRITE}
    )
    authorization = GrantAuthorizer().authorize(
        actor,
        requested_grants if grants is None else grants | requested_grants,
        target_environment=env,
        decided_at=moment,
    )
    effective = grants if grants is not None else authorization.effective
    if grants is not None:
        authorization = authorization.model_copy(update={"effective": grants, "requested": grants})
        effective = grants
    registry = kernel_registry()
    spec = registry.get(capability_id, 1)
    resolved = digest64(capability_id)
    workflow_id = uuid4()
    phase_run_id = uuid4()
    key = compute_operation_idempotency_key(
        workflow_id=workflow_id,
        phase_run_id=phase_run_id,
        local_id="t1",
        capability_id=capability_id,
        capability_contract_version=1,
        connector_id=connector.connector_id if connector else None,
        connector_version=connector.version if connector else None,
        target_environment=env,
        resolved_input_digest=resolved,
    )
    advertises_flag = advertises
    if advertises_flag is None:
        advertises_flag = connector.advertises(capability_id, 1) if connector else True
    payload = (
        sql
        if sql is not None
        else (read_sql() if capability_id in {"execute_query", "classify_sql"} else None)
    )
    kwargs: dict[str, object] = dict(
        workflow_id=workflow_id,
        phase_run_id=phase_run_id,
        task_id=uuid4(),
        operation_idempotency_key=key,
        resolved_input_digest=resolved,
        contract_snapshot_id=uuid4(),
        principal=actor,
        grant_authorization=authorization,
        capability=spec,
        connector=connector,
        connector_health=health_snapshot
        if health_snapshot is not None
        else (health(connector.connector_id, now=moment) if connector else None),
        target_environment=env,
        workflow_grants=effective,
        payload_classification=payload,
        artifact_provenance=provenance,
        approvals=approvals,
        evaluated_at=moment,
        capability_known=capability_known,
        connector_registered=connector_registered,
        connector_advertises_capability=advertises_flag,
    )
    if extra:
        kwargs.update(extra)
    evaluated = kwargs["evaluated_at"]
    assert isinstance(evaluated, datetime)
    if extra is None or "approval_expires_at" not in extra:
        kwargs["approval_expires_at"] = evaluated + timedelta(hours=1)
    return PolicyRequest.model_validate(kwargs)


def mock_provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        execution_mode=ExecutionMode.MOCK,
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        capability_id="execute_query",
        capability_version=1,
        operation_idempotency_key="a" * 64,
        resolved_input_digest="b" * 64,
    )


def real_provenance() -> ArtifactProvenance:
    return ArtifactProvenance(
        execution_mode=ExecutionMode.REAL,
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        capability_id="execute_query",
        capability_version=1,
        operation_idempotency_key="a" * 64,
        resolved_input_digest="b" * 64,
    )


def approval_record(
    subject: ApprovalSubject, actor: PrincipalRef, *, now: datetime
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=uuid4(),
        workflow_id=uuid4(),
        subject=subject,
        subject_digest="digest",
        requester=actor,
        status=ApprovalStatus.APPROVED,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        decided_by=actor,
        decided_at=now,
    )


__all__ = [
    "QueryInput",
    "SNOWFLAKE_DEV",
    "SNOWFLAKE_RO",
    "Decimal",
    "approval_record",
    "digest64",
    "grants_for",
    "health",
    "mock_provenance",
    "policy_request",
    "principal",
    "read_sql",
    "real_provenance",
    "utcnow",
]
