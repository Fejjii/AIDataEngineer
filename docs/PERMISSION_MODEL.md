# Permission Model, Policy, Approvals, Security, Failure & Repair

**Task:** DE 001 (corrected by DE 001R1) · **Status:** PROPOSED · ADRs: DE-ADR-015, DE-ADR-016, DE-ADR-023

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
   set at creation. All permission checks are **set membership**: a capability may run
   only if its required permission is a member of the workflow grant set (or covered by an
   approval) *and* a member of the connector instance's allowed set. There is no ordering
   between permissions and no "higher/lower" comparison anywhere in the system.
4. **Approvals are bound to content.** An approval references artifact hashes and a
   specific capability/permission; any change invalidates it.
5. **Separate authority for Git and deployment.** `GIT_WRITE` never implies any deploy
   permission.

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
| `STAGING_DEPLOY` | Promote to staging target | deploy(STAGING) | not granted by default; grant via approval | **always** |
| `PRODUCTION_WRITE` | Any write/deploy affecting production | deploy(PROD), create/alter in PROD | **disabled** in V1 (`DENY`) | always (when enabled) |
| `DESTRUCTIVE` | Drop/truncate/delete/overwrite non-owned objects; force-push; PR merge | drop_dataset | not granted; DEV only via approval | **always**; non-DEV disabled |
| `INFRASTRUCTURE` | Warehouse sizing, resource creation, schedules | — (none in V1) | disabled | always (when enabled) |
| `SECURITY` | Roles, grants, network, identity, secrets | — (none in V1) | **disabled** | strict approval or disabled — V1: disabled |

### 2.1 Connector instance allowed permission sets (V1)

`ConnectorSpec.allowed_permissions: frozenset[PermissionLevel]` lists every permission the
instance may ever exercise. Membership is the only check (rule R4). A connector instance
must list a permission for each capability it advertises (startup check, §3 R0);
`READ` must be listed explicitly where read capabilities are advertised — nothing is
implied by another grant.

| Connector instance | `allowed_permissions` | Notes |
|---|---|---|
| `snowflake_dev` | `{READ, DEVELOPMENT_WRITE, DESTRUCTIVE}` | `DESTRUCTIVE` only reachable through `drop_dataset` in DEV with approval (R16) |
| `snowflake_ro` | `{READ}` | profiling / discovery identity |
| `postgres_source` | `{READ}` | |
| `dbt_dev` | `{READ, DEVELOPMENT_EXECUTE, DEVELOPMENT_WRITE}` | `get_lineage` (READ), compile/run/test (DX), `create_transformation` (DW) |
| `dbt_staging` | `{STAGING_DEPLOY}` | `deploy(STAGING)` only |
| `github` | `{GIT_WRITE}` | `prepare_git_change`, `prepare_pull_request` |

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
    task_id: UUID
    idempotency_key: str                    # operation identity (docs/STATE_MODEL.md §4.2); stable across attempts
    capability: CapabilitySpec
    connector: ConnectorSpec | None
    connector_status: ConnectorStatus | None
    target_environment: TargetEnv | None
    workflow_grants: frozenset[PermissionLevel]
    payload_classification: SqlClassification | GitChangeClassification | None
    estimated_cost: CostEstimate | None
    approvals: list[ApprovalRecord]         # existing, for this workflow

class PolicyDecision(BaseModel):
    decision: Literal["ALLOW", "REQUIRE_APPROVAL", "DENY"]
    reasons: list[ReasonCode]               # stable codes, e.g. PERM_NOT_GRANTED, SQL_DESTRUCTIVE
    deny_class: Literal["ENVIRONMENTAL", "SCOPE", "SECURITY"] | None   # set iff decision == DENY; derived from reasons (§3.1)
    routing: Literal["EXECUTE", "APPROVAL", "PARK", "FAIL_CLOSED"]     # deterministic function of (decision, deny_class)
    required_permission: PermissionLevel
    approval_kind: ApprovalKind | None
    evaluated_rules: list[RuleId]
    decided_at: datetime
```

Membership helpers used by the rules (pure functions, the only permitted way to compare
permissions):

```python
def granted(req) -> bool:          # workflow may exercise the permission
    return req.capability.required_permission in req.workflow_grants \
        or any(a.status == "APPROVED" and a.requested_permission == req.capability.required_permission
               and a.covers(req.idempotency_key) for a in req.approvals)

def connector_allows(req) -> bool: # connector instance may exercise the permission
    return req.connector is None or req.capability.required_permission in req.connector.allowed_permissions

