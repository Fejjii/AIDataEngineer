# Capability Model

**Task:** DE 001 · **Status:** PROPOSED · ADR: DE-ADR-013

The orchestrator reasons about **capabilities**, never about vendors. A capability is a
typed, versioned contract. A **tool** is the binding of a capability to an implementation
(a connector handler or an LLM reasoner). A **connector** is an adapter to one external
system that advertises which capabilities it implements.

```text
Capability (contract)  ──implemented by──►  Tool (binding)  ──backed by──►  Connector | Reasoner
        ▲                                        ▲
   Capability Registry                      Tool Registry
```

---

## 1. Contract structure

Every capability is declared once, in code, as an immutable `CapabilitySpec`:

```python
class CapabilitySpec(BaseModel, frozen=True):
    id: CapabilityId                     # e.g. "execute_query"
    version: int                         # bump on incompatible schema change
    kind: Literal["deterministic", "reasoning", "control"]
    purpose: str                         # one sentence, shown to the planner
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    required_permission: PermissionLevel # docs/PERMISSION_MODEL.md §2 — one grant; checked by set membership, never by rank
    risk: RiskLevel                      # LOW | MEDIUM | HIGH | CRITICAL
    approval: ApprovalRule               # NEVER | IF_POLICY_FLAGS | ALWAYS | DISABLED
    timeout_seconds: int
    retry: RetryPolicy                   # max_attempts, backoff, retry_on: {FailureClass}
    failure_classes: frozenset[FailureClass]
    validators: tuple[ValidatorId, ...]  # deterministic output validators
    audit: AuditSpec                     # which input/output fields are recorded, redaction
    connector_requirement: ConnectorRequirement  # NONE | REQUIRED(kind) | OPTIONAL(kind)
    idempotent: bool                     # True: re-execution converges, safe after crash; False: never auto-repeated after an ambiguous attempt (docs/STATE_MODEL.md §4.6)
    cost_class: Literal["free", "warehouse", "llm", "external_api"]
```

Rules:

- `input_schema` and `output_schema` are Pydantic v2 models; the Tool Registry validates
  both on every call. Invalid output is a failure (`OUTPUT_INVALID`), never passed on.
- `kind = reasoning` capabilities have `connector_requirement = NONE`, `cost_class = llm`,
  and `required_permission = READ` — they can never cause an external effect by themselves.
- `kind = control` capabilities (`request_approval`, `emit_clarification`) act on
  workflow state only.
- Versioning: `id@version` is recorded on every task and audit event. Two versions may
  coexist during migration; the planner only sees the latest.

---

## 2. Catalogue (V1)

Permission abbreviations: R = READ, DX = DEVELOPMENT_EXECUTE, DW = DEVELOPMENT_WRITE,
GW = GIT_WRITE, SD = STAGING_DEPLOY, PW = PRODUCTION_WRITE, DS = DESTRUCTIVE.
Full per-capability contracts: `docs/TOOL_CONTRACTS.md`.

### 2.1 Discovery

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `discover_assets` | Enumerate databases/schemas/tables/views/files within an allow-listed scope | R | L | NEVER | REQUIRED(warehouse\|database\|storage) |
| `describe_asset` | Columns, types, constraints, comments, row count, last altered for one asset | R | L | NEVER | REQUIRED |
| `detect_schema_drift` | Diff current `describe_asset` against a stored snapshot | R | L | NEVER | REQUIRED |
| `select_relevant_assets` *(reasoning)* | Choose assets relevant to the requirement; output must be a subset of the catalogue | R | M | NEVER | NONE |

### 2.2 Profiling

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `profile_dataset` | Column statistics, null/distinct ratios, candidate keys, duplicates, within budget | R | L | NEVER | REQUIRED(warehouse\|database) |
| `sample_dataset` | Bounded, column-masked sample rows | R | M (privacy) | NEVER | REQUIRED |
| `infer_relationships` | Candidate FK/join paths by inclusion-dependency sampling between assets | R | L | NEVER | REQUIRED |

