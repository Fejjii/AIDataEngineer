# Permission Model, Policy, Approvals, Security, Failure & Repair

**Task:** DE 001 (corrected by DE 001R1, DE 001R2A and DE 001R2B) · **Status:** ACCEPTED · ADRs: DE-ADR-015, DE-ADR-016, DE-ADR-023, DE-ADR-027

This document is the single reference for *who may do what*, *how it is enforced*, *how
humans approve*, *how secrets and untrusted inputs are contained*, and *how failures are
classified and bounded*.

---

## 1. Principles

1. **Deterministic policy.** Every real operation passes `PolicyEngine.evaluate()`; the
   result is persisted before execution. The LLM has no API to grant permissions.
2. **Fail closed.** Unknown capability, unknown connector, unparseable SQL, unresolved
   scope, missing environment binding → `DENY`.
3. **Least privilege by construction.** Permissions are attached to *connector instances*
   (identity + environment) and to *capabilities*; a workflow receives an explicit grant
   set authorized by the server at creation. All permission checks are **set membership**: a capability may run
   only if its required permission is a member of the workflow grant set (or covered by an
   approval) *and* a member of the connector instance's allowed set. There is no ordering
   between permissions and no "higher/lower" comparison anywhere in the system.
4. **Approvals are typed subjects.** Operation permission, design acceptance and budget
   increase are distinct facts. Design approval is never an execution grant.
5. **Separate authority for Git and deployment.** `GIT_WRITE` never implies any deploy
   permission.

### 1.1 Trusted principals and grant authorization

```python
class PrincipalRef(BaseModel, frozen=True):
    principal_id: UUID
    authentication_source: Literal["LOCAL_SESSION"]
    roles: frozenset[Literal["operator", "approver"]]
    session_id: UUID

class GrantAuthorization(BaseModel, frozen=True):
    principal: PrincipalRef
    requested: frozenset[PermissionLevel]
    effective: frozenset[PermissionLevel]
    environment_policy_version: str
    decided_at: datetime
```

The simplest credible MVP authentication is one operator-provisioned local account with an
Argon2id password hash referenced by configuration. Login creates a random opaque,
server-side PostgreSQL session; the browser receives only `HttpOnly`, `Secure` (outside
localhost), `SameSite=Strict` cookie state. Mutating routes require a session-bound CSRF
token. Same-origin SSE is read-only and uses the session cookie. The CLI authenticates
through the same login/session API. Raw credentials and hashes never enter workflow state,
audit payloads or prompts.

Authentication middleware creates `PrincipalRef`; clients cannot submit `principal_id`,
roles, or effective grants. They may request a subset. Server-side `GrantAuthorizer`
intersects it with role grants, target environment, connector policy and globally disabled
permissions, persists the decision, and supplies only `effective` grants to policy. V1's
one human may hold both `operator` and `approver`, but the roles remain distinct checks;
production self-approval remains disabled. Actor identity propagates through commands,
workflow events, approvals, attempts and audit events.

Role authorization is intentionally small: `operator` may create workflows, request grant
subsets, answer clarifications, resume/cancel/abandon and submit validated manual result
imports; `approver` may decide approval subjects. Neither role directly sets grants,
mutates policy decisions or writes task success. Both roles may be held by the one V1
principal; every action still records the checked role.

---

## 2. Permission levels

`PermissionLevel` is a **set of distinct grants, not an ordered hierarchy**. The canonical
definition is this table, implemented once as `aide.domain.permissions.PermissionLevel`
(a `StrEnum` with **no** ordering methods; `aide.policy` imports it and never redefines it).
A capability declares one required permission; a connector instance declares an
`allowed_permissions` set; a workflow declares a grant set. Anything that compares two
permissions with `<`, `>`, `≤`, `≥`, `max()` or numeric rank is a design violation; a unit
test asserts that ordering comparisons on `PermissionLevel` raise `TypeError`.

