# Connector Architecture

**Task:** DE 001 (corrected by DE 001R1, DE 001R2A and DE 001R2B) · **Status:** ACCEPTED · ADR: DE-ADR-014

Connectors are the only code that talks to data/Git/deployment systems. Connector adapters
and LLM provider adapters are the only components that may resolve allow-listed
`SecretRef`s; each receives a scoped resolver that cannot enumerate or resolve another
adapter's secrets. Everything above them sees typed results.

---

## 1. Connector kinds

| Kind | Purpose | V1 instances | Future |
|---|---|---|---|
| `warehouse` | SQL execution, metadata, profiling, cost | Snowflake (real + fake) | BigQuery, Databricks SQL, Redshift, Fabric Warehouse |
| `database` | Relational sources | PostgreSQL synthetic source (real + fake) | MySQL, SQL Server, Oracle |
| `transformation` | Model compile/run/test/lineage | dbt-core with Snowflake adapter (real + fake) | SQLMesh, Spark jobs, Fabric notebooks |
| `vcs` | Branch, commit, PR | GitHub (real + fake) | GitLab, Azure DevOps |
| `orchestration` | Schedule and trigger pipelines | — | Airflow, Dagster, Fabric pipelines |
| `storage` | Object listing/loading | — | S3, Azure Blob, GCS |
| `api_source` | HTTP APIs | — | generic REST, Salesforce |
| `streaming` | Event streams | — | Kafka, Event Hubs |
| `bi` | Semantic and dashboard metadata | — | Power BI, Tableau, Looker |
| `catalog` | Governance metadata | — | Purview, Collibra, Unity Catalog |

---

## 2. Stable connector protocol

```python
class Connector(Protocol):
    spec: ConnectorSpec
    async def health(self) -> ConnectorHealthSnapshot
    async def reconcile(self, recovery: RecoveryContext) -> ReconcileResult
    async def close(self) -> None

class CapabilityImplementation(BaseModel, frozen=True):
    capability_id: CapabilityId
    supported_contract_versions: frozenset[int]
    input_schema_versions: frozenset[int]
    output_schema_versions: frozenset[int]

class ConnectorSpec(BaseModel, frozen=True):
    connector_id: str                         # e.g. "snowflake_dev"
    kind: ConnectorKind
    vendor: str                               # "snowflake", "dbt", "github", "postgres", "fake"
    version: str                              # connector implementation version
    target_environment: TargetEnv             # exactly one of DEV | STAGING | PROD
    identity_class: Literal["READ_ONLY", "DEVELOPMENT", "STAGING_DEPLOY", "VCS"]
    implementations: frozenset[CapabilityImplementation]
    # capability id + supported contract/input/output schema versions
    allowed_permissions: frozenset[PermissionLevel]  # every permission this instance may exercise; membership only, no ordering
    allow_list: ObjectAllowList               # databases/schemas/repos this instance may touch
    dialect: str | None                       # for SQL classification
    is_fake: bool

class CallContext(BaseModel, frozen=True):
    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str
    resolved_input_digest: str
    contract_snapshot_id: UUID
    attempt_id: UUID
    attempt_number: int
    claim_epoch: int
    cancellation_epoch: int
    deadline: datetime
    external_correlation: str
    redaction: RedactionPolicy

class RecoveryContext(BaseModel, frozen=True):
    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str
    resolved_input_digest: str
    resolved_input_schema_version: int
    capability: CapabilityContractRef
    connector_id: str
    connector_version: str
    target_environment: TargetEnv
    attempts: tuple[AttemptRecoveryRef, ...]  # attempt ids, query/release/commit refs
    operation_locator: dict[str, str]         # typed allow-listed fields, never secrets
    reconcile_deadline: datetime

ReconcileResult = (
    EffectFound(output: BaseModel, external_ref: str | None)
    | NoEffect(evidence: str)
    | InProgress(external_ref: str, retry_after_seconds: int)
    | Unknown(reason: str, evidence: str | None)
)
```

