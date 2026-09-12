"""DuckDB-backed fake Snowflake connector with the same handler set as real.py."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

import duckdb
from pydantic import BaseModel

from aide.capabilities.io import (
    CandidateKey,
    CatalogAsset,
    ColumnSpec,
    CreateDatasetInput,
    CreateDatasetOutput,
    DescribeAssetInput,
    DescribeAssetOutput,
    DetectSchemaDriftInput,
    DetectSchemaDriftOutput,
    DiscoverAssetsInput,
    DiscoverAssetsOutput,
    DropDatasetInput,
    DropDatasetOutput,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    GetCostMetricsOutput,
    GetExecutionMetricsOutput,
    InferRelationshipsInput,
    InferRelationshipsOutput,
    MetricsQueryInput,
    PlanSummary,
    ProfileColumn,
    ProfileDatasetInput,
    ProfileDatasetOutput,
    QueryError,
    QueryMetric,
    RelationshipCandidate,
    SampleDatasetInput,
    SampleDatasetOutput,
    TaskCostBreakdown,
    TopValue,
    ValidateQueryInput,
    ValidateQueryOutput,
)
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot, HealthStatus
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.snowflake.dialect import (
    is_read_statement,
    normalize_identifier,
    referenced_tables,
    rewrite_snowflake_to_duckdb,
    statement_type,
)
from aide.connectors.snowflake.drift import compare_columns
from aide.connectors.snowflake.enforcement import (
    canonical_query_tag,
    require_asset_allowed,
    require_read_identity,
    require_scope_allowed,
    require_write_identity,
    statement_timeout_seconds,
)
from aide.connectors.snowflake.errors import FakeSnowflakeError, SnowflakeMappedError, raise_mapped
from aide.connectors.snowflake.health import health_snapshot
from aide.connectors.snowflake.masking import (
    column_is_sensitive,
    infer_semantic,
    mask_row,
    mask_value,
)
from aide.connectors.snowflake.namespace import (
    provenance_comment,
    require_dev_namespace,
    workflow_short_id,
)
from aide.connectors.snowflake.query_tags import parse_query_tag
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef

T = TypeVar("T", bound=BaseModel)

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
        self._snapshots: dict[str, DescribeAssetOutput] = {}
        self._profiles: dict[str, ProfileDatasetOutput] = {}
        self._object_provenance: dict[str, str] = {}
        self._fail_next: dict[str, FailureClass] = {}
        self._fail_after: set[str] = set()
        self._in_progress: dict[str, str] = {}
        self._history_lag = False
        self._renames: dict[tuple[str, str, str], tuple[str, str]] = {}
        self._conn = duckdb.connect(database=":memory:")
        self._install_catalogue()

    def force_health(self, status: str | None) -> None:
        self._health_override = status

    def fail_next(self, capability: str, failure: FailureClass) -> None:
        self._fail_next[capability] = failure

    def fail_after_effect(self, capability: str) -> None:
        self._fail_after.add(capability)

    def set_history_lag(self, lag: bool = True) -> None:
        self._history_lag = lag

    def mark_in_progress(self, operation_idempotency_key: str, query_id: str) -> None:
        self._in_progress[operation_idempotency_key] = query_id

    def rename_column(self, address: tuple[str, str, str], from_name: str, to_name: str) -> None:
        self._renames[address] = (from_name, to_name)
        ident = _table_ident(*address)
        self._duck(
            f'ALTER TABLE "{ident}" RENAME COLUMN "{normalize_identifier(from_name)}" '
            f'TO "{normalize_identifier(to_name)}"'
        )

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
        status: HealthStatus = "MOCK"
        if self._health_override in {"AVAILABLE", "DEGRADED", "UNAVAILABLE", "MOCK"}:
            status = cast(HealthStatus, self._health_override)
        return health_snapshot(self.spec, status=status)

    async def close(self) -> None:
        self._conn.close()

    async def discover_assets(
        self, payload: DiscoverAssetsInput, context: CallContext
    ) -> DiscoverAssetsOutput:
        self._prepare("discover_assets", context, read=True)
        require_scope_allowed(self.spec, payload.scope)
        assets: list[CatalogAsset] = []
        for database, schema, table, _columns in sorted(CATALOGUE):
            if database not in payload.scope.databases:
                continue
            if payload.scope.schemas is not None and schema not in payload.scope.schemas:
                continue
            if payload.filters.name_pattern and payload.filters.name_pattern not in table:
                continue
            asset = AssetRef(
                connector_id=self.spec.connector_id,
                address=(database, schema, table),
                kind=AssetKind.TABLE,
                platform_type="snowflake",
            )
            require_asset_allowed(self.spec, asset)
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
        output = DiscoverAssetsOutput(assets=tuple(assets), snapshot_id=uuid4(), truncated=False)
        return self._finish("discover_assets", context, output)

    async def describe_asset(
        self, payload: DescribeAssetInput, context: CallContext
    ) -> DescribeAssetOutput:
        self._prepare("describe_asset", context, read=True)
        asset = require_asset_allowed(self.spec, payload.asset)
        match = self._require_asset(asset)
        database, schema, table, columns = match
        columns = self._apply_rename(database, schema, table, columns)
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
        self._snapshots[str(output.snapshot_id)] = output
        return self._finish("describe_asset", context, output)

    async def detect_schema_drift(
        self, payload: DetectSchemaDriftInput, context: CallContext
    ) -> DetectSchemaDriftOutput:
        self._prepare("detect_schema_drift", context, read=True)
        described = await self.describe_asset(
            DescribeAssetInput(
                asset=payload.asset, include_constraints=True, include_row_count=False
            ),
            context,
        )
        baseline_columns = payload.baseline_columns
        if baseline_columns is None:
            stored = self._snapshots.get(str(payload.baseline_snapshot_id))
            if stored is None:
                raise FakeSnowflakeError(
                    FailureClass.MISSING_OBJECT, "baseline snapshot is not available"
                )
            baseline_columns = stored.columns
        output = compare_columns(described.columns, baseline_columns)
        return self._finish("detect_schema_drift", context, output)

    async def profile_dataset(
        self, payload: ProfileDatasetInput, context: CallContext
    ) -> ProfileDatasetOutput:
        self._prepare("profile_dataset", context, read=True)
        asset = require_asset_allowed(self.spec, payload.asset)
        match = self._require_asset(asset)
        database, schema, table, columns = self._apply_rename_match(match)
        selected = payload.columns or tuple(name for name, _dtype, _null in columns)
        ident = _table_ident(database, schema, table)
        row_count = self._row_count(database, schema, table)
        profile_columns: list[ProfileColumn] = []
        candidate_keys: list[CandidateKey] = []
        for name, dtype, _nullable in columns:
            if name not in selected:
                continue
            stats = self._duck(
                f'SELECT COUNT(*) - COUNT("{name}"), COUNT(DISTINCT "{name}"), '
                f'MIN("{name}"), MAX("{name}") FROM "{ident}"'
            ).fetchone()
            null_count = int(stats[0]) if stats is not None else 0
            distinct_count = int(stats[1]) if stats is not None else 0
            min_value = _jsonable(stats[2]) if stats is not None else None
            max_value = _jsonable(stats[3]) if stats is not None else None
            mean_value = None
            if dtype == "NUMBER":
                mean_row = self._duck(f'SELECT AVG("{name}") FROM "{ident}"').fetchone()
                mean_value = float(mean_row[0]) if mean_row and mean_row[0] is not None else None
            ratio_den = max(row_count, 1)
            top_rows = self._duck(
                f'SELECT "{name}", COUNT(*) AS c FROM "{ident}" '
                f'WHERE "{name}" IS NOT NULL GROUP BY 1 ORDER BY c DESC LIMIT {payload.top_k}'
            ).fetchall()
            sensitive = column_is_sensitive(name)
            top_values = tuple(
                TopValue(
                    value_masked=mask_value(item[0])
                    if sensitive
                    else (None if item[0] is None else str(item[0])),
                    count=int(item[1]),
                )
                for item in top_rows
            )
            uniqueness = distinct_count / ratio_den
            profile_columns.append(
                ProfileColumn(
                    name=name,
                    null_ratio=null_count / ratio_den,
                    distinct_ratio=uniqueness,
                    min=min_value,
                    max=max_value,
                    mean=mean_value,
                    top_values=top_values,
                    inferred_semantic=infer_semantic(name, dtype),  # type: ignore[arg-type]
                )
            )
            if uniqueness >= 0.99 and null_count == 0:
                candidate_keys.append(CandidateKey(columns=(name,), uniqueness_ratio=uniqueness))
        output = ProfileDatasetOutput(
            asset=asset,
            row_count=row_count,
            sampled=payload.sample_fraction is not None and payload.sample_fraction < 1,
            columns=tuple(profile_columns),
            candidate_keys=tuple(candidate_keys),
            duplicate_groups_estimate=0,
            profile_id=uuid4(),
        )
        self._profiles[str(output.profile_id)] = output
        return self._finish("profile_dataset", context, output)

    async def sample_dataset(
        self, payload: SampleDatasetInput, context: CallContext
    ) -> SampleDatasetOutput:
        self._prepare("sample_dataset", context, read=True)
        asset = require_asset_allowed(self.spec, payload.asset)
        match = self._require_asset(asset)
        database, schema, table, columns = self._apply_rename_match(match)
        where_class = payload.where.classification if payload.where is not None else None
        if where_class is not None and not where_class.is_read_only:
            raise FakeSnowflakeError(
                FailureClass.UNSAFE_OPERATION, "sample where clause is not read-only"
            )
        ident = _table_ident(database, schema, table)
        selected = payload.columns or tuple(name for name, _dtype, _null in columns)
        col_sql = ", ".join(f'"{name}"' for name in selected)
        relation = self._duck(f'SELECT {col_sql} FROM "{ident}" LIMIT {payload.n}')
        description = relation.description or []
        raw_rows = relation.fetchall()
        col_names = [item[0] for item in description]
        sensitive = {name for name in col_names if column_is_sensitive(name)}
        rows = tuple(
            mask_row(
                {col_names[index]: _jsonable(value) for index, value in enumerate(row)},
                sensitive=sensitive,
            )
            for row in raw_rows
        )
        output = SampleDatasetOutput(
            rows=rows, masked_columns=tuple(sorted(sensitive)), sample_id=uuid4()
        )
        return self._finish("sample_dataset", context, output)

    async def infer_relationships(
        self, payload: InferRelationshipsInput, context: CallContext
    ) -> InferRelationshipsOutput:
        self._prepare("infer_relationships", context, read=True)
        candidates: list[RelationshipCandidate] = []
        assets = [require_asset_allowed(self.spec, item) for item in payload.assets]
        matches = [self._apply_rename_match(self._require_asset(asset)) for asset in assets]
        pairs = 0
        for left in matches:
            for right in matches:
                if left[0:3] == right[0:3]:
                    continue
                for lname, ltype, _ln in left[3]:
                    for rname, rtype, _rn in right[3]:
                        if pairs >= payload.max_pairs:
                            break
                        left_sem = infer_semantic(lname, ltype)
                        right_sem = infer_semantic(rname, rtype)
                        if left_sem not in {"ID", "CODE"} or right_sem not in {"ID", "CODE"}:
                            continue
                        if ltype != rtype:
                            continue
                        inclusion = self._inclusion_ratio(left, lname, right, rname)
                        if inclusion < 0.5:
                            continue
                        cardinality: str = "N:M"
                        if inclusion >= 0.99:
                            cardinality = "1:N" if lname.endswith("_ID") else "1:1"
                        candidates.append(
                            RelationshipCandidate(
                                from_asset=AssetRef(
                                    connector_id=self.spec.connector_id,
                                    address=left[0:3],
                                    kind=AssetKind.TABLE,
                                    platform_type="snowflake",
                                ),
                                from_columns=(lname,),
                                to_asset=AssetRef(
                                    connector_id=self.spec.connector_id,
                                    address=right[0:3],
                                    kind=AssetKind.TABLE,
                                    platform_type="snowflake",
                                ),
                                to_columns=(rname,),
                                inclusion_ratio=inclusion,
                                cardinality=cardinality,  # type: ignore[arg-type]
                                confidence=round(inclusion, 4),
                            )
                        )
                        pairs += 1
        output = InferRelationshipsOutput(candidates=tuple(candidates), relationships_id=uuid4())
        return self._finish("infer_relationships", context, output)

    async def validate_query(
        self, payload: ValidateQueryInput, context: CallContext
    ) -> ValidateQueryOutput:
        self._prepare("validate_query", context, read=True)
        try:
            kind = statement_type(payload.sql.text)
            if kind not in {"SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "CREATE"}:
                output = ValidateQueryOutput(
                    valid=False,
                    error=QueryError(
                        code="UNSAFE_OPERATION",
                        message="statement is not explainable as a read or DEV create",
                    ),
                )
                return self._finish("validate_query", context, output)
            for asset in referenced_tables(payload.sql.text, connector_id=self.spec.connector_id):
                if len(asset.address) >= 3:
                    require_asset_allowed(self.spec, asset)
            rewritten = rewrite_snowflake_to_duckdb(payload.sql.text)
            self._duck(f"EXPLAIN {rewritten}")
        except SnowflakeMappedError as exc:
            output = ValidateQueryOutput(
                valid=False,
                error=QueryError(code=exc.failure.value, message=str(exc)),
            )
            return self._finish("validate_query", context, output)
        except Exception as exc:
            output = ValidateQueryOutput(
                valid=False,
                error=QueryError(code="SQL_SYNTAX", message=str(exc)),
            )
            return self._finish("validate_query", context, output)
        output = ValidateQueryOutput(valid=True, plan_summary=PlanSummary(estimated_bytes=1024))
        return self._finish("validate_query", context, output)

    async def execute_query(
        self, payload: ExecuteQueryInput, context: CallContext
    ) -> ExecuteQueryOutput:
        self._prepare("execute_query", context, read=True)
        self._enforce_read_sql(payload.sql.text)
        started = datetime.now(UTC)
        query_tag = canonical_query_tag(context)
        rewritten = rewrite_snowflake_to_duckdb(payload.sql.text)
        relation = self._duck(rewritten)
        description = relation.description or []
        raw_rows = relation.fetchall()
        columns = [item[0] for item in description]
        limited = raw_rows[: payload.budget.max_rows]
        rows = tuple(
            {columns[index]: _jsonable(value) for index, value in enumerate(row)} for row in limited
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
            "query_id": query_id,
            "query_tag": query_tag,
            "operation_idempotency_key": context.operation_idempotency_key,
            "attempt_id": str(context.attempt_id),
            "output": dumped,
            "status": "SUCCESS",
        }
        return self._finish("execute_query", context, output, query_id=query_id)

    async def get_execution_metrics(
        self, payload: MetricsQueryInput, context: CallContext
    ) -> GetExecutionMetricsOutput:
        self._prepare("get_execution_metrics", context, read=True)
        parse_query_tag(payload.query_tag)
        queries = tuple(
            QueryMetric(
                query_id=str(record["query_id"]),
                duration_ms=int(record["output"].get("duration_ms") or 1),
                bytes_scanned=record["output"].get("bytes_scanned"),
                rows_produced=record["output"].get("row_count"),
                warehouse="AIDE_DEV_WH",
            )
            for record in self._queries.values()
            if record.get("query_tag") == payload.query_tag
        )
        output = GetExecutionMetricsOutput(
            queries=queries,
            as_of=datetime.now(UTC).replace(tzinfo=None),
            complete=not self._history_lag,
        )
        return self._finish("get_execution_metrics", context, output)

    async def get_cost_metrics(
        self, payload: MetricsQueryInput, context: CallContext
    ) -> GetCostMetricsOutput:
        self._prepare("get_cost_metrics", context, read=True)
        parse_query_tag(payload.query_tag)
        matching = [
            record
            for record in self._queries.values()
            if record.get("query_tag") == payload.query_tag
        ]
        credits = 0.001 * len(matching)
        output = GetCostMetricsOutput(
            credits_used=credits,
            estimated_cost=credits,
            currency="USD",
            breakdown_by_task=(
                TaskCostBreakdown(task_id=str(context.task_id), credits_used=credits),
            ),
            as_of=datetime.now(UTC).replace(tzinfo=None),
            complete=False,
        )
        return self._finish("get_cost_metrics", context, output)

    async def create_dataset(
        self, payload: CreateDatasetInput, context: CallContext
    ) -> CreateDatasetOutput:
        self._prepare("create_dataset", context, read=False)
        target = require_asset_allowed(self.spec, payload.target)
        require_dev_namespace(target, context.workflow_id)
        if len(target.address) != 3:
            raise FakeSnowflakeError(
                FailureClass.SCHEMA_MISMATCH, "target must be database.schema.table"
            )
        ident = _table_ident(*target.address)
        exists = self._table_exists(ident)
        rewritten = rewrite_snowflake_to_duckdb(payload.definition.text)
        if exists and not payload.replace:
            raise FakeSnowflakeError(FailureClass.SCHEMA_MISMATCH, "target already exists")
        if exists:
            self._duck(f'DROP TABLE "{ident}"')
        self._duck(rewritten)
        count = self._duck(f'SELECT COUNT(*) FROM "{ident}"').fetchone()
        self._object_provenance[ident] = provenance_comment(
            workflow_id=context.workflow_id,
            operation_idempotency_key=context.operation_idempotency_key,
        )
        output = CreateDatasetOutput(
            created=target,
            replaced_existing=exists,
            row_count=int(count[0]) if count is not None else None,
        )
        return self._finish("create_dataset", context, output)

    async def drop_dataset(
        self, payload: DropDatasetInput, context: CallContext
    ) -> DropDatasetOutput:
        self._prepare("drop_dataset", context, read=False)
        target = require_asset_allowed(self.spec, payload.target)
        require_dev_namespace(target, context.workflow_id)
        ident = _table_ident(*target.address)
        marker = self._object_provenance.get(ident)
        expected = str(payload.created_by_workflow)
        if marker is None:
            raise FakeSnowflakeError(FailureClass.MISSING_OBJECT, "dataset does not exist")
        if str(context.workflow_id) != expected and expected not in marker:
            raise FakeSnowflakeError(
                FailureClass.UNSAFE_OPERATION, "dataset provenance does not match workflow"
            )
        if str(payload.created_by_workflow) not in marker and str(
            payload.created_by_workflow
        ) != str(context.workflow_id):
            raise FakeSnowflakeError(
                FailureClass.UNSAFE_OPERATION, "dataset was not created by this workflow"
            )
        self._duck(f'DROP TABLE IF EXISTS "{ident}"')
        self._object_provenance.pop(ident, None)
        output = DropDatasetOutput(dropped=True)
        return self._finish("drop_dataset", context, output)

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown:
        key = recovery.operation_idempotency_key
        if key in self._in_progress:
            return InProgress(external_ref=self._in_progress[key], retry_after_seconds=2)
        if self._history_lag:
            return Unknown(reason="query history lag", evidence="fake history lag flag")
        for attempt in recovery.attempts:
            if attempt.query_id and attempt.query_id in self._queries:
                record = self._queries[attempt.query_id]
                output = record.get("output")
                if not isinstance(output, dict):
                    return Unknown(reason="persisted query has no validated output")
                return EffectFound(output=output, external_ref=str(record.get("query_id")))
        stored = self._effects.get(key)
        if stored is None:
            locator = recovery.operation_locator
            tag = locator.get("query_tag")
            if tag:
                try:
                    parsed = parse_query_tag(tag)
                except ValueError:
                    return Unknown(reason="query tag could not be parsed")
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

    def _duck(self, sql: str, params: list[Any] | None = None) -> Any:
        try:
            if params is None:
                return self._conn.execute(sql)
            return self._conn.execute(sql, params)
        except SnowflakeMappedError:
            raise
        except Exception as exc:
            raise_mapped(exc)
            raise

    def _enforce_read_sql(self, sql: str) -> None:
        if not is_read_statement(sql):
            raise FakeSnowflakeError(
                FailureClass.UNSAFE_OPERATION, "execute_query requires a read statement"
            )
        for asset in referenced_tables(sql, connector_id=self.spec.connector_id):
            if len(asset.address) >= 3:
                require_asset_allowed(self.spec, asset)

    def _prepare(self, capability_id: str, context: CallContext, *, read: bool) -> None:
        if read:
            require_read_identity(self.spec)
        else:
            require_write_identity(self.spec)
        statement_timeout_seconds(context)
        if self._health_override == "UNAVAILABLE":
            raise FakeSnowflakeError(FailureClass.CONNECTOR_FAILURE, "connector unavailable")
        failure = self._fail_next.pop(capability_id, None)
        if failure is not None:
            raise FakeSnowflakeError(failure, f"injected {failure.value}")

    def _finish(
        self,
        capability_id: str,
        context: CallContext,
        output: T,
        *,
        query_id: str | None = None,
    ) -> T:
        dumped = output.model_dump(mode="json")
        self._record(context, dumped, capability_id=capability_id, query_id=query_id)
        if capability_id in self._fail_after:
            self._fail_after.discard(capability_id)
            raise FakeSnowflakeError(FailureClass.CONNECTOR_FAILURE, "fail_after_effect")
        return output

    def _record(
        self,
        context: CallContext,
        output: dict[str, Any],
        *,
        capability_id: str,
        query_id: str | None = None,
    ) -> None:
        self._effects[context.operation_idempotency_key] = {
            "output": output,
            "capability_id": capability_id,
            "query_tag": canonical_query_tag(context),
            "attempt_id": str(context.attempt_id),
            "query_id": query_id,
        }

    def _require_asset(
        self, asset: AssetRef
    ) -> tuple[str, str, str, tuple[tuple[str, str, bool], ...]]:
        if len(asset.address) != 3:
            raise FakeSnowflakeError(FailureClass.MISSING_OBJECT, "asset address incomplete")
        wanted = tuple(normalize_identifier(part) for part in asset.address)
        for item in CATALOGUE:
            if tuple(normalize_identifier(part) for part in item[0:3]) == wanted:
                return item
        ident = _table_ident(*wanted)
        if self._table_exists(ident):
            description = self._duck(f'SELECT * FROM "{ident}" LIMIT 0').description or []
            columns = tuple((str(col[0]), "VARCHAR", True) for col in description)
            return (wanted[0], wanted[1], wanted[2], columns)
        raise FakeSnowflakeError(FailureClass.MISSING_OBJECT, "asset not in fake catalogue")

    def _apply_rename(
        self,
        database: str,
        schema: str,
        table: str,
        columns: tuple[tuple[str, str, bool], ...],
    ) -> tuple[tuple[str, str, bool], ...]:
        rename = self._renames.get((database, schema, table))
        if rename is None:
            return columns
        from_name, to_name = rename
        return tuple(
            (to_name, dtype, nullable) if name == from_name else (name, dtype, nullable)
            for name, dtype, nullable in columns
        )

    def _apply_rename_match(
        self, match: tuple[str, str, str, tuple[tuple[str, str, bool], ...]]
    ) -> tuple[str, str, str, tuple[tuple[str, str, bool], ...]]:
        database, schema, table, columns = match
        return database, schema, table, self._apply_rename(database, schema, table, columns)

    def _row_count(self, database: str, schema: str, table: str) -> int:
        ident = _table_ident(database, schema, table)
        row = self._duck(f'SELECT COUNT(*) FROM "{ident}"').fetchone()
        return int(row[0]) if row is not None else 0

    def _table_exists(self, ident: str) -> bool:
        row = self._duck(
            "SELECT 1 FROM information_schema.tables WHERE table_name = ?",
            [ident],
        ).fetchone()
        return row is not None

    def _inclusion_ratio(
        self,
        child: tuple[str, str, str, tuple[tuple[str, str, bool], ...]],
        child_col: str,
        parent: tuple[str, str, str, tuple[tuple[str, str, bool], ...]],
        parent_col: str,
    ) -> float:
        child_ident = _table_ident(*child[0:3])
        parent_ident = _table_ident(*parent[0:3])
        child_vals = {
            row[0]
            for row in self._duck(
                f'SELECT DISTINCT "{child_col}" FROM "{child_ident}" '
                f'WHERE "{child_col}" IS NOT NULL'
            ).fetchall()
        }
        if not child_vals:
            return 0.0
        parent_vals = {
            row[0]
            for row in self._duck(
                f'SELECT DISTINCT "{parent_col}" FROM "{parent_ident}" '
                f'WHERE "{parent_col}" IS NOT NULL'
            ).fetchall()
        }
        return len(child_vals & parent_vals) / len(child_vals)


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


__all__ = [
    "CATALOGUE",
    "FakeSnowflakeConnector",
    "build_fake_pair",
    "rewrite_snowflake_to_duckdb",
    "workflow_short_id",
]
