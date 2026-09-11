# Connector Architecture

**Task:** DE 001 (corrected by DE 001R1) · **Status:** PROPOSED · ADR: DE-ADR-014

Connectors are the only code that talks to external systems and the only code that resolves
secrets. Everything above them sees typed capability results. Adding a connector must not
touch `aide.orchestration`, `aide.policy`, `aide.capabilities` or `aide.domain`.

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
    spec: ConnectorSpec                       # id, kind, vendor, version, environment, capabilities
    async def health(self) -> ConnectorHealth # cheap; used for status
    async def reconcile(self, capability_id: CapabilityId, idempotency_key: str,
                        ctx: CallContext) -> ReconcileResult   # crash recovery, docs/STATE_MODEL.md §4.6
    async def close(self) -> None

class ConnectorSpec(BaseModel, frozen=True):
    connector_id: str                         # e.g. "snowflake_dev"
    kind: ConnectorKind
    vendor: str                               # "snowflake", "dbt", "github", "postgres", "fake"
    version: str                              # connector implementation version
    target_environment: TargetEnv             # exactly one of DEV | STAGING | PROD
    capabilities: frozenset[CapabilityId]     # advertised implementations
    allowed_permissions: frozenset[PermissionLevel]  # every permission this instance may exercise; membership only, no ordering
    allow_list: ObjectAllowList               # databases/schemas/repos this instance may touch
    dialect: str | None                       # for SQL classification
    is_fake: bool

class CallContext(BaseModel, frozen=True):
    workflow_id: UUID
    task_id: UUID
    idempotency_key: str                      # operation identity — stable across attempts; use for dedup/reconcile
    attempt_id: UUID                          # execution attempt identity — use for tagging/diagnostics only
    attempt_number: int
    deadline: datetime
    query_tag: str                            # "aide:wf=<id>;task=<id>;op=<idempotency_key[:16]>;attempt=<n>"
    redaction: RedactionPolicy

