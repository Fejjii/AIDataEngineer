# Tool Contracts

**Task:** DE 001 (hardened by DE 001R2A and DE 001R2B) · **Status:** ACCEPTED

Per-capability contracts. Schemas are given in Pydantic-like notation; the implementation
must match field names so the planner catalogue, UI and evaluation harness share one
vocabulary. Field types ending in `Ref` are identifiers of persisted objects, never inline
blobs.

Shared conventions for **every** capability:

- **Audit metadata (always recorded):** `workflow_id`, `phase_run_id`, `task_id`,
  `operation_idempotency_key`, `resolved_input_digest`, `attempt_id`, `attempt_number`,
  `claim_epoch`, `capability_id@version`, input/output schema versions,
  `connector_id`, `target_environment`, `policy_decision_id`, `started_at`, `finished_at`,
  `duration_ms`, `status`, `failure_class`, `input_digest` (sha256 of validated input),
  `output_digest`, `redacted_input_excerpt`, `redacted_output_excerpt`.
- **Retry policy notation:** `max_attempts=n` includes the initial attempt. Every created
  attempt—including expired, recovered, cancelled and ambiguous—consumes the budget;
  reconciliation checks and pre-attempt parking do not. Attempts share
  `operation_idempotency_key`; attempt identity never contributes to it.
  `retry_on` never means blind retry for a side-effecting operation. Authoritative rule
  (`docs/STATE_MODEL.md` §4.7): a definite pre-dispatch failure may retry directly; an
  ambiguous side effect must reconcile first; only proven `NoEffect` may retry while
  `attempt_count < max_attempts`; exhausted `NoEffect` is `FAILED`. Side-effect-free
  capabilities may retry listed classes directly within `max_attempts`.
- **Effect semantics:** `SIDE_EFFECT_FREE`, `EXTERNALLY_DEDUPLICATED`,
  `PROVEN_CONVERGENT`, or `NON_IDEMPOTENT`. Every ambiguous side-effecting result
  reconciles before retry; only authoritative `NoEffect` permits another attempt.
- **Warehouse/database read binding:** a capability with `required_permission=READ` that
  requires a warehouse or database connector must bind to an instance with
  `identity_class=READ_ONLY` (Snowflake: `snowflake_ro`). Policy rule R4b and
  `allowed_permissions` membership both enforce this (`docs/PERMISSION_MODEL.md` §2.1, §3).
- **Permission row semantics:** the single `PermissionLevel` the capability requires; policy
  checks membership in the workflow grant set and in the connector's `allowed_permissions`
  (`docs/PERMISSION_MODEL.md` §3). Permissions are never compared by rank.
- **Timeouts** are enforced by the Tool Registry wrapper *and* passed to the connector
  (e.g., Snowflake `STATEMENT_TIMEOUT_IN_SECONDS`) so a hung driver cannot outlive the task.
- **Failure classes** listed are the ones the connector must map to; anything else → `UNKNOWN`.

---

## 0. Shared types

```python
AssetRef      = {connector_id: str, address: tuple[str, ...], kind: str, platform_type: str|None}
# address is an ordered provider-neutral hierarchy; connector dialect interprets segments.
ColumnSpec    = {name: str, data_type: str, nullable: bool, ordinal: int, comment: str|None, is_untrusted_text: True}
SqlText       = {dialect: str, text: str, classification: SqlClassification|None}
SqlClassification = {statement_types: list[str], objects_read: list[AssetRef], objects_written: list[AssetRef],
                     functions: list[str], table_functions: list[str], stages_or_urls: list[str],
                     unsafe_constructs: list[str], unknown_ast_nodes: list[str],
                     is_read_only: bool, is_destructive: bool, is_multi_statement: bool, has_dynamic_sql: bool}
ArtifactProvenance = {execution_mode: "REAL"|"MOCK", connector_id: str|None,
                      connector_version: str|None, capability_id: str,
                      capability_version: int, operation_idempotency_key: str,
                      resolved_input_digest: str, parent_artifact_ids: tuple[UUID, ...]}
ArtifactRef   = {artifact_id: UUID, sha256: str, type: ArtifactType, version: int,
                 schema_version: int, provenance: ArtifactProvenance}
Budget        = {max_rows: int, max_bytes: int, max_seconds: int}
TargetEnv     = "DEV" | "STAGING" | "PROD"       # bound on the connector instance
```

Shared transformation capabilities use generic `TransformationProjectRef`,
`TransformationSelection`, `TransformationManifestRef`, `TransformationRunResult` and
`TransformationTestResult` contracts. Connector-specific fields live in a versioned
extension payload keyed by `platform` (for example `DbtProjectExtension` containing dbt
node selectors, manifest metadata and `run_results` details). The orchestrator consumes
only generic status, nodes, artifacts and validation evidence; it never assumes `ref`,
`source`, dbt model kinds or dbt file layout. A SQLMesh/Spark connector may define another
extension without changing generic task or orchestration schemas.

