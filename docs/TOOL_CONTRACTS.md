# Tool Contracts

**Task:** DE 001 · **Status:** PROPOSED

Per-capability contracts. Schemas are given in Pydantic-like notation; the implementation
must match field names so the planner catalogue, UI and evaluation harness share one
vocabulary. Field types ending in `Ref` are identifiers of persisted objects, never inline
blobs.

Shared conventions for **every** capability:

- **Audit metadata (always recorded):** `workflow_id`, `task_id`, `idempotency_key` (operation
  identity), `attempt_id`, `attempt_number`, `capability_id@version`,
  `connector_id`, `target_environment`, `policy_decision_id`, `started_at`, `finished_at`,
  `duration_ms`, `status`, `failure_class`, `input_digest` (sha256 of validated input),
  `output_digest`, `redacted_input_excerpt`, `redacted_output_excerpt`.
- **Retry policy notation:** `retry(n, backoff, on={classes})` — `n` total attempts including
  the first; retries apply only to listed failure classes (see `docs/PERMISSION_MODEL.md` §10).
  Every attempt of a task shares the task's `idempotency_key`; the attempt number is never
  part of the operation identity (`docs/STATE_MODEL.md` §4.2, §4.6).
- **`Idempotent` row semantics:** `yes` — safe to re-execute after a crash (re-execution
  converges); `no` — never re-executed automatically after an ambiguous attempt; the
  connector must implement `reconcile` for every side-effecting capability regardless.
- **Permission row semantics:** the single `PermissionLevel` the capability requires; policy
  checks membership in the workflow grant set and in the connector's `allowed_permissions`
  (`docs/PERMISSION_MODEL.md` §3). Permissions are never compared by rank.
- **Timeouts** are enforced by the Tool Registry wrapper *and* passed to the connector
  (e.g., Snowflake `STATEMENT_TIMEOUT_IN_SECONDS`) so a hung driver cannot outlive the task.
- **Failure classes** listed are the ones the connector must map to; anything else → `UNKNOWN`.

---

## 0. Shared types

```python
AssetRef      = {connector_id: str, database: str|None, schema: str|None, name: str, kind: "TABLE"|"VIEW"|"FILE"|"EXTERNAL"}
ColumnSpec    = {name: str, data_type: str, nullable: bool, ordinal: int, comment: str|None, is_untrusted_text: True}
SqlText       = {dialect: "snowflake"|"postgres"|"ansi", text: str, classification: SqlClassification|None}
SqlClassification = {statement_types: list[str], objects_read: list[AssetRef], objects_written: list[AssetRef],
                     is_read_only: bool, is_destructive: bool, is_multi_statement: bool, has_dynamic_sql: bool}
ArtifactRef   = {artifact_id: UUID, sha256: str, type: ArtifactType, version: int}
Budget        = {max_rows: int, max_bytes: int, max_seconds: int}
TargetEnv     = "DEV" | "STAGING" | "PROD"       # bound on the connector instance
```

---