`allowed_permissions` replaces any notion of a permission "ceiling": `PermissionLevel` is a
set of distinct grants with no ordering (`docs/PERMISSION_MODEL.md` §2), so the policy
engine checks `required_permission ∈ allowed_permissions` (rule R4) and a startup check
(R0) fails if an advertised capability's required permission is not listed. Warehouse and
database read capabilities additionally require `identity_class=READ_ONLY` (rule R4b).
V1 sets per instance are in `docs/PERMISSION_MODEL.md` §2.1.

Capability implementations are registered per connector as handlers:

```python
@implements("execute_query", contract_versions={1}, input_schema_versions={1}, output_schema_versions={1})
async def execute_query(self, req: ExecuteQueryInput, ctx: CallContext) -> ExecuteQueryOutput: ...
```

The Tool Registry resolves handlers by the phase-pinned capability and schema versions. A
connector that advertises an unsupported or absent handler fails startup. A handler
receives immutable validated input and `CallContext`—never a template or raw task.

**Identity and reconciliation duties.** A side-effecting handler propagates both operation
and attempt identity, persists any provider handle, and implements reconciliation from the
complete `RecoveryContext`. Reconciliation runs before retry for every ambiguous outcome,
including timeout, response loss, fail-after-effect, crash and lease expiry—not only lease
reaping. `InProgress` is bounded by the scheduler; exhausted checks park and never imply
absence. `EffectFound` output must validate against the pinned output contract. Handlers
must never derive operation identity from an attempt.

Every connector package provides:

| Element | Requirement |
|---|---|
| `real.py` | Vendor implementation |
| `fake.py` | Deterministic in-memory or fixture-backed implementation with the *same* handler set and `reconcile`, scriptable failures including `fail_after_effect(capability)` (effect applied, exception raised before return — drives the crash-recovery contract test) |
| `errors.py` | `map_error(exc) -> FailureClassification` — vendor error → failure class |
| `config.py` | Pydantic settings with `SecretRef` fields only |
| `dialect.py` | (warehouse/database) sqlglot dialect + object identifier quoting rules |
| `tests/` | Contract tests parametrized over real (skipped without credentials) and fake |
| `README.md` | Setup, required env var names, permissions, limitations |

---

## 3. Connector status

Health is represented by an immutable, TTL-bound value:

```python
class ConnectorHealthSnapshot(BaseModel, frozen=True):
    connector_id: str
    status: Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "MOCK"]
    checked_at: datetime
    expires_at: datetime
    missing_permissions: frozenset[PermissionLevel]
    reason_codes: tuple[str, ...]
```

An expired snapshot is environmental unavailability until refreshed. The product-visible
status has these execution-readiness semantics:

| Status | Meaning | Planner behaviour |
|---|---|---|
| `AVAILABLE` | Health check passed within TTL | Eligible |
| `DEGRADED` | Health passed but with warnings (latency, partial permissions, rate limited) | Eligible; tasks get extended timeouts; UI badge |
| `UNAVAILABLE` | Health failed or credentials unresolved | Structurally valid plans remain accepted; policy/execution readiness parks materialized tasks (`ENVIRONMENTAL`) until health recovers |
| `MOCK` | Fake implementation active | Eligible; every artifact and UI element is watermarked "mock connector" |

Plan validation checks that the connector id, kind and pinned capability version exist; it
does not reject a plan for temporary health. Health is checked at startup and every
`health_ttl_seconds`; snapshots are cached in `connector_status`. Policy evaluates a fresh
snapshot and tests `required_permission ∈ missing_permissions`.

### 3.1 Contract snapshots, upgrades and provenance

- Connector advertisements include capability contract and payload schema compatibility;
  each phase run pins selected implementations in `contract_snapshot_id`.
- New phase runs may select upgraded implementations. In-flight runs continue on pinned
  versions. If a pinned version is absent from the runtime registry, the **scheduler**
  emits `CONTRACT_VERSION_UNAVAILABLE` (`docs/PERMISSION_MODEL.md` §3.2) and parks the
  work; no JSONB payload is silently reinterpreted.