---

## 1. `discover_assets` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Enumerate assets inside an allow-listed scope. |
| Input | `{scope: {databases: list[str], schemas: list[str]|None, include_views: bool}, filters: {name_pattern: str|None}}` — scope must be a subset of the connector's configured allow-list; otherwise `POLICY_DENIED` (`SCOPE_VIOLATION`, fail closed) before execution. |
| Output | `{assets: list[AssetRef & {row_count_estimate: int|None, last_altered: datetime|None, comment: str|None}], snapshot_id: UUID, truncated: bool}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 120 s / `max_attempts=3, backoff=exp, retry_on={TRANSIENT_PROVIDER, CONNECTOR_FAILURE}` |
| Failure classes | `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER`, `TIMEOUT` |
| Validation | Every returned asset must lie within `scope`; snapshot persisted with hash; `truncated` must be set if connector paging stopped early. |
| Connector | REQUIRED: warehouse, database, or storage kind. Warehouse/database instances must be `identity_class=READ_ONLY` (Snowflake: `snowflake_ro`). Snowflake: `SHOW TABLES/VIEWS IN SCHEMA` + `INFORMATION_SCHEMA`. PostgreSQL: `information_schema`. |
| Effect semantics | SIDE_EFFECT_FREE |

## 2. `describe_asset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Column-level metadata for one asset. |
| Input | `{asset: AssetRef, include_constraints: bool, include_row_count: bool}` |
| Output | `{asset: AssetRef, columns: list[ColumnSpec], primary_key: list[str]|None, unique_keys: list[list[str]], foreign_keys: list[{columns, ref_asset, ref_columns}], row_count: int|None, clustering: list[str]|None, snapshot_id: UUID}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 60 s / `max_attempts=3, backoff=exp, retry_on={TRANSIENT_PROVIDER, CONNECTOR_FAILURE}` |
| Failure classes | `MISSING_OBJECT`, `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER`, `TIMEOUT` |
| Validation | Column names unique; `comment` fields flagged `is_untrusted_text`. |
| Connector | REQUIRED |
| Effect semantics | SIDE_EFFECT_FREE |

## 3. `detect_schema_drift` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Compare current asset shape to a stored snapshot. |
| Input | `{asset: AssetRef, baseline_snapshot_id: UUID}` |
| Output | `{drifted: bool, added: list[ColumnSpec], removed: list[ColumnSpec], type_changed: list[{name, from, to}], renamed_candidates: list[{from, to, confidence}]}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 60 s / as `describe_asset` |
| Failure classes | as `describe_asset` |
| Validation | `renamed_candidates` computed by type + position + name-distance heuristic; confidence ∈ [0,1]. |
| Connector | REQUIRED |
| Effect semantics | SIDE_EFFECT_FREE |