| Level | Meaning | Typical capabilities | Default in V1 workflow grant | Approval |
|---|---|---|---|---|
| `READ` | Read metadata and data within allow-list; run read-only queries; LLM reasoning | discover, describe, profile, sample, validate, execute (read-only), all reasoning | granted | never |
| `DEVELOPMENT_EXECUTE` | Run transformations/tests in DEV target | compile, execute_transformation, run_pipeline, run_tests | granted | never |
| `DEVELOPMENT_WRITE` | Create/replace objects in DEV workflow schemas; write project files | create_dataset, create_transformation, register_monitor | granted | policy-flagged cases only |
| `GIT_WRITE` | Branch, commit, push to non-protected branches; open PR | prepare_git_change, prepare_pull_request | granted (configurable) | configurable (default: none for branch/PR; DENY on protected branches) |
| `STAGING_DEPLOY` | Promote to staging target | `deploy_staging` | not granted by default; authorize only through an operation approval | **always** |
| `PRODUCTION_WRITE` | Any write/deploy affecting production | `deploy_production`, create/alter in PROD | **disabled** in V1 (`DENY`) | always (when enabled) |
| `DESTRUCTIVE` | Drop/truncate/delete/overwrite non-owned objects; force-push; PR merge | drop_dataset | not granted; DEV only via approval | **always**; non-DEV disabled |
| `INFRASTRUCTURE` | Warehouse sizing, resource creation, schedules | — (none in V1) | disabled | always (when enabled) |
| `SECURITY` | Roles, grants, network, identity, secrets | — (none in V1) | **disabled** | strict approval or disabled — V1: disabled |

### 2.1 Connector instance allowed permission sets (V1)

`ConnectorSpec.allowed_permissions: frozenset[PermissionLevel]` lists every permission the
instance may ever exercise. Membership is the only permission check (rule R4). A connector
instance must list a permission for each capability it advertises (startup check, §3 R0);
`READ` must be listed explicitly where read capabilities are advertised — nothing is
implied by another grant.

Warehouse and database instances also carry `identity_class`. Read capabilities that
require those kinds may bind only to `READ_ONLY` (rule R4b). `snowflake_dev` retains
`DEVELOPMENT_WRITE` and `DESTRUCTIVE` for DEV object writes; it does **not** list `READ`
and is not a valid read binding.

| Connector instance | `identity_class` | `allowed_permissions` | Notes |
|---|---|---|---|
| `snowflake_dev` | `DEVELOPMENT` | `{DEVELOPMENT_WRITE, DESTRUCTIVE}` | DEV writes (`create_dataset`, `drop_dataset`); `DESTRUCTIVE` only via `drop_dataset` in DEV with approval (R16). No READ capabilities. |
| `snowflake_ro` | `READ_ONLY` | `{READ}` | every Snowflake read capability: discover, describe, profile, sample, infer, validate/EXPLAIN, `execute_query`, metrics |
| `postgres_source` | `READ_ONLY` | `{READ}` | |
| `dbt_dev` | `DEVELOPMENT` | `{READ, DEVELOPMENT_EXECUTE, DEVELOPMENT_WRITE}` | `get_lineage` (READ), compile/run/test (DX), `create_transformation` (DW) |
| `dbt_staging` | `STAGING_DEPLOY` | `{STAGING_DEPLOY}` | `deploy_staging` only |
| `github` | `VCS` | `{GIT_WRITE}` | `prepare_git_change`, `prepare_pull_request` |

Approval-eligible permissions (the only permissions a workflow may obtain at runtime
through an approval rather than at creation): `APPROVAL_ELIGIBLE = {STAGING_DEPLOY,
DESTRUCTIVE}`; `DESTRUCTIVE` is approval-eligible only when `target_environment = DEV`.
`PRODUCTION_WRITE`, `INFRASTRUCTURE` and `SECURITY` are disabled in V1 and are never
approval-eligible.

---

## 3. Policy evaluation

```python
class PolicyRequest(BaseModel):
    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str
    resolved_input_digest: str
    contract_snapshot_id: UUID
    principal: PrincipalRef
    grant_authorization: GrantAuthorization # trusted server-side result
    capability: CapabilitySpec
    connector: ConnectorSpec | None
    connector_health: ConnectorHealthSnapshot | None
    target_environment: TargetEnv | None
    workflow_grants: frozenset[PermissionLevel] # copied from grant_authorization.effective
    payload_classification: SqlClassification | GitChangeClassification | None
    estimated_cost: CostEstimate | None
    artifact_provenance: tuple[ArtifactProvenance, ...]
    approvals: tuple[ApprovalRecord, ...]

class PolicyDecision(BaseModel):
    decision: Literal["ALLOW", "REQUIRE_APPROVAL", "DENY"]
    reasons: tuple[ReasonCode, ...]         # every applicable denial reason, canonical RuleId/code order
    deny_class: Literal["ENVIRONMENTAL", "SCOPE", "SECURITY"] | None   # set iff decision == DENY; derived from reasons (§3.1)
    routing: Literal["EXECUTE", "APPROVAL", "PARK", "FAIL_CLOSED"]     # deterministic function of (decision, deny_class)
    required_permission: PermissionLevel
    approval_requirements: tuple[ApprovalSubject, ...]
    evaluated_rules: tuple[RuleId, ...]     # every applicable deterministic rule
    decided_at: datetime
```

