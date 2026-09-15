"""Credential-gated live probes for the Interview MVP Snowflake boundary.

Never logs secret values. Never issues GRANT or REVOKE. Never mutates
VANTARA_RAW, production, or staging. Write prohibition is proven from
read-only grant metadata, not DML against RAW.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from aide.capabilities.io import (
    Budget,
    ExecuteQueryInput,
    LoadManifestSourcesInput,
)
from aide.connectors.base.context import CallContext, RedactionPolicy
from aide.connectors.base.spec import IdentityClass
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.snowflake.config import (
    DEV_IDENTITY_SECRET_NAMES,
    RO_IDENTITY_SECRET_NAMES,
    ROLE_DEVELOPMENT,
    ROLE_READ_ONLY,
    SHARED_SECRET_NAMES,
    missing_secret_names,
    settings_for_identity,
    snowflake_credentials_available,
    snowflake_dev_credentials_available,
)
from aide.connectors.snowflake.errors import SnowflakeMappedError, sanitize_error_message
from aide.connectors.snowflake.manifest import (
    csv_path_for,
    schema_sha256,
    tiny_manifest_digest,
    workflow_source_address,
)
from aide.connectors.snowflake.namespace import DEV_DATABASE, workflow_short_id
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.connectors.snowflake.session import SnowflakeSession
from aide.domain.benchmark import LiveSmokeStatus
from aide.domain.enums import TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.sql import SqlText
from aide.domain.twin import SHA256_PATTERN

SELECTED_RAW_TABLES: tuple[tuple[str, str, str], ...] = (
    ("VANTARA_RAW", "CRM", "ACCOUNTS"),
    ("VANTARA_RAW", "CRM", "CONTACTS"),
    ("VANTARA_RAW", "CRM", "ACCOUNT_CROSSWALK"),
    ("VANTARA_RAW", "BILLING", "CUSTOMERS"),
    ("VANTARA_RAW", "BILLING", "SUBSCRIPTIONS"),
    ("VANTARA_RAW", "BILLING", "INVOICES"),
    ("VANTARA_RAW", "BILLING", "INVOICE_LINES"),
    ("VANTARA_RAW", "PAYMENTS", "PAYMENTS"),
    ("VANTARA_RAW", "PAYMENTS", "REFUNDS"),
    ("VANTARA_RAW", "PRODUCT", "PLANS"),
)
HANDOFF_TABLES: tuple[tuple[str, str, str], ...] = (
    ("VANTARA_RAW", "BILLING", "CUSTOMERS"),
    ("VANTARA_RAW", "BILLING", "INVOICES"),
    ("VANTARA_RAW", "PRODUCT", "PLANS"),
)
WORKFLOW_DEV_SCHEMA_SUFFIXES: tuple[str, ...] = (
    "CRM",
    "BILLING",
    "PAYMENTS",
    "PRODUCT",
    "DBT",
)

LIVE_SECRET_NAMES: tuple[str, ...] = (
    SHARED_SECRET_NAMES + RO_IDENTITY_SECRET_NAMES + DEV_IDENTITY_SECRET_NAMES
)
HUMAN_ACTION = (
    "On a credentialed host, set environment variables "
    + ", ".join(LIVE_SECRET_NAMES)
    + ". Do not paste secret values into chat. Do not grant AIDE_DEV_RW any "
    "new VANTARA_RAW privilege."
)
_BUDGET = Budget(max_rows=32, max_bytes=65536, max_seconds=60)
_RAW_TOKEN = "VANTARA_RAW"
_SAFE_RO_RAW_PRIVILEGES = frozenset(
    {
        "USAGE",
        "SELECT",
        "REFERENCES",
        "MONITOR",
        "IMPORTED PRIVILEGES",
    }
)


class LiveProbeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LiveProbeReport(LiveProbeModel):
    status: LiveSmokeStatus
    missing_env_names: tuple[str, ...] = ()
    human_action: str = HUMAN_ACTION
    ro_inspected_raw: bool = False
    ro_write_blocked: bool = False
    dev_raw_read_blocked: bool = False
    dev_raw_write_blocked: bool = False
    dev_scope_aide_dev: bool = False
    manifest_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    raw_dev_reconciled: bool = False
    production_or_staging_action: bool = False
    grant_sql_executed: bool = False
    future_grants_inspected: bool = False
    governed_path_exercised: bool = False
    gateway_connector_ids: tuple[str, ...] = ()
    policy_evaluated: bool = False
    evidence_persisted: bool = False
    dev_only_execution: bool = False
    independent_verifier_ran: bool = False
    tests_ok: bool = False
    quality_ok: bool = False
    include_schema_drift: bool = False
    detail: str = ""


def missing_live_secret_names() -> tuple[str, ...]:
    names: list[str] = []
    names.extend(missing_secret_names(settings_for_identity(IdentityClass.READ_ONLY)))
    names.extend(missing_secret_names(settings_for_identity(IdentityClass.DEVELOPMENT)))
    return tuple(sorted(set(names)))


def interview_live_credentials_available() -> bool:
    return snowflake_credentials_available() and snowflake_dev_credentials_available()


def _row_field(row: Mapping[str, Any], *names: str) -> str:
    lookup = {str(key).upper(): value for key, value in row.items()}
    for name in names:
        value = lookup.get(name.upper())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _privilege_name(row: Mapping[str, Any]) -> str:
    return _row_field(row, "privilege", "privileges").upper().replace("_", " ").strip()


def _targets_vantara_raw(row: Mapping[str, Any]) -> bool:
    blob = " ".join(
        (
            _row_field(row, "name", "table_name", "object_name"),
            _row_field(row, "granted_on", "grant_on"),
            _row_field(row, "database_name"),
            _row_field(row, "schema_name"),
        )
    )
    return _RAW_TOKEN in blob.upper().replace('"', "")


def _is_write_capable_privilege(privilege: str) -> bool:
    """Fail closed: only a narrow read/usage set is tolerated on RAW for RO."""
    cleaned = privilege.upper().replace("_", " ").strip()
    if not cleaned:
        return False
    return cleaned not in _SAFE_RO_RAW_PRIVILEGES


def ro_raw_write_violations(grants: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Privileges that would let AIDE_DEV_RO mutate VANTARA_RAW."""
    found: list[str] = []
    for row in grants:
        if not _targets_vantara_raw(row):
            continue
        privilege = _privilege_name(row)
        if _is_write_capable_privilege(privilege):
            target = _row_field(row, "name") or _RAW_TOKEN
            found.append(f"{privilege} on {target}")
    return tuple(found)