## 4. `select_relevant_assets` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Choose which catalogued assets matter for the requirement. |
| Input | `{requirement: RequirementSpecRef, catalogue_snapshot_id: UUID, max_assets: int}` — the prompt receives asset names, comments (delimited as untrusted), column names and row counts; **no sample data**. |
| Output | `{selected: list[{asset: AssetRef, role: "SOURCE"|"REFERENCE"|"LOOKUP", reason: str, confidence: float}], excluded_notable: list[{asset, reason}]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 90 s / `max_attempts=2, backoff=fixed, retry_on={TRANSIENT_PROVIDER, OUTPUT_INVALID}` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `TIMEOUT`, `LLM_BUDGET_EXCEEDED` |
| Validation | Every `selected.asset` ∈ catalogue snapshot (Det subset check); `len(selected) ≤ max_assets`; reasons non-empty. Violations → `OUTPUT_INVALID` → one retry with the violation appended → then `BLOCKED` for human. |
| Connector | NONE |
| Effect semantics | SIDE_EFFECT_FREE (replayable via prompt version + inputs) |

## 5. `profile_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Statistics per column and dataset with budget. |
| Input | `{asset: AssetRef, columns: list[str]|None, budget: Budget, sample_fraction: float|None, top_k: int}` |
| Output | `{asset, row_count: int, sampled: bool, columns: list[{name, null_ratio, distinct_ratio, min, max, mean|None, top_values: list[{value_masked, count}], inferred_semantic: "ID"|"DATE"|"AMOUNT"|"CODE"|"TEXT"|"FLAG"|None}], candidate_keys: list[{columns, uniqueness_ratio}], duplicate_groups_estimate: int, profile_id: UUID}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 300 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER, TIMEOUT}` (second attempt halves the budget) |
| Failure classes | `MISSING_OBJECT`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER` |
| Validation | Ratios ∈ [0,1]; `top_values` masked when column classified sensitive by heuristics (email, phone, name patterns); profile SQL generated from templates only (no LLM). |
| Connector | REQUIRED |
| Effect semantics | SIDE_EFFECT_FREE |

## 6. `sample_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Small masked sample for LLM reasoning and human display. |
| Input | `{asset: AssetRef, columns: list[str]|None, n: int ≤ 20, where: SqlText|None (must classify read-only, single statement)}` |
| Output | `{rows: list[dict[str, str|int|float|bool|None]], masked_columns: list[str], sample_id: UUID}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 60 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | as `profile_dataset` + `UNSAFE_OPERATION` (if `where` fails classification) |
| Validation | `n ≤ 20` enforced by wrapper; sensitive columns masked before persistence; total bytes ≤ 64 KB. |
| Connector | REQUIRED |
| Effect semantics | SIDE_EFFECT_FREE; output is non-deterministic and must be reconstructed by a new attempt |

## 7. `infer_relationships` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Candidate joins via inclusion-dependency sampling. |
| Input | `{assets: list[AssetRef], profiles: list[UUID], max_pairs: int, budget: Budget}` |
| Output | `{candidates: list[{from_asset, from_columns, to_asset, to_columns, inclusion_ratio, cardinality: "1:1"|"1:N"|"N:M", confidence}], relationships_id: UUID}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 300 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER, TIMEOUT}` |
| Failure classes | as `profile_dataset` |
| Validation | Only column pairs with compatible types and `inferred_semantic ∈ {ID, CODE}` tested; `inclusion_ratio ∈ [0,1]`. |
| Connector | REQUIRED |
| Effect semantics | SIDE_EFFECT_FREE |

## 8. `classify_sql` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Parse SQL and classify safety attributes. Used by policy and as a pre-validator. |
| Input | `{sql: SqlText}` |
| Output | `SqlClassification & {parse_ok: bool, parse_error: str|None, normalized_sql: str}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 10 s / none |
| Failure classes | `SQL_SYNTAX` (unparseable) |
| Validation | Unparseable SQL is `is_read_only=False, is_destructive=True`. Parse with the declared dialect, normalized render, then reparse and require equivalent AST. Classify functions/table functions, UDF/external-function calls, stages/URLs, session constructs and unknown nodes. Read operations use a dialect-versioned safe-function allow-list; unknown/external functions, unapproved UDFs, stages/URLs, dynamic SQL, role/session mutation and unknown AST nodes are denied. Canonical object addresses are checked after quoted-identifier/case normalization. |
| Connector | NONE (sqlglot with dialect registry) |
| Effect semantics | SIDE_EFFECT_FREE |

## 9. `validate_query` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Dry-run compile / explain without side effects. |
| Input | `{sql: SqlText, mode: "EXPLAIN"|"COMPILE"}` |
| Output | `{valid: bool, error: {code: str|None, message: str, line: int|None, object: str|None}|None, plan_summary: {estimated_bytes: int|None, partitions_total: int|None, partitions_scanned: int|None}|None}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 60 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TRANSIENT_PROVIDER` — returned **as output** (`valid=false`) not as task failure, so generation can iterate. |
| Validation | Pre-validator `classify_sql` must return `is_read_only=True` or the statement must be a CREATE VIEW/TABLE AS in a DEV schema (EXPLAIN only). |
| Connector | REQUIRED(warehouse). Snowflake: `EXPLAIN USING JSON`. |
| Effect semantics | SIDE_EFFECT_FREE |

## 10. `execute_query` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Execute a **read-only** statement with caps; used by profiling, quality checks, reconciliation. |
| Input | `{sql: SqlText, budget: Budget, result_mode: "ROWS"|"SCALAR"|"COUNT_ONLY"}`; canonical query identity is generated from `CallContext`, never supplied by planner/client input |
| Output | `{rows: list[dict]|None, scalar: Any|None, row_count: int, bytes_scanned: int|None, duration_ms: int, query_id: str|None, truncated: bool}` |
| Permission / Risk / Approval | READ (strictly read-only; temporary objects are not supported in V1 — use `create_dataset`) / MEDIUM / NEVER |
| Timeout / Retry | `budget.max_seconds` ≤ 300 / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `TRANSIENT_PROVIDER`, `UNSAFE_OPERATION` |
| Validation | Pre-validator: `classify_sql.is_read_only == True`, `is_multi_statement == False`, `has_dynamic_sql == False`, all `objects_read` within connector allow-list. Wrapper adds `LIMIT` when `result_mode == ROWS`. Rows persisted only as artifact when ≤ `max_rows`; otherwise `COUNT_ONLY`. |
| Connector | REQUIRED(warehouse\|database). Binding is valid only when `connector.identity_class = READ_ONLY` (Snowflake: `snowflake_ro` / `AIDE_DEV_RO`). A DEVELOPMENT identity (`snowflake_dev`) is not a valid implementation of this capability; R0/R4/R4b reject it. |
| Effect semantics | SIDE_EFFECT_FREE |