ReconcileResult = EffectFound(output: BaseModel, external_ref: str | None) | NoEffect() | Unknown(reason: str)
```

`allowed_permissions` replaces any notion of a permission "ceiling": `PermissionLevel` is a
set of distinct grants with no ordering (`docs/PERMISSION_MODEL.md` §2), so the policy
engine checks `required_permission ∈ allowed_permissions` (rule R4) and a startup check
(R0) fails if an advertised capability's required permission is not listed. V1 sets per
instance are in `docs/PERMISSION_MODEL.md` §2.1.

Capability implementations are registered per connector as handlers:

```python
@implements("execute_query")
async def execute_query(self, req: ExecuteQueryInput, ctx: CallContext) -> ExecuteQueryOutput: ...
```

The Tool Registry discovers handlers via `spec.capabilities`. A connector that advertises a
capability it does not implement fails startup. A handler receives the **validated** input
and a `CallContext` — never the raw task.

**Idempotency and reconciliation duties.** A handler for a side-effecting capability must
(a) propagate `ctx.idempotency_key` into the external system (query tag, provenance
comment, commit trailer, PR head branch, release id) and (b) implement `reconcile` for
that capability so that, after a crash, the Tool Registry can determine whether the effect
exists **before** any re-execution. Handlers for read-only capabilities return `NoEffect`.
A connector that cannot reconcile a capability must return `Unknown`; for non-idempotent
capabilities this parks the task for human resolution rather than re-executing
(`docs/STATE_MODEL.md` §4.6). Handlers must never build dedup logic on `attempt_id`.

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

`ConnectorStatus` is a product-visible enum, exposed by `GET /connectors` and shown in the UI:

| Status | Meaning | Planner behaviour |
|---|---|---|
| `AVAILABLE` | Health check passed within TTL | Eligible |
| `DEGRADED` | Health passed but with warnings (latency, partial permissions, rate limited) | Eligible; tasks get extended timeouts; UI badge |
| `UNAVAILABLE` | Health failed or credentials unresolved | Not eligible at plan time; existing tasks needing it are `PARKED` (policy deny class `ENVIRONMENTAL`) and the workflow is `BLOCKED` until the operator resolves it |
| `MOCK` | Fake implementation active | Eligible; every artifact and UI element is watermarked "mock connector" |

Health is checked at startup and every `health_ttl_seconds`; results cached in
`connector_status`. Never pretend a real integration is active when it is not.

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
| Identity | Key-pair or password auth via `SecretRef`; **one role per environment**: `AIDE_DEV_RW` (DEV RW, RAW read), `AIDE_DEV_RO` (read-only profiling), `AIDE_STAGING_DEPLOY` (future). The DEV instance uses `AIDE_DEV_RW` but `execute_query` always runs with a session-level `USE SECONDARY ROLES NONE` and the classifier guarantees read-only. |
| Session defaults | `STATEMENT_TIMEOUT_IN_SECONDS` from task deadline, `QUERY_TAG = aide:wf=<id>;task=<id>`, `AUTOCOMMIT = TRUE`, warehouse from config (X-Small, auto-suspend 60 s) |
| Capabilities | `discover_assets`, `describe_asset`, `detect_schema_drift`, `profile_dataset`, `sample_dataset`, `infer_relationships`, `validate_query` (EXPLAIN), `execute_query`, `create_dataset`, `drop_dataset` (DEV), `get_execution_metrics`, `get_cost_metrics` |
| Allow-list | Configured databases/schemas; DEV write schema pattern `AIDE_DEV.<WORKFLOW_SHORT_ID>_*` |
| Error mapping | Snowflake error codes: 001003 → `SQL_SYNTAX`; 002003 → `MISSING_OBJECT`; 000904 → `SCHEMA_MISMATCH` (invalid identifier); 100038/100040 → `TYPE_MISMATCH`; 003001/001011 → `PERMISSION_FAILURE`; 000630/604 → `TIMEOUT`/cancelled; 390114/network → `TRANSIENT_PROVIDER`; credit quota → `RESOURCE_LIMIT` |
| Reconcile | `create_dataset`/`drop_dataset`: look up the object and its provenance comment (`idempotency_key`) and, as fallback, `QUERY_HISTORY` by `QUERY_TAG`; `execute_query`/read-only: `NoEffect` |
| Fake | Backed by an in-process DuckDB database loaded from the synthetic fixtures with Snowflake→DuckDB transpilation via sqlglot; supports fault injection (`fail_next(capability, failure_class)`, `fail_after_effect(capability)`, latency, rename column to simulate drift) |

### 5.2 dbt (`transformation`)

| Aspect | Specification |
|---|---|
| Library | `dbt-core` + `dbt-snowflake`, invoked through `dbtRunner` **in a subprocess** per call (isolation from the API process, clean environment, hard timeout via process kill) |
| Project | A dbt project repository checked out per workflow into an isolated working copy (`.aide/work/<workflow_id>/project`); `profiles.yml` generated from connector config with `SecretRef` resolved into the subprocess environment only |
| Capabilities | `create_transformation`, `compile_transformation`, `execute_transformation`, `run_pipeline`, `run_tests`, `get_lineage`, `deploy` (strategy `DBT_RUN_TARGET`, STAGING only) |
| Artifacts | `manifest.json`, `run_results.json`, compiled SQL captured as artifacts |
| Error mapping | dbt `CompilationError` → `DBT_COMPILE`; `DatabaseError` → re-mapped through the Snowflake mapper (so a renamed column yields `SCHEMA_MISMATCH`, not generic `DBT_RUNTIME`); test `fail` → `DBT_TEST`; `RuntimeError` unknown → `DBT_RUNTIME` |
| Reconcile | `execute_transformation`/`run_pipeline`/`run_tests`: read `run_results.json` from the per-workflow working copy for the invocation tagged with `idempotency_key`, else `QUERY_HISTORY` by query tag; `create_transformation`: compare written file hashes; `deploy`: look up `release_id` in the staging target's release marker (`AIDE_STAGING.__AIDE_RELEASES`) — `Unknown` if absent and the warehouse is unreachable |
| Fake (unit tests) | Lightweight deterministic fake: executes generated SQL against the fake warehouse's DuckDB, emulating `ref`/`source` resolution and dbt's generic tests; produces real `manifest.json`-shaped output; fast enough for the unit suite and CI scenarios. Retained regardless of the note below |
| Integration target (DE 008 evaluation) | **DE 008 must evaluate running real dbt Core (`dbtRunner` subprocess) against an offline DuckDB-compatible target (`dbt-duckdb` adapter over the synthetic fixtures) for the integration and connector-contract layers**, so that dbt parsing, Jinja, materializations and generic tests are exercised without Snowflake credentials. Decision criteria: adapter maturity vs the pinned `dbt-core`, Snowflake→DuckDB SQL portability of the generated models, run time in CI. Outcome recorded in DE 008's handoff and, if adopted, as an additive change here (the unit-level fake stays) |

### 5.3 GitHub (`vcs`)

| Aspect | Specification |
|---|---|
| Library | `git` CLI via subprocess wrapper for local operations; GitHub REST v3 via `httpx` for PRs (no heavy SDK) |
| Identity | Fine-grained PAT or GitHub App installation token via `SecretRef`, scoped to the target repository, **no admin scopes** |
| Capabilities | `prepare_git_change`, `prepare_pull_request`, `deploy` (strategy `MERGE_PR` — **disabled in V1**) |
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
2. Declare `ConnectorSpec` with advertised capabilities and the `allowed_permissions` set (every advertised capability's required permission must be a member — checked at startup).
3. Implement handlers for each advertised capability using the existing input/output schemas, and `reconcile` for every side-effecting one (propagate `ctx.idempotency_key` into the external system).
4. Map vendor errors to failure classes.
5. Add configuration entry (`connectors.yaml` + env var names) and permission mapping in `config/permissions/<connector_id>.yaml`.
6. Run the **connector contract test suite** (`tests/connectors/contract/`) against the fake; against the real system when credentials exist.
7. Write `README.md`.
8. Register the module in `connectors/registry_entries.py` (one line).

If a new connector needs a capability that does not exist, that is a **capability
addition** (ADR + Capability Registry change), not a connector change.

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