Membership helpers used by the rules (pure functions, the only permitted way to compare
permissions):

```python
def granted(req) -> bool:          # workflow may exercise the permission
    return req.capability.required_permission in req.workflow_grants \
        or any(a.status == "APPROVED" and a.subject.covers_operation(
               req.operation_idempotency_key, req.resolved_input_digest,
               req.capability.required_permission) for a in req.approvals)

def connector_allows(req) -> bool: # connector instance may exercise the permission
    return req.connector is None or req.capability.required_permission in req.connector.allowed_permissions

def approval_eligible(req) -> bool:
    p = req.capability.required_permission
    return p == "STAGING_DEPLOY" or (p == "DESTRUCTIVE" and req.target_environment == "DEV")
```

R0 runs at startup. At runtime **every applicable deterministic deny rule is evaluated**;
no short circuit is permitted. All denial reason codes are persisted. Only when the denial
set is empty are approval rules evaluated; all mandatory approval requirements are
returned together. `ALLOW` is possible only when neither denials nor unmet approvals
exist.

| # | Rule | Outcome |
|---|---|---|
| R0 | *(startup)* connector advertises capability `c` ∧ `c.required_permission ∉ connector.allowed_permissions` | startup failure `CONNECTOR_PERMISSION_CONFIG` — misconfiguration, never reached at runtime |
| R1 | capability not in registry ∨ connector not registered ∨ connector does not advertise capability | DENY `UNKNOWN_TARGET` |
| R2 | capability requires connector ∧ health snapshot expired or `status ∉ {AVAILABLE, DEGRADED, MOCK}` | DENY `CONNECTOR_UNAVAILABLE` |
| R2b | `status = DEGRADED` ∧ `required_permission ∈ connector_health.missing_permissions` ∨ `SECRET_UNRESOLVED` reported | DENY `CONNECTOR_PERMISSION_MISSING` / `SECRET_UNRESOLVED` |
| R3 | ¬`granted(req)` | REQUIRE_APPROVAL (kind `DEPLOY` or `DESTRUCTIVE`) if `approval_eligible(req)`; else DENY `PERM_NOT_GRANTED` |
| R4 | ¬`connector_allows(req)` | DENY `PERMISSION_NOT_ALLOWED_FOR_CONNECTOR` |
| R4b | `required_permission = READ` ∧ `connector.kind ∈ {warehouse, database}` ∧ `connector.identity_class ≠ READ_ONLY` | DENY `READ_ONLY_IDENTITY_REQUIRED` |
| R5 | `target_environment ≠ connector.target_environment` | DENY `ENV_MISMATCH` |
| R6 | `target_environment = PROD` | DENY `PROD_DISABLED_V1` |
| R7 | SQL payload: `parse_ok = false` | DENY `SQL_UNPARSEABLE` |
| R8 | SQL payload: `is_destructive` ∧ capability ≠ `drop_dataset` | DENY `SQL_DESTRUCTIVE` |
| R9 | SQL payload: dynamic/security statement, external or unapproved function/UDF/table function, stage/URL, unsafe session construct, or unknown AST node | DENY all applicable `SQL_SECURITY`, `SQL_UNSAFE_FUNCTION`, `SQL_UNSAFE_CONSTRUCT` |
| R10 | SQL payload: `is_multi_statement` | DENY `SQL_MULTI` |
| R11 | SQL payload: any object outside connector allow-list | DENY `SCOPE_VIOLATION` |
| R12 | SQL payload: writes ∧ target schema ∉ DEV workflow namespace | DENY `WRITE_OUTSIDE_NAMESPACE` |
| R13 | capability = `execute_query` ∧ `is_read_only = false` | DENY `READ_ONLY_REQUIRED` |
| R13b | capability = `drop_dataset` ∧ target provenance tag ≠ `created_by_workflow` | DENY `PROVENANCE_MISMATCH` |
| R14 | Git payload: base or target branch protected ∨ force flag | DENY `PROTECTED_BRANCH` |
| R15 | Git payload: secret scan hit | DENY `SECRET_IN_DIFF` |
| R16 | capability.approval = ALWAYS ∧ no APPROVED matching approval | REQUIRE_APPROVAL (kind from capability) |
| R17 | `create_dataset.replace` on object not tagged with this workflow | REQUIRE_APPROVAL `DESTRUCTIVE` |
| R18 | atomic worst-case budget reservation would exceed current versioned cap | REQUIRE `BudgetIncreaseApproval` |
| R19 | design `approval_required` | REQUIRE_APPROVAL `DESIGN` |
| R20 | any transitive artifact is MOCK-derived ∧ target action is real Git/deploy | DENY `MOCK_PROVENANCE_TO_REAL_TARGET` |
| R21 | otherwise | ALLOW |