- Every connector-produced artifact carries immutable `REAL|MOCK` execution mode,
  connector id/version, capability version, operation identity, resolved-input digest and
  transitive parent artifact ids.
- Policy denies real Git or deployment when any transitive input is MOCK-derived. An
  explicit promotion flow must recreate and validate it through real connectors; approval
  cannot waive this provenance boundary.

---

## 4. Explicit degraded behaviour

| Situation | Behaviour |
|---|---|
| Credentials missing | Status `UNAVAILABLE`, reason `SECRET_UNRESOLVED:<ENV_VAR_NAME>`; no retries; affected tasks `PARKED`, workflow `BLOCKED`; UI shows the env var **name** to set |
| Vendor rate limit | Map to `TRANSIENT_PROVIDER`; exponential backoff within task retry policy; status `DEGRADED` |
| Partial permission (can read metadata, cannot run queries) | `DEGRADED` with `missing_permissions`; policy rule R2b denies affected capabilities with `CONNECTOR_PERMISSION_MISSING` (deny class `ENVIRONMENTAL` → task `PARKED`, workflow `BLOCKED`) rather than attempting |
| Warehouse suspended / cold start | `DEGRADED`; first query timeout extended once |
| dbt adapter version mismatch | `UNAVAILABLE` at health; explicit message |
| GitHub token lacks `repo` write | `DEGRADED`; `prepare_git_change` denied pre-execution (`CONNECTOR_PERMISSION_MISSING`, parked) |
| Account usage views lagging | `get_cost_metrics` returns `as_of` timestamp and `complete=false` |

---

## 5. V1 connector specifications

### 5.1 Snowflake (`warehouse`)

| Aspect | Specification |
|---|---|
| Library | `snowflake-connector-python` (async via thread pool) |
| Identity | Separate instances and credentials. `snowflake_ro` has `identity_class=READ_ONLY` and uses `AIDE_DEV_RO` for every read capability (discover, describe, profile, sample, infer, validate/EXPLAIN, `execute_query`, metrics). `snowflake_dev` has `identity_class=DEVELOPMENT`, uses `AIDE_DEV_RW`, and advertises only DEV writes (`create_dataset`, `drop_dataset`); it does not list `READ`. Classifier checks are defence in depth, never a substitute for RO grants or R4b. `AIDE_STAGING_DEPLOY` is separate. |
| Session defaults | `STATEMENT_TIMEOUT_IN_SECONDS` from task deadline; `AUTOCOMMIT = TRUE`; warehouse from config. Every statement sets canonical `QUERY_TAG = aide:v1;wf=<uuid>;phase_run=<uuid>;task=<uuid>;op=<64-hex>;attempt=<uuid>;n=<int>`. The serializer/parser round-trips exact fields, rejects duplicate/unknown mandatory keys, and never truncates the operation key. |
| Capabilities | **RO instance:** `discover_assets`, `describe_asset`, `detect_schema_drift`, `profile_dataset`, `sample_dataset`, `infer_relationships`, `validate_query` (EXPLAIN), `execute_query`, `get_execution_metrics`, `get_cost_metrics`. **DEV instance:** `create_dataset`, `drop_dataset` (DEV). |
| Allow-list | Configured databases/schemas; DEV write schema pattern `AIDE_DEV.<WORKFLOW_SHORT_ID>_*` |
| Error mapping | Snowflake error codes: 001003 → `SQL_SYNTAX`; 002003 → `MISSING_OBJECT`; 000904 → `SCHEMA_MISMATCH` (invalid identifier); 100038/100040 → `TYPE_MISMATCH`; 003001/001011 → `PERMISSION_FAILURE`; 000630/604 → `TIMEOUT`/cancelled; 390114/network → `TRANSIENT_PROVIDER`; credit quota → `RESOURCE_LIMIT` |
| SQL safety | Parse and re-render with the Snowflake dialect, then reparse and require an equivalent normalized AST. Classify statement type, canonical scoped identifiers, functions, table functions, stages/URLs, UDFs, external functions and session constructs. Read paths use an explicit safe-function allow-list; external/unknown functions, stages/URLs, dynamic SQL, unknown AST nodes and role/session mutation are denied. Quoted identifiers are normalized with Snowflake case rules before allow-list checks. |
| Reconcile | Prefer the persisted Snowflake `query_id`; otherwise parse canonical `QUERY_TAG` and query exact operation identity. For object writes, verify provenance comment plus expected object shape. `RUNNING` query → `InProgress`; completed query with schema-valid result/effect → `EffectFound`; authoritative absence/rejection → `NoEffect`; history lag or unreachable service → `Unknown`. |
| Cost boundary | Query estimates, statement timeout, row/byte limits and tags bound/attribute work. They do **not** enforce a hard per-workflow credit cap. A true credit boundary requires an isolated warehouse/resource monitor outside the default MVP. |
| Fake | Backed by an in-process DuckDB database loaded from the synthetic fixtures with Snowflake→DuckDB transpilation via sqlglot; supports fault injection (`fail_next(capability, failure_class)`, `fail_after_effect(capability)`, latency, rename column to simulate drift) |