## 10a. `generate_sql_query` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | One SQL statement for investigation-type requests or a single development table (DE 002 slice); not a substitute for dbt generation. |
| Input | `{requirement: RequirementSpecRef, selected_assets: list[AssetRef], metadata: list[UUID], dialect, target: AssetRef|None (DEV namespace; when set the output must be a single CREATE TABLE AS SELECT), prior_attempt_feedback: list[ValidationFeedback]|None}` |
| Output | `{sql: SqlText, explanation: str, expected_columns: list[{name, type_hint}], expected_grain: list[str]|None, assumptions: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 120 s / `max_attempts=2, backoff=fixed, retry_on={TRANSIENT_PROVIDER, OUTPUT_INVALID}` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `TIMEOUT`, `LLM_BUDGET_EXCEEDED` |
| Validation (Det, mandatory) | `classify_sql`: single statement, no dynamic SQL; if `target` is null → `is_read_only`; else exactly one write to `target` inside the DEV namespace and the inner query read-only; all referenced objects ∈ `selected_assets` ∪ `target`; `validate_query` (EXPLAIN) valid; `expected_columns` ⊆ EXPLAIN/describe output after execution. |
| Connector | NONE |
| Effect semantics | SIDE_EFFECT_FREE (replayable) |

## 11. `create_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Create/replace table or view in DEV. |
| Input | `{target: AssetRef (schema must be in DEV allow-list), definition: SqlText (CREATE [OR REPLACE] TABLE|VIEW … AS SELECT), replace: bool}` |
| Output | `{created: AssetRef, replaced_existing: bool, row_count: int|None}` |
| Permission / Risk / Approval | DEVELOPMENT_WRITE / MEDIUM / IF_POLICY_FLAGS (flag: `replace=True` on an object not created by this workflow) |
| Timeout / Retry | 600 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `UNSAFE_OPERATION` |
| Validation | `classify_sql.objects_written == [target]`; no other writes; target schema ∈ DEV allow-list; provenance tag carries workflow and `operation_idempotency_key`. |
| Connector | REQUIRED(warehouse), bound to DEV |
| Effect semantics | EXTERNALLY_DEDUPLICATED by operation provenance; every ambiguous result reconciles before retry |

## 12. `drop_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Drop an object created by this workflow in DEV. |
| Input | `{target: AssetRef, created_by_workflow: UUID}` |
| Output | `{dropped: bool}` |
| Permission / Risk / Approval | DESTRUCTIVE / HIGH / ALWAYS in DEV; DISABLED for STAGING/PROD in V1 |
| Timeout / Retry | 60 s / none |
| Failure classes | `MISSING_OBJECT`, `PERMISSION_FAILURE`, `UNSAFE_OPERATION` |
| Validation | Target must have provenance tag equal to `created_by_workflow`; otherwise DENY `PROVENANCE_MISMATCH` (rule R13b, fail closed). |
| Connector | REQUIRED(warehouse), DEV only |
| Effect semantics | EXTERNALLY_DEDUPLICATED; reconcile verifies object/provenance state |