def approval_eligible(req) -> bool:
    p = req.capability.required_permission
    return p == "STAGING_DEPLOY" or (p == "DESTRUCTIVE" and req.target_environment == "DEV")
```

Rule order (first `DENY` wins; then `REQUIRE_APPROVAL`; else `ALLOW`). R0 runs at startup,
not per call:

| # | Rule | Outcome |
|---|---|---|
| R0 | *(startup)* connector advertises capability `c` ∧ `c.required_permission ∉ connector.allowed_permissions` | startup failure `CONNECTOR_PERMISSION_CONFIG` — misconfiguration, never reached at runtime |
| R1 | capability not in registry ∨ connector not registered ∨ connector does not advertise capability | DENY `UNKNOWN_TARGET` |
| R2 | capability requires connector ∧ `connector_status ∉ {AVAILABLE, DEGRADED, MOCK}` | DENY `CONNECTOR_UNAVAILABLE` |
| R2b | `connector_status = DEGRADED` ∧ capability ∈ `connector_status.missing_permissions` ∨ `SECRET_UNRESOLVED` reported | DENY `CONNECTOR_PERMISSION_MISSING` / `SECRET_UNRESOLVED` |
| R3 | ¬`granted(req)` | REQUIRE_APPROVAL (kind `DEPLOY` or `DESTRUCTIVE`) if `approval_eligible(req)`; else DENY `PERM_NOT_GRANTED` |
| R4 | ¬`connector_allows(req)` | DENY `PERMISSION_NOT_ALLOWED_FOR_CONNECTOR` |
| R5 | `target_environment ≠ connector.target_environment` | DENY `ENV_MISMATCH` |
| R6 | `target_environment = PROD` | DENY `PROD_DISABLED_V1` |
| R7 | SQL payload: `parse_ok = false` | DENY `SQL_UNPARSEABLE` |
| R8 | SQL payload: `is_destructive` ∧ capability ≠ `drop_dataset` | DENY `SQL_DESTRUCTIVE` |
| R9 | SQL payload: `has_dynamic_sql` ∨ security statements (GRANT/REVOKE/ROLE/USER) | DENY `SQL_SECURITY` |
| R10 | SQL payload: `is_multi_statement` | DENY `SQL_MULTI` |
| R11 | SQL payload: any object outside connector allow-list | DENY `SCOPE_VIOLATION` |
| R12 | SQL payload: writes ∧ target schema ∉ DEV workflow namespace | DENY `WRITE_OUTSIDE_NAMESPACE` |
| R13 | capability = `execute_query` ∧ `is_read_only = false` | DENY `READ_ONLY_REQUIRED` |
| R13b | capability = `drop_dataset` ∧ target provenance tag ≠ `created_by_workflow` | DENY `PROVENANCE_MISMATCH` |
| R14 | Git payload: base or target branch protected ∨ force flag | DENY `PROTECTED_BRANCH` |
| R15 | Git payload: secret scan hit | DENY `SECRET_IN_DIFF` |
| R16 | capability.approval = ALWAYS ∧ no APPROVED matching approval | REQUIRE_APPROVAL (kind from capability) |
| R17 | `create_dataset.replace` on object not tagged with this workflow | REQUIRE_APPROVAL `DESTRUCTIVE` |
| R18 | estimated warehouse cost > workflow cap ∨ LLM spend > cap | REQUIRE_APPROVAL `COST` |
| R19 | design `approval_required` | REQUIRE_APPROVAL `DESIGN` |
| R20 | otherwise | ALLOW |

Rules are pure functions over `PolicyRequest`; each has unit tests including negative
cases. `docs/TECHNICAL_RISKS.md` lists the property tests for the SQL classifier.

### 3.1 Deterministic outcome routing (authoritative)

A `DENY` is not one thing. Every reason code belongs to exactly one **deny class**, and the
class determines what happens to the task and the workflow. The mapping is data
(`REASON_CLASS: dict[ReasonCode, DenyClass]`) with a test asserting every reason code is
mapped. `routing` is derived as: `ALLOW → EXECUTE`; `REQUIRE_APPROVAL → APPROVAL`;
`DENY ∧ ENVIRONMENTAL → PARK`; `DENY ∧ (SCOPE ∨ SECURITY) → FAIL_CLOSED`. When several
reasons apply, the most severe class wins: `SECURITY > SCOPE > ENVIRONMENTAL`.

| Deny class | Meaning | Reason codes | Task outcome | Workflow routing | Human action |
|---|---|---|---|---|---|
| `ENVIRONMENTAL` | Operator-resolvable condition; the operation itself is legitimate | `CONNECTOR_UNAVAILABLE`, `CONNECTOR_PERMISSION_MISSING`, `SECRET_UNRESOLVED` | `PARKED` (no execution; not counted as an attempt) | `BLOCKED` with `BlockReason(class=ENVIRONMENTAL, reason_code, connector_id, env var **name** if any)`; on resume the task returns to `READY` and policy is **re-evaluated** | fix credentials / grants / availability, then *Resume* |
| `SCOPE` | Operation outside what this workflow, connector or environment is permitted to do | `UNKNOWN_TARGET`, `PERM_NOT_GRANTED`, `PERMISSION_NOT_ALLOWED_FOR_CONNECTOR`, `ENV_MISMATCH`, `PROD_DISABLED_V1`, `SCOPE_VIOLATION`, `WRITE_OUTSIDE_NAMESPACE`, `READ_ONLY_REQUIRED`, `PROVENANCE_MISMATCH` | `FAILED(POLICY_DENIED)`; never retried | **fail closed**: `FAILED` (execution-time) — see plan-time note below | none automatic; new workflow with corrected scope |
| `SECURITY` | Payload is unsafe or a protection boundary would be crossed | `SQL_UNPARSEABLE`, `SQL_DESTRUCTIVE`, `SQL_SECURITY`, `SQL_MULTI`, `PROTECTED_BRANCH`, `SECRET_IN_DIFF` | `FAILED(POLICY_DENIED)` + failure classification `UNSAFE_OPERATION`; never retried | **fail closed**: `FAILED`; audit `POLICY_DENY_SECURITY` alert event | investigate the audit alert |
| — (`REQUIRE_APPROVAL`) | Approval-eligible operation | rules R3 (eligible), R16, R17, R18, R19 | `AWAITING_APPROVAL` | `APPROVAL_REQUIRED` with `approval_kind`; approved → task `READY`; rejected → per `docs/STATE_MODEL.md` §2 | approve / reject |

Precedence when a phase-level evaluation (`POLICY_CHECK`) yields mixed results across
tasks: any `FAIL_CLOSED` → workflow `FAILED`; else any `PARK` → `BLOCKED`; else any
`APPROVAL` → `APPROVAL_REQUIRED`; else `EXECUTION`.

**Plan-time pre-check vs execution-time enforcement.** The plan validator (`PLANNING`)
runs the same rule set in *pre-check mode* on every planned task with its static inputs
(`$from` placeholders unresolved ⇒ payload rules skipped). A pre-check `DENY` of class
`SCOPE` or `SECURITY` makes the plan **invalid**, and the planner is re-invoked with the
violations (max 2 replans, then `BLOCKED`). This is the only place where the system
"routes around" a denial, and it happens before any task exists. A pre-check `DENY` of
class `ENVIRONMENTAL` is not a planning error — re-planning cannot repair the environment —
so the validated plan is retained and the workflow parks in `BLOCKED` (`blocked_from_phase
= PLANNING`); on resume the plan is re-validated and, if clean, its tasks are created.
Once a task exists, an execution-time `DENY` follows the table above without exception; a
`SCOPE`/`SECURITY` denial at execution time means a validator or the plan pre-check was
bypassed and is treated as an anomaly.

Consistency: `docs/STATE_MODEL.md` §2 (`POLICY_CHECK`, `BLOCKED`), §3 (transition table)
and §4.3 (task state `PARKED`), `docs/CAPABILITY_MODEL.md` §4, and §10 of this document
implement this table and must not define a different routing.

---

## 4. Approval system

| Aspect | Design |
|---|---|
| Record | `approvals(approval_id, workflow_id, task_id?, kind, requested_permission, artifact_hashes[], summary_ref, requested_by=system, requested_at, expires_at, status, decided_by, decided_at, comment)` |
| Kinds | `DESIGN`, `COST`, `GIT` (optional), `DEPLOY`, `DESTRUCTIVE` |
| Binding | `artifact_hashes` are sha256 of every artifact the action would use. On resolution and again at execution, hashes are recompared; mismatch → approval `INVALIDATED`, workflow back to `APPROVAL_REQUIRED` with a new request. |
| Expiry | default 7 days; configurable per kind |
| Authorization | Approver must hold role `approver` (V1: single operator identity with roles `operator`, `approver`); production approvals (when enabled) require a distinct `release_approver` role — no self-approval by the requester identity if identities are separated later |
| Scope | One approval authorizes exactly one **logical operation** (identified by the task `idempotency_key`, `docs/STATE_MODEL.md` §4.2) or one design. Every execution attempt of that same operation — retry after a transient failure, re-run after a crash, reconciliation — is covered by the same approval as long as the bound artifact hashes are unchanged. A different operation (new inputs, new artifact version, new task) needs a new approval. |
| UI | Shows the exact action, target environment, artifacts, validation report, cost, and diff; approve/reject with comment |
| Audit | `APPROVAL_REQUESTED`, `APPROVAL_GRANTED`, `APPROVAL_REJECTED`, `APPROVAL_INVALIDATED`, `APPROVAL_EXPIRED` |

Human gates required in V1: staging deploy (always), destructive in DEV (always), design
when flagged, cost over cap, optionally PR creation.

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

- Configuration contains only `SecretRef(name="SNOWFLAKE_DEV_PRIVATE_KEY")`; the
  `SecretProvider` resolves at call time inside the connector; the value lives as a
  `pydantic.SecretStr` and is never serialized.
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
| Writes | DEV namespace only | via `deploy` after approval | disabled |
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

Consequential actions are written to `audit_events` (append-only) separately from debug
logs: request received, clarification asked/answered, plan accepted, policy decision, tool
call (capability, connector, redacted input/output excerpts, digests), model call summary
(template id/version, tokens, cost; prompt and completion stored as redacted artifacts with
retention), approval lifecycle, repair applied/rejected, delivery events, state transitions,
suspected injection, secret-scan hits. Every event carries `workflow_id`, `task_id`, actor
(system/human id), timestamp, and a monotonic sequence per workflow.

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
| `CONNECTOR_FAILURE` | driver/HTTP errors | yes (policy) | no | BLOCKED |
| `TRANSIENT_PROVIDER` | rate limit, 5xx, network | yes (exp backoff) | no | BLOCKED |
| `TIMEOUT` | wrapper/vendor | yes (profiling: reduced budget) | no | BLOCKED |
| `RESOURCE_LIMIT` | credits, memory, quota | no | no | BLOCKED (COST approval) |
| `PERMISSION_FAILURE` | vendor auth errors at runtime | no | no | task PARKED; workflow BLOCKED (`ENVIRONMENTAL`; human fixes grants, then resumes) |
| `POLICY_DENIED` | Policy Engine `DENY` | no | no | **routed by deny class (§3.1)**: `ENVIRONMENTAL` → task PARKED, workflow BLOCKED; `SCOPE`/`SECURITY` → task FAILED, workflow FAILED (fail closed). No automatic replanning once a task exists |
| `BUSINESS_AMBIGUITY` | interpret/design | no | no | CLARIFICATION_REQUIRED |
| `UNSAFE_OPERATION` | classifier/policy `SECURITY` class, path escape, unsafe `where` | no | no | FAILED + audit alert (`POLICY_DENY_SECURITY`) |
| `OUTPUT_INVALID` | schema/validators on LLM output | yes (1, with violations) | — | BLOCKED |
| `LLM_BUDGET_EXCEEDED` | gateway | no | no | BLOCKED (COST approval) |
| `LEASE_EXPIRED` | scheduler (lease reaper) | see `docs/STATE_MODEL.md` §4.6: reconcile first; idempotent → new attempt | no | non-idempotent with `UNKNOWN` reconcile → `AMBIGUOUS_OUTCOME` |
| `AMBIGUOUS_OUTCOME` | attempt of a non-idempotent operation ended without a persisted result and reconciliation cannot prove or disprove the side effect | **never** | no | task PARKED; workflow BLOCKED with `BlockReason(AMBIGUOUS_SIDE_EFFECT)`; human verifies the external system and either records the result (`resolve_ambiguous_attempt`) or abandons → FAILED. The operation is **never** re-executed automatically |
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

1. Identity: DEV role cannot write outside `AIDE_DEV`; no PROD role exists.
2. Classifier: destructive/security/multi-statement SQL is `DENY` before any call.
3. Namespace: writes must target the workflow namespace (R12).
4. dbt: materializations write only to the bound DEV target; `profiles.yml` generated by the system, not by the LLM; `dbt_project.yml` not writable by capabilities; `run_query`/`execute` Jinja forbidden.
5. Approval: destructive DEV actions need explicit approval bound to the object.
6. Audit: every executed statement is recorded with its classification.
