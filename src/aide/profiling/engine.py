"""Deterministic PROFILING engine using accepted warehouse capability contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from aide.capabilities.io import (
    CandidateKey,
    DescribeAssetInput,
    ExecuteQueryInput,
    InferRelationshipsInput,
    ProfileColumn,
    ProfileDatasetInput,
    RelationshipCandidate,
    SampleDatasetInput,
)
from aide.connectors.base.context import CallContext, RedactionPolicy
from aide.domain.identity import canonical_json_bytes
from aide.domain.sql import AssetRef, SqlText
from aide.profiling.artifacts import (
    BudgetUsage,
    DatasetProfileArtifact,
    DuplicateEvidence,
    KeyEvidence,
    MaskingState,
    NumericRange,
    ProfilingFact,
    ProfilingRunResult,
    ProfilingSummary,
    RelationshipEvidence,
    SampleArtifact,
)
from aide.profiling.budgets import (
    TINY_OFFLINE_BUDGET,
    BudgetTracker,
    ProfilingBudget,
    ProfilingBudgetExceeded,
)
from aide.profiling.fixtures import grain_columns, load_pii_columns
from aide.profiling.join_candidates import INCLUSION_FLOOR, select_join_candidates_for_measurement
from aide.profiling.masking import (
    column_is_sensitive,
    jsonable,
    looks_like_raw_email,
    looks_like_raw_phone,
    mask_profile_columns,
    mask_row,
)
from aide.profiling.sql_templates import (
    composite_uniqueness_sql,
    duplicate_group_sql,
    inclusion_sql,
    normalized_domain_sql,
    numeric_range_sql,
)
from aide.profiling.warehouse import WarehouseReadPort, upper_row

PROFILE_NAMESPACE = UUID("6ba7b810-9dad-11d1-80b4-00000000de06")
CANDIDATE_UNIQUENESS = 0.99


def _stable_uuid(*parts: str) -> UUID:
    return uuid5(PROFILE_NAMESPACE, "|".join(parts))


def _make_context() -> CallContext:
    """Offline fallback deadline. Live profile_estate passes the gateway context."""
    now = datetime.now(UTC)
    return CallContext(
        workflow_id=uuid4(),
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key="a" * 64,
        resolved_input_digest="b" * 64,
        contract_snapshot_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        claim_epoch=1,
        cancellation_epoch=0,
        deadline=now + timedelta(seconds=120),
        external_correlation="profiling",
        redaction=RedactionPolicy(),
    )


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _contains_raw_pii(payload: object, path: str = "$") -> str | None:
    if isinstance(payload, dict):
        for key, item in payload.items():
            found = _contains_raw_pii(item, f"{path}.{key}")
            if found is not None:
                return found
        return None
    if isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            found = _contains_raw_pii(item, f"{path}[{index}]")
            if found is not None:
                return found
        return None
    if looks_like_raw_email(payload) or looks_like_raw_phone(payload):
        return path
    return None


def sample_assets_for(
    selected: tuple[AssetRef, ...],
    *,
    limit: int,
    priority: tuple[tuple[str, ...], ...] = (),
) -> tuple[AssetRef, ...]:
    if limit <= 0:
        return ()
    selected_keys = {asset.address for asset in selected}
    ordered: list[AssetRef] = []
    by_address = {asset.address: asset for asset in selected}
    for address in priority:
        if address in selected_keys:
            ordered.append(by_address[address])
        if len(ordered) >= limit:
            return tuple(ordered)
    for asset in selected:
        if asset.address not in {item.address for item in ordered}:
            ordered.append(asset)
        if len(ordered) >= limit:
            break
    return tuple(ordered)


class ProfilingEngine:
    def __init__(
        self,
        warehouse: WarehouseReadPort,
        *,
        fixture_version: str,
        budget: ProfilingBudget | None = None,
        connector_id: str = "snowflake_ro",
        context: CallContext | None = None,
        excluded_addresses: tuple[tuple[str, ...], ...] = (),
        sample_priority: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        self._warehouse = warehouse
        self._fixture_version = fixture_version
        self._budget = budget or TINY_OFFLINE_BUDGET
        self._connector_id = connector_id
        self._context = context or _make_context()
        self._tracker = BudgetTracker(self._budget)
        self._pii_columns = load_pii_columns()
        self._call_seq = 0
        self._excluded_addresses = excluded_addresses
        self._sample_priority = sample_priority

    async def run(self, selected: tuple[AssetRef, ...]) -> ProfilingRunResult:
        assets = tuple(sorted(selected, key=lambda item: item.address))
        profiles: list[DatasetProfileArtifact] = []
        for asset in assets:
            profiles.append(await self._profile_asset(asset))
        relationships = await self._infer_relationships(assets, tuple(profiles))
        sample_pool = sample_assets_for(
            assets, limit=self._budget.sample_asset_limit, priority=self._sample_priority
        )
        samples = await self._sample_assets(sample_pool)
        facts = _facts(self._fixture_version, tuple(profiles), tuple(relationships))
        masking = MaskingState(
            pii_columns=tuple(sorted(self._pii_columns)),
            samples_masked=True,
            top_values_masked=True,
            raw_pii_persisted=False,
        )
        usage = self._tracker.usage()
        summary = ProfilingSummary(
            fixture_version=self._fixture_version,
            connector_id=self._connector_id,
            assets=assets,
            excluded_addresses=self._excluded_addresses,
            facts=facts,
            relationship_count=len(relationships),
            sample_asset_count=len(samples),
            budget=BudgetUsage(
                queries=int(usage["queries"]),
                pairs=int(usage["pairs"]),
                elapsed_seconds=float(usage["elapsed_seconds"]),
                max_queries=int(usage["max_queries"]),
                max_pairs=int(usage["max_pairs"]),
                max_seconds=int(usage["max_seconds"]),
                sample_n=int(usage["sample_n"]),
            ),
            masking_applied=True,
        )
        result = ProfilingRunResult(
            fixture_version=self._fixture_version,
            duration_seconds=float(usage["elapsed_seconds"]),
            profiles=tuple(profiles),
            relationships=tuple(relationships),
            samples=tuple(samples),
            summary=summary,
            relationships_id=_stable_uuid(
                self._fixture_version,
                "relationships",
                canonical_json_bytes(
                    [
                        {
                            "from": list(item.candidate.from_asset.address),
                            "from_columns": list(item.candidate.from_columns),
                            "to": list(item.candidate.to_asset.address),
                            "to_columns": list(item.candidate.to_columns),
                            "inclusion": item.candidate.inclusion_ratio,
                        }
                        for item in relationships
                    ]
                ).decode("utf-8"),
            ),
            masking=masking,
        )
        dumped = json.loads(result.model_dump_json())
        leaked = _contains_raw_pii(dumped)
        if leaked is not None:
            raise ProfilingBudgetExceeded(f"raw PII leaked into profiling artifacts at {leaked}")
        return result

    def _call_context(self) -> CallContext:
        self._call_seq += 1
        seed = f"{self._fixture_version}:{self._call_seq}"
        digest = hashlib.sha256(seed.encode()).hexdigest()
        return self._context.model_copy(
            update={
                "task_id": uuid5(PROFILE_NAMESPACE, seed),
                "attempt_id": uuid5(PROFILE_NAMESPACE, f"{seed}:attempt"),
                "operation_idempotency_key": digest,
                "resolved_input_digest": hashlib.sha256(f"{seed}:in".encode()).hexdigest(),
            }
        )

    async def _scalar(self, sql: str) -> dict[str, Any]:
        self._tracker.charge_query()
        output = await self._warehouse.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text=sql),
                budget=self._budget.capability_budget(),
                result_mode="ROWS",
            ),
            self._call_context(),
        )
        if not output.rows:
            return {}
        return upper_row(output.rows[0])

    async def _profile_asset(self, asset: AssetRef) -> DatasetProfileArtifact:
        self._tracker.charge_query()
        described = await self._warehouse.describe_asset(
            DescribeAssetInput(asset=asset, include_constraints=True, include_row_count=True),
            self._call_context(),
        )
        self._tracker.charge_query()
        profiled = await self._warehouse.profile_dataset(
            ProfileDatasetInput(
                asset=asset,
                budget=self._budget.capability_budget(),
                top_k=self._budget.top_k,
            ),
            self._call_context(),
        )
        columns = mask_profile_columns(profiled.columns, pii_columns=self._pii_columns)
        extras = await self._key_evidence(asset, columns)
        key_evidence, duplicate_evidence, extra_keys, extra_groups, ranges = extras
        candidate_keys = _advertised_candidate_keys(
            profiled.candidate_keys, extra_keys, key_evidence
        )
        duplicate_groups = max(profiled.duplicate_groups_estimate, extra_groups)
        artifact = DatasetProfileArtifact(
            fixture_version=self._fixture_version,
            asset=asset,
            profile_id=_stable_uuid(self._fixture_version, "profile", *asset.address),
            describe_snapshot_id=described.snapshot_id,
            capability_profile_id=profiled.profile_id,
            row_count=profiled.row_count,
            sampled=profiled.sampled,
            columns=columns,
            candidate_keys=candidate_keys,
            key_evidence=key_evidence,
            duplicate_evidence=duplicate_evidence,
            duplicate_groups_estimate=duplicate_groups,
            masking=MaskingState(
                pii_columns=tuple(sorted(self._pii_columns)),
                samples_masked=True,
                top_values_masked=True,
                raw_pii_persisted=False,
            ),
            numeric_ranges=ranges,
            column_types=tuple((spec.name, spec.data_type) for spec in described.columns),
        )
        return artifact

    async def _key_evidence(
        self, asset: AssetRef, columns: tuple[ProfileColumn, ...]
    ) -> tuple[
        tuple[KeyEvidence, ...],
        tuple[DuplicateEvidence, ...],
        tuple[CandidateKey, ...],
        int,
        tuple[NumericRange, ...],
    ]:
        by_name = {column.name.upper(): column for column in columns}
        evidence: list[KeyEvidence] = []
        duplicates: list[DuplicateEvidence] = []
        extra_keys: list[CandidateKey] = []
        extra_groups = 0
        ranges: list[NumericRange] = []
        amount_names = {
            "AMOUNT",
            "TOTAL_AMOUNT",
            "UNIT_PRICE",
            "MONTHLY_PRICE",
            "QUANTITY",
        }
        for column in columns:
            is_key = column.distinct_ratio >= CANDIDATE_UNIQUENESS and column.null_ratio == 0
            evidence.append(
                KeyEvidence(
                    columns=(column.name,),
                    uniqueness_ratio=column.distinct_ratio,
                    null_ratio=column.null_ratio,
                    expression=None,
                    is_candidate=is_key,
                    reason=(
                        "unique non-null column"
                        if is_key
                        else "column uniqueness below candidate-key threshold"
                    ),
                )
            )
            if column.mean is not None or column.inferred_semantic == "AMOUNT":
                ranges.append(
                    NumericRange(
                        column=column.name,
                        min_value=jsonable(column.min),
                        max_value=jsonable(column.max),
                        mean=column.mean,
                    )
                )
        grain = grain_columns(asset.address)
        if len(grain) >= 2 and all(name in by_name for name in grain):
            stats = await self._scalar(composite_uniqueness_sql(asset.address, grain))
            row_count = max(_as_int(stats.get("ROW_COUNT")), 1)
            distinct = _as_int(stats.get("DISTINCT_GROUPS"))
            uniqueness = distinct / row_count
            evidence.append(
                KeyEvidence(
                    columns=grain,
                    uniqueness_ratio=uniqueness,
                    null_ratio=0.0,
                    expression=",".join(grain),
                    is_candidate=uniqueness >= CANDIDATE_UNIQUENESS,
                    reason="declared source grain uniqueness",
                )
            )
            if uniqueness >= CANDIDATE_UNIQUENESS:
                extra_keys.append(CandidateKey(columns=grain, uniqueness_ratio=uniqueness))
        pair = ("INVOICE_ID", "PAYMENT_REF")
        if all(name in by_name for name in pair):
            stats = await self._scalar(composite_uniqueness_sql(asset.address, pair))
            row_count = max(_as_int(stats.get("ROW_COUNT")), 1)
            distinct = _as_int(stats.get("DISTINCT_GROUPS"))
            uniqueness = distinct / row_count
            extra_rows = max(row_count - distinct, 0)
            extra_groups = max(extra_groups, extra_rows)
            evidence.append(
                KeyEvidence(
                    columns=pair,
                    uniqueness_ratio=uniqueness,
                    null_ratio=0.0,
                    expression="INVOICE_ID,PAYMENT_REF",
                    is_candidate=uniqueness >= CANDIDATE_UNIQUENESS,
                    reason="business payment grain INVOICE_ID+PAYMENT_REF",
                )
            )
            if uniqueness >= CANDIDATE_UNIQUENESS:
                extra_keys.append(CandidateKey(columns=pair, uniqueness_ratio=uniqueness))
            duplicates.append(
                DuplicateEvidence(
                    columns=pair,
                    expression="INVOICE_ID,PAYMENT_REF",
                    duplicate_groups_estimate=extra_rows,
                    extra_row_estimate=extra_rows,
                    uniqueness_ratio=uniqueness,
                    reason="duplicate payment rows at INVOICE_ID+PAYMENT_REF"
                    if uniqueness < 1
                    else "pre-redelivery payment grain is unique",
                )
            )
        if "WEBSITE_DOMAIN" in by_name:
            stats = await self._scalar(normalized_domain_sql(asset.address, "WEBSITE_DOMAIN"))
            row_count = max(_as_int(stats.get("ROW_COUNT")), 1)
            distinct = _as_int(stats.get("DISTINCT_NORMALIZED"))
            null_count = _as_int(stats.get("NULL_COUNT"))
            uniqueness = distinct / row_count
            groups = await self._scalar(duplicate_group_sql(asset.address, "WEBSITE_DOMAIN"))
            domain_groups = _as_int(groups.get("GROUP_COUNT"))
            extra_groups = max(extra_groups, domain_groups)
            extra_rows = _as_int(groups.get("EXTRA_ROWS"))
            evidence.append(
                KeyEvidence(
                    columns=("WEBSITE_DOMAIN",),
                    uniqueness_ratio=uniqueness,
                    null_ratio=null_count / row_count,
                    expression="regexp_replace(lower(trim(WEBSITE_DOMAIN)), '^www.', '')",
                    is_candidate=uniqueness >= CANDIDATE_UNIQUENESS and null_count == 0,
                    reason="normalized website domain is not a unique account key"
                    if uniqueness < 1
                    else "normalized website domain is unique",
                )
            )
            duplicates.append(
                DuplicateEvidence(
                    columns=("WEBSITE_DOMAIN",),
                    expression="lower(trim(WEBSITE_DOMAIN)) without www prefix",
                    duplicate_groups_estimate=domain_groups,
                    extra_row_estimate=extra_rows,
                    uniqueness_ratio=uniqueness,
                    reason="duplicate CRM accounts share a normalized WEBSITE_DOMAIN",
                )
            )
        seen_ranges = {item.column for item in ranges}
        for column in columns:
            amountish = column.name.upper() in amount_names
            needs_range = column.inferred_semantic != "AMOUNT" and column.mean is None
            if not needs_range or not amountish or column.name in seen_ranges:
                continue
            stats = await self._scalar(numeric_range_sql(asset.address, column.name))
            ranges.append(
                NumericRange(
                    column=column.name,
                    min_value=jsonable(stats.get("MIN_VALUE")),
                    max_value=jsonable(stats.get("MAX_VALUE")),
                    mean=_as_float(stats.get("MEAN_VALUE")),
                )
            )
        return tuple(evidence), tuple(duplicates), tuple(extra_keys), extra_groups, tuple(ranges)

    async def _infer_relationships(
        self,
        assets: tuple[AssetRef, ...],
        profiles: tuple[DatasetProfileArtifact, ...],
    ) -> tuple[RelationshipEvidence, ...]:
        self._tracker.charge_query()
        await self._warehouse.infer_relationships(
            InferRelationshipsInput(
                assets=assets,
                profiles=tuple(item.profile_id for item in profiles),
                max_pairs=self._budget.max_pairs,
                budget=self._budget.capability_budget(),
            ),
            self._call_context(),
        )
        evidence: list[RelationshipEvidence] = []
        for spec in select_join_candidates_for_measurement(
            profiles, max_pairs=self._budget.max_pairs
        ):
            self._tracker.charge_pair()
            stats = await self._scalar(
                inclusion_sql(
                    spec.from_asset.address,
                    spec.from_column,
                    spec.to_asset.address,
                    spec.to_column,
                )
            )
            child_distinct = _as_int(stats.get("CHILD_DISTINCT"))
            missing = _as_int(stats.get("MISSING_IN_PARENT"))
            if child_distinct == 0:
                inclusion = 0.0
            else:
                inclusion = max(0.0, (child_distinct - missing) / child_distinct)
            if inclusion < INCLUSION_FLOOR and not spec.name_related:
                continue
            uniqueness = spec.from_uniqueness
            cardinality: str = "N:M"
            if inclusion >= 0.99 and uniqueness >= CANDIDATE_UNIQUENESS:
                cardinality = "1:1"
            elif inclusion >= 0.99:
                cardinality = "1:N"
            bonus = 0.02 if spec.name_related else 0.0
            if spec.to_uniqueness >= CANDIDATE_UNIQUENESS:
                bonus += 0.01
            confidence = round(min(1.0, inclusion + bonus), 4)
            candidate = RelationshipCandidate(
                from_asset=spec.from_asset,
                from_columns=(spec.from_column,),
                to_asset=spec.to_asset,
                to_columns=(spec.to_column,),
                inclusion_ratio=round(inclusion, 6),
                cardinality=cardinality,  # type: ignore[arg-type]
                confidence=confidence,
            )
            parent = ".".join(spec.to_asset.address)
            reason = (
                f"inclusion_ratio={inclusion:.4f}; {missing} distinct {spec.from_column} "
                f"values missing from {parent}.{spec.to_column}"
            )
            evidence.append(
                RelationshipEvidence(
                    candidate=candidate,
                    reason=reason,
                    missing_count=missing,
                    child_distinct=child_distinct,
                    name_related=spec.name_related,
                    measured=True,
                )
            )
        return tuple(
            sorted(
                evidence,
                key=lambda item: (
                    item.candidate.from_asset.address,
                    item.candidate.from_columns,
                    item.candidate.to_asset.address,
                    item.candidate.to_columns,
                ),
            )
        )

    async def _sample_assets(self, assets: tuple[AssetRef, ...]) -> tuple[SampleArtifact, ...]:
        samples: list[SampleArtifact] = []
        for asset in assets:
            self._tracker.charge_query()
            sampled = await self._warehouse.sample_dataset(
                SampleDatasetInput(asset=asset, n=self._budget.sample_n),
                self._call_context(),
            )
            sensitive = {
                name
                for name in (
                    set(sampled.masked_columns) | {key for row in sampled.rows for key in row}
                )
                if column_is_sensitive(name, pii_columns=self._pii_columns)
            }
            rows = tuple(mask_row(dict(row), sensitive=sensitive) for row in sampled.rows)
            encoded = canonical_json_bytes(list(rows))
            if len(encoded) > self._budget.sample_bytes:
                raise ProfilingBudgetExceeded(
                    f"sample bytes {len(encoded)} exceed limit {self._budget.sample_bytes}"
                )
            samples.append(
                SampleArtifact(
                    fixture_version=self._fixture_version,
                    asset=asset,
                    sample_id=_stable_uuid(self._fixture_version, "sample", *asset.address),
                    row_count=len(rows),
                    masked_columns=tuple(sorted(sensitive | set(sampled.masked_columns))),
                    rows=rows,
                    masking=MaskingState(
                        pii_columns=tuple(sorted(self._pii_columns)),
                        samples_masked=True,
                        top_values_masked=True,
                        raw_pii_persisted=False,
                    ),
                    bytes_used=len(encoded),
                )
            )
        return tuple(samples)


def _merge_candidate_keys(
    base: tuple[CandidateKey, ...], extra: tuple[CandidateKey, ...]
) -> tuple[CandidateKey, ...]:
    seen: dict[tuple[str, ...], CandidateKey] = {item.columns: item for item in base}
    for item in extra:
        seen[item.columns] = item
    return tuple(sorted(seen.values(), key=lambda item: item.columns))


def _advertised_candidate_keys(
    base: tuple[CandidateKey, ...],
    extra: tuple[CandidateKey, ...],
    evidence: tuple[KeyEvidence, ...],
) -> tuple[CandidateKey, ...]:
    """Keep CandidateKey rows only when uniqueness meets the candidate threshold."""
    merged = _merge_candidate_keys(base, extra)
    evidence_by_cols = {item.columns: item for item in evidence}
    advertised: list[CandidateKey] = []
    for key in merged:
        measured = evidence_by_cols.get(key.columns)
        uniqueness = measured.uniqueness_ratio if measured is not None else key.uniqueness_ratio
        is_candidate = (
            measured.is_candidate if measured is not None else uniqueness >= CANDIDATE_UNIQUENESS
        )
        if not is_candidate or uniqueness < CANDIDATE_UNIQUENESS:
            continue
        advertised.append(key)
    return tuple(advertised)


def _profile_named(
    profiles: tuple[DatasetProfileArtifact, ...], schema: str, table: str
) -> DatasetProfileArtifact | None:
    return next(
        (item for item in profiles if item.asset.address[1:] == (schema, table)),
        None,
    )


def _facts(
    fixture_version: str,
    profiles: tuple[DatasetProfileArtifact, ...],
    relationships: tuple[RelationshipEvidence, ...],
) -> tuple[ProfilingFact, ...]:
    facts: list[ProfilingFact] = []
    accounts = _profile_named(profiles, "CRM", "ACCOUNTS")
    if accounts is not None:
        domain = next(
            (item for item in accounts.duplicate_evidence if "WEBSITE_DOMAIN" in item.columns),
            None,
        )
        domain_key = next(
            (
                item
                for item in accounts.key_evidence
                if item.expression and "WEBSITE_DOMAIN" in item.columns
            ),
            None,
        )
        facts.append(
            ProfilingFact(
                fact_id="P1_duplicate_accounts",
                asset=accounts.asset,
                columns=("WEBSITE_DOMAIN",),
                metric="normalized_domain_uniqueness",
                value=domain_key.uniqueness_ratio if domain_key is not None else None,
                detail=(
                    f"duplicate_groups={domain.duplicate_groups_estimate if domain else 0}; "
                    "normalized WEBSITE_DOMAIN is not unique"
                ),
            )
        )
    customers = _profile_named(profiles, "BILLING", "CUSTOMERS")
    contacts = _profile_named(profiles, "CRM", "CONTACTS")
    if customers is not None:
        crm_col = next((col for col in customers.columns if col.name == "CRM_ACCOUNT_ID"), None)
        facts.append(
            ProfilingFact(
                fact_id="P2_null_crm_account_id",
                asset=customers.asset,
                columns=("CRM_ACCOUNT_ID",),
                metric="null_ratio",
                value=crm_col.null_ratio if crm_col is not None else None,
                detail="BILLING.CUSTOMERS.CRM_ACCOUNT_ID null ratio",
            )
        )
    rel = next(
        (
            item
            for item in relationships
            if item.candidate.from_asset.address[1:] == ("BILLING", "CUSTOMERS")
            and item.candidate.from_columns == ("CUSTOMER_ID",)
            and item.candidate.to_asset.address[1:] == ("CRM", "ACCOUNT_CROSSWALK")
        ),
        None,
    )
    if rel is not None:
        facts.append(
            ProfilingFact(
                fact_id="P3_crm_billing_crosswalk",
                asset=rel.candidate.from_asset,
                columns=("CUSTOMER_ID", "BILLING_CUSTOMER_ID"),
                metric="inclusion_ratio",
                value=rel.candidate.inclusion_ratio,
                detail=rel.reason,
            )
        )
    if contacts is not None:
        account_col = next((col for col in contacts.columns if col.name == "ACCOUNT_ID"), None)
        facts.append(
            ProfilingFact(
                fact_id="P5_orphan_contacts",
                asset=contacts.asset,
                columns=("ACCOUNT_ID",),
                metric="null_ratio",
                value=account_col.null_ratio if account_col is not None else None,
                detail="CRM.CONTACTS.ACCOUNT_ID nulls are planted orphan contacts",
            )
        )
    unknown = next(
        (
            item
            for item in relationships
            if item.candidate.from_asset.address[1:] == ("BILLING", "INVOICES")
            and item.candidate.from_columns == ("CUSTOMER_ID",)
            and item.candidate.to_asset.address[1:] == ("BILLING", "CUSTOMERS")
        ),
        None,
    )
    if unknown is not None:
        facts.append(
            ProfilingFact(
                fact_id="P5_unknown_invoice_customers",
                asset=unknown.candidate.from_asset,
                columns=("CUSTOMER_ID",),
                metric="inclusion_ratio",
                value=unknown.candidate.inclusion_ratio,
                detail=unknown.reason,
            )
        )
    payments = _profile_named(profiles, "PAYMENTS", "PAYMENTS")
    if payments is not None:
        grain = next(
            (
                item
                for item in payments.key_evidence
                if item.columns == ("INVOICE_ID", "PAYMENT_REF")
            ),
            None,
        )
        facts.append(
            ProfilingFact(
                fact_id="P10_payment_grain",
                asset=payments.asset,
                columns=("INVOICE_ID", "PAYMENT_REF"),
                metric="uniqueness_ratio",
                value=grain.uniqueness_ratio if grain is not None else None,
                detail=(
                    "v1 pre-redelivery unique grain"
                    if fixture_version == "v1"
                    else "v2 redelivery duplicate payment evidence"
                ),
            )
        )
    if contacts is not None:
        facts.append(
            ProfilingFact(
                fact_id="masking_contacts",
                asset=contacts.asset,
                columns=("EMAIL", "PHONE", "FIRST_NAME", "LAST_NAME"),
                metric="masked",
                value=True,
                detail="PII columns are classified sensitive and masked in samples/top-values",
            )
        )
    return tuple(facts)


async def profile_selected_assets(
    warehouse: WarehouseReadPort,
    selected: tuple[AssetRef, ...],
    *,
    fixture_version: str,
    budget: ProfilingBudget | None = None,
    context: CallContext | None = None,
    excluded_addresses: tuple[tuple[str, ...], ...] = (),
    sample_priority: tuple[tuple[str, ...], ...] = (),
) -> ProfilingRunResult:
    engine = ProfilingEngine(
        warehouse,
        fixture_version=fixture_version,
        budget=budget,
        context=context,
        excluded_addresses=excluded_addresses,
        sample_priority=sample_priority,
    )
    return await engine.run(selected)