Rules are pure functions over `PolicyRequest`; each has positive/negative tests. A policy
test injects simultaneous permission, scope and SQL-security violations and requires every
reason plus SECURITY routing independent of rule order.

### 3.1 Deterministic outcome routing (authoritative)

A `DENY` is not one thing. Every reason code belongs to exactly one **deny class**, and the
class determines what happens to the task and workflow. Evaluation persists the complete
reason set before deriving the maximum class. The mapping is data
(`REASON_CLASS: dict[ReasonCode, DenyClass]`) with a test asserting every reason code is
mapped. `routing` is derived as: `ALLOW → EXECUTE`; `REQUIRE_APPROVAL → APPROVAL`;
`DENY ∧ ENVIRONMENTAL → PARK`; `DENY ∧ (SCOPE ∨ SECURITY) → FAIL_CLOSED`. Authoritative
severity is `SECURITY > SCOPE > ENVIRONMENTAL`; routing uses the maximum while retaining
and auditing lower-severity reasons. Rule declaration order never affects the result.

| Deny class | Meaning | Reason codes | Task outcome | Workflow routing | Human action |
|---|---|---|---|---|---|
| `ENVIRONMENTAL` | Operator-resolvable condition; the operation itself is legitimate | `CONNECTOR_UNAVAILABLE`, `CONNECTOR_PERMISSION_MISSING`, `SECRET_UNRESOLVED`, `CONTRACT_VERSION_UNAVAILABLE` | `PARKED` (no new attempt) | `BLOCKED` with all reasons; resume re-evaluates | fix environment, then resume |
| `SCOPE` | Operation outside authorized workflow/connector/environment scope | `UNKNOWN_TARGET`, `PERM_NOT_GRANTED`, `PERMISSION_NOT_ALLOWED_FOR_CONNECTOR`, `READ_ONLY_IDENTITY_REQUIRED`, `ENV_MISMATCH`, `PROD_DISABLED_V1`, `SCOPE_VIOLATION`, `WRITE_OUTSIDE_NAMESPACE`, `READ_ONLY_REQUIRED`, `PROVENANCE_MISMATCH`, `MOCK_PROVENANCE_TO_REAL_TARGET` | `FAILED(POLICY_DENIED)`; never retried | **fail closed** | create a correctly scoped operation |
| `SECURITY` | Payload is unsafe or a protection boundary would be crossed | `SQL_UNPARSEABLE`, `SQL_DESTRUCTIVE`, `SQL_SECURITY`, `SQL_UNSAFE_FUNCTION`, `SQL_UNSAFE_CONSTRUCT`, `SQL_MULTI`, `PROTECTED_BRANCH`, `SECRET_IN_DIFF` | `FAILED(POLICY_DENIED)` + failure classification `UNSAFE_OPERATION`; never retried | **fail closed**: `FAILED`; audit `POLICY_DENY_SECURITY` alert event | investigate the audit alert |
| — (`REQUIRE_APPROVAL`) | No denial exists and one or more typed approval subjects are unmet | rules R3, R16–R19 | `AWAITING_APPROVAL` | `APPROVAL_REQUIRED` with all mandatory subject ids | approve/reject each subject |

Precedence when a phase-level evaluation (`POLICY_CHECK`) yields mixed results across
tasks: any `FAIL_CLOSED` → workflow `FAILED`; else any `PARK` → `BLOCKED`; else any
`APPROVAL` → `APPROVAL_REQUIRED`; else `EXECUTION`.