### 5.2 dbt (`transformation`)

| Aspect | Specification |
|---|---|
| Library | `dbt-core` 1.11.x invoked through `dbtRunner` **in a subprocess** per call (isolation from the API process, clean environment, hard timeout via process kill). Offline Cloud/CI target is `dbt-duckdb` 1.11.x. Live Snowflake adapter is **not** pinned in DE008A: `dbt-snowflake` 1.10+ requires `snowflake-connector-python>=4`, which conflicts with the DE006 pin `<4`. |
| Project | A dbt project repository checked out per workflow into an isolated working copy (`.aide/work/<workflow_id>/project`); `profiles.yml` generated from connector config with `SecretRef` resolved into the subprocess environment only |
| Capabilities | `create_transformation`, `compile_transformation`, `execute_transformation`, `run_pipeline`, `run_tests`, `get_lineage`, `deploy_staging` (strategy `DBT_RUN_TARGET`) |
| Artifacts | `manifest.json`, `run_results.json`, compiled SQL captured as artifacts |
| Error mapping | dbt `CompilationError` → `DBT_COMPILE`; `DatabaseError` → re-mapped through the Snowflake mapper (so a renamed column yields `SCHEMA_MISMATCH`, not generic `DBT_RUNTIME`); test `fail` → `DBT_TEST`; `RuntimeError` unknown → `DBT_RUNTIME` |
| Effect safety and journal | Each invocation gets an immutable directory keyed by operation and attempt plus an append-only journal of selected nodes, compiled SQL/config/hooks/macros, dispatch, adapter response and artifact hashes. Side-effecting dbt execution defaults to `NON_IDEMPOTENT`; a materialization may be marked `PROVEN_CONVERGENT` only after validated unique keys, deterministic SQL, no unsafe hooks/macros/snapshots, and an invocation-specific convergence validator. Partial DAG completion is never adopted as whole-run success. |
| Reconcile | Read the invocation journal and unique `run_results.json`, then query provider history by canonical operation tag. Return `EffectFound` only when every required node has schema-valid results; running nodes return `InProgress`; incomplete/indeterminate work returns `Unknown`. `create_transformation` compares file hashes. `deploy_staging` verifies `release_id` in `AIDE_STAGING.__AIDE_RELEASES`. |
| Fake (unit tests) | Lightweight deterministic fake: executes generated SQL against the fake warehouse's DuckDB, emulating `ref`/`source` resolution and dbt's generic tests; produces real `manifest.json`-shaped output; fast enough for the unit suite and CI scenarios. Retained regardless of the note below |
| Integration target (DE 008 evaluation) | **Adopted (DE008A):** real dbt Core `1.11.15` + `dbt-duckdb` `1.11.0` against Vantara tiny DuckDB fixtures. Evidence: parser and Jinja execute, models compile, view/table materializations run, generic tests execute, `manifest.json` and `run_results.json` are produced, fixture row counts query successfully, CI-suitable runtimes. Lightweight fake retained for unit tests. Live Snowflake `dbt` validation remains LOCAL (`READY_FOR_LIVE_DBT_VALIDATION`). `dbt-core` 1.12 was not adopted (heavier metricflow stack). |