def dev_raw_access_violations(grants: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Any AIDE_DEV_RW grant whose object involves VANTARA_RAW."""
    found: list[str] = []
    for row in grants:
        if not _targets_vantara_raw(row):
            continue
        privilege = _privilege_name(row) or "UNKNOWN"
        target = _row_field(row, "name") or _RAW_TOKEN
        found.append(f"{privilege} on {target}")
    return tuple(found)


def _context(workflow_id: UUID, label: str, *, deadline_seconds: int = 180) -> CallContext:
    now = datetime.now(UTC)
    return CallContext(
        workflow_id=workflow_id,
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key=(label[:8].ljust(8, "a") + "b" * 56)[:64],
        resolved_input_digest="c" * 64,
        contract_snapshot_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        claim_epoch=1,
        cancellation_epoch=0,
        deadline=now + timedelta(seconds=deadline_seconds),
        external_correlation="mvp004-live",
        redaction=RedactionPolicy(),
    )


def _denied(exc: SnowflakeMappedError) -> bool:
    return exc.failure in {
        FailureClass.PERMISSION_FAILURE,
        FailureClass.UNSAFE_OPERATION,
        FailureClass.MISSING_OBJECT,
    }


def _failed(detail: str) -> LiveProbeReport:
    return LiveProbeReport(status=LiveSmokeStatus.FAILED, detail=detail)


async def _identity_sql(
    identity: IdentityClass, context: CallContext, sql: str
) -> list[dict[str, Any]]:
    spec = SNOWFLAKE_DEV if identity is IdentityClass.DEVELOPMENT else SNOWFLAKE_RO
    connector = RealSnowflakeConnector(spec)
    try:

        def run(session: SnowflakeSession) -> list[dict[str, Any]]:
            _columns, rows, _query_id = session.execute(sql)
            return rows

        return await connector._session_call(context, run)  # noqa: SLF001
    finally:
        await connector.close()


async def _dev_sql(context: CallContext, sql: str) -> list[dict[str, Any]]:
    return await _identity_sql(IdentityClass.DEVELOPMENT, context, sql)


async def _show_grants_to_role(
    identity: IdentityClass,
    context: CallContext,
    role: str,
    *,
    future: bool = False,
) -> list[dict[str, Any]] | None:
    kind = "FUTURE GRANTS" if future else "GRANTS"
    sql = f'SHOW {kind} TO ROLE "{role}"'
    try:
        return await _identity_sql(identity, context, sql)
    except SnowflakeMappedError:
        if future:
            return None
        raise


def _csv_expected(address: tuple[str, str, str], version: str) -> tuple[int, str]:
    path = csv_path_for(address, version)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = list(reader)
    return len(rows), schema_sha256(tuple(header))


def _allow_lists_are_dev_only() -> bool:
    if SNOWFLAKE_DEV.target_environment is not TargetEnv.DEV:
        return False
    if SNOWFLAKE_RO.target_environment is not TargetEnv.DEV:
        return False
    if "VANTARA_RAW" in SNOWFLAKE_DEV.allow_list.databases:
        return False
    prod_tokens = {"PROD", "PRODUCTION", "STAGING"}
    for name in SNOWFLAKE_DEV.allow_list.databases | SNOWFLAKE_RO.allow_list.databases:
        if name.upper() in prod_tokens:
            return False
    return SNOWFLAKE_DEV.allow_list.databases == frozenset({DEV_DATABASE})


async def drop_workflow_dev_schemas(workflow_id: UUID) -> None:
    """Remove only workflow-scoped AIDE_DEV schemas. RAW stays untouched."""
    prefix = workflow_short_id(workflow_id)
    context = _context(workflow_id, "cleanup")
    for suffix in WORKFLOW_DEV_SCHEMA_SUFFIXES:
        schema = f"{prefix}_{suffix}"
        quoted = schema.replace('"', '""')
        try:
            await _dev_sql(
                context,
                f'DROP SCHEMA IF EXISTS {DEV_DATABASE}."{quoted}" CASCADE',
            )
        except Exception:
            continue


async def run_live_interview_smoke() -> LiveProbeReport:
    """AT-18 and AT-19 live grant/handoff checks. Fail closed. Never GRANT."""
    missing = missing_live_secret_names()
    if missing:
        return LiveProbeReport(
            status=LiveSmokeStatus.CREDENTIAL_GATED,
            missing_env_names=missing,
            detail="Snowflake RO/DEV credentials are not present in this environment",
        )
    if not _allow_lists_are_dev_only():
        return _failed("connector allow lists are not limited to the accepted DEV/RAW scopes")
    workflow_id = uuid4()
    context = _context(workflow_id, "mvp004live", deadline_seconds=300)
    ro_inspected = False
    ro_write_blocked = False
    dev_read_blocked = False
    dev_write_blocked = False
    future_inspected = False
    digest: str | None = None
    reconciled = False
    raw_counts: dict[tuple[str, str, str], int] = {}
    try:
        ro = RealSnowflakeConnector(SNOWFLAKE_RO)
        try:
            health = await ro.health()
            if health.status != "AVAILABLE":
                return _failed("RO identity is not AVAILABLE")
            role = await ro.execute_query(
                ExecuteQueryInput(
                    sql=SqlText(dialect="snowflake", text="SELECT CURRENT_ROLE() AS ROLE"),
                    budget=_BUDGET,
                ),
                context,
            )
            current_role = str(next(iter(role.rows[0].values()))).upper() if role.rows else ""
            if current_role != ROLE_READ_ONLY:
                return _failed("RO identity is not using AIDE_DEV_RO")
            raw_ok = True
            raw_counts = {}
            for address in SELECTED_RAW_TABLES:
                sql = f"SELECT COUNT(*) AS N FROM {address[0]}.{address[1]}.{address[2]}"
                counted = await ro.execute_query(
                    ExecuteQueryInput(
                        sql=SqlText(dialect="snowflake", text=sql),
                        budget=Budget(max_rows=8, max_bytes=65536, max_seconds=60),
                    ),
                    context,
                )
                if not counted.rows:
                    raw_ok = False
                    break
                raw_counts[address] = int(next(iter(counted.rows[0].values())))
            ro_inspected = raw_ok and all(count > 0 for count in raw_counts.values())
        finally:
            await ro.close()

        ro_grants = await _show_grants_to_role(IdentityClass.READ_ONLY, context, ROLE_READ_ONLY)
        if ro_grants is None:
            return _failed("could not inspect current grants for AIDE_DEV_RO")
        ro_future = await _show_grants_to_role(
            IdentityClass.READ_ONLY, context, ROLE_READ_ONLY, future=True
        )
        if ro_future is not None:
            future_inspected = True
        ro_violations = ro_raw_write_violations(list(ro_grants) + list(ro_future or ()))
        if ro_violations:
            return LiveProbeReport(
                status=LiveSmokeStatus.FAILED,
                ro_inspected_raw=ro_inspected,
                ro_write_blocked=False,
                future_grants_inspected=future_inspected,
                detail="AIDE_DEV_RO has write-capable privileges on VANTARA_RAW",
            )
        ro_write_blocked = True

        try:
            await _identity_sql(
                IdentityClass.DEVELOPMENT,
                context,
                "SELECT COUNT(*) AS N FROM VANTARA_RAW.BILLING.INVOICES",
            )
        except SnowflakeMappedError as exc:
            dev_read_blocked = _denied(exc)
        else:
            return LiveProbeReport(
                status=LiveSmokeStatus.FAILED,
                ro_inspected_raw=ro_inspected,
                ro_write_blocked=ro_write_blocked,
                dev_raw_read_blocked=False,
                future_grants_inspected=future_inspected,
                detail=(
                    "DEV identity can still read VANTARA_RAW; "
                    "previously revoked grants remain a blocker"
                ),
            )

        dev = RealSnowflakeConnector(SNOWFLAKE_DEV)
        try:
            health = await dev.health()
            if health.status != "AVAILABLE":
                return _failed("DEV identity is not AVAILABLE")
            role_rows = await _dev_sql(context, "SELECT CURRENT_ROLE() AS ROLE")
            dev_role = str(next(iter(role_rows[0].values()))).upper() if role_rows else ""
            if dev_role != ROLE_DEVELOPMENT:
                return _failed("DEV identity is not using AIDE_DEV_RW")
            dev_grants = await _show_grants_to_role(
                IdentityClass.DEVELOPMENT, context, ROLE_DEVELOPMENT
            )
            if dev_grants is None:
                return _failed("could not inspect current grants for AIDE_DEV_RW")
            dev_future = await _show_grants_to_role(
                IdentityClass.DEVELOPMENT, context, ROLE_DEVELOPMENT, future=True
            )
            if dev_future is not None:
                future_inspected = True
            dev_violations = dev_raw_access_violations(list(dev_grants) + list(dev_future or ()))
            if dev_violations:
                return LiveProbeReport(
                    status=LiveSmokeStatus.FAILED,
                    ro_inspected_raw=ro_inspected,
                    ro_write_blocked=ro_write_blocked,
                    dev_raw_read_blocked=dev_read_blocked,
                    dev_raw_write_blocked=False,
                    future_grants_inspected=future_inspected,
                    detail="AIDE_DEV_RW has unintended VANTARA_RAW access",
                )
            dev_write_blocked = True

            digest = tiny_manifest_digest()
            loaded = await dev.load_manifest_sources(
                LoadManifestSourcesInput(
                    fixture_version="v2",
                    manifest_sha256=digest,
                    selected_addresses=HANDOFF_TABLES,
                ),
                context,
            )
            if loaded.fixture_digest != digest or loaded.target_database != DEV_DATABASE:
                return _failed("manifest load did not stay on the pinned digest and AIDE_DEV")
            prefix = workflow_short_id(workflow_id) + "_"
            if not all(str(item.address[1]).startswith(prefix) for item in loaded.tables):
                return _failed("DEV load escaped the workflow namespace")
            reconciled = loaded.reconcile_ok
            loaded_by_table = {tuple(item.address[1:]): item for item in loaded.tables}
            for source in HANDOFF_TABLES:
                expected_rows, expected_schema = _csv_expected(source, "v2")
                key = workflow_source_address(workflow_id, source)[1:]
                found = loaded_by_table.get(key)
                if found is None:
                    reconciled = False
                    continue
                if found.row_count != expected_rows or found.schema_sha256 != expected_schema:
                    reconciled = False
                raw_count = raw_counts.get(source)
                if raw_count is not None and raw_count != expected_rows:
                    reconciled = False
        finally:
            await dev.close()

        passed = (
            ro_inspected
            and ro_write_blocked
            and dev_read_blocked
            and dev_write_blocked
            and reconciled
        )
        return LiveProbeReport(
            status=LiveSmokeStatus.PASSED if passed else LiveSmokeStatus.FAILED,
            ro_inspected_raw=ro_inspected,
            ro_write_blocked=ro_write_blocked,
            dev_raw_read_blocked=dev_read_blocked,
            dev_raw_write_blocked=dev_write_blocked,
            dev_scope_aide_dev=True,
            manifest_digest=digest,
            raw_dev_reconciled=reconciled,
            production_or_staging_action=False,
            grant_sql_executed=False,
            future_grants_inspected=future_inspected,
            detail=(
                "live grant metadata probe and RAW/DEV fixture reconciliation completed"
                if passed
                else "live probe failed a least-privilege or reconciliation check"
            ),
        )
    except Exception as exc:
        return _failed(sanitize_error_message(str(exc)))
    finally:
        await drop_workflow_dev_schemas(workflow_id)


__all__ = [
    "HUMAN_ACTION",
    "LIVE_SECRET_NAMES",
    "LiveProbeReport",
    "dev_raw_access_violations",
    "drop_workflow_dev_schemas",
    "interview_live_credentials_available",
    "missing_live_secret_names",
    "ro_raw_write_violations",
    "run_live_interview_smoke",
]