## 13. `generate_transformation` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Produce SQL/YAML/tests for one design unit (a model). |
| Input | `{design_unit: ModelDesignUnitRef, metadata: list[UUID] (describe snapshots), profiles: list[UUID], samples: list[UUID]|None, conventions: ProjectConventions, dialect, prior_attempt_feedback: list[ValidationFeedback]|None}` |
| Output | `{files: list[{path: str, content: str, kind: "MODEL_SQL"|"SCHEMA_YML"|"SOURCE_YML"|"MACRO"|"SNAPSHOT"|"DOC_MD"}], tests_declared: list[TestSpec], assumptions: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 180 s / `max_attempts=2, backoff=fixed, retry_on={TRANSIENT_PROVIDER, OUTPUT_INVALID}` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `TIMEOUT`, `LLM_BUDGET_EXCEEDED` |
| Validation (Det, mandatory) | Every `MODEL_SQL` passes `classify_sql` as a single read-only SELECT (dbt wraps materialization); references only `ref()`/`source()` to known models/sources; every column in `SCHEMA_YML` exists in the compiled model (checked after `compile_transformation`); declared grain keys match `design_unit.grain`; `path` inside project model dir; no Jinja `run_query` or `execute` blocks; file size ≤ 200 KB. |
| Connector | NONE |
| Effect semantics | SIDE_EFFECT_FREE (replayable) |

## 14. `create_transformation` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Write artifact files into the transformation project working tree. |
| Input | `{artifact_set: list[ArtifactRef], project_ref: TransformationProjectRef, mode: "ADD"|"REPLACE"}` |
| Output | `{written: list[{path, sha256}], project_state_id: UUID}` |
| Permission / Risk / Approval | DEVELOPMENT_WRITE / LOW / NEVER |
| Timeout / Retry | 30 s / none |
| Failure classes | `CONNECTOR_FAILURE`, `UNSAFE_OPERATION` (path escape) |
| Validation | Paths normalized and confined to project root; only allowed extensions (`.sql`, `.yml`, `.md`); `dbt_project.yml` and `profiles.yml` **never** writable by this capability. |
| Connector | REQUIRED(transformation) — operates on a per-workflow working copy |
| Effect semantics | EXTERNALLY_DEDUPLICATED by validated file hashes |

## 15. `compile_transformation` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | `dbt parse` + `dbt compile` for selection. |
| Input | `{project_state_id: UUID, select: list[str]|None, target: "DEV"}` |
| Output | `{ok: bool, manifest_ref: ArtifactRef|None, compiled: list[{model, compiled_sql_ref}], errors: list[{model|None, message, class}]}` |
| Permission / Risk / Approval | DEVELOPMENT_EXECUTE / LOW / NEVER |
| Timeout / Retry | 300 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `DBT_COMPILE` (as output `ok=false`), `CONNECTOR_FAILURE`, `TIMEOUT` |
| Validation | Manifest parsed and stored as artifact; every compiled SQL re-classified via `classify_sql` (must be non-destructive; dbt materializations write only to the DEV target schema). |
| Connector | REQUIRED(transformation) |
| Effect semantics | SIDE_EFFECT_FREE |

## 16. `execute_transformation` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | `dbt run --select …` in DEV. |
| Input | `{project_state_id: UUID, select: list[str], full_refresh: bool, target: "DEV"}`; query identity comes from `CallContext` |
| Output | `{ok: bool, results: list[{model, status: "success"|"error"|"skipped", execution_time_s, rows_affected|None, message|None, error_class|None}], run_results_ref: ArtifactRef}` |
| Permission / Risk / Approval | DEVELOPMENT_EXECUTE / MEDIUM / NEVER |
| Timeout / Retry | 900 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `DBT_RUNTIME`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER` |
| Validation | Target profile must be the DEV profile bound to the connector; `run_results.json` parsed; per-model error text mapped to failure class by the dbt/Snowflake error mapper. |
| Connector | REQUIRED(transformation), DEV |
| Effect semantics | NON_IDEMPOTENT by default. `PROVEN_CONVERGENT` is allowed only per materialized invocation after deterministic SQL, unique merge keys, full compiled config/hooks/macros and convergence validators pass. |

## 17. `run_pipeline` (deterministic, v1)

As `execute_transformation` but `dbt build` (run + test + snapshot + seed) for the whole
project or selection. Output adds `tests: list[TestResult]`. Timeout 900 s. Failure classes
add `DBT_TEST`. Effect semantics are `NON_IDEMPOTENT`; snapshots, hooks and partial DAG
completion prohibit a capability-level convergence claim.

## 18. `run_tests` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | `dbt test --select …`; structured results. |
| Input | `{project_state_id: UUID, select: list[str]|None, store_failures: bool}` |
| Output | `{ok: bool, tests: list[{test_name, model, column|None, status: "pass"|"fail"|"warn"|"error", failures: int|None, failing_rows_sample_ref: ArtifactRef|None}], run_results_ref}` |
| Permission / Risk / Approval | DEVELOPMENT_EXECUTE / LOW / NEVER |
| Timeout / Retry | 600 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `DBT_TEST` (as output), `DBT_RUNTIME`, `CONNECTOR_FAILURE`, `TIMEOUT` |
| Validation | Failing-row samples capped at 20 rows and masked. |
| Connector | REQUIRED(transformation) |
| Effect semantics | NON_IDEMPOTENT when `store_failures=true`; otherwise SIDE_EFFECT_FREE |

## 19. `inspect_failure` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Build an evidence bundle for diagnosis. |
| Input | `{task_id: UUID, attempt_id: UUID}` |
| Output | `{failure_class, error_code|None, error_message (redacted), failing_sql_ref|None, model|None, related_metadata: list[UUID], related_profiles: list[UUID], prior_repairs: list[RepairAttemptSummary], drift: DriftReport|None}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 60 s / none |
| Failure classes | `CONNECTOR_FAILURE` |
| Validation | Automatically runs `detect_schema_drift` for objects referenced in the failing SQL when class ∈ {MISSING_OBJECT, SCHEMA_MISMATCH}. |
| Connector | OPTIONAL |
| Effect semantics | SIDE_EFFECT_FREE |

## 20. `diagnose_failure` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Produce a `RepairProposal`. |
| Input | `{evidence: InspectFailureOutput, artifact_under_repair: ArtifactRef, forbidden_hypotheses: list[str] (hashes of prior hypotheses)}` |
| Output | `{diagnosis: str, root_cause_class: FailureClass, hypothesis: str, hypothesis_hash: str, patch: {file_path, new_content}|{sql_ref}, expected_validation: list[ValidatorId], confidence: float, requires_human: bool, human_question: str|None}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 120 s / `max_attempts=2, backoff=fixed, retry_on={TRANSIENT_PROVIDER, OUTPUT_INVALID}` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `LLM_BUDGET_EXCEEDED` |
| Validation | `hypothesis_hash ∉ forbidden_hypotheses`; `root_cause_class` must be in the repairable set unless `requires_human=True`; patch must target the artifact under repair or its direct upstream in the same phase; patched SQL passes `classify_sql` and `validate_query`. |
| Connector | NONE |
| Effect semantics | SIDE_EFFECT_FREE (replayable) |

