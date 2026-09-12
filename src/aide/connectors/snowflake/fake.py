"""DuckDB-backed fake Snowflake connector for the offline DE 002C slice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import duckdb
import sqlglot
from sqlglot import exp

from aide.capabilities.io import (
    CatalogAsset,
    ColumnSpec,
    CreateDatasetInput,
    CreateDatasetOutput,
    DescribeAssetInput,
    DescribeAssetOutput,
    DiscoverAssetsInput,
    DiscoverAssetsOutput,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    PlanSummary,
    QueryError,
    ValidateQueryInput,
    ValidateQueryOutput,
)
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.snowflake.errors import FakeSnowflakeError
from aide.connectors.snowflake.query_tags import format_query_tag, parse_query_tag
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef

CATALOGUE: tuple[tuple[str, str, str, tuple[tuple[str, str, bool], ...]], ...] = (
    (
        "RAW",
        "SALES",
        "ORDERS",
        (
            ("ORDER_ID", "NUMBER", False),
            ("CUSTOMER_ID", "NUMBER", False),
            ("ORDER_TS", "TIMESTAMP_NTZ", False),
            ("AMOUNT", "NUMBER", False),
        ),
    ),
    (
        "RAW",
        "SALES",
        "CUSTOMERS",
        (
            ("CUSTOMER_ID", "NUMBER", False),
            ("CUSTOMER_NAME", "VARCHAR", False),
            ("REGION", "VARCHAR", True),
        ),
    ),
    (
        "RAW",
        "CRM",
        "ACCOUNTS",
        (
            ("ACCOUNT_ID", "NUMBER", False),
            ("ACCOUNT_NAME", "VARCHAR", False),
            ("SEGMENT", "VARCHAR", True),
        ),
    ),
)


def _table_ident(database: str, schema: str, table: str) -> str:
    return f"{database}.{schema}.{table}"


class FakeSnowflakeConnector:
    """Deterministic warehouse fake with health, provenance, and query-tag round-trip."""

    def __init__(self, spec: ConnectorSpec) -> None:
        self.spec = spec
        self._health_override: str | None = None
        self._queries: dict[str, dict[str, Any]] = {}
        self._effects: dict[str, dict[str, Any]] = {}
        self._conn = duckdb.connect(database=":memory:")
        self._install_catalogue()

    def force_health(self, status: str | None) -> None:
        self._health_override = status

    def _install_catalogue(self) -> None:
        for database, schema, table, columns in CATALOGUE:
            ident = _table_ident(database, schema, table)
            col_sql = ", ".join(
                f'"{name}" {"DOUBLE" if dtype == "NUMBER" else "VARCHAR"}'
                for name, dtype, _nullable in columns
            )
            self._conn.execute(f'CREATE TABLE "{ident}" ({col_sql})')
            if table == "ORDERS":
                self._conn.execute(
                    f"""
                    INSERT INTO "{ident}" VALUES
                    (1, 10, '2026-01-01 00:00:00', 10.5),
                    (2, 11, '2026-01-02 00:00:00', 20.0),
                    (3, 10, '2026-01-03 00:00:00', 5.25)
                    """
                )
            elif table == "CUSTOMERS":
                self._conn.execute(
                    f"""
                    INSERT INTO "{ident}" VALUES
                    (10, 'Northwind', 'EMEA'),
                    (11, 'Contoso', 'NA')
                    """
                )
            else:
                self._conn.execute(
                    f"""
                    INSERT INTO "{ident}" VALUES
                    (100, 'Northwind Holdings', 'ENTERPRISE'),
                    (101, 'Contoso Retail', 'SMB')
                    """
                )
        self._conn.execute('CREATE SCHEMA IF NOT EXISTS "AIDE_DEV"')

    async def health(self) -> ConnectorHealthSnapshot:
        now = datetime.now(UTC).replace(tzinfo=None)
        status = self._health_override or "MOCK"
        return ConnectorHealthSnapshot(
            connector_id=self.spec.connector_id,
            status=status,  # type: ignore[arg-type]
            checked_at=now,
            expires_at=now + timedelta(minutes=5),
        )

    async def close(self) -> None:
        self._conn.close()

    async def discover_assets(
        self, payload: DiscoverAssetsInput, context: CallContext
    ) -> DiscoverAssetsOutput:
        self._require_read()
        self._require_available()
        assets: list[CatalogAsset] = []
        for database, schema, table, _columns in sorted(CATALOGUE):
            if database not in payload.scope.databases:
                continue
            if payload.scope.schemas is not None and schema not in payload.scope.schemas:
                continue
            if payload.filters.name_pattern and payload.filters.name_pattern not in table:
                continue
            assets.append(
                CatalogAsset(
                    connector_id=self.spec.connector_id,
                    address=(database, schema, table),
                    kind=AssetKind.TABLE,
                    platform_type="snowflake",
                    row_count_estimate=self._row_count(database, schema, table),
                    comment=None,
                )
            )
        snapshot_id = uuid4()
        output = DiscoverAssetsOutput(
            assets=tuple(assets), snapshot_id=snapshot_id, truncated=False
        )
        self._record(context, output.model_dump(mode="json"), capability_id="discover_assets")
        return output

    async def describe_asset(
        self, payload: DescribeAssetInput, context: CallContext
    ) -> DescribeAssetOutput:
        self._require_read()
        self._require_available()
        match = self._require_asset(payload.asset)
        database, schema, table, columns = match
        column_specs = tuple(
            ColumnSpec(
                name=name,
                data_type=dtype,
                nullable=nullable,
                ordinal=index + 1,
                comment=None,
                is_untrusted_text=True,
            )
            for index, (name, dtype, nullable) in enumerate(columns)
        )
        output = DescribeAssetOutput(
            asset=AssetRef(
                connector_id=self.spec.connector_id,
                address=(database, schema, table),
                kind=AssetKind.TABLE,
                platform_type="snowflake",
            ),
            columns=column_specs,
            primary_key=(columns[0][0],),
            row_count=(
                self._row_count(database, schema, table) if payload.include_row_count else None
            ),
            snapshot_id=uuid4(),
        )
        self._record(context, output.model_dump(mode="json"), capability_id="describe_asset")
        return output

    async def validate_query(
        self, payload: ValidateQueryInput, context: CallContext
    ) -> ValidateQueryOutput:
        self._require_read()
        self._require_available()
        try:
            rewritten = rewrite_snowflake_to_duckdb(payload.sql.text)
            self._conn.execute(f"EXPLAIN {rewritten}")
        except Exception as exc:
            output = ValidateQueryOutput(
                valid=False,
                error=QueryError(code="SQL_SYNTAX", message=str(exc)),
            )
            self._record(context, output.model_dump(mode="json"), capability_id="validate_query")
            return output
        output = ValidateQueryOutput(valid=True, plan_summary=PlanSummary(estimated_bytes=1024))
        self._record(context, output.model_dump(mode="json"), capability_id="validate_query")
        return output

    async def execute_query(
        self, payload: ExecuteQueryInput, context: CallContext
    ) -> ExecuteQueryOutput:
        self._require_read()
        self._require_available()
        started = datetime.now(UTC)
        query_tag = format_query_tag(context)
        parse_query_tag(query_tag)
        rewritten = rewrite_snowflake_to_duckdb(payload.sql.text)
        relation = self._conn.execute(rewritten)
        description = relation.description or []
        raw_rows = relation.fetchall()
        columns = [item[0] for item in description]
        rows = tuple(
            {columns[index]: _jsonable(value) for index, value in enumerate(row)}
            for row in raw_rows[: payload.budget.max_rows]
        )
        duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
        query_id = str(uuid4())
        output = ExecuteQueryOutput(
            rows=rows if payload.result_mode == "ROWS" else None,
            scalar=(
                rows[0][columns[0]]
                if payload.result_mode == "SCALAR" and rows and columns
                else None
            ),
            row_count=len(raw_rows),
            bytes_scanned=len(raw_rows) * 64,
            duration_ms=max(duration, 1),
            query_id=query_id,
            query_tag=query_tag,
            truncated=len(raw_rows) > payload.budget.max_rows,
        )
        dumped = output.model_dump(mode="json")
        self._queries[query_id] = {
            "query_tag": query_tag,
            "operation_idempotency_key": context.operation_idempotency_key,
            "attempt_id": str(context.attempt_id),
            "output": dumped,
        }
        self._record(context, dumped, capability_id="execute_query")
        return output

    async def create_dataset(
        self, payload: CreateDatasetInput, context: CallContext
    ) -> CreateDatasetOutput:
        if self.spec.identity_class.value != "DEVELOPMENT":
            raise FakeSnowflakeError(
                FailureClass.PERMISSION_FAILURE, "create_dataset requires DEVELOPMENT identity"
            )
        self._require_available()
        target = payload.target.address
        if len(target) != 3:
            raise FakeSnowflakeError(
                FailureClass.SCHEMA_MISMATCH, "target must be database.schema.table"
            )
        ident = _table_ident(*target)
        exists = self._table_exists(ident)
        rewritten = rewrite_snowflake_to_duckdb(payload.definition.text)
        if exists and not payload.replace:
            raise FakeSnowflakeError(FailureClass.SCHEMA_MISMATCH, "target already exists")
        if exists:
            self._conn.execute(f'DROP TABLE "{ident}"')
        self._conn.execute(rewritten)
        count = self._conn.execute(f'SELECT COUNT(*) FROM "{ident}"').fetchone()
        output = CreateDatasetOutput(
            created=payload.target,
            replaced_existing=exists,
            row_count=int(count[0]) if count is not None else None,
        )
        self._record(context, output.model_dump(mode="json"), capability_id="create_dataset")
        return output

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown:
        key = recovery.operation_idempotency_key
        stored = self._effects.get(key)
        if stored is None:
            locator = recovery.operation_locator
            tag = locator.get("query_tag")
            if tag:
                parsed = parse_query_tag(tag)
                if parsed.operation_idempotency_key != key:
                    return Unknown(reason="query tag operation identity mismatch")
                for record in self._queries.values():
                    if record["query_tag"] == tag:
                        output = record["output"]
                        if not isinstance(output, dict):
                            return Unknown(reason="reconstructed output is not an object")
                        return EffectFound(output=output, external_ref=str(record.get("query_id")))
            return NoEffect(evidence="fake snowflake has no matching operation")
        output = stored.get("output")
        if not isinstance(output, dict):
            return Unknown(reason="stored effect has no validated output")
        return EffectFound(output=output, external_ref=stored.get("query_id"))

    def provenance(
        self,
        *,
        capability_id: str,
        operation_idempotency_key: str,
        resolved_input_digest: str,
        capability_version: int = 1,
        parent_artifact_ids: tuple[UUID, ...] = (),
    ) -> ArtifactProvenance:
        return ArtifactProvenance(
            execution_mode=ExecutionMode.MOCK,
            connector_id=self.spec.connector_id,
            connector_version=self.spec.version,
            capability_id=capability_id,
            capability_version=capability_version,
            operation_idempotency_key=operation_idempotency_key,
            resolved_input_digest=resolved_input_digest,
            parent_artifact_ids=parent_artifact_ids,
        )

    def recorded_query(self, query_id: str) -> dict[str, Any]:
        return self._queries[query_id]

    def _record(self, context: CallContext, output: dict[str, Any], *, capability_id: str) -> None:
        self._effects[context.operation_idempotency_key] = {
            "output": output,
            "capability_id": capability_id,
            "query_tag": format_query_tag(context),
            "attempt_id": str(context.attempt_id),
        }

    def _require_read(self) -> None:
        if self.spec.identity_class.value != "READ_ONLY":
            raise FakeSnowflakeError(
                FailureClass.PERMISSION_FAILURE,
                "warehouse READ requires identity_class=READ_ONLY",
            )

    def _require_available(self) -> None:
        if self._health_override == "UNAVAILABLE":
            raise FakeSnowflakeError(FailureClass.CONNECTOR_FAILURE, "connector unavailable")

    def _require_asset(
        self, asset: AssetRef
    ) -> tuple[str, str, str, tuple[tuple[str, str, bool], ...]]:
        if len(asset.address) != 3:
            raise FakeSnowflakeError(FailureClass.MISSING_OBJECT, "asset address incomplete")
        for item in CATALOGUE:
            if item[0:3] == asset.address:
                return item
        raise FakeSnowflakeError(FailureClass.MISSING_OBJECT, "asset not in fake catalogue")

    def _row_count(self, database: str, schema: str, table: str) -> int:
        ident = _table_ident(database, schema, table)
        row = self._conn.execute(f'SELECT COUNT(*) FROM "{ident}"').fetchone()
        return int(row[0]) if row is not None else 0

    def _table_exists(self, ident: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            [ident],
        ).fetchone()
        return row is not None


def rewrite_snowflake_to_duckdb(sql: str) -> str:
    tree = sqlglot.parse_one(sql, read="snowflake")
    for table in tree.find_all(exp.Table):
        parts = [part for part in (table.catalog, table.db, table.name) if part]
        if not parts:
            continue
        ident = ".".join(str(part).strip('"').upper() for part in parts)
        table.set("this", exp.to_identifier(ident, quoted=True))
        table.set("db", None)
        table.set("catalog", None)
    return tree.sql(dialect="duckdb")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def build_fake_pair() -> tuple[FakeSnowflakeConnector, FakeSnowflakeConnector]:
    return (
        FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO),
        FakeSnowflakeConnector(FAKE_SNOWFLAKE_DEV),
    )
