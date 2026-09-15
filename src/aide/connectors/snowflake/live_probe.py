"""Credential-gated live probes for the Interview MVP Snowflake boundary.

Never logs secret values. Never issues GRANT statements. Never mutates
VANTARA_RAW, production, or staging.
"""

from __future__ import annotations

import csv
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
    detail: str = ""


def missing_live_secret_names() -> tuple[str, ...]:
    names: list[str] = []
    names.extend(missing_secret_names(settings_for_identity(IdentityClass.READ_ONLY)))
    names.extend(missing_secret_names(settings_for_identity(IdentityClass.DEVELOPMENT)))
    return tuple(sorted(set(names)))


def interview_live_credentials_available() -> bool:
    return snowflake_credentials_available() and snowflake_dev_credentials_available()


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


async def _ro_sql(context: CallContext, sql: str) -> list[dict[str, Any]]:
    return await _identity_sql(IdentityClass.READ_ONLY, context, sql)


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


async def _write_is_blocked(sql: str, context: CallContext, identity: IdentityClass) -> bool:
    try:
        await _identity_sql(identity, context, sql)
    except SnowflakeMappedError as exc:
        return _denied(exc)
    return False


async def run_live_interview_smoke() -> LiveProbeReport:
    """AT-18, AT-19, and AT-24 live checks. Fail closed. Never GRANT."""
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
    loaded_schemas: set[str] = set()
    ro_inspected = False
    ro_write_blocked = False
    dev_read_blocked = False
    dev_write_blocked = False
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

        probe = f"AIDE_MVP004_{uuid4().hex[:10]}"
        ro_write_blocked = await _write_is_blocked(
            f"CREATE TABLE VANTARA_RAW.BILLING.{probe} AS SELECT 1 AS ID",
            context,
            IdentityClass.READ_ONLY,
        )
        if not ro_write_blocked:
            await _ro_sql(context, f"DROP TABLE IF EXISTS VANTARA_RAW.BILLING.{probe}")
            return LiveProbeReport(
                status=LiveSmokeStatus.FAILED,
                ro_inspected_raw=ro_inspected,
                ro_write_blocked=False,
                detail="RO identity was able to write VANTARA_RAW; probe did not grant access",
            )

        try:
            await _dev_sql(context, "SELECT COUNT(*) AS N FROM VANTARA_RAW.BILLING.INVOICES")
        except SnowflakeMappedError as exc:
            dev_read_blocked = _denied(exc)
        else:
            return LiveProbeReport(
                status=LiveSmokeStatus.FAILED,
                ro_inspected_raw=ro_inspected,
                ro_write_blocked=ro_write_blocked,
                dev_raw_read_blocked=False,
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
            probe = f"AIDE_MVP004_{uuid4().hex[:10]}"
            dev_write_blocked = await _write_is_blocked(
                f"CREATE TABLE VANTARA_RAW.BILLING.{probe} AS SELECT 1 AS ID",
                context,
                IdentityClass.DEVELOPMENT,
            )
            if not dev_write_blocked:
                await _dev_sql(context, f"DROP TABLE IF EXISTS VANTARA_RAW.BILLING.{probe}")
                return _failed("DEV identity was able to write VANTARA_RAW")

            digest = tiny_manifest_digest()
            loaded = await dev.load_manifest_sources(
                LoadManifestSourcesInput(
                    fixture_version="v2",
                    manifest_sha256=digest,
                    selected_addresses=HANDOFF_TABLES,
                ),
                context,
            )
            for loaded_table in loaded.tables:
                loaded_schemas.add(str(loaded_table.schema_name))
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
            detail=(
                "live grant probe and RAW/DEV fixture reconciliation completed"
                if passed
                else "live probe failed a least-privilege or reconciliation check"
            ),
        )
    except Exception as exc:
        return _failed(sanitize_error_message(str(exc)))
    finally:
        for schema in loaded_schemas:
            if not schema.upper().startswith("WF"):
                continue
            quoted = schema.replace('"', '""')
            try:
                await _dev_sql(
                    _context(workflow_id, "cleanup"),
                    f'DROP SCHEMA IF EXISTS {DEV_DATABASE}."{quoted}" CASCADE',
                )
            except Exception:
                continue


__all__ = [
    "HUMAN_ACTION",
    "LIVE_SECRET_NAMES",
    "LiveProbeReport",
    "interview_live_credentials_available",
    "missing_live_secret_names",
    "run_live_interview_smoke",
]