**Plan validation vs operation policy.** Plan validation is structural: registered pinned
capability/connector versions, connector kind, template schema, acyclic dependencies,
bounded task count and statically known scope. Temporary connector health never makes a
plan invalid. Static known inputs may receive advisory policy findings used for one bounded
replan, but no approval or executable policy decision exists yet.

After dependencies finish, each template resolves and validates immutable input, receives
an operation identity, then runs the complete policy set. Connector health and every
payload rule are now applicable. Environmental denial parks the materialized task and
retains the plan; scope/security denial fails closed. This removes the old placeholder
exception and ensures approvals never bind to unresolved input.

Consistency: `docs/STATE_MODEL.md` §2 (`POLICY_CHECK`, `BLOCKED`), §3 (transition table)
and §4.3 (task state `PARKED`), `docs/CAPABILITY_MODEL.md` §4, and §10 of this document
implement this table and must not define a different routing.

### 3.2 Scheduler-emitted environmental reasons

`CONTRACT_VERSION_UNAVAILABLE` is mapped in §3.1 as `ENVIRONMENTAL`, but it is **not**
produced by policy rules R0–R21. The **authoritative emitter** is the scheduler /
materialization layer:

1. After a phase contract snapshot is pinned, and again before claim/dispatch, the
   scheduler looks up the pinned capability contract version, payload schema versions and
   connector implementation version in the runtime registry and connector advertisements.
2. If any pinned version is absent, unsupported, or disabled, the scheduler emits
   `CONTRACT_VERSION_UNAVAILABLE` without silently upcasting. The task is `PARKED`; the
   workflow is `BLOCKED`. Routing remains the §3.1 `ENVIRONMENTAL` path.
3. This is distinct from R1 `UNKNOWN_TARGET` (unknown capability/connector — `SCOPE`, fail
   closed). A known capability whose **pinned historical version** is temporarily
   unavailable is environmental: restoring the advertised handler unparks the work.

DE 002A tests the emission predicate and the reason→class mapping. DE 002B tests that the
scheduler actually parks (does not fail closed) and that resume re-evaluates availability.

---

## 4. Approval system

`ApprovalRecord` stores `approval_id`, workflow, typed `subject`, subject digest, requester
principal, timestamps/expiry, `PENDING|APPROVED|REJECTED|INVALIDATED|EXPIRED`, deciding
`PrincipalRef`, comment and audit refs. The subject is a discriminated union:

```python
class OperationApproval(BaseModel, frozen=True):
    kind: Literal["OPERATION"]
    operation_idempotency_key: str
    resolved_input_digest: str
    artifact_hashes: tuple[str, ...]
    capability_id: str
    capability_contract_version: int
    connector_id: str
    connector_version: str
    target_environment: TargetEnv
    required_permission: PermissionLevel
    external_state_digest: str | None
    expires_at: datetime

class DesignApproval(BaseModel, frozen=True):
    kind: Literal["DESIGN"]
    design_artifact_hash: str
    validation_report_hash: str
    invariant_hashes: tuple[str, ...]
    expires_at: datetime

class BudgetIncreaseApproval(BaseModel, frozen=True):
    kind: Literal["BUDGET_INCREASE"]
    budget_scope: Literal["WORKFLOW_LLM", "WORKFLOW_WAREHOUSE"]
    ledger_version: int
    unit: Literal["USD", "SNOWFLAKE_CREDITS_ESTIMATED"]
    prior_cap: Decimal
    authorized_new_cap: Decimal
    authorized_delta: Decimal
    expires_at: datetime
```

Operation approval is a permission authorization for exactly one fully materialized
operation. All fields, current artifact/provenance closure and relevant external-state
digest are rechecked at decision and before each attempt; mismatch invalidates it. Retry
and reconciliation remain covered only while the subject is identical. Design approval
accepts design evidence and returns to design/planning; it grants no `PermissionLevel`.
Budget approval atomically advances the ledger cap to the explicit authorized value (the
delta must equal new minus prior); it does not approve an operation.

A policy decision may produce multiple mandatory subject requirements. They are stored as
an unordered set with a canonical digest; execution resumes only when **all** are approved
and valid. Any rejection prevents execution immediately and invalidates sibling pending
requirements for that gate. Subject-specific routing is authoritative and **must** appear
as guarded rows in `docs/STATE_MODEL.md` §3 (approval semantics are not weakened):