### 5.3 GitHub (`vcs`)

| Aspect | Specification |
|---|---|
| Library | `git` CLI via subprocess wrapper for local operations; GitHub REST v3 via `httpx` for PRs (no heavy SDK) |
| Identity | Fine-grained PAT or GitHub App installation token via `SecretRef`, scoped to the target repository, **no admin scopes** |
| Capabilities | `prepare_git_change`, `prepare_pull_request`; `deploy_production(strategy=MERGE_PR)` is not advertised in V1 |
| Guarantees | Never touches protected branches; never force-pushes; runs `gitleaks`-style secret scan on the diff before commit; bot author identity fixed |
| Reconcile | `prepare_git_change`: branch exists on remote with a commit whose trailer `Aide-Idempotency-Key` equals the key → `EffectFound(commit_sha)`; `prepare_pull_request`: open PR with the same head branch → `EffectFound(pr_number)` |
| Fake | Bare local repository in a temp dir + in-memory PR store; supports `fail_after_effect` |

### 5.4 PostgreSQL synthetic source (`database`)

| Aspect | Specification |
|---|---|
| Library | `psycopg` 3 (async) |
| Role | Read-only role `aide_source_ro` |
| Capabilities | `discover_assets`, `describe_asset`, `detect_schema_drift`, `profile_dataset`, `sample_dataset`, `infer_relationships`, `execute_query` |
| Use | Represents source operational systems for the synthetic company; loaded into Snowflake RAW by the synthetic loader script (not by the agent in V1) |
| Fake | DuckDB-backed, same fixtures |

---

## 6. Adding a connector — checklist (no core changes)

1. Create `src/aide/connectors/<vendor>/` with `real.py`, `fake.py`, `errors.py`, `config.py`, (`dialect.py`).
2. Declare `ConnectorSpec.implementations` with supported contract/schema versions and the `allowed_permissions` set.
3. Implement each advertised version and `reconcile` for every side-effecting capability; propagate `ctx.operation_idempotency_key` and `ctx.attempt_id`.
4. Map vendor errors to failure classes.
5. Add configuration entry (`connectors.yaml` + env var names) and permission mapping in `config/permissions/<connector_id>.yaml`.
6. Run the **connector contract test suite** (`tests/connectors/contract/`) against the fake; against the real system when credentials exist.
7. Write `README.md`.
8. Register the module in `connectors/registry_entries.py` (one line).

If a new connector needs a capability that does not exist, that is an additive Capability
Registry change with synchronized contracts and normal review under DE-ADR-026. An ADR is
required only when existing semantics or an architecture boundary changes.

---

## 7. Isolation and concurrency

- One connector *instance* per (vendor, environment, identity). Instances are shared across
  workflows; handlers are stateless per call.
- Connection pooling per instance with a hard maximum; a task waiting for a connection
  counts against its timeout.
- dbt runs are subprocesses with their own working copy per workflow; concurrent workflows
  cannot collide on the file system.
- Snowflake DEV objects are namespaced by workflow short id, so concurrent workflows never
  share tables.

---

## 8. Testing strategy for connectors

| Layer | What | Runs where |
|---|---|---|
| Contract tests | Same test module runs against fake and real; asserts schemas, error mapping, allow-list enforcement, timeout behaviour, `allowed_permissions` covers advertised capabilities, and crash recovery (`fail_after_effect` → `reconcile` → exactly one external effect) | CI (fake), LOCAL (real, opt-in via env) |
| Fault injection | Fake `fail_next()`, `fail_after_effect()` and `rename_column()` scripts used by repair-loop tests, recovery tests and evaluation scenarios | CI |
| Recorded fixtures | Optional recorded real responses (redacted) for regression of error mappers | CI |
| Live smoke | `aide connectors check` against real DEV | LOCAL, manual |