## 21. `get_lineage` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Lineage graph. |
| Input | `{manifest_ref: ArtifactRef, column_level: bool}` |
| Output | `{nodes: list[{id, kind: "source"|"model"|"seed"|"snapshot"|"test", name}], edges: list[{from, to, columns: list[{from_col, to_col}]|None}], lineage_ref: ArtifactRef}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 120 s / none |
| Failure classes | `CONNECTOR_FAILURE` |
| Validation | Graph acyclic; every model in manifest present. |
| Connector | REQUIRED(transformation); column-level via sqlglot on compiled SQL |
| Effect semantics | SIDE_EFFECT_FREE |

## 22. `generate_documentation` (reasoning, v1)

Input `{scope: "MODEL"|"COLUMN"|"RUN_SUMMARY"|"PR_BODY", design_ref, profiles, lineage_ref, validation_report_ref|None}`; output `{documents: list[{path|None, markdown}]}`. READ / LOW / NEVER. 120 s. Validation: markdown only, size ≤ 100 KB, no code fences that contain SQL differing from artifact SQL (prevents "documentation drift"), every referenced model/column exists.

## 23. `get_execution_metrics` / 24. `get_cost_metrics` (deterministic, v1)

Input `{query_tag: str, since: datetime}`; outputs `{queries: list[{query_id, duration_ms, bytes_scanned, rows_produced, partitions_scanned, partitions_total, spilled_bytes, warehouse}]}` and `{credits_used: float, estimated_cost: float, currency, breakdown_by_task: list}`. READ / LOW / NEVER. 60 s. Retry on transient. Snowflake: `QUERY_HISTORY` and `WAREHOUSE_METERING_HISTORY` (account usage may lag; output has `as_of`).

## 25. `prepare_git_change` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Branch + commit + push artifact set. |
| Input | `{repository_ref, base_branch: str, branch_name: str (pattern `aide/<workflow_short_id>_<slug>`), artifact_set: list[ArtifactRef], commit_message: str, author: FixedBotIdentity}` |
| Output | `{branch: str, commit_sha: str, files_changed: int, pushed: bool}` |
| Permission / Risk / Approval | GIT_WRITE / MEDIUM / IF_POLICY_FLAGS (flag: `base_branch` is protected → DENY; branch exists and not owned by this workflow → DENY) |
| Timeout / Retry | 120 s / `max_attempts=2, backoff=exp, retry_on={TRANSIENT_PROVIDER}` |
| Failure classes | `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER`, `UNSAFE_OPERATION` |
| Validation | Never pushes to `main`/protected branches; never force-pushes; secret scan of file contents before commit (fail closed, `SECRET_IN_DIFF`); commit message is an artifact; commit carries trailer `Aide-Operation-Key: <operation_idempotency_key>`. |
| Connector | REQUIRED(vcs) |
| Effect semantics | EXTERNALLY_DEDUPLICATED by workflow-owned branch, expected remote head, tree digest and operation trailer; commit SHA determinism is not assumed |

## 26. `prepare_pull_request` (deterministic, v1)

Input `{repository_ref, head_branch, base_branch, title, body_ref: ArtifactRef, labels: list[str], draft: bool}`; output `{pr_number, url, state}`. GIT_WRITE / MEDIUM / IF_POLICY_FLAGS (default no approval; configurable to ALWAYS). 60 s. Never merges. Effect semantics: `EXTERNALLY_DEDUPLICATED`; reconciliation matches workflow-owned head plus operation marker.

## 27. `deploy_staging` (deterministic, v1 — gated)

| Field | Value |
|---|---|
| Purpose | Promote an artifact set to STAGING. Production uses the separate, disabled-in-V1 `deploy_production` contract. |
| Input | `{artifact_set, strategy: "DBT_RUN_TARGET"|"ORCHESTRATOR_RELEASE", release_id: str}` — target is statically STAGING. `release_id` is part of the materialized input and is persisted before dispatch (`docs/STATE_MODEL.md` §4.7). **`approval_id` is not an input field:** approval identity depends on the materialized operation and therefore cannot participate in the operation key. Policy decides whether `OperationApproval` is required; the approval binds to the already computed `operation_idempotency_key` and `resolved_input_digest`. After approval the same operation continues. |
| Output | `{deployed: bool, target: "STAGING", release_id: str, rollback_ref: str|None}` |
| Permission / Risk / Approval | STAGING_DEPLOY / HIGH / OperationApproval ALWAYS |
| Timeout / Retry | 900 s / `max_attempts=1`. Ambiguous outcomes reconcile first. Proven `NoEffect` cannot retry because the budget is already exhausted → task/workflow `FAILED`. `Unknown` or bounded `InProgress` exhaustion parks and never auto-retries. |
| Failure classes | `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `DBT_RUNTIME`, `TIMEOUT`, `UNSAFE_OPERATION`, `AMBIGUOUS_OUTCOME` |
| Validation | Approval subject must match operation key, resolved-input digest, artifact/provenance closure, connector/version, STAGING target and external-state digest. MOCK-derived artifacts are denied. |
| Connector | REQUIRED(transformation\|orchestration); must implement `reconcile` by looking up `release_id` in the target's release marker |
| Effect semantics | NON_IDEMPOTENT |