- rejected design → `PLANNING` with human feedback;
- rejected staging operation → task `CANCELLED(APPROVAL_REJECTED)` and delivery completes
  as `DELIVERED_PR_ONLY` when that documented fallback exists (`APPROVAL_REQUIRED →
  COMPLETED`), otherwise `BLOCKED`;
- rejected required destructive/Git operation → task `FAILED` (fail closed), workflow
  `FAILED`; optional such task is `SKIPPED(APPROVAL_REJECTED)` and the originating phase
  continues;
- rejected budget increase → workflow `BLOCKED(BUDGET_NOT_AUTHORIZED)` until the
  operator reduces scope or abandons.

Only a trusted principal with role `approver` may decide. The V1 principal may also be the
operator; production approval is disabled. Audit events cover request, decision,
invalidation and expiry with subject digest, never secret values.

### 4.1 Atomic budget authorization

The LLM gateway and warehouse preflight use a versioned PostgreSQL budget ledger. Before a
call, the same transaction locks the ledger row and reserves deterministic worst-case cost;
completion settles actual cost and releases unused reservation. Concurrent calls therefore
cannot each pass a stale total. If reservation exceeds cap, no call/attempt dispatches and
the policy requests `BudgetIncreaseApproval`. Approval atomically changes the cap and
re-evaluates the reservation. Snowflake credits remain estimates unless an isolated
warehouse/resource monitor provides an external hard boundary.

---

## 5. Identities and credentials

| Identity | Environment | Permissions | Used by |
|---|---|---|---|
| `AIDE_DEV_RO` (Snowflake role) | DEV/RAW | `USAGE` + `SELECT` on RAW and DEV; no writes | `snowflake_ro` connector (profiling/discovery) |
| `AIDE_DEV_RW` (Snowflake role) | DEV | `AIDE_DEV_RO` + `CREATE SCHEMA/TABLE/VIEW` in `AIDE_DEV`, restricted warehouse | `snowflake_dev`, `dbt_dev` |
| `AIDE_STAGING_DEPLOY` | STAGING | run dbt against `AIDE_STAGING`; no RAW writes | `dbt_staging` (approval-gated) |
| `AIDE_PROD_*` | PROD | **not created in V1** | — |
| `aide_source_ro` (PostgreSQL) | source | `SELECT` on synthetic schemas | `postgres_source` |
| GitHub fine-grained token / App | repo | contents: write, pull requests: write; **no** admin, no workflow scope | `github` |
| LLM provider key | — | API access | LLM Gateway only |
| App DB user | — | PostgreSQL app schema | Persistence |

Secret handling:

- Configuration contains only `SecretRef(name="SNOWFLAKE_DEV_PRIVATE_KEY")`. Connector
  adapters and LLM provider adapters receive separate allow-listed resolver views; neither
  can enumerate names or resolve the other's credential. Values live as
  `pydantic.SecretStr` and are never serialized.
- dbt subprocesses receive secrets as environment variables of the child only; the
  generated `profiles.yml` uses `env_var()`.
- Logging and audit pass through a redaction filter (known secret names, high-entropy
  strings, connection-string patterns, JWT/PEM patterns).
- Tests include a **secret leakage scan** over all persisted artifacts, logs and recorded
  prompts produced by the offline demo run.

---

## 6. Environment separation

| | DEV | STAGING | PROD |
|---|---|---|---|
| Connector instances | `snowflake_dev`, `snowflake_ro`, `dbt_dev`, `postgres_source`, `github` | `dbt_staging` | none in V1 |
| Writes | DEV namespace only | via `deploy_staging` after operation approval | disabled |
| Data | synthetic RAW | synthetic | — |
| Identities | RW/RO dev roles | deploy role | — |
| Automation | full within policy | approval per deploy | — |

A task is bound to exactly one target environment at creation; connectors are bound at
configuration; the policy engine enforces equality (R5).

---

## 7. Trust boundaries and untrusted input