### 2.3 SQL and datasets

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `classify_sql` | Deterministic classification: statement types, referenced objects, destructive flags, dialect | R | L | NEVER | NONE (uses dialect registry) |
| `validate_query` | Compile/explain without executing (dry run) | R | L | NEVER | REQUIRED(warehouse) |
| `execute_query` | Run a **read-only** statement with row/byte/time caps | R | M | NEVER | REQUIRED(warehouse\|database) |
| `generate_sql_query` *(reasoning)* | Produce one read-only SELECT, or one `CREATE TABLE … AS SELECT` targeting a DEV namespace, for investigation requests and the DE 002 slice | R | M | NEVER | NONE |
| `create_dataset` | Create/replace a table or view in a DEV schema | DW | M | IF_POLICY_FLAGS | REQUIRED(warehouse) |
| `drop_dataset` | Drop an object | DS | H | ALWAYS (DEV) / DISABLED (non-DEV) | REQUIRED(warehouse) |

### 2.4 Transformations and pipelines

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `generate_transformation` *(reasoning)* | Produce model SQL/YAML/tests for one design unit | R | M | NEVER | NONE |
| `create_transformation` | Materialize generated files into the transformation project working tree (no execution) | DW | L | NEVER | REQUIRED(transformation) |
| `compile_transformation` | `dbt compile`/parse; returns manifest and compiled SQL | DX | L | NEVER | REQUIRED(transformation) |
| `execute_transformation` | Run selected models in DEV target | DX | M | NEVER | REQUIRED(transformation) |
| `run_pipeline` | Run the full DAG (`dbt build` = run + test) in DEV target | DX | M | NEVER | REQUIRED(transformation) |
| `run_tests` | Execute tests for selected models; structured results | DX | L | NEVER | REQUIRED(transformation) |

### 2.5 Failure and repair

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `inspect_failure` | Collect structured evidence: error text, error code, failing SQL, run_results, related metadata | R | L | NEVER | OPTIONAL |
| `diagnose_failure` *(reasoning)* | Produce `RepairProposal` (diagnosis, hypothesis, patch, expected validation) | R | M | NEVER | NONE |

### 2.6 Lineage, documentation, metrics

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `get_lineage` | Model- and column-level lineage graph from manifest + SQL parsing | R | L | NEVER | REQUIRED(transformation) |
| `generate_documentation` *(reasoning)* | Model/column descriptions, run summary, PR body | R | L | NEVER | NONE |
| `get_execution_metrics` | Query history: duration, bytes scanned, rows, spilling for tagged queries | R | L | NEVER | REQUIRED(warehouse) |
| `get_cost_metrics` | Credits/cost attributed to a workflow tag | R | L | NEVER | REQUIRED(warehouse) |

### 2.7 Delivery and monitoring

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `prepare_git_change` | Branch, commit artifact set, push to remote | GW | M | IF_POLICY_FLAGS | REQUIRED(vcs) |
| `prepare_pull_request` | Open/update PR with generated body | GW | M | IF_POLICY_FLAGS (default: NEVER) | REQUIRED(vcs) |
| `deploy` | Promote artifact set to a named target environment | SD / PW | H / C | ALWAYS | REQUIRED(transformation\|orchestration) |
| `register_monitor` | Persist monitor definitions (freshness, tests, cost thresholds) as artifacts | DW | L | NEVER | OPTIONAL |
| `check_monitor` | Evaluate a registered monitor once | R | L | NEVER | REQUIRED |

### 2.8 Reasoning and control

