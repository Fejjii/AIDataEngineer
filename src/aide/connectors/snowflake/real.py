"""Real Snowflake warehouse connector. Vendor I/O only; policy remains the safety boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import uuid4

from pydantic import SecretStr

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
    EvaluateExecutionPolicyInput,
    EvaluateExecutionPolicyOutput,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    GetCostMetricsOutput,
    GetExecutionMetricsOutput,
    InferRelationshipsInput,
    InferRelationshipsOutput,
    LoadedSourceTable,
    LoadManifestSourcesInput,
    LoadManifestSourcesOutput,
    MetricsQueryInput,
    PlanSummary,
    ProfileColumn,
    ProfileDatasetInput,
    ProfileDatasetOutput,
    ProfileEstateInput,
    ProfileEstateOutput,
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
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.snowflake.config import (
    EnvConnectorSecretResolver,
    SnowflakeSettings,
    missing_secret_names,
    settings_for_identity,
)
from aide.connectors.snowflake.dialect import (
    is_read_statement,
    normalize_identifier,
    qualify_parts,
    referenced_tables,
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
from aide.connectors.snowflake.errors import SnowflakeMappedError, map_error, sanitize_error_message
from aide.connectors.snowflake.health import (
    current_role_from_rows,
    health_from_current_role,
    health_snapshot,
    missing_credential_health,
)
from aide.connectors.snowflake.masking import (
    column_is_sensitive,
    infer_semantic,
    mask_row,
    mask_value,
)
from aide.connectors.snowflake.namespace import (
    provenance_comment,
    require_dev_namespace,
)
from aide.connectors.snowflake.query_tags import parse_query_tag
from aide.connectors.snowflake.session import SnowflakeSession
from aide.connectors.snowflake.sql_templates import (
    column_profile_sql,
    explain_sql,
    inclusion_sql,
    qualified_table,
    row_count_sql,
    sample_sql,
    top_values_sql,
)
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef
from aide.secrets.resolvers import UnresolvedSecretError

T = TypeVar("T")

_SUCCESS_STATUSES = frozenset({"SUCCESS", "SUCCEEDED"})
_RUNNING_STATUSES = frozenset({"RUNNING", "QUEUED", "QUEUEING", "RESUMING", "BLOCKED"})
_FAILED_STATUSES = frozenset({"FAIL", "FAILED", "ABORTED", "INCIDENT", "FAILED_WITH_INCIDENT"})
# Unqualified INFORMATION_SCHEMA.QUERY_HISTORY() resolves to the session database
# (e.g. VANTARA_RAW) and fails. Use the account-level Snowflake information schema.
_QUERY_HISTORY = "TABLE(SNOWFLAKE.INFORMATION_SCHEMA.QUERY_HISTORY())"


class RealSnowflakeConnector:
    """snowflake-connector-python adapter. Blocking vendor calls use a thread boundary."""

    def __init__(
        self,
        spec: ConnectorSpec,
        *,
        settings: SnowflakeSettings | None = None,
        resolver: EnvConnectorSecretResolver | None = None,
        run_session: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.spec = spec
        self._settings = settings or settings_for_identity(spec.identity_class)
        self._resolver = resolver or EnvConnectorSecretResolver()
        self._run_session = run_session
        self._closed = False

    async def health(self) -> ConnectorHealthSnapshot:
        missing = missing_credential_health(self.spec, self._settings)
        if missing is not None:
            return missing
        if self._closed:
            return health_snapshot(
                self.spec, status="UNAVAILABLE", reason_codes=("CONNECTOR_CLOSED",)
            )
        try:
            rows = await self._with_session(
                query_tag="aide:v1;health",
                timeout_seconds=15,
                fn=lambda session: session.execute("SELECT CURRENT_ROLE() AS ROLE"),
            )
            _columns, result, _query_id = rows
            return health_from_current_role(
                self.spec,
                expected_role=self._settings.role,
                current_role=current_role_from_rows(result),
            )
        except SnowflakeMappedError as exc:
            return health_snapshot(
                self.spec,
                status="UNAVAILABLE",
                reason_codes=(exc.failure.value,),
            )
        except Exception as exc:
            return health_snapshot(
                self.spec,
                status="UNAVAILABLE",
                reason_codes=(map_error(exc).value,),
            )

    async def close(self) -> None:
        self._closed = True

    async def discover_assets(
        self, payload: DiscoverAssetsInput, context: CallContext
    ) -> DiscoverAssetsOutput:
        self._prepare_read(context)
        require_scope_allowed(self.spec, payload.scope)
        include_views = payload.scope.include_views

        def run(session: SnowflakeSession) -> tuple[CatalogAsset, ...]:
            found: list[CatalogAsset] = []
            for database in payload.scope.databases:
                db = normalize_identifier(database)
                table_rel = qualify_parts((db, "INFORMATION_SCHEMA", "TABLES"))
                sql = (
                    f"SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, "
                    f"ROW_COUNT, LAST_ALTERED, COMMENT FROM {table_rel} "
                    f"WHERE TABLE_SCHEMA IS NOT NULL"
                )
                _cols, rows, _qid = session.execute(sql)
                for row in rows:
                    schema = normalize_identifier(str(row["TABLE_SCHEMA"]))
                    table = normalize_identifier(str(row["TABLE_NAME"]))
                    kind_raw = str(row.get("TABLE_TYPE") or "BASE TABLE").upper()
                    if kind_raw == "VIEW" and not include_views:
                        continue
                    if payload.scope.schemas is not None and schema not in {
                        normalize_identifier(item) for item in payload.scope.schemas
                    }:
                        continue
                    if payload.filters.name_pattern and payload.filters.name_pattern not in table:
                        continue
                    kind = AssetKind.VIEW if "VIEW" in kind_raw else AssetKind.TABLE
                    asset = AssetRef(
                        connector_id=self.spec.connector_id,
                        address=(db, schema, table),
                        kind=kind,
                        platform_type="snowflake",
                    )
                    if not self.spec.allow_list.contains_asset(asset):
                        continue
                    last_altered = row.get("LAST_ALTERED")
                    found.append(
                        CatalogAsset(
                            connector_id=self.spec.connector_id,
                            address=asset.address,
                            kind=kind,
                            platform_type="snowflake",
                            row_count_estimate=_as_int(row.get("ROW_COUNT")),
                            last_altered=_as_datetime(last_altered),
                            comment=None if row.get("COMMENT") is None else str(row["COMMENT"]),
                        )
                    )
            return tuple(found)

        assets = await self._session_call(context, run)
        return DiscoverAssetsOutput(assets=assets, snapshot_id=uuid4(), truncated=False)

    async def describe_asset(
        self, payload: DescribeAssetInput, context: CallContext
    ) -> DescribeAssetOutput:
        self._prepare_read(context)
        asset = require_asset_allowed(self.spec, payload.asset)
        if len(asset.address) != 3:
            raise SnowflakeMappedError(FailureClass.MISSING_OBJECT, "asset address incomplete")

        def run(session: SnowflakeSession) -> DescribeAssetOutput:
            db, schema, table = asset.address
            col_rel = qualify_parts((db, "INFORMATION_SCHEMA", "COLUMNS"))
            sql = (
                f"SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION, COMMENT "
                f"FROM {col_rel} WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                f"ORDER BY ORDINAL_POSITION"
            )
            _cols, rows, _qid = session.execute(sql, (schema, table))
            if not rows:
                raise SnowflakeMappedError(FailureClass.MISSING_OBJECT, "asset not found")
            columns = tuple(
                ColumnSpec(
                    name=str(row["COLUMN_NAME"]),
                    data_type=str(row["DATA_TYPE"]),
                    nullable=str(row.get("IS_NULLABLE") or "").upper() in {"Y", "YES"},
                    ordinal=int(row["ORDINAL_POSITION"]),
                    comment=None,
                    is_untrusted_text=True,
                )
                for row in rows
            )
            row_count = None
            if payload.include_row_count:
                _c2, count_rows, _ = session.execute(row_count_sql(asset.address))
                row_count = _as_int(count_rows[0].get("ROW_COUNT")) if count_rows else None
            primary_key = None
            if payload.include_constraints:
                primary_key = _primary_key(session, asset)
            return DescribeAssetOutput(
                asset=asset,
                columns=columns,
                primary_key=primary_key,
                row_count=row_count,
                snapshot_id=uuid4(),
            )

        return await self._session_call(context, run)

    async def detect_schema_drift(
        self, payload: DetectSchemaDriftInput, context: CallContext
    ) -> DetectSchemaDriftOutput:
        described = await self.describe_asset(
            DescribeAssetInput(
                asset=payload.asset, include_constraints=False, include_row_count=False
            ),
            context,
        )
        if payload.baseline_columns is None:
            raise SnowflakeMappedError(
                FailureClass.MISSING_OBJECT,
                "baseline snapshot columns are not available to the connector",
            )
        return compare_columns(described.columns, payload.baseline_columns)

    async def profile_dataset(
        self, payload: ProfileDatasetInput, context: CallContext
    ) -> ProfileDatasetOutput:
        self._prepare_read(context)
        asset = require_asset_allowed(self.spec, payload.asset)
        described = await self.describe_asset(
            DescribeAssetInput(asset=asset, include_constraints=False, include_row_count=True),
            context,
        )
        selected = payload.columns or tuple(col.name for col in described.columns)
        type_by_name = {col.name: col.data_type for col in described.columns}

        def run(session: SnowflakeSession) -> ProfileDatasetOutput:
            _c, count_rows, _ = session.execute(row_count_sql(asset.address))
            row_count = _as_int(count_rows[0].get("ROW_COUNT")) if count_rows else 0
            row_count = row_count or 0
            profile_columns: list[ProfileColumn] = []
            candidate_keys: list[CandidateKey] = []
            for name in selected:
                data_type = type_by_name.get(name, "VARCHAR")
                numeric = (
                    "NUMBER" in data_type.upper()
                    or "FLOAT" in data_type.upper()
                    or "INT" in data_type.upper()
                )
                _c2, stats_rows, _ = session.execute(
                    column_profile_sql(asset.address, name, numeric=numeric)
                )
                stats = stats_rows[0] if stats_rows else {}
                null_count = _as_int(stats.get("NULL_COUNT")) or 0
                distinct_count = _as_int(stats.get("DISTINCT_COUNT")) or 0
                den = max(row_count, 1)
                _c3, top_rows, _ = session.execute(
                    top_values_sql(asset.address, name, top_k=payload.top_k)
                )
                sensitive = column_is_sensitive(name)
                top_values = tuple(
                    TopValue(
                        value_masked=mask_value(item.get("VALUE"))
                        if sensitive
                        else _as_str(item.get("VALUE")),
                        count=int(item.get("VALUE_COUNT") or 0),
                    )
                    for item in top_rows
                )
                uniqueness = distinct_count / den
                profile_columns.append(
                    ProfileColumn(
                        name=name,
                        null_ratio=null_count / den,
                        distinct_ratio=uniqueness,
                        min=stats.get("MIN_VALUE"),
                        max=stats.get("MAX_VALUE"),
                        mean=_as_float(stats.get("MEAN_VALUE")),
                        top_values=top_values,
                        inferred_semantic=infer_semantic(name, data_type),  # type: ignore[arg-type]
                    )
                )
                if uniqueness >= 0.99 and null_count == 0:
                    candidate_keys.append(
                        CandidateKey(columns=(name,), uniqueness_ratio=uniqueness)
                    )
            sampled = payload.sample_fraction is not None and payload.sample_fraction < 1
            return ProfileDatasetOutput(
                asset=asset,
                row_count=row_count,
                sampled=sampled,
                columns=tuple(profile_columns),
                candidate_keys=tuple(candidate_keys),
                duplicate_groups_estimate=0,
                profile_id=uuid4(),
            )

        return await self._session_call(context, run)

    async def sample_dataset(
        self, payload: SampleDatasetInput, context: CallContext
    ) -> SampleDatasetOutput:
        self._prepare_read(context)
        asset = require_asset_allowed(self.spec, payload.asset)
        if payload.where is not None:
            classification = payload.where.classification
            if (
                classification is None
                or not classification.is_read_only
                or classification.is_multi_statement
            ):
                raise SnowflakeMappedError(
                    FailureClass.UNSAFE_OPERATION,
                    "sample where clause must be a classified read-only statement",
                )
        where_sql = payload.where.text if payload.where is not None else None
        sql = sample_sql(asset.address, payload.columns, payload.n, where_sql)

        def run(session: SnowflakeSession) -> SampleDatasetOutput:
            _cols, rows, _qid = session.execute(sql)
            sensitive = {key for row in rows for key in row if column_is_sensitive(key)}
            masked_rows = tuple(mask_row(row, sensitive=sensitive) for row in rows)
            return SampleDatasetOutput(
                rows=masked_rows,
                masked_columns=tuple(sorted(sensitive)),
                sample_id=uuid4(),
            )

        return await self._session_call(context, run)

    async def infer_relationships(
        self, payload: InferRelationshipsInput, context: CallContext
    ) -> InferRelationshipsOutput:
        self._prepare_read(context)
        assets = [require_asset_allowed(self.spec, item) for item in payload.assets]
        described: list[DescribeAssetOutput] = []
        for asset in assets:
            described.append(
                await self.describe_asset(
                    DescribeAssetInput(
                        asset=asset, include_constraints=False, include_row_count=False
                    ),
                    context,
                )
            )

        def run(session: SnowflakeSession) -> InferRelationshipsOutput:
            candidates: list[RelationshipCandidate] = []
            pairs = 0
            for left in described:
                for right in described:
                    if left.asset.address == right.asset.address:
                        continue
                    for left_col in left.columns:
                        for right_col in right.columns:
                            if pairs >= payload.max_pairs:
                                break
                            left_sem = infer_semantic(left_col.name, left_col.data_type)
                            right_sem = infer_semantic(right_col.name, right_col.data_type)
                            if left_sem not in {"ID", "CODE"} or right_sem not in {"ID", "CODE"}:
                                continue
                            if left_col.data_type != right_col.data_type:
                                continue
                            sql = inclusion_sql(
                                left.asset.address,
                                left_col.name,
                                right.asset.address,
                                right_col.name,
                            )
                            _c, rows, _ = session.execute(sql)
                            stats = rows[0] if rows else {}
                            child_distinct = _as_int(stats.get("CHILD_DISTINCT")) or 0
                            missing = _as_int(stats.get("MISSING_IN_PARENT")) or 0
                            if child_distinct == 0:
                                continue
                            inclusion = max(0.0, (child_distinct - missing) / child_distinct)
                            if inclusion < 0.5:
                                continue
                            cardinality: str = "N:M"
                            if inclusion >= 0.99:
                                cardinality = "1:N"
                            candidates.append(
                                RelationshipCandidate(
                                    from_asset=left.asset,
                                    from_columns=(left_col.name,),
                                    to_asset=right.asset,
                                    to_columns=(right_col.name,),
                                    inclusion_ratio=inclusion,
                                    cardinality=cardinality,  # type: ignore[arg-type]
                                    confidence=round(inclusion, 4),
                                )
                            )
                            pairs += 1
            return InferRelationshipsOutput(candidates=tuple(candidates), relationships_id=uuid4())

        return await self._session_call(context, run)

    async def validate_query(
        self, payload: ValidateQueryInput, context: CallContext
    ) -> ValidateQueryOutput:
        self._prepare_read(context)
        sql = payload.sql.text
        try:
            kind = statement_type(sql)
            if kind not in {"SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "CREATE"}:
                return ValidateQueryOutput(
                    valid=False,
                    error=QueryError(
                        code="UNSAFE_OPERATION",
                        message="statement is not explainable as a read or DEV create",
                    ),
                )
            for asset in referenced_tables(sql, connector_id=self.spec.connector_id):
                if len(asset.address) >= 3:
                    require_asset_allowed(self.spec, asset)

            def run(session: SnowflakeSession) -> ValidateQueryOutput:
                try:
                    _cols, rows, _qid = session.execute(explain_sql(sql))
                except SnowflakeMappedError as exc:
                    return ValidateQueryOutput(
                        valid=False,
                        error=QueryError(code=exc.failure.value, message=str(exc)),
                    )
                estimated = None
                if rows:
                    estimated = _as_int(next(iter(rows[0].values()), None))
                return ValidateQueryOutput(
                    valid=True,
                    plan_summary=PlanSummary(estimated_bytes=estimated),
                )

            return await self._session_call(context, run)
        except SnowflakeMappedError as exc:
            return ValidateQueryOutput(
                valid=False,
                error=QueryError(code=exc.failure.value, message=str(exc)),
            )

    async def execute_query(
        self, payload: ExecuteQueryInput, context: CallContext
    ) -> ExecuteQueryOutput:
        self._prepare_read(context)
        if not is_read_statement(payload.sql.text):
            raise SnowflakeMappedError(
                FailureClass.UNSAFE_OPERATION, "execute_query requires a read statement"
            )
        for asset in referenced_tables(payload.sql.text, connector_id=self.spec.connector_id):
            if len(asset.address) >= 3:
                require_asset_allowed(self.spec, asset)
        query_tag = canonical_query_tag(context)
        started = datetime.now(UTC)
        sql = payload.sql.text
        if payload.result_mode == "ROWS" and " LIMIT " not in sql.upper():
            sql = f"{sql.rstrip(';')} LIMIT {payload.budget.max_rows}"

        def run(session: SnowflakeSession) -> ExecuteQueryOutput:
            columns, rows, query_id = session.execute(sql)
            duration = int((datetime.now(UTC) - started).total_seconds() * 1000)
            limited = rows[: payload.budget.max_rows]
            return ExecuteQueryOutput(
                rows=tuple(limited) if payload.result_mode == "ROWS" else None,
                scalar=(
                    next(iter(limited[0].values()))
                    if payload.result_mode == "SCALAR" and limited
                    else None
                ),
                row_count=len(rows),
                bytes_scanned=None,
                duration_ms=max(duration, 1),
                query_id=query_id,
                query_tag=query_tag,
                truncated=len(rows) > payload.budget.max_rows,
            )

        return await self._session_call(context, run)

    async def get_execution_metrics(
        self, payload: MetricsQueryInput, context: CallContext
    ) -> GetExecutionMetricsOutput:
        self._prepare_read(context)
        parse_query_tag(payload.query_tag)

        def run(session: SnowflakeSession) -> GetExecutionMetricsOutput:
            try:
                _cols, rows, _qid = session.execute(
                    "SELECT QUERY_ID, TOTAL_ELAPSED_TIME, BYTES_SCANNED, ROWS_PRODUCED, "
                    f"WAREHOUSE_NAME FROM {_QUERY_HISTORY} WHERE QUERY_TAG = %s",
                    (payload.query_tag,),
                )
            except SnowflakeMappedError:
                return GetExecutionMetricsOutput(
                    queries=(),
                    as_of=datetime.now(UTC).replace(tzinfo=None),
                    complete=False,
                )
            queries = tuple(
                QueryMetric(
                    query_id=str(row.get("QUERY_ID")),
                    duration_ms=int(row.get("TOTAL_ELAPSED_TIME") or 0),
                    bytes_scanned=_as_int(row.get("BYTES_SCANNED")),
                    rows_produced=_as_int(row.get("ROWS_PRODUCED")),
                    partitions_scanned=_as_int(row.get("PARTITIONS_SCANNED")),
                    partitions_total=_as_int(row.get("PARTITIONS_TOTAL")),
                    spilled_bytes=_as_int(row.get("BYTES_SPILLED_TO_LOCAL_STORAGE")),
                    warehouse=_as_str(row.get("WAREHOUSE_NAME")),
                )
                for row in rows
                if row.get("QUERY_ID")
            )
            return GetExecutionMetricsOutput(
                queries=queries,
                as_of=datetime.now(UTC).replace(tzinfo=None),
                complete=True,
            )

        return await self._session_call(context, run)

    async def get_cost_metrics(
        self, payload: MetricsQueryInput, context: CallContext
    ) -> GetCostMetricsOutput:
        self._prepare_read(context)
        parse_query_tag(payload.query_tag)
        metrics = await self.get_execution_metrics(payload, context)
        credits = 0.0
        for item in metrics.queries:
            credits += max(item.duration_ms, 1) / 3_600_000
        return GetCostMetricsOutput(
            credits_used=credits,
            estimated_cost=credits,
            currency="USD",
            breakdown_by_task=(
                TaskCostBreakdown(task_id=str(context.task_id), credits_used=credits),
            ),
            as_of=datetime.now(UTC).replace(tzinfo=None),
            complete=False,
        )

    async def evaluate_execution_policy(
        self, payload: EvaluateExecutionPolicyInput, context: CallContext
    ) -> EvaluateExecutionPolicyOutput:
        self._prepare_read(context)
        del payload
        return EvaluateExecutionPolicyOutput(decision="ALLOW", routing="EXECUTE", reasons=())

    async def profile_estate(
        self, payload: ProfileEstateInput, context: CallContext
    ) -> ProfileEstateOutput:
        self._prepare_read(context)
        from aide.profiling.engine import profile_selected_assets

        run = await profile_selected_assets(
            self, payload.assets, fixture_version=payload.fixture_version
        )
        return ProfileEstateOutput(
            fixture_version=run.fixture_version,
            duration_seconds=run.duration_seconds,
            profile_count=len(run.profiles),
            relationship_count=len(run.relationships),
            relationships_id=run.relationships_id,
            run_payload=run.model_dump(mode="json"),
        )

    async def load_manifest_sources(
        self, payload: LoadManifestSourcesInput, context: CallContext
    ) -> LoadManifestSourcesOutput:
        self._prepare_write(context)
        import csv

        from aide.connectors.snowflake.manifest import (
            csv_path_for,
            schema_sha256,
            verify_pinned_manifest,
            workflow_source_address,
        )
        from aide.connectors.snowflake.namespace import require_dev_namespace
        from aide.connectors.snowflake.sql_templates import qualified_table
        from aide.domain.sql import AssetKind, AssetRef

        digest = verify_pinned_manifest(payload.manifest_sha256)

        def run(session: SnowflakeSession) -> LoadManifestSourcesOutput:
            loaded: list[LoadedSourceTable] = []
            for source in payload.selected_addresses:
                target = workflow_source_address(context.workflow_id, source)
                require_dev_namespace(
                    AssetRef(
                        connector_id="snowflake_dev",
                        address=target,
                        kind=AssetKind.TABLE,
                        platform_type="snowflake",
                    ),
                    context.workflow_id,
                )
                csv_file = csv_path_for(source, payload.fixture_version)
                with csv_file.open(newline="", encoding="utf-8") as handle:
                    reader = csv.reader(handle)
                    header = next(reader)
                    rows = [tuple(item) for item in reader]
                db, schema, table = target
                session.execute(f"CREATE SCHEMA IF NOT EXISTS {qualify_parts((db, schema))}")
                col_sql = ", ".join(f'"{col}" VARCHAR' for col in header)
                qualified = qualified_table(target)
                session.execute(f"CREATE OR REPLACE TABLE {qualified} ({col_sql})")
                if rows:
                    placeholders = "(" + ", ".join(["%s"] * len(header)) + ")"
                    insert_sql = f"INSERT INTO {qualified} VALUES " + ", ".join(
                        placeholders for _ in rows
                    )
                    flattened = [value for row in rows for value in row]
                    session.execute(insert_sql, tuple(flattened))
                loaded.append(
                    LoadedSourceTable(
                        address=target,
                        schema_name=schema,
                        row_count=len(rows),
                        schema_sha256=schema_sha256(tuple(header)),
                    )
                )
            return LoadManifestSourcesOutput(
                fixture_digest=digest,
                target_database="AIDE_DEV",
                tables=tuple(loaded),
                reconcile_ok=True,
            )

        return await self._session_call(context, run)

    async def create_dataset(
        self, payload: CreateDatasetInput, context: CallContext
    ) -> CreateDatasetOutput:
        self._prepare_write(context)
        target = require_asset_allowed(self.spec, payload.target)
        require_dev_namespace(target, context.workflow_id)
        if statement_type(payload.definition.text) != "CREATE":
            raise SnowflakeMappedError(
                FailureClass.UNSAFE_OPERATION, "create_dataset requires CREATE SQL"
            )
        comment = provenance_comment(
            workflow_id=context.workflow_id,
            operation_idempotency_key=context.operation_idempotency_key,
        )

        def run(session: SnowflakeSession) -> CreateDatasetOutput:
            db, schema, table = target.address
            session.execute(f"CREATE SCHEMA IF NOT EXISTS {qualify_parts((db, schema))}")
            existing = _table_comment(session, target)
            if existing is not None and not payload.replace:
                raise SnowflakeMappedError(FailureClass.SCHEMA_MISMATCH, "target already exists")
            if existing is not None and payload.replace:
                session.execute(f"DROP TABLE IF EXISTS {qualified_table(target.address)}")
            session.execute(payload.definition.text)
            session.execute(
                f"ALTER TABLE {qualified_table(target.address)} SET COMMENT = %s",
                (comment,),
            )
            row_count = None
            try:
                _c, count_rows, _ = session.execute(row_count_sql(target.address))
                row_count = _as_int(count_rows[0].get("ROW_COUNT")) if count_rows else None
            except SnowflakeMappedError:
                row_count = None
            return CreateDatasetOutput(
                created=target,
                replaced_existing=existing is not None,
                row_count=row_count,
            )

        return await self._session_call(context, run)

    async def drop_dataset(
        self, payload: DropDatasetInput, context: CallContext
    ) -> DropDatasetOutput:
        self._prepare_write(context)
        target = require_asset_allowed(self.spec, payload.target)
        require_dev_namespace(target, context.workflow_id)

        def run(session: SnowflakeSession) -> DropDatasetOutput:
            comment = _table_comment(session, target)
            if comment is None:
                raise SnowflakeMappedError(FailureClass.MISSING_OBJECT, "dataset does not exist")
            if (
                str(payload.created_by_workflow) not in comment
                and str(context.workflow_id) not in comment
            ):
                raise SnowflakeMappedError(
                    FailureClass.UNSAFE_OPERATION,
                    "dataset provenance does not match the creating workflow",
                )
            session.execute(f"DROP TABLE IF EXISTS {qualified_table(target.address)}")
            return DropDatasetOutput(dropped=True)

        return await self._session_call(context, run)

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown:
        missing = missing_secret_names(self._settings)
        if missing:
            return Unknown(
                reason="SECRET_UNRESOLVED:" + missing[0],
                evidence="credentials unavailable; not inferred as success",
            )
        try:
            return await self._with_session(
                query_tag="aide:v1;reconcile",
                timeout_seconds=30,
                fn=lambda session: _reconcile_blocking(session, recovery),
            )
        except SnowflakeMappedError as exc:
            return Unknown(reason=exc.failure.value, evidence=str(exc))
        except Exception as exc:
            return Unknown(reason=map_error(exc).value, evidence=sanitize_error_message(str(exc)))

    def _prepare_read(self, context: CallContext) -> None:
        require_read_identity(self.spec)
        self._require_credentials()
        statement_timeout_seconds(context)

    def _prepare_write(self, context: CallContext) -> None:
        require_write_identity(self.spec)
        self._require_credentials()
        statement_timeout_seconds(context)

    def _require_credentials(self) -> None:
        missing = missing_secret_names(self._settings)
        if missing:
            raise SnowflakeMappedError(
                FailureClass.CONNECTOR_FAILURE,
                f"SECRET_UNRESOLVED:{missing[0]}",
            )

    async def _session_call(self, context: CallContext, fn: Callable[[SnowflakeSession], T]) -> T:
        timeout = statement_timeout_seconds(context)
        tag = canonical_query_tag(context)
        return await self._with_session(query_tag=tag, timeout_seconds=timeout, fn=fn)

    async def _with_session(
        self,
        *,
        query_tag: str,
        timeout_seconds: int,
        fn: Callable[[SnowflakeSession], T],
    ) -> T:
        if self._run_session is not None:
            return cast(
                T,
                await self._run_session(
                    query_tag=query_tag, timeout_seconds=timeout_seconds, fn=fn
                ),
            )
        settings = self._settings
        resolver = self._resolver

        def run() -> T:
            try:
                account = resolver.resolve(settings.account)
                user = resolver.resolve(settings.user)
                private_key = resolver.resolve(settings.private_key)
                warehouse = resolver.resolve(settings.warehouse)
                passphrase: SecretStr | None = None
                if settings.passphrase is not None:
                    passphrase = resolver.resolve(settings.passphrase)
            except UnresolvedSecretError as exc:
                raise SnowflakeMappedError(
                    FailureClass.CONNECTOR_FAILURE,
                    f"SECRET_UNRESOLVED:{exc.args[0] if exc.args else 'UNKNOWN'}",
                ) from exc
            session = SnowflakeSession(
                settings,
                account=account,
                user=user,
                private_key=private_key,
                warehouse=warehouse,
                passphrase=passphrase,
                query_tag=query_tag,
                timeout_seconds=timeout_seconds,
            )
            try:
                return fn(session)
            finally:
                session.close()

        return await asyncio.to_thread(run)


def _primary_key(session: SnowflakeSession, asset: AssetRef) -> tuple[str, ...] | None:
    db, schema, table = asset.address
    cons = qualify_parts((db, "INFORMATION_SCHEMA", "TABLE_CONSTRAINTS"))
    usage = qualify_parts((db, "INFORMATION_SCHEMA", "KEY_COLUMN_USAGE"))
    sql = (
        f"SELECT k.COLUMN_NAME FROM {cons} c "
        f"JOIN {usage} k ON c.CONSTRAINT_NAME = k.CONSTRAINT_NAME "
        f"AND c.TABLE_SCHEMA = k.TABLE_SCHEMA AND c.TABLE_NAME = k.TABLE_NAME "
        f"WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s AND c.CONSTRAINT_TYPE = 'PRIMARY KEY' "
        f"ORDER BY k.ORDINAL_POSITION"
    )
    try:
        _cols, rows, _ = session.execute(sql, (schema, table))
    except SnowflakeMappedError:
        return None
    names = tuple(str(row["COLUMN_NAME"]) for row in rows if row.get("COLUMN_NAME"))
    return names or None


def _table_comment(session: SnowflakeSession, asset: AssetRef) -> str | None:
    db, schema, table = asset.address
    rel = qualify_parts((db, "INFORMATION_SCHEMA", "TABLES"))
    sql = f"SELECT COMMENT FROM {rel} WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s"
    try:
        _cols, rows, _ = session.execute(sql, (schema, table))
    except SnowflakeMappedError:
        return None
    if not rows:
        return None
    comment = rows[0].get("COMMENT")
    return None if comment is None else str(comment)


def _history_row(session: SnowflakeSession, query_id: str) -> dict[str, Any] | None:
    sql = (
        "SELECT QUERY_ID, EXECUTION_STATUS, ERROR_CODE, BYTES_SCANNED, ROWS_PRODUCED, "
        "TOTAL_ELAPSED_TIME, QUERY_TAG, WAREHOUSE_NAME "
        f"FROM {_QUERY_HISTORY} WHERE QUERY_ID = %s"
    )
    _cols, rows, _ = session.execute(sql, (query_id,))
    return rows[0] if rows else None


def _history_by_tag(session: SnowflakeSession, query_tag: str) -> list[dict[str, Any]]:
    sql = (
        "SELECT QUERY_ID, EXECUTION_STATUS, ERROR_CODE, BYTES_SCANNED, ROWS_PRODUCED, "
        "TOTAL_ELAPSED_TIME, QUERY_TAG, WAREHOUSE_NAME "
        f"FROM {_QUERY_HISTORY} WHERE QUERY_TAG = %s"
    )
    _cols, rows, _ = session.execute(sql, (query_tag,))
    return rows


def _status(row: dict[str, Any]) -> str:
    return str(row.get("EXECUTION_STATUS") or "").upper()


def _effect_from_history(row: dict[str, Any], recovery: RecoveryContext) -> EffectFound | Unknown:
    status = _status(row)
    if status not in _SUCCESS_STATUSES:
        return Unknown(reason="query completed without authoritative success", evidence=status)
    duration = int(row.get("TOTAL_ELAPSED_TIME") or 0)
    output = ExecuteQueryOutput(
        rows=None,
        scalar=None,
        row_count=_as_int(row.get("ROWS_PRODUCED")) or 0,
        bytes_scanned=_as_int(row.get("BYTES_SCANNED")),
        duration_ms=max(duration, 1),
        query_id=str(row.get("QUERY_ID")),
        query_tag=str(row.get("QUERY_TAG") or ""),
        truncated=False,
    )
    capability_id = recovery.capability.capability_id
    if capability_id == "create_dataset":
        target = _target_from_locator(recovery)
        if target is None:
            return Unknown(reason="create_dataset reconcile lacks target in operation_locator")
        dumped = CreateDatasetOutput(
            created=target, replaced_existing=False, row_count=None
        ).model_dump(mode="json")
        return EffectFound(output=dumped, external_ref=str(row.get("QUERY_ID")))
    if capability_id == "drop_dataset":
        dumped = DropDatasetOutput(dropped=True).model_dump(mode="json")
        return EffectFound(output=dumped, external_ref=str(row.get("QUERY_ID")))
    return EffectFound(output=output.model_dump(mode="json"), external_ref=str(row.get("QUERY_ID")))


def _target_from_locator(recovery: RecoveryContext) -> AssetRef | None:
    raw = recovery.operation_locator.get("target")
    if not raw:
        return None
    parts = tuple(part for part in raw.split(".") if part)
    if len(parts) < 2:
        return None
    return AssetRef(
        connector_id=recovery.connector_id,
        address=tuple(normalize_identifier(part) for part in parts),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )


def _reconcile_blocking(
    session: SnowflakeSession, recovery: RecoveryContext
) -> EffectFound | NoEffect | InProgress | Unknown:
    for attempt in recovery.attempts:
        if not attempt.query_id:
            continue
        try:
            row = _history_row(session, attempt.query_id)
        except SnowflakeMappedError as exc:
            return Unknown(reason=exc.failure.value, evidence="query_id lookup failed")
        if row is None:
            return Unknown(reason="persisted query id not found in history")
        return _classify_history_row(session, row, recovery)
    tag = recovery.operation_locator.get("query_tag")
    if tag:
        try:
            parsed = parse_query_tag(tag)
        except ValueError:
            return Unknown(reason="query tag could not be parsed")
        if parsed.operation_idempotency_key != recovery.operation_idempotency_key:
            return Unknown(reason="query tag operation identity mismatch")
        try:
            rows = _history_by_tag(session, tag)
        except SnowflakeMappedError as exc:
            return Unknown(reason=exc.failure.value, evidence="query tag lookup failed")
        if not rows:
            return NoEffect(evidence="no QUERY_HISTORY row for canonical query tag")
        return _classify_history_row(session, rows[0], recovery)
    return _reconcile_object_state(session, recovery)


def _classify_history_row(
    session: SnowflakeSession, row: dict[str, Any], recovery: RecoveryContext
) -> EffectFound | NoEffect | InProgress | Unknown:
    status = _status(row)
    if status in _RUNNING_STATUSES:
        query_id = str(row.get("QUERY_ID") or "unknown")
        return InProgress(external_ref=query_id, retry_after_seconds=5)
    if status in _FAILED_STATUSES:
        if recovery.capability.capability_id in {"create_dataset", "drop_dataset"}:
            return _reconcile_object_state(session, recovery)
        return NoEffect(evidence=f"query {status}")
    if status in _SUCCESS_STATUSES:
        if recovery.capability.capability_id in {"create_dataset", "drop_dataset"}:
            object_result = _reconcile_object_state(session, recovery)
            if isinstance(object_result, (EffectFound, NoEffect, InProgress, Unknown)):
                if isinstance(object_result, Unknown):
                    return object_result
                return object_result
        return _effect_from_history(row, recovery)
    return Unknown(reason="ambiguous execution status", evidence=status or None)


def _reconcile_object_state(
    session: SnowflakeSession, recovery: RecoveryContext
) -> EffectFound | NoEffect | InProgress | Unknown:
    capability_id = recovery.capability.capability_id
    target = _target_from_locator(recovery)
    if capability_id not in {"create_dataset", "drop_dataset"}:
        return NoEffect(evidence="no persisted query id or canonical query tag")
    if target is None:
        return Unknown(reason="write reconcile requires target in operation_locator")
    comment = _table_comment(session, target)
    if capability_id == "drop_dataset":
        if comment is None:
            return EffectFound(
                output=DropDatasetOutput(dropped=True).model_dump(mode="json"), external_ref=None
            )
        return Unknown(reason="drop target still exists", evidence="object still present")
    if comment is None:
        return NoEffect(evidence="create target does not exist")
    if recovery.operation_idempotency_key not in comment:
        return Unknown(reason="object exists but provenance does not match operation")
    dumped = CreateDatasetOutput(
        created=target, replaced_existing=False, row_count=None
    ).model_dump(mode="json")
    return EffectFound(output=dumped, external_ref=None)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is None else value.astimezone(UTC).replace(tzinfo=None)
    return None


def build_real_pair() -> tuple[RealSnowflakeConnector, RealSnowflakeConnector]:
    return (
        RealSnowflakeConnector(SNOWFLAKE_RO),
        RealSnowflakeConnector(SNOWFLAKE_DEV),
    )