| Input | Trust | Handling |
|---|---|---|
| Human request text | untrusted content, trusted intent | length limit; stored as artifact; wrapped in prompts as data |
| Metadata (names, comments, tags) | untrusted | flagged `is_untrusted_text`; delimited in prompts; never executed; identifiers always quoted through the dialect layer |
| Source data samples | untrusted + sensitive | capped, masked; never joined into SQL by string concatenation |
| Generated code (SQL, YAML, Python) | untrusted until validated | `classify_sql`, compile, EXPLAIN, policy; Python not executed in V1 |
| Tool outputs (error messages, dbt logs) | untrusted | redacted; delimited in prompts |
| LLM outputs | untrusted | schema-parsed; validated; proposals only |
| PR body / docs | untrusted content | rendered escaped; human-reviewed |
| Connector configuration | trusted (operator-controlled) | validated at startup |

Prompt-injection defences: delimiting and labelling untrusted text; instruction hierarchy
in templates; reasoning capabilities have no tools; `SUSPECTED_INJECTION` heuristic
detection (imperative + role-switch patterns) → audit + asset flag; all effects gated by
Det policy regardless of text.

---

## 8. Audit behaviour

Consequential actions are written to `audit_events` separately from debug logs: request
received, authentication/grant authorization, clarification asked/answered, plan accepted,
operation materialized, policy decision, tool
call (capability, connector, redacted input/output excerpts, digests), model call summary
(template id/version, tokens, cost; prompt and completion stored as redacted artifacts with
retention), approval lifecycle, repair applied/rejected, delivery events, state transitions,
suspected injection, secret-scan hits and stale-result rejection. Every event carries
`workflow_id`, `phase_run_id`, `task_id`, `operation_idempotency_key`, `attempt_id`,
trusted `PrincipalRef` or system actor, timestamp, and a monotonic sequence per workflow.

Each consequential state mutation and its audit event commit in the same PostgreSQL
transaction. Sequence allocation locks a per-workflow counter and has a unique
`(workflow_id, sequence)` constraint. The application audit-writer database role may
`INSERT`/`SELECT` but not `UPDATE`/`DELETE`; retention deletion uses a separate
operator-only maintenance role and emits a deletion manifest. V1 claims transactional,
append-only application audit—not cryptographic tamper evidence.

---

## 9. Redaction

Applied before logging, before audit write, before LLM context assembly, and before any
artifact leaves the system (PR body, docs):

- Known secret variable names and values (from `SecretProvider` registry) → `[REDACTED:<NAME>]`
- Patterns: PEM blocks, JWTs, `password=`, `token=`, connection strings, AWS/GCP/Azure key formats, high-entropy ≥ 32-char tokens
- Sensitive column masks (email, phone, person name, IBAN patterns) in samples and failing rows
- Redaction is tested with a fixture corpus; a redaction failure in tests is a build failure

---

## 10. Failure classification

| Class | Detection | Retryable | Repairable | Terminal handling |
|---|---|---|---|---|
| `SQL_SYNTAX` | parser / vendor 001003 | no | yes | escalate after budget |
| `MISSING_OBJECT` | vendor 002003 / dbt | no | yes (with drift evidence) | escalate |
| `SCHEMA_MISMATCH` | vendor 000904, drift report | no | yes | escalate |
| `TYPE_MISMATCH` | vendor 100038/100040 | no | yes | escalate |
| `DBT_COMPILE` | dbt CompilationError | no | yes | escalate |
| `DBT_RUNTIME` | dbt run error (re-mapped through vendor mapper when possible) | no | yes if sub-class repairable, else BLOCKED | escalate |
| `DBT_TEST` | test status fail | no | yes | escalate |
| `DATA_QUALITY` | Quality Engine | no | yes | escalate |
| `CONNECTOR_FAILURE` | driver/HTTP errors | only if side-effect-free or definitely no dispatch/effect | no | ambiguous side effect → reconcile first |
| `TRANSIENT_PROVIDER` | rate limit, 5xx, network | same evidence rule; exception class alone is insufficient | no | ambiguous side effect → reconcile first |
| `TIMEOUT` | wrapper/vendor | side-effect-free may retry; side-effecting must reconcile unless proven pre-dispatch | no | bounded reconciliation or BLOCKED |
| `RESOURCE_LIMIT` | credits, memory, quota | no | no | BLOCKED; scope reduction or explicit `BudgetIncreaseApproval` when a budget cap caused it |
| `PERMISSION_FAILURE` | vendor auth errors at runtime | no | no | task PARKED; workflow BLOCKED (`ENVIRONMENTAL`; human fixes grants, then resumes) |
| `POLICY_DENIED` | Policy Engine `DENY` | no | no | **routed by deny class (§3.1)**: `ENVIRONMENTAL` → task PARKED, workflow BLOCKED; `SCOPE`/`SECURITY` → task FAILED, workflow FAILED (fail closed). No automatic replanning once a task exists |
| `BUSINESS_AMBIGUITY` | interpret/design | no | no | CLARIFICATION_REQUIRED |
| `UNSAFE_OPERATION` | classifier/policy `SECURITY` class, path escape, unsafe `where` | no | no | FAILED + audit alert (`POLICY_DENY_SECURITY`) |
| `OUTPUT_INVALID` | schema/validators on LLM output | yes (1, with violations) | — | BLOCKED |
| `LLM_BUDGET_EXCEEDED` | atomic reservation cannot fit current cap | no | no | request explicit `BudgetIncreaseApproval`; no provider dispatch |
| `LEASE_EXPIRED` | scheduler | no direct retry | no | acquire recovery ownership and reconcile under `docs/STATE_MODEL.md` §4.7 |
| `AMBIGUOUS_OUTCOME` | any side-effecting attempt without proof of outcome (timeout, response loss, fail-after-effect, crash, expired lease) and reconciliation cannot resolve it | **never** | no | PARKED/BLOCKED; only verified schema-valid recovery/import can succeed; otherwise confirm-result-unknown, compensate or abandon |
| `UNKNOWN` | anything unmapped | no | **no** | BLOCKED; LLM may *suggest* a class for the human |