## 1. `discover_assets` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Enumerate assets inside an allow-listed scope. |
| Input | `{scope: {databases: list[str], schemas: list[str]|None, include_views: bool}, filters: {name_pattern: str|None}}` — scope must be a subset of the connector's configured allow-list; otherwise `POLICY_DENIED` (`SCOPE_VIOLATION`, fail closed) before execution. |
| Output | `{assets: list[AssetRef & {row_count_estimate: int|None, last_altered: datetime|None, comment: str|None}], snapshot_id: UUID, truncated: bool}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 120 s / `retry(3, exp, on={TRANSIENT_PROVIDER, CONNECTOR_FAILURE})` |
| Failure classes | `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER`, `TIMEOUT` |
| Validation | Every returned asset must lie within `scope`; snapshot persisted with hash; `truncated` must be set if connector paging stopped early. |
| Connector | REQUIRED: warehouse, database, or storage kind. Snowflake: `SHOW TABLES/VIEWS IN SCHEMA` + `INFORMATION_SCHEMA`. PostgreSQL: `information_schema`. |
| Idempotent | yes |

## 2. `describe_asset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Column-level metadata for one asset. |
| Input | `{asset: AssetRef, include_constraints: bool, include_row_count: bool}` |
| Output | `{asset: AssetRef, columns: list[ColumnSpec], primary_key: list[str]|None, unique_keys: list[list[str]], foreign_keys: list[{columns, ref_asset, ref_columns}], row_count: int|None, clustering: list[str]|None, snapshot_id: UUID}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 60 s / `retry(3, exp, on={TRANSIENT_PROVIDER, CONNECTOR_FAILURE})` |
| Failure classes | `MISSING_OBJECT`, `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER`, `TIMEOUT` |
| Validation | Column names unique; `comment` fields flagged `is_untrusted_text`. |
| Connector | REQUIRED |
| Idempotent | yes |

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
| Idempotent | yes |

## 4. `select_relevant_assets` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Choose which catalogued assets matter for the requirement. |
| Input | `{requirement: RequirementSpecRef, catalogue_snapshot_id: UUID, max_assets: int}` — the prompt receives asset names, comments (delimited as untrusted), column names and row counts; **no sample data**. |
| Output | `{selected: list[{asset: AssetRef, role: "SOURCE"|"REFERENCE"|"LOOKUP", reason: str, confidence: float}], excluded_notable: list[{asset, reason}]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 90 s / `retry(2, fixed, on={TRANSIENT_PROVIDER, OUTPUT_INVALID})` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `TIMEOUT`, `LLM_BUDGET_EXCEEDED` |
| Validation | Every `selected.asset` ∈ catalogue snapshot (Det subset check); `len(selected) ≤ max_assets`; reasons non-empty. Violations → `OUTPUT_INVALID` → one retry with the violation appended → then `BLOCKED` for human. |
| Connector | NONE |
| Idempotent | yes (replayable via prompt version + inputs) |

## 5. `profile_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Statistics per column and dataset with budget. |
| Input | `{asset: AssetRef, columns: list[str]|None, budget: Budget, sample_fraction: float|None, top_k: int}` |
| Output | `{asset, row_count: int, sampled: bool, columns: list[{name, null_ratio, distinct_ratio, min, max, mean|None, top_values: list[{value_masked, count}], inferred_semantic: "ID"|"DATE"|"AMOUNT"|"CODE"|"TEXT"|"FLAG"|None}], candidate_keys: list[{columns, uniqueness_ratio}], duplicate_groups_estimate: int, profile_id: UUID}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 300 s / `retry(2, exp, on={TRANSIENT_PROVIDER, TIMEOUT})` (second attempt halves the budget) |
| Failure classes | `MISSING_OBJECT`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER` |
| Validation | Ratios ∈ [0,1]; `top_values` masked when column classified sensitive by heuristics (email, phone, name patterns); profile SQL generated from templates only (no LLM). |
| Connector | REQUIRED |
| Idempotent | yes |

## 6. `sample_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Small masked sample for LLM reasoning and human display. |
| Input | `{asset: AssetRef, columns: list[str]|None, n: int ≤ 20, where: SqlText|None (must classify read-only, single statement)}` |
| Output | `{rows: list[dict[str, str|int|float|bool|None]], masked_columns: list[str], sample_id: UUID}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 60 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | as `profile_dataset` + `UNSAFE_OPERATION` (if `where` fails classification) |
| Validation | `n ≤ 20` enforced by wrapper; sensitive columns masked before persistence; total bytes ≤ 64 KB. |
| Connector | REQUIRED |
| Idempotent | no (data may change) — flagged `non_deterministic` in artifact |

## 7. `infer_relationships` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Candidate joins via inclusion-dependency sampling. |
| Input | `{assets: list[AssetRef], profiles: list[UUID], max_pairs: int, budget: Budget}` |
| Output | `{candidates: list[{from_asset, from_columns, to_asset, to_columns, inclusion_ratio, cardinality: "1:1"|"1:N"|"N:M", confidence}], relationships_id: UUID}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 300 s / `retry(2, exp, on={TRANSIENT_PROVIDER, TIMEOUT})` |
| Failure classes | as `profile_dataset` |
| Validation | Only column pairs with compatible types and `inferred_semantic ∈ {ID, CODE}` tested; `inclusion_ratio ∈ [0,1]`. |
| Connector | REQUIRED |
| Idempotent | yes |

## 8. `classify_sql` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Parse SQL and classify safety attributes. Used by policy and as a pre-validator. |
| Input | `{sql: SqlText}` |
| Output | `SqlClassification & {parse_ok: bool, parse_error: str|None, normalized_sql: str}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 10 s / none |
| Failure classes | `SQL_SYNTAX` (unparseable) |
| Validation | Unparseable SQL is classified `is_read_only=False, is_destructive=True` (fail closed). Statement types recognized: SELECT, WITH, SHOW, DESCRIBE, EXPLAIN → read-only; CREATE/ALTER/INSERT/UPDATE/MERGE/COPY → write; DROP/TRUNCATE/DELETE without WHERE/ALTER … DROP COLUMN → destructive; CALL/EXECUTE IMMEDIATE/GRANT/REVOKE/USE ROLE → `has_dynamic_sql` or security → denied. |
| Connector | NONE (sqlglot with dialect registry) |
| Idempotent | yes |

## 9. `validate_query` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Dry-run compile / explain without side effects. |
| Input | `{sql: SqlText, mode: "EXPLAIN"|"COMPILE"}` |
| Output | `{valid: bool, error: {code: str|None, message: str, line: int|None, object: str|None}|None, plan_summary: {estimated_bytes: int|None, partitions_total: int|None, partitions_scanned: int|None}|None}` |
| Permission / Risk / Approval | READ / LOW / NEVER |
| Timeout / Retry | 60 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TRANSIENT_PROVIDER` — returned **as output** (`valid=false`) not as task failure, so generation can iterate. |
| Validation | Pre-validator `classify_sql` must return `is_read_only=True` or the statement must be a CREATE VIEW/TABLE AS in a DEV schema (EXPLAIN only). |
| Connector | REQUIRED(warehouse). Snowflake: `EXPLAIN USING JSON`. |
| Idempotent | yes |

## 10. `execute_query` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Execute a **read-only** statement with caps; used by profiling, quality checks, reconciliation. |
| Input | `{sql: SqlText, budget: Budget, query_tag: str (workflow/task), result_mode: "ROWS"|"SCALAR"|"COUNT_ONLY"}` |
| Output | `{rows: list[dict]|None, scalar: Any|None, row_count: int, bytes_scanned: int|None, duration_ms: int, query_id: str|None, truncated: bool}` |
| Permission / Risk / Approval | READ (strictly read-only; temporary objects are not supported in V1 — use `create_dataset`) / MEDIUM / NEVER |
| Timeout / Retry | `budget.max_seconds` ≤ 300 / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `TRANSIENT_PROVIDER`, `UNSAFE_OPERATION` |
| Validation | Pre-validator: `classify_sql.is_read_only == True`, `is_multi_statement == False`, `has_dynamic_sql == False`, all `objects_read` within connector allow-list. Wrapper adds `LIMIT` when `result_mode == ROWS`. Rows persisted only as artifact when ≤ `max_rows`; otherwise `COUNT_ONLY`. |
| Connector | REQUIRED(warehouse\|database). Connector instance must be bound to `DEV` in V1. |
| Idempotent | yes (read-only) |

## 10a. `generate_sql_query` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | One SQL statement for investigation-type requests or a single development table (DE 002 slice); not a substitute for dbt generation. |
| Input | `{requirement: RequirementSpecRef, selected_assets: list[AssetRef], metadata: list[UUID], dialect, target: AssetRef|None (DEV namespace; when set the output must be a single CREATE TABLE AS SELECT), prior_attempt_feedback: list[ValidationFeedback]|None}` |
| Output | `{sql: SqlText, explanation: str, expected_columns: list[{name, type_hint}], expected_grain: list[str]|None, assumptions: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 120 s / `retry(2, fixed, on={TRANSIENT_PROVIDER, OUTPUT_INVALID})` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `TIMEOUT`, `LLM_BUDGET_EXCEEDED` |
| Validation (Det, mandatory) | `classify_sql`: single statement, no dynamic SQL; if `target` is null → `is_read_only`; else exactly one write to `target` inside the DEV namespace and the inner query read-only; all referenced objects ∈ `selected_assets` ∪ `target`; `validate_query` (EXPLAIN) valid; `expected_columns` ⊆ EXPLAIN/describe output after execution. |
| Connector | NONE |
| Idempotent | replayable |

## 11. `create_dataset` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | Create/replace table or view in DEV. |
| Input | `{target: AssetRef (schema must be in DEV allow-list), definition: SqlText (CREATE [OR REPLACE] TABLE|VIEW … AS SELECT), replace: bool}` |
| Output | `{created: AssetRef, replaced_existing: bool, row_count: int|None}` |
| Permission / Risk / Approval | DEVELOPMENT_WRITE / MEDIUM / IF_POLICY_FLAGS (flag: `replace=True` on an object not created by this workflow) |
| Timeout / Retry | 600 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `UNSAFE_OPERATION` |
| Validation | `classify_sql.objects_written == [target]`; no other writes; target schema ∈ DEV allow-list; provenance tag comment on the created object carrying `workflow_id` and `idempotency_key`. |
| Connector | REQUIRED(warehouse), bound to DEV |
| Idempotent | yes when `replace=True`; otherwise `reconcile` finds the object by provenance tag (`EffectFound`) so a crashed attempt is adopted, not repeated |

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
| Idempotent | yes (`reconcile`: object absent → `EffectFound(dropped=true)`) |

## 13. `generate_transformation` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Produce SQL/YAML/tests for one design unit (a model). |
| Input | `{design_unit: ModelDesignUnitRef, metadata: list[UUID] (describe snapshots), profiles: list[UUID], samples: list[UUID]|None, conventions: ProjectConventions, dialect, prior_attempt_feedback: list[ValidationFeedback]|None}` |
| Output | `{files: list[{path: str, content: str, kind: "MODEL_SQL"|"SCHEMA_YML"|"SOURCE_YML"|"MACRO"|"SNAPSHOT"|"DOC_MD"}], tests_declared: list[TestSpec], assumptions: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 180 s / `retry(2, fixed, on={TRANSIENT_PROVIDER, OUTPUT_INVALID})` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `TIMEOUT`, `LLM_BUDGET_EXCEEDED` |
| Validation (Det, mandatory) | Every `MODEL_SQL` passes `classify_sql` as a single read-only SELECT (dbt wraps materialization); references only `ref()`/`source()` to known models/sources; every column in `SCHEMA_YML` exists in the compiled model (checked after `compile_transformation`); declared grain keys match `design_unit.grain`; `path` inside project model dir; no Jinja `run_query` or `execute` blocks; file size ≤ 200 KB. |
| Connector | NONE |
| Idempotent | replayable |

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
| Idempotent | yes |

## 15. `compile_transformation` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | `dbt parse` + `dbt compile` for selection. |
| Input | `{project_state_id: UUID, select: list[str]|None, target: "DEV"}` |
| Output | `{ok: bool, manifest_ref: ArtifactRef|None, compiled: list[{model, compiled_sql_ref}], errors: list[{model|None, message, class}]}` |
| Permission / Risk / Approval | DEVELOPMENT_EXECUTE / LOW / NEVER |
| Timeout / Retry | 300 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `DBT_COMPILE` (as output `ok=false`), `CONNECTOR_FAILURE`, `TIMEOUT` |
| Validation | Manifest parsed and stored as artifact; every compiled SQL re-classified via `classify_sql` (must be non-destructive; dbt materializations write only to the DEV target schema). |
| Connector | REQUIRED(transformation) |
| Idempotent | yes |

## 16. `execute_transformation` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | `dbt run --select …` in DEV. |
| Input | `{project_state_id: UUID, select: list[str], full_refresh: bool, target: "DEV", query_tag: str}` |
| Output | `{ok: bool, results: list[{model, status: "success"|"error"|"skipped", execution_time_s, rows_affected|None, message|None, error_class|None}], run_results_ref: ArtifactRef}` |
| Permission / Risk / Approval | DEVELOPMENT_EXECUTE / MEDIUM / NEVER |
| Timeout / Retry | 900 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `DBT_RUNTIME`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `PERMISSION_FAILURE`, `TIMEOUT`, `RESOURCE_LIMIT`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER` |
| Validation | Target profile must be the DEV profile bound to the connector; `run_results.json` parsed; per-model error text mapped to failure class by the dbt/Snowflake error mapper. |
| Connector | REQUIRED(transformation), DEV |
| Idempotent | yes for table/view materializations; incremental runs are idempotent by design (merge) |

## 17. `run_pipeline` (deterministic, v1)

As `execute_transformation` but `dbt build` (run + test + snapshot + seed) for the whole
project or selection. Output adds `tests: list[TestResult]`. Timeout 900 s. Failure classes
add `DBT_TEST`.

## 18. `run_tests` (deterministic, v1)

| Field | Value |
|---|---|
| Purpose | `dbt test --select …`; structured results. |
| Input | `{project_state_id: UUID, select: list[str]|None, store_failures: bool}` |
| Output | `{ok: bool, tests: list[{test_name, model, column|None, status: "pass"|"fail"|"warn"|"error", failures: int|None, failing_rows_sample_ref: ArtifactRef|None}], run_results_ref}` |
| Permission / Risk / Approval | DEVELOPMENT_EXECUTE / LOW / NEVER |
| Timeout / Retry | 600 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `DBT_TEST` (as output), `DBT_RUNTIME`, `CONNECTOR_FAILURE`, `TIMEOUT` |
| Validation | Failing-row samples capped at 20 rows and masked. |
| Connector | REQUIRED(transformation) |
| Idempotent | yes |

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
| Idempotent | yes |

## 20. `diagnose_failure` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Produce a `RepairProposal`. |
| Input | `{evidence: InspectFailureOutput, artifact_under_repair: ArtifactRef, forbidden_hypotheses: list[str] (hashes of prior hypotheses)}` |
| Output | `{diagnosis: str, root_cause_class: FailureClass, hypothesis: str, hypothesis_hash: str, patch: {file_path, new_content}|{sql_ref}, expected_validation: list[ValidatorId], confidence: float, requires_human: bool, human_question: str|None}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 120 s / `retry(2, fixed, on={TRANSIENT_PROVIDER, OUTPUT_INVALID})` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `LLM_BUDGET_EXCEEDED` |
| Validation | `hypothesis_hash ∉ forbidden_hypotheses`; `root_cause_class` must be in the repairable set unless `requires_human=True`; patch must target the artifact under repair or its direct upstream in the same phase; patched SQL passes `classify_sql` and `validate_query`. |
| Connector | NONE |
| Idempotent | replayable |

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
| Idempotent | yes |

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
| Timeout / Retry | 120 s / `retry(2, exp, on={TRANSIENT_PROVIDER})` |
| Failure classes | `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `TRANSIENT_PROVIDER`, `UNSAFE_OPERATION` |
| Validation | Never pushes to `main`/protected branches; never force-pushes; secret scan of file contents before commit (fail closed, `SECRET_IN_DIFF`); commit message is an artifact; commit carries trailer `Aide-Idempotency-Key: <idempotency_key>`. |
| Connector | REQUIRED(vcs) |
| Idempotent | yes (same tree → same commit; re-push is no-op; `reconcile` finds the commit by trailer) |

## 26. `prepare_pull_request` (deterministic, v1)

Input `{repository_ref, head_branch, base_branch, title, body_ref: ArtifactRef, labels: list[str], draft: bool}`; output `{pr_number, url, state}`. GIT_WRITE / MEDIUM / IF_POLICY_FLAGS (default no approval; configurable to ALWAYS). 60 s. Never merges. Idempotent: updates existing PR for the same head; `reconcile` finds the open PR by head branch.

## 27. `deploy` (deterministic, v1 — gated)

| Field | Value |
|---|---|
| Purpose | Promote an artifact set to a target environment. |
| Input | `{artifact_set, target: "STAGING"|"PROD", strategy: "DBT_RUN_TARGET"|"MERGE_PR"|"ORCHESTRATOR_RELEASE", approval_id: UUID, release_id: str}` — `release_id` is generated by the Delivery service and persisted as an intent row **before** the call (`docs/STATE_MODEL.md` §4.6). |
| Output | `{deployed: bool, target, release_id: str, rollback_ref: str|None}` |
| Permission / Risk / Approval | STAGING_DEPLOY (HIGH) or PRODUCTION_WRITE (CRITICAL) / ALWAYS |
| Timeout / Retry | 900 s / none. Definite failure → `FAILED`, human decides. Ambiguous attempt (crash, timeout, lost connection) → `reconcile(release_id)`; if `Unknown` → `AMBIGUOUS_OUTCOME`, task `PARKED`, workflow `BLOCKED`; **never re-executed automatically**. |
| Failure classes | `PERMISSION_FAILURE`, `CONNECTOR_FAILURE`, `DBT_RUNTIME`, `TIMEOUT`, `UNSAFE_OPERATION`, `AMBIGUOUS_OUTCOME` |
| Validation | `approval_id` must be APPROVED, unexpired, and bound to the exact artifact hashes and to this operation's `idempotency_key`; connector instance must be bound to `target`; V1 ships only `STAGING` with a staging-like dbt target; `PROD` returns `POLICY_DENIED` (`PROD_DISABLED_V1`, fail closed). |
| Connector | REQUIRED(transformation\|orchestration); must implement `reconcile` by looking up `release_id` in the target's release marker |
| Idempotent | no |

## 28. `register_monitor` / 29. `check_monitor` (deterministic, v1)

`register_monitor` input `{kind: "FRESHNESS"|"TEST_SUITE"|"ROW_COUNT"|"COST", target: AssetRef|model, threshold, schedule_hint}` → `{monitor_id}` (artifact only in V1). `check_monitor` input `{monitor_id}` → `{status: "OK"|"WARN"|"FAIL", observed, threshold, checked_at}`. DW / READ, LOW, NEVER.

## 30. `interpret_requirement` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Natural language → typed spec. |
| Input | `{text: str (≤ 8 000 chars), prior_clarifications: list[{question, answer}], organisation_glossary: list[{term, definition}]|None}` |
| Output | `RequirementSpec = {goal: str, deliverable_type: "ANALYTICAL_DATA_PRODUCT"|"PIPELINE"|"MODEL_CHANGE"|"QUALITY_SUITE"|"INVESTIGATION", business_entities: list[{name, description}], metrics: list[{name, definition|None, ambiguous: bool}], grain_hints, history_requirements: "NONE"|"CURRENT_ONLY"|"FULL_HISTORY"|"UNKNOWN", freshness_requirement, consumers, constraints, ambiguities: list[{topic, question, options: list[str], blocking: bool}], out_of_scope: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 90 s / `retry(2, fixed, on={TRANSIENT_PROVIDER, OUTPUT_INVALID})` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `LLM_BUDGET_EXCEEDED`, `BUSINESS_AMBIGUITY` (if blocking ambiguities remain after max rounds) |
| Validation | Blocking ambiguities → `emit_clarification`; the Det rule "metrics without definition are ambiguous" is applied regardless of LLM flag. |
| Connector | NONE |

## 31. `plan_phase` (reasoning, v1)

| Field | Value |
|---|---|
| Purpose | Task DAG for the next phase. |
| Input | `{workflow_context_ref, phase: WorkflowState, capability_catalogue: list[{id, purpose, permission, risk, input_fields}], constraints: {max_tasks, granted_permissions, available_connectors: list[{connector_id, kind, capabilities, status}]}}` |
| Output | `Plan = {phase, tasks: list[{local_id, capability_id, connector_id|None, depends_on: list[local_id], inputs: dict, rationale: str}], phase_exit_criteria: list[str], assumptions: list[str]}` |
| Permission / Risk / Approval | READ / MEDIUM / NEVER |
| Timeout / Retry | 120 s / `retry(2, fixed, on={TRANSIENT_PROVIDER, OUTPUT_INVALID})` |
| Failure classes | `OUTPUT_INVALID`, `TRANSIENT_PROVIDER`, `LLM_BUDGET_EXCEEDED` |
| Validation | Every `capability_id` ∈ catalogue; every `connector_id` advertises that capability and is `AVAILABLE|DEGRADED|MOCK`; DAG acyclic; `len(tasks) ≤ max_tasks`; required permission of each task ∈ `granted_permissions ∪ APPROVAL_ELIGIBLE` and ∈ the chosen connector's `allowed_permissions` (set membership, never rank); policy pre-check on static inputs passes (`docs/PERMISSION_MODEL.md` §3.1); inputs validate against capability input schema (unresolved references to prior outputs allowed via `{"$from": local_id, "path": ...}` placeholders that Det resolves at runtime). |
| Connector | NONE |

## 32. `propose_model_design` (reasoning, v1)

Input `{requirement_ref, architecture_decision: ArchitectureDecision (Det-selected, see docs/DATA_MODELLING_STRATEGY.md), selected_assets, metadata, profiles, relationships}`; output `ModelDesign = {layers: list, models: list[ModelDesignUnit{name, layer, kind: STAGING|INTERMEDIATE|DIMENSION|FACT|MART|SNAPSHOT, grain: list[str], surrogate_key, natural_keys, scd_type|None, incremental: {strategy, unique_key, watermark_column}|None, sources: list, columns: list[{name, expression_hint, type, tests}], dedup_rule|None}], relationships, tests, open_questions}`. READ / MEDIUM / NEVER. 180 s. Validation: architecture class matches Det decision; each grain is a candidate key or a declared dedup rule exists; every source column referenced exists in metadata; SCD2 units have a valid change-tracking column set.

## 33. `summarize_for_human` (reasoning, v1)

Input `{workflow_ref, audience: "ENGINEER"|"BUSINESS"|"APPROVER", scope}`; output `{markdown}`. READ / LOW / NEVER. 60 s. Validation: must not contain content absent from persisted state (checked by referencing ids); size ≤ 20 KB.

## 34. `emit_clarification` (control, v1)

Input `{questions: list[{topic, question, options, blocking}]}`; output `{clarification_id}`. Transitions workflow to `CLARIFICATION_REQUIRED`. Max 2 rounds per workflow (Det).

## 35. `request_approval` (control, v1)

Input `{kind: "DESIGN"|"GIT"|"DEPLOY"|"DESTRUCTIVE"|"COST", requested_permission, artifact_hashes: list[str], summary_ref}`; output `{approval_id, status: "PENDING"}`. Transitions workflow to `APPROVAL_REQUIRED`. Approval is invalidated if any bound artifact hash changes.

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
| `CONNECTOR_FAILURE` | any connector | yes (per policy) | no | BLOCKED |
| `TRANSIENT_PROVIDER` | any | yes | no | BLOCKED after retries |
| `TIMEOUT` | any | yes (profiling with reduced budget) | no | BLOCKED |
| `RESOURCE_LIMIT` | warehouse | no | no | BLOCKED (cost gate) |
| `PERMISSION_FAILURE` | any | no | no | task PARKED; workflow BLOCKED (human fixes grants) |
| `POLICY_DENIED` | policy | no | no | by deny class (`docs/PERMISSION_MODEL.md` §3.1): ENVIRONMENTAL → PARKED/BLOCKED; SCOPE/SECURITY → FAILED (fail closed) |
| `BUSINESS_AMBIGUITY` | interpret/design | no | no | CLARIFICATION_REQUIRED |
| `UNSAFE_OPERATION` | classify/policy | no | no | FAILED + audit alert |
| `AMBIGUOUS_OUTCOME` | non-idempotent capability after crash/timeout with `Unknown` reconcile | **never** | no | PARKED/BLOCKED; human reconciles |
| `LLM_BUDGET_EXCEEDED` | gateway | no | no | BLOCKED |
| `UNKNOWN` | any | no | **no** | BLOCKED |