| Id | Purpose | Perm | Risk | Approval | Connector |
|---|---|---|---|---|---|
| `interpret_requirement` *(reasoning)* | Natural language → `RequirementSpec` with ambiguity flags | R | M | NEVER | NONE |
| `plan_phase` *(reasoning)* | Produce the task DAG for the next phase | R | M | NEVER | NONE |
| `propose_model_design` *(reasoning)* | Entity mapping and design details inside a Det-selected architecture class | R | M | NEVER | NONE |
| `summarize_for_human` *(reasoning)* | Explain state, decisions, failures in plain language | R | L | NEVER | NONE |
| `emit_clarification` *(control)* | Park workflow in `CLARIFICATION_REQUIRED` with typed questions | R | L | NEVER | NONE |
| `request_approval` *(control)* | Create approval request bound to artifact hashes | R | L | — | NONE |

---

## 3. Improvements over the initial taxonomy

| Change | Reason |
|---|---|
| Split `describe_asset` from `detect_schema_drift` | Drift is a distinct deterministic check with its own failure class and monitor use |
| Added `infer_relationships` | Key/join inference is central to modelling and is deterministic sampling, not profiling |
| Added `classify_sql` as a first-class capability | Policy must be able to cite the classification; it is reused by validation, repair, and lineage |
| Split `compile_transformation` from `execute_transformation` | Compile failures are a separate, cheap, repairable class |
| Split `run_tests` from `run_pipeline` | Repair loop reruns tests only; `run_pipeline` is the full build |
| Renamed `monitor` → `register_monitor` + `check_monitor` | "monitor" conflated definition and evaluation |
| `drop_dataset` explicit and DISABLED outside DEV | Destructive actions must be visible in the catalogue, not hidden inside `execute_query` |
| Reasoning capabilities are catalogued alongside deterministic ones | Same contract discipline: typed I/O, validators, audit, cost accounting |
| `request_approval` and `emit_clarification` as control capabilities | The planner can schedule human gates explicitly; they appear in the DAG and audit |

---

## 4. Lifecycle of a capability call

```text
Task claimed
 → Tool Registry resolves (capability_id@version, connector_id)
 → input validated against input_schema                      (Det)
 → Policy Engine evaluates → ALLOW | REQUIRE_APPROVAL | DENY   (Det, persisted with deny_class + routing)
     REQUIRE_APPROVAL → task AWAITING_APPROVAL, workflow APPROVAL_REQUIRED
     DENY, class ENVIRONMENTAL → task PARKED, workflow BLOCKED (operator resolves, then resume re-evaluates)
     DENY, class SCOPE | SECURITY → task FAILED(POLICY_DENIED), workflow FAILED (fail closed; SECURITY raises audit alert)
     (routing table: docs/PERMISSION_MODEL.md §3.1; never retried, never re-planned around at execution time)
 → pre-validators (e.g. classify_sql for any SQL-bearing input)
 → execute with timeout, cancellation, resource caps           (connector or reasoner)
 → output validated against output_schema + validators          (Det)
 → failure classified if any                                   (Det)
 → audit event + telemetry written (redacted)
 → result persisted on task
```

---

## 5. Registry behaviour

- **Registration** is declarative at import time (`@capability(spec)`); duplicate ids fail startup.
- **Catalogue for the planner** contains only: id, purpose, kind, permission, risk, input
  field names. It never contains connector details or secrets.
- **Compatibility check** at startup: every connector's advertised capability handler
  must accept the capability's input schema version, and the capability's
  `required_permission` must be a member of the connector's `allowed_permissions`
  (`docs/PERMISSION_MODEL.md` §3 rule R0); side-effecting capabilities must have a
  `reconcile` implementation.
- **Introspection endpoint** (`GET /capabilities`) exposes the catalogue for the UI and
  evaluation harness.

---

## 6. Non-goals

- No dynamic capability creation by the LLM. The planner can only reference catalogued ids.
- No capability may accept free-form shell commands or unclassified SQL.
- No capability bypasses the Tool Registry wrapper; direct connector imports outside
  `aide.connectors` are forbidden by import-linter rules (see `docs/IMPLEMENTATION_PLAN.md`).