Repairable set (auto-repair allowed): `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`,
`TYPE_MISMATCH`, `DBT_COMPILE`, `DBT_RUNTIME` (mapped sub-class), `DBT_TEST`, `DATA_QUALITY`.

Terminal handling uses only workflow states (`BLOCKED`, `FAILED`, `CLARIFICATION_REQUIRED`,
`APPROVAL_REQUIRED`) and task states; handoff statuses such as `REVIEW_REQUIRED` are
development-process vocabulary and never appear in product state.

---

## 11. Bounded repair loop

```text
failure classified as repairable ∧ task_repairs < 2 ∧ workflow_repairs < 4
 → inspect_failure  (Det evidence bundle incl. drift, samples, prior attempts)
 → diagnose_failure (LLM) → RepairProposal
 → Det checks:
     hypothesis_hash ∉ prior hashes for this task     (changed hypothesis)
     root_cause_class ∈ repairable                     (or requires_human → BLOCKED)
     patch targets artifact under repair or its direct upstream in same phase
     patched SQL: classify_sql read-only ∧ validate_query valid
     tests not weakened (Quality §5)
   any check fails → proposal REJECTED (counts as attempt) → second diagnose with feedback
 → apply patch as new artifact version; audit REPAIR_APPLIED
 → rerun: pre-execution → GENERATION(unit); post-execution → EXECUTION(select patched+)
 → VALIDATION: failed check must pass ∧ no regression
 → success: counters persist; continue
 → failure: counters++ ; loop or terminate
termination: budget exhausted ∨ two rejected proposals ∨ requires_human ∨ non-repairable class
escalation: workflow BLOCKED with RepairExhausted{evidence, proposals, validation deltas, suggested human action}
```

Guarantees: no recursion (repair never invokes repair); every iteration persisted before
the next starts; budgets are configuration, not prompt text; total LLM spend still bounded
by the workflow cap.

---

## 12. Can generated SQL cause unsafe mutations?

Defence in depth, each independently sufficient for the common case:

1. Identity: every warehouse/database read capability, including `execute_query`, binds
   only to `identity_class=READ_ONLY` (`snowflake_ro` / `AIDE_DEV_RO`). R4b and the
   absence of `READ` from `snowflake_dev.allowed_permissions` make this a policy failure,
   not a convention. Write identity is never selected for a read contract.
2. Classifier: Snowflake parse → normalized render → reparse must preserve the AST;
   destructive/security/multi-statement, external functions, unapproved UDFs/table
   functions, stages/URLs, dynamic/session constructs and unknown AST nodes are denied.
3. Namespace: writes must target the workflow namespace (R12).
4. dbt: materializations write only to the bound DEV target; `profiles.yml` generated by the system, not by the LLM; `dbt_project.yml` not writable by capabilities; `run_query`/`execute` Jinja forbidden.
5. Approval: destructive DEV actions need explicit approval bound to the object.
6. Audit: every executed statement is recorded with its classification.