`deploy_production` is a distinct `PRODUCTION_WRITE`, CRITICAL,
`OperationApproval(ALWAYS)` capability with a statically PROD input/output schema. It is
registered as `DISABLED` and no connector advertises it in V1; policy returns
`PROD_DISABLED_V1`.

## 28. `register_monitor` / 29. `check_monitor` (deterministic, v1)

`register_monitor` input `{kind: "FRESHNESS"|"TEST_SUITE"|"ROW_COUNT"|"COST", target: AssetRef|model, threshold, schedule_hint}` → `{monitor_id}` (artifact only in V1). `check_monitor` input `{monitor_id}` → `{status: "OK"|"WARN"|"FAIL", observed, threshold, checked_at}`. DW / READ, LOW, NEVER.

## 30. `interpret_requirement` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Natural language → typed spec. |
| Input | `{text: str (≤ 8 000 chars), prior_clarifications: list[{question, answer}], organisation_glossary: list[{term, definition}]|None}` |
| Output | `RequirementSpec = {goal: str, deliverable_type: "ANALYTICAL_DATA_PRODUCT"|"PIPELINE"|"MODEL_CHANGE"|"QUALITY_SUITE"|"INVESTIGATION", business_entities: list[{name, description}], metrics: list[{name, definition|None, ambiguous: bool}], grain_hints, history_requirements: "NONE"|"CURRENT_ONLY"|"FULL_HISTORY"|"UNKNOWN", freshness_requirement, consumers, constraints, ambiguities: list[{topic, question, options: list[str], blocking: bool}], out_of_scope: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 90 s / `max_attempts=2, backoff=fixed, retry_on={TRANSIENT_PROVIDER, OUTPUT_INVALID}` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `LLM_BUDGET_EXCEEDED`, `BUSINESS_AMBIGUITY` (if blocking ambiguities remain after max rounds) |
| Validation | Blocking ambiguities → `emit_clarification`; the Det rule "metrics without definition are ambiguous" is applied regardless of LLM flag. |
| Connector | NONE |

## 31. `plan_phase` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Task DAG for the next phase. |
| Input | `{workflow_context_ref, phase: WorkflowState, contract_snapshot_ref, capability_catalogue: list[{id, version, purpose, permission, risk, input_schema_version}], constraints: {max_tasks, effective_grants, registered_connectors: list[{connector_id, kind, supported_contract_versions}]}}` |
| Output | `Plan = {phase, tasks: list[{local_id, capability_id, connector_id|None, depends_on: list[local_id], inputs: dict, rationale: str}], phase_exit_criteria: list[str], assumptions: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 120 s / `max_attempts=2, backoff=fixed, retry_on={TRANSIENT_PROVIDER, OUTPUT_INVALID}` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `LLM_BUDGET_EXCEEDED` |
| Validation | Capability/connector versions exist in the snapshot; connector kind and permissions are structurally compatible; warehouse/database READ tasks name a `READ_ONLY` identity; DAG acyclic; task count bounded. Temporary health is not structural validity. Templates may contain scalar `{"$from": local_id, "path": ...}` references, but cannot receive policy/approval/operation identity until Det resolves and validates all input. List fan-out is forbidden inside an active phase: discovery enumeration ends when that run's `phase_exit_criteria` (catalogue) are satisfied; assets are sorted; a new planning boundary creates explicit description templates unique on `(phase_run_id, local_id)` whose exit criteria include catalogue plus selection. |
| Connector | NONE |

## 32. `propose_model_design` (reasoning, v1)

Input `{requirement_ref, architecture_decision: ArchitectureDecision (Det-selected, see docs/DATA_MODELLING_STRATEGY.md), selected_assets, metadata, profiles, relationships}`; output `ModelDesign = {layers: list, models: list[ModelDesignUnit{name, layer, kind: STAGING|INTERMEDIATE|DIMENSION|FACT|MART|SNAPSHOT, grain: list[str], surrogate_key, natural_keys, scd_type|None, incremental: {strategy, unique_key, watermark_column}|None, sources: list, columns: list[{name, expression_hint, type, tests}], dedup_rule|None}], relationships, tests, open_questions}`. READ / MEDIUM / NEVER. 180 s. Validation: architecture class matches Det decision; each grain is a candidate key or a declared dedup rule exists; every source column referenced exists in metadata; SCD2 units have a valid change-tracking column set.

## 33. `summarize_for_human` (reasoning, v1)

Input `{workflow_ref, audience: "ENGINEER"|"BUSINESS"|"APPROVER", scope}`; output `{markdown}`. READ / LOW / NEVER. 60 s. Validation: must not contain content absent from persisted state (checked by referencing ids); size ≤ 20 KB.

## 34. `emit_clarification` (control, v1)

Input `{questions: list[{topic, question, options, blocking}]}`; output `{clarification_id}`. Transitions workflow to `CLARIFICATION_REQUIRED`. Max 2 rounds per workflow (Det).

## 35. `request_approval` (control, v1)

Input `{subjects: list[OperationApproval|DesignApproval|BudgetIncreaseApproval], summary_ref}`;
output `{approval_requirement_ids: list[UUID], status: "PENDING"}`. Operation subjects are
created only after materialization and include operation key, resolved-input digest,
artifact/provenance closure, connector/version, target, permission, relevant external
state and expiry. They never include an `approval_id` inside capability input. Design subjects contain no permission. Budget subjects authorize an
explicit new cap/delta. All mandatory subjects must approve; rejection routing is defined
in `docs/PERMISSION_MODEL.md` §4.

---

## 36. Failure-class → capability matrix (summary)

| Failure class | Raised by | Retryable | Repairable | Escalate |
|---|---|---|---|---|
| `SQL_SYNTAX` | validate/execute/dbt | no | yes | after 2 |
| `MISSING_OBJECT` | describe/validate/execute/dbt | no | yes (with drift evidence) | after 2 |
| `SCHEMA_MISMATCH` | validate/execute/dbt | no | yes | after 2 |
| `TYPE_MISMATCH` | validate/execute/dbt | no | yes | after 2 |
| `DBT_COMPILE` | compile | no | yes | after 2 |
| `DBT_RUNTIME` | run/build | no | yes (if mapped to a repairable sub-class) | after 2 |
| `DBT_TEST` | test/build | no | yes | after 2 |
| `DATA_QUALITY` | Quality Engine | no | yes | after 2 |
| `OUTPUT_INVALID` | reasoning capabilities | yes (1) | — | then BLOCKED |
| `CONNECTOR_FAILURE` | any connector | **not blindly.** Side-effect-free: yes within `max_attempts`. Side-effecting: only `DEFINITELY_BEFORE_DISPATCH` or `DEFINITELY_REJECTED_NO_EFFECT`; else reconcile first; proven `NoEffect` only if `attempt_count < max_attempts` | no | PARKED/BLOCKED if ambiguous/`Unknown`; `FAILED` if `NoEffect` exhausted |
| `TRANSIENT_PROVIDER` | any | same evidence rule as `CONNECTOR_FAILURE`; exception class alone is insufficient | no | PARKED/BLOCKED after bounded reconcile; `FAILED` if `NoEffect` exhausted |
| `TIMEOUT` | any | side-effect-free may retry (profiling may reduce budget); side-effecting must reconcile unless proven pre-dispatch | no | PARKED/BLOCKED if still ambiguous; `FAILED` if `NoEffect` exhausted |
| `RESOURCE_LIMIT` | warehouse | no | no | BLOCKED (cost gate) |
| `PERMISSION_FAILURE` | any | no | no | task PARKED; workflow BLOCKED (human fixes grants) |
| `POLICY_DENIED` | policy | no | no | by deny class (`docs/PERMISSION_MODEL.md` §3.1): ENVIRONMENTAL → PARKED/BLOCKED; SCOPE/SECURITY → FAILED (fail closed) |
| `BUSINESS_AMBIGUITY` | interpret/design | no | no | CLARIFICATION_REQUIRED |
| `UNSAFE_OPERATION` | classify/policy | no | no | FAILED + audit alert |
| `AMBIGUOUS_OUTCOME` | any ambiguous side-effecting attempt unresolved by bounded reconciliation | **never** | no | PARKED/BLOCKED; verified recovery/import, effect-result-unknown, compensation or abandonment |
| `LLM_BUDGET_EXCEEDED` | gateway | no | no | BLOCKED |
| `UNKNOWN` | any | no | **no** | BLOCKED |
