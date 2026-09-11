# DE 001 — Independent Architecture Review

**Task ID:** DE 001 (Independent Architecture Review)
**Review model:** GPT 5.6 Sol High<br>
**Artifact persistence:** Composer 2.5 was used only after the review to write the already-completed review into this repository. Composer did not perform, delegate, or alter the architecture analysis.<br>
**Branch reviewed:** `docs/DE001_mvp_architecture`
**Commit reviewed:** `b12b61ddeada830597809b9e70d15feca1105625`
**Review date:** 2026-09-11
**Review mode:** READ ONLY (review artifact only; no architecture or product code modified)
**Repository path reviewed:** `/workspace` (Cloud Agent checkout)

## Review scope

Independent principal architecture review of DE 001 after DE 001R1 corrections. Documents read:

- `docs/ARCHITECTURE.md`
- `docs/MVP_SCOPE.md`
- `docs/CAPABILITY_MODEL.md`
- `docs/TOOL_CONTRACTS.md`
- `docs/CONNECTOR_ARCHITECTURE.md`
- `docs/STATE_MODEL.md`
- `docs/AGENT_MODEL.md`
- `docs/PERMISSION_MODEL.md`
- `docs/DATA_MODELLING_STRATEGY.md`
- `docs/QUALITY_STRATEGY.md`
- `docs/OBSERVABILITY.md`
- `docs/EVALUATION_STRATEGY.md`
- `docs/TECH_STACK.md`
- `docs/TECHNICAL_RISKS.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/DEMO_COMPANY.md`
- `docs/EXECUTION_FLOW.md`
- `docs/DATA_ENGINEERING_CAPABILITY_MAP.md`
- `docs/adr/*` (DE-ADR-008 … DE-ADR-026)
- `.ai/ARCHITECTURE.md`
- `.ai/DECISIONS.md`

Validation method: full document read, targeted consistency greps for DE 001R1 stale semantics, cross-reference of state/policy/connector/recovery contracts, and independent challenge of architectural coherence, modularity, security, resumability, idempotency, evaluation realism, Snowflake/dbt/GitHub integration, and DE 002 sequencing.

---

## DE 001R1 correction verification

All eight DE 001R1 corrections **PASS** at the documented semantic level:

| # | Correction | Verdict | Primary evidence |
|---|---|---|---|
| 1 | `PermissionLevel` is an unordered set of grants; one canonical definition | **PASS** | `docs/PERMISSION_MODEL.md` §2; `docs/CAPABILITY_MODEL.md` §1; DE-ADR-015 |
| 2 | `ConnectorSpec.allowed_permissions` replaces permission ceiling; membership-only checks | **PASS** | `docs/CONNECTOR_ARCHITECTURE.md` §2; `docs/PERMISSION_MODEL.md` §2.1, §3 R0/R4; DE-ADR-014 |
| 3 | Operation identity (`idempotency_key`) stable across retries; separate from attempt identity | **PASS** | `docs/STATE_MODEL.md` §4.2, §4.2b; `docs/ARCHITECTURE.md` §4.1; DE-ADR-011 |
| 4 | Ambiguous non-idempotent completion never auto-replayed; reconcile-before-retry | **PASS** | `docs/STATE_MODEL.md` §4.6; `docs/TOOL_CONTRACTS.md` §27; DE-ADR-022; `docs/EVALUATION_STRATEGY.md` S06b/S06c |
| 5 | Policy reason codes route deterministically by deny class | **PASS** | `docs/PERMISSION_MODEL.md` §3.1; `docs/STATE_MODEL.md` §3; DE-ADR-015 |
| 6 | DE 002 establishes baseline, not permanent freeze (DE-ADR-026) | **PASS** | `docs/adr/DE-ADR-026-contract-stability.md`; `docs/IMPLEMENTATION_PLAN.md` §5.2 |
| 7 | Scale profiles `tiny` / `demo` / `full` | **PASS** | `docs/DEMO_COMPANY.md` §11; `docs/IMPLEMENTATION_PLAN.md` DE 004 |
| 8 | DE 008 evaluates real dbt Core + `dbt-duckdb`; do not mandate if rejected | **PASS** | `docs/CONNECTOR_ARCHITECTURE.md` §5.2; `docs/TECH_STACK.md` §1 |

Consistency greps found no live product contradictions for stale `permission_ceiling`, ordinal permission comparison, attempt-in-operation-key, uniform DENY→FAILED, permanent interface freeze, or profile id `ci`. Six low-severity incomplete summaries in secondary sections are listed under **LOW** findings below.

**Important note:** Passing DE 001R1 verification does not eliminate deeper contract defects exposed during independent challenge. Several blocking issues concern contracts DE 002 would otherwise baseline.

---

## Architectural strengths (retain)

- **Modular monolith + PostgreSQL** is proportionate for ≤ 5 concurrent workflows; rejecting microservices, Kubernetes, Redis, Kafka, and agent frameworks is credible restraint (DE-ADR-008, DE-ADR-009, DE-ADR-010).
- **No autonomous specialist agents**; reasoning capabilities are tool-less, typed, and bounded (DE-ADR-010, `docs/AGENT_MODEL.md`).
- **Deterministic orchestration** with explicit transition table, phase templates, and bounded repair (DE-ADR-009, DE-ADR-023).
- **Operation vs attempt identity split** and reconcile-before-retry for crash recovery are unusually strong foundations (DE-ADR-011, DE-ADR-022, `docs/STATE_MODEL.md` §4.6).
- **Unordered permission grants** and deterministic deny-class routing are coherent improvements over ordinal permissions and blanket failure routing (DE-ADR-015).
- **Real + fake connector parity**, fault injection, explicit `MOCK` status, and contract tests are sound (DE-ADR-014).
- **DE-ADR-026** baseline-plus-additive-evolution policy is pragmatic.
- **Evidence-gated `dbt-duckdb` evaluation** (evaluate, do not mandate) is the correct stance (DE 008).
- **Evaluation** rejects LLM-as-judge for pass/fail and labels time-saved as estimate (DE-ADR-019).

---

## Findings

### CRITICAL

#### C-01 — Operation identity computed before inputs are materialized

| Field | Detail |
|---|---|
| **Document and section** | `docs/STATE_MODEL.md` §4.2 “Task record”; `docs/TOOL_CONTRACTS.md` §31 `plan_phase`; `docs/PERMISSION_MODEL.md` §4 “Approval system”; `docs/CONNECTOR_ARCHITECTURE.md` §2 `reconcile` |
| **Problem** | `idempotency_key` is computed when the task row is created, but task inputs may still contain unresolved `$from` placeholders until claim time. The key therefore hashes placeholder syntax, not resolved operation inputs. It also lacks a phase-run or plan-occurrence identifier. Reconciliation receives only `idempotency_key` without guaranteed access to the original resolved input or operation-specific context (e.g. `release_id` for deploy). |
| **Why it matters** | Different resolved inputs can share one operation identity, causing incorrect deduplication, reconciliation against the wrong external effect, or reuse of an approval across materially different operations. Re-entering a phase can collide with an earlier legitimate operation. |
| **Recommended correction** | Separate task templates from materialized operations. Resolve and validate all inputs first, then atomically persist immutable resolved-input digest, `phase_run_id` (or equivalent occurrence id), operation key, and capability version before policy evaluation, approval binding, or attempt creation. Pass sufficient recovery context into `reconcile`. |
| **Blocks DE 002?** | **Yes** — DE 002 baselines and tests the current formula. |

#### C-02 — Lease/recovery lacks fencing; stale workers can duplicate effects

| Field | Detail |
|---|---|
| **Document and section** | `docs/STATE_MODEL.md` §§4.3–4.6; `docs/adr/DE-ADR-022-background-execution.md` “Decision” |
| **Problem** | Leases have no documented heartbeat, fencing token/epoch, conditional finalization, or `IN_PROGRESS` reconciliation result. A lease reaper can expire and reconcile (or schedule retry) while the original handler is still running. |
| **Why it matters** | Reconciliation may return `NO_EFFECT` immediately before the original call commits, allowing a second attempt and duplicate side effect. A stale worker can overwrite or conflict with the replacement attempt. |
| **Recommended correction** | Add monotonically increasing claim/fencing epoch, renewable heartbeat, owner-and-epoch predicates on every task/attempt completion, and bounded `IN_PROGRESS` reconciliation. Reaping must atomically acquire recovery ownership and suppress late stale-worker writes. |
| **Blocks DE 002?** | **Yes**. |

#### C-03 — Reconcile-before-retry applies only after lease expiry, not on ambiguous normal failures

| Field | Detail |
|---|---|
| **Document and section** | `docs/CAPABILITY_MODEL.md` §4 “Lifecycle of a capability call”; `docs/STATE_MODEL.md` §4.6; `docs/CONNECTOR_ARCHITECTURE.md` §2; `docs/TOOL_CONTRACTS.md` shared retry conventions |
| **Problem** | Reconcile-before-retry is specified for lease expiry. Normal wrapper retries for timeout, network loss, or `TRANSIENT_PROVIDER` — including when `fail_after_effect` raises after applying the effect — can occur immediately without reconciliation. |
| **Why it matters** | A lost response is ambiguous regardless of whether the process crashed. Immediate retry can duplicate an externally successful operation. |
| **Recommended correction** | Classify failures as definitely-before-dispatch, definitely-failed, or outcome-ambiguous. Every ambiguous result from a side-effecting capability must reconcile before another attempt. Only proven pre-dispatch failures may retry directly. |
| **Blocks DE 002?** | **Yes**. |

#### C-04 — Security denials can be masked by earlier scope denials

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §3 rules R1–R20 and §3.1 routing; `docs/adr/DE-ADR-015-deterministic-policy.md` |
| **Problem** | Rule evaluation states “first DENY wins,” but routing says all reasons are considered and the most severe class wins. A scope rule such as R3/R4 can therefore hide a later SQL-security denial and suppress `POLICY_DENY_SECURITY` audit alerting. |
| **Why it matters** | Identical unsafe input can receive different classification and alerting depending on rule order. |
| **Recommended correction** | Evaluate all applicable deny rules, persist every reason, derive routing from maximum severity. Approval evaluation must occur only if no denial exists. |
| **Blocks DE 002?** | **Yes**. |

---

### HIGH

#### H-01 — Approval records cannot represent their claimed scope

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §4; `docs/TOOL_CONTRACTS.md` §35 `request_approval`; `docs/STATE_MODEL.md` §2 `APPROVAL_REQUIRED`; DE-ADR-016 |
| **Problem** | Approval row schema omits `idempotency_key` although approval is claimed to bind to it. `request_approval` input omits operation key. COST and DESIGN approvals require `requested_permission` even though neither corresponds to a permission grant. Target environment, connector identity/version, normalized action input, and expected external state are not bound. Multiple simultaneous approvals have incomplete aggregation/rejection semantics. |
| **Why it matters** | Implementations will invent incompatible matching rules; approvals may loop forever, apply to wrong operations, or be reused after target state changes. |
| **Recommended correction** | Define discriminated approval subjects: `OperationApproval`, `DesignApproval`, `BudgetIncreaseApproval`. Bind operation approvals to operation key, normalized input digest, artifact hashes, connector identity/version, environment, and expiry. COST approval must specify authorized cap delta/absolute cap. Define batch aggregation and kind-specific rejection outcomes. |
| **Blocks DE 002?** | **Yes** — `PolicyRequest`/`ApprovalRecord` become baseline contracts. |

#### H-02 — Workflow grant issuance has no authorization contract

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §1, §3; `docs/ARCHITECTURE.md` §§3.2–3.3; `docs/IMPLEMENTATION_PLAN.md` §5; `docs/MVP_SCOPE.md` §3 |
| **Problem** | Policy accepts `workflow_grants` as input, but no rule defines how an authenticated principal is authorized to obtain that grant set. Authentication is asserted repeatedly, but principal/session/authentication contract and implementation task are absent. V1 uses a single operator who is also approver. |
| **Why it matters** | Preventing the LLM from self-granting does not prevent an API, CLI, fixture, or compromised internal caller from supplying excessive grants. Approval attribution is not a security control without trusted identity. |
| **Recommended correction** | Baseline `PrincipalRef`, authentication source, role claims, and actor propagation in DE 002. Add trusted server-side `GrantAuthorization` derived from actor and environment; clients may request grants but never authoritatively set them. Select explicit local MVP auth/session mechanism and document CSRF/SSE behavior before approval work. |
| **Blocks DE 002?** | **Yes**. |

#### H-03 — `deploy` cannot use a single static `required_permission`

| Field | Detail |
|---|---|
| **Document and section** | `docs/CAPABILITY_MODEL.md` §§1, 2.7; `docs/PERMISSION_MODEL.md` §2–§3; `docs/TOOL_CONTRACTS.md` §27 |
| **Problem** | `CapabilitySpec` permits exactly one static `required_permission`, while `deploy` requires either `STAGING_DEPLOY` or `PRODUCTION_WRITE` based on payload target. Catalog lists `SD / PW` without a deterministic resolver. |
| **Why it matters** | Startup R0, planning, approval eligibility, connector `allowed_permissions`, and policy evaluation cannot agree on the required grant without undocumented special cases. |
| **Recommended correction** | Prefer separate `deploy_staging` and `deploy_production` capabilities, or define and test a typed deterministic `required_permission_for(validated_input)` used consistently by registration, planning, policy, and audit. |
| **Blocks DE 002?** | **Yes** — `CapabilitySpec` is baselined in DE 002. |

#### H-04 — Phase DAG immutability contradicts dynamic fan-out expansion

| Field | Detail |
|---|---|
| **Document and section** | `docs/ARCHITECTURE.md` §4; `docs/EXECUTION_FLOW.md` §3; `docs/STATE_MODEL.md` §4.1–§4.2; DE-ADR-011 |
| **Problem** | Phase DAG is declared immutable within a phase, but `assets[*]` expands one planned task into many `describe_asset` tasks after discovery completes. Placeholder resolution at claim time does not define safe dynamic task creation semantics. |
| **Why it matters** | Task identity, idempotency keys, phase completion, and audit ordering depend on when mapped tasks are materialized. Two schedulers could expand the same fan-out differently or twice. |
| **Recommended correction** | Define first-class deterministic mapped tasks with transactional expansion and uniqueness constraints on `(phase_run_id, local_id)`, or insert a new planning boundary after asset discovery before description fan-out. |
| **Blocks DE 002?** | **Yes** — first vertical slice relies on this fan-out. |

#### H-05 — Orchestrator phase completion is not serialized

| Field | Detail |
|---|---|
| **Document and section** | `docs/ARCHITECTURE.md` §§3.4, 3.6–3.7, §9; `docs/STATE_MODEL.md` §§3–5 |
| **Problem** | Workflow optimistic locking protects only the workflow row. It does not serialize phase completion evaluation, planning, task-graph creation, and transition as one operation. Required dependency failure has no complete terminal cascade (only optional dependants are skipped). |
| **Why it matters** | Two orchestrators can both observe phase completion and create duplicate plans/tasks. Failed required dependencies can leave tasks permanently `PENDING` with no legal transition despite reachability tests passing. |
| **Recommended correction** | Introduce persisted `phase_runs` with unique active generation per workflow, plus coordinator claim/lease or advisory locking. Define exhaustive deterministic phase reducer covering every terminal task outcome. Required dependency failure must cascade to specified `FAILED`, `BLOCKED`, or defined `SKIPPED`. |
| **Blocks DE 002?** | **Yes**. |

#### H-06 — Cancellation semantics are incomplete

| Field | Detail |
|---|---|
| **Document and section** | `docs/STATE_MODEL.md` §§2–3; `docs/ARCHITECTURE.md` §3.3; `docs/CAPABILITY_MODEL.md` §4 |
| **Problem** | Any non-terminal workflow may immediately become `CANCELLED` without defining cancellation propagation, subprocess termination, connector cancellation, lease invalidation, reconciliation, or late-result suppression. |
| **Why it matters** | A connector call may complete after the workflow is terminal, producing an unrecorded or incorrectly attributed external effect. |
| **Recommended correction** | Add persisted cancellation intent and `CANCEL_REQUESTED`/`CANCELLING` semantics: stop new claims, signal cooperative cancellation, fence results, reconcile ambiguous running attempts, then enter terminal `CANCELLED` only after quiescence or explicit park. |
| **Blocks DE 002?** | **Yes** — full transition table and worker are baselined. |

#### H-07 — Capability versioning is incomplete across registry and connectors

| Field | Detail |
|---|---|
| **Document and section** | `docs/CAPABILITY_MODEL.md` §§1, 5; `docs/CONNECTOR_ARCHITECTURE.md` §2; DE-ADR-013; DE-ADR-026 |
| **Problem** | Tasks resolve `capability_id@version` and two versions may coexist, but connectors advertise only `frozenset[CapabilityId]` without supported-version range. Persisted JSONB inputs/outputs have no documented schema version or upcasting policy. |
| **Why it matters** | In-flight workflows may bind to incompatible handlers after deployment; connector can appear compatible while implementing wrong contract version. |
| **Recommended correction** | Register implementations by `(capability_id, version)` with supported range; persist payload schema versions; pin each phase run to contract snapshot; define drain/park behavior for unsupported old work. |
| **Blocks DE 002?** | **Yes**. |

#### H-08 — `resolve_ambiguous_attempt` can mark success without validated output

| Field | Detail |
|---|---|
| **Document and section** | `docs/STATE_MODEL.md` §4.6 step 3; `docs/ARCHITECTURE.md` §3.3; `docs/IMPLEMENTATION_PLAN.md` §5.1 item 19 |
| **Problem** | `resolve_ambiguous_attempt(... outcome=SUCCEEDED|FAILED, external_ref?, note)` can mark success without supplying or reconstructing the capability’s validated typed output. |
| **Why it matters** | Downstream `$from` references and validators may consume missing or fabricated output. Human assertion alone is insufficient evidence of exact completion. |
| **Recommended correction** | Resolution should invoke connector-specific verification and reconstruct schema-valid result. If reconstruction is impossible, record effect-confirmed-but-result-unknown and require compensation, manual result import, or workflow abandonment rather than `SUCCEEDED`. |
| **Blocks DE 002?** | **Yes** — minimal resolver is in DE 002 scope. |

#### H-09 — Plan validation contradicts environmental parking design

| Field | Detail |
|---|---|
| **Document and section** | `docs/STATE_MODEL.md` §2 `PLANNING`; `docs/PERMISSION_MODEL.md` §3.1; `docs/TOOL_CONTRACTS.md` §31 |
| **Problem** | `plan_phase` validation rejects connectors not in `AVAILABLE|DEGRADED|MOCK`, while policy design says unavailable connector produces retained valid plan parked as environmental denial. |
| **Why it matters** | Same condition becomes `OUTPUT_INVALID` and consumes replans instead of deterministically parking and resuming. |
| **Recommended correction** | Structural plan validation should accept registered connectors regardless of current health; connector status evaluated by policy producing `PARK`. Alternatively remove retained-plan behavior and define one consistent path. |
| **Blocks DE 002?** | **Yes**. |

#### H-10 — dbt idempotency assumptions are unsafe

| Field | Detail |
|---|---|
| **Document and section** | `docs/TOOL_CONTRACTS.md` §§16–17; `docs/CONNECTOR_ARCHITECTURE.md` §5.2; `docs/STATE_MODEL.md` §4.6; `docs/PERMISSION_MODEL.md` §12; DE-ADR-014; DE-ADR-022 |
| **Problem** | Idempotence is capability-level boolean; dbt incremental runs and `run_pipeline` composites declared idempotent “by design.” MERGE, snapshots, hooks, nondeterministic SQL, and partial DAG completion are not generally convergent. `run_results.json` overwrite and query history cannot prove atomic multi-model completion. |
| **Why it matters** | Crash recovery can duplicate rows, adopt incomplete builds, or trigger unsafe rerun on `UNKNOWN` reconciliation. Generated macros/hooks may execute statements not covered by pre-execution SQL classification. |
| **Recommended correction** | Make effect semantics invocation-specific: side-effect-free, externally deduplicated, proven convergent, or non-idempotent. Default dbt execution to non-idempotent unless convergence proven per invocation. Use operation-specific invocation directories/journals; validate compiled models, tests, hooks, macros, and config. |
| **Blocks DE 002?** | **Partially** — baseline `CapabilitySpec.idempotent` blocks DE 002; dbt-specific completion blocks DE 008. |

#### H-11 — SQL classifier cannot support read-only guarantee under DEV RW identity

| Field | Detail |
|---|---|
| **Document and section** | `docs/TOOL_CONTRACTS.md` §§8–10; `docs/CONNECTOR_ARCHITECTURE.md` §5.1; `docs/PERMISSION_MODEL.md` §12 |
| **Problem** | Classification records statement and object access but not invoked functions, stages, external functions, UDFs, table functions, or unsafe session constructs. `execute_query` may run through DEV read-write identity (`AIDE_DEV_RW`). |
| **Why it matters** | Parseable `SELECT` or CTAS can invoke externally acting or data-egress functions while passing documented checks. |
| **Recommended correction** | Use RO identity for every read capability. Add function/construct classification with explicit allow-list; deny external functions, unapproved UDFs, stages/URLs, unknown AST nodes. Test Snowflake-specific adversarial statements. |
| **Blocks DE 002?** | **Yes** — SQL classifier is in DE 002 scope. |

#### H-12 — MOCK artifacts can enter real delivery paths

| Field | Detail |
|---|---|
| **Document and section** | `docs/CONNECTOR_ARCHITECTURE.md` §3; `docs/TOOL_CONTRACTS.md` §0, §27; `docs/ARCHITECTURE.md` §3.21 |
| **Problem** | `MOCK` connectors are eligible; only UI watermark promised. `ArtifactRef` has no execution-mode or connector-provenance field; deploy/Git policy does not reject mock-derived artifacts. |
| **Why it matters** | Offline/simulated outputs can be mistaken for real evidence or deployed to staging after approval. |
| **Recommended correction** | Add immutable provenance and sensitivity labels to artifacts. Policy must deny real Git/deploy when any transitive input is mock-derived unless explicit promotion workflow recreates and validates against real connectors. |
| **Blocks DE 002?** | **Yes** — `ArtifactRef` is baselined. |

#### H-13 — Cost approval and cap enforcement are non-executable

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §3 R18; `docs/OBSERVABILITY.md` §2; `docs/EVALUATION_STRATEGY.md` S11; `docs/MVP_SCOPE.md` §5 |
| **Problem** | R18 requires COST approval when cap exceeded, but no approval field states authorized new amount. `LLM_BUDGET_EXCEEDED` routes to `BLOCKED` with no deterministic continuation after approval. `estimated_cost` optional; no atomic reservation for concurrent calls. Snowflake credit cap described as enforced but only query tags/timeouts exist. |
| **Why it matters** | Approval may loop forever; concurrent calls can each pass stale running-total check and overspend. UI may present estimated budget as hard safety control. |
| **Recommended correction** | Versioned budget ledger with atomic worst-case reservation before each call and settlement afterward. COST approval specifies cap delta/absolute cap, currency, scope, expiry. Describe Snowflake control as estimated preflight plus hard time/query limits unless isolated warehouse/resource monitor used. |
| **Blocks DE 002?** | **Yes** for atomic LLM budget enforcement; warehouse refinement can wait for DE 005. |

#### H-14 — Audit integrity is asserted, not enforced

| Field | Detail |
|---|---|
| **Document and section** | `docs/OBSERVABILITY.md` §1, §7; `docs/PERMISSION_MODEL.md` §8; `docs/ARCHITECTURE.md` §§3.23, 8; DE-ADR-018 |
| **Problem** | Audit append-only behavior and atomicity with policy decisions, state transitions, and results are asserted but not specified. No DB role separation, revoked UPDATE/DELETE, transactional outbox, hash chaining, or monotonic sequence allocation under concurrent writers. Operator deletion by workflow conflicts with compliance retention claims. |
| **Why it matters** | Crashes can leave state without audit evidence or evidence for rolled-back actions. Application-level append-only is not tamper-resistant. |
| **Recommended correction** | Commit each state mutation and audit event in same PostgreSQL transaction. Allocate sequence numbers transactionally with unique constraint. Restrict audit-table privileges. Add hash chain or signed checkpoints if compliance-grade integrity claimed; otherwise narrow claims. |
| **Blocks DE 002?** | **Yes** for transactional completeness; cryptographic anchoring can be deferred if claims narrowed. |

#### H-15 — Vendor-neutral abstraction is overstated for transformation contracts

| Field | Detail |
|---|---|
| **Document and section** | `docs/ARCHITECTURE.md` §11; `docs/TOOL_CONTRACTS.md` shared types §0 and §§14–21; `docs/CAPABILITY_MODEL.md` §2.4; DE-ADR-013 |
| **Problem** | Claimed vendor-neutral abstraction contains fixed dialect literals (`snowflake|postgres|ansi`), relational-only `AssetRef`, and dbt-specific concepts (project state, manifest, `ref`/`source`, dbt tests, `run_results`). |
| **Why it matters** | BigQuery/Fabric naming, storage assets, SQLMesh and Spark cannot implement without semantic distortion or core schema changes despite “no orchestrator change” claim. |
| **Recommended correction** | Extensible dialect identifiers and hierarchical asset addresses. Separate generic transformation plans/results from dbt-specific extension contracts. |
| **Blocks DE 002?** | **Yes** for shared `AssetRef`/`SqlText`; transformation refinements may finish before DE 008. |

#### H-16 — DE 002 scope is overloaded as contract baseline

| Field | Detail |
|---|---|
| **Document and section** | `docs/IMPLEMENTATION_PLAN.md` §§3–5; DE-ADR-021; DE-ADR-026 |
| **Problem** | DE 002 combines domain contracts, full transition table, queue/recovery, persistence/migrations, policy, SQL classifier, connector SDK and fake, LLM gateway, observability, secrets, CLI/API, four reasoning capabilities, and end-to-end slice — while simultaneously establishing most long-lived contracts. CI (DE 003) follows entire slice. Later waves run DE 008b parallel with DE 007 and DE 016a parallel with DE 014 without separate task contracts. |
| **Why it matters** | Foundational defects become difficult to localize. Parallel consumers may build against unmerged producer contracts. |
| **Recommended correction** | Split sequentially: contract kernel → durable scheduler/recovery → offline safe-SQL slice. Put minimal CI immediately after kernel. Create explicit DE 008a/008b and DE 016a/016b contracts with distinct dependencies; consumers start only after required schemas merge. |
| **Blocks DE 002?** | **Yes** for current DE 002 task definition (scope revision required before execution). |

#### H-17 — Connector health / degraded-permission model is type-inconsistent

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §3 R2b; `docs/CONNECTOR_ARCHITECTURE.md` §§2–4 |
| **Problem** | R2b tests `capability ∈ connector_status.missing_permissions`, but `ConnectorStatus` is enum and `missing_permissions` implies permission values not capabilities. `ConnectorHealth` referenced but not defined as typed snapshot. |
| **Why it matters** | Implementations may park wrong capabilities or silently allow unavailable permissions. |
| **Recommended correction** | Define immutable `ConnectorHealthSnapshot(status, checked_at, expires_at, missing_permissions: frozenset[PermissionLevel], reason_codes)`. Test `required_permission ∈ missing_permissions`; reject expired snapshots. |
| **Blocks DE 002?** | **Yes**. |

#### H-18 — Secret-resolution ownership contradicts itself

| Field | Detail |
|---|---|
| **Document and section** | `docs/CONNECTOR_ARCHITECTURE.md` introduction; `docs/ARCHITECTURE.md` §§3.10, 3.26; `docs/IMPLEMENTATION_PLAN.md` §2 import rules |
| **Problem** | Connectors called only secret resolvers, while LLM provider layer also authorized to resolve provider credentials. Import-linter graph ambiguous. |
| **Why it matters** | Conflicting boundaries lead to forbidden imports or broad secret-provider access. |
| **Recommended correction** | State only connector adapters and LLM provider adapters may resolve allow-listed `SecretRef`s, each with scoped resolver; prohibit secret enumeration elsewhere. |
| **Blocks DE 002?** | **Yes**. |

#### H-19 — Prompt-injection evaluation tests syntax, not semantic integrity

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §7; `docs/AGENT_MODEL.md` §9; `docs/EVALUATION_STRATEGY.md` S09 |
| **Problem** | Injection raises event only; S09 uses replayed output and checks unsafe SQL not generated. Structural validators do not detect manipulated joins, filters, source selection, misleading documentation, or sensitive metadata copied into PR. |
| **Why it matters** | Injection can cause semantically corrupt DEV tables and externally visible Git artifacts while remaining syntactically safe. |
| **Recommended correction** | Track untrusted-source taint through reasoning outputs; require review before writes/egress when suspected injection influenced them. Add adversarial live-model suites for semantic deviation, source selection, canary leakage. |
| **Blocks DE 002?** | **No** if DE 002 remains offline with trusted fixtures; **Yes** before untrusted live metadata in production paths (DE 006+). |

#### H-20 — “Tests not weakened” does not protect test semantics

| Field | Detail |
|---|---|
| **Document and section** | `docs/QUALITY_STRATEGY.md` §§2, 5; `docs/PERMISSION_MODEL.md` §11 |
| **Problem** | Comparing test sets and thresholds does not prevent changing predicate SQL, expected values, source filters, grain, or upstream logic so bad rows disappear. |
| **Why it matters** | Repair can produce green but incorrect dataset. |
| **Recommended correction** | Bind validation definitions to normalized AST/digests and approved design invariants. Repairs must not alter checks, grain, source scope, or reconciliation bases without new design approval. Add anti-vacuity and row-loss checks. |
| **Blocks DE 002?** | **No**; blocks DE 009/010. |

#### H-21 — Credentialless tests do not establish fake/real parity

| Field | Detail |
|---|---|
| **Document and section** | `docs/CONNECTOR_ARCHITECTURE.md` §§2, 8; `docs/EVALUATION_STRATEGY.md` §1; `docs/TECH_STACK.md` §1 |
| **Problem** | Real contract tests optional/skipped without credentials; recorded real fixtures optional. E2 uses fake connectors and replayed LLM. `dbt-duckdb` path may be rejected without defined credentialless replacement. |
| **Why it matters** | CI can remain green while production SDK, dialect, auth, error mapping, or transaction behavior diverges. |
| **Recommended correction** | Versioned redacted real-response fixtures for error/protocol behavior; parity reports; mandatory live contract gates before connector release; real dbt Core in credentialless CI or explicit accepted gap documented. |
| **Blocks DE 002?** | **No**; blocks real connector readiness (DE 005/008). |

#### H-22 — Snowflake reconciliation tagging is contradictory

| Field | Detail |
|---|---|
| **Document and section** | `docs/CONNECTOR_ARCHITECTURE.md` §§2, 5.1; `docs/STATE_MODEL.md` §4.6 |
| **Problem** | `CallContext.query_tag` contains operation key, but Snowflake session defaults specify only workflow and task. Reconciliation depends on finding operation key in query history. |
| **Why it matters** | Crash recovery can return `Unknown` or associate wrong query. |
| **Recommended correction** | One canonical structured tag containing full operation identity and attempt identity, with round-trip parser and truncation/collision tests. |
| **Blocks DE 002?** | **Yes**. |

#### H-23 — Human deduplication ownership conflicts with LLM-proposed survivorship

| Field | Detail |
|---|---|
| **Document and section** | `docs/ARCHITECTURE.md` §6; `docs/DATA_MODELLING_STRATEGY.md` §4; `docs/DATA_ENGINEERING_CAPABILITY_MAP.md` §3; `docs/DEMO_COMPANY.md` §4 |
| **Problem** | Human owns entity identity, but LLM may invent survivorship/deduplication rules shown later in PR. Mechanical uniqueness validation cannot establish semantic identity correctness. |
| **Why it matters** | Incorrect customer merging produces plausible but materially wrong facts undetectable by current deterministic tests. |
| **Recommended correction** | Make inferred identity/survivorship assumptions blocking clarifications or design approvals before execution unless organization policy explicitly supplies the rule. |
| **Blocks DE 002?** | **No**; required before DE 007. |

#### H-24 — Offline evaluation does not prove live reasoning quality

| Field | Detail |
|---|---|
| **Document and section** | `docs/EVALUATION_STRATEGY.md` §§1, 3, 5; DE-ADR-019; `docs/IMPLEMENTATION_PLAN.md` DE 015, DE 018 |
| **Problem** | E2 replays predetermined LLM outputs — evaluates orchestration/validators, not reasoning quality. No unseen/holdout requirements or live success thresholds. E4 runs once despite evaluation contract requiring distributions over N ≥ 3 runs. |
| **Why it matters** | Passing CI cannot support credible claim that live AI reliably discovers, models, or repairs unseen enterprise tasks. |
| **Recommended correction** | Separate engine and reasoning scorecards; held-out schema/request variants, semantic ground truth, minimum E3/E4 thresholds; E4 at least three runs or revise stated rule. |
| **Blocks DE 002?** | **No**; blocks MVP credibility before demo hardening. |

#### H-25 — Demo repair narrative contradicts validated design

| Field | Detail |
|---|---|
| **Document and section** | `docs/DEMO_COMPANY.md` §§4–6; `docs/EXECUTION_FLOW.md` §§5, 12; `docs/DATA_MODELLING_STRATEGY.md` §2.4 |
| **Problem** | Profiling detects payment duplicates; rule F4 and target design already contain `int_payments_deduplicated`; worked execution omits effective deduplication and “discovers” it only after test failure. |
| **Why it matters** | Flagship repair demonstrates generator bypassing validated design. Correct generation validator should reject that output before execution. |
| **Recommended correction** | Make duplicates arrive after profiling (latent defect), or classify generation omitting mandated design rule as `OUTPUT_INVALID`, not successful design followed by runtime repair. |
| **Blocks DE 002?** | **No**; blocks recruiter credibility (DE 007–018). |

#### H-26 — Module import graph is ambiguous

| Field | Detail |
|---|---|
| **Document and section** | `docs/IMPLEMENTATION_PLAN.md` §2; `docs/CAPABILITY_MODEL.md` §1; `docs/PERMISSION_MODEL.md` §2 |
| **Problem** | Declared layer order places `domain` above `capabilities`, while `CapabilitySpec` must import canonical `PermissionLevel` from `domain`. Conflicts with import-linter enforcement intent. |
| **Why it matters** | DE 002 cannot enforce documented dependency DAG without cycle or exception weakening architecture boundary. |
| **Recommended correction** | Publish acyclic package graph: `domain` at bottom; `capabilities` and `connectors.base` depend on domain; policy, reasoning, connectors, tools depend on those contracts; orchestration depends on tools and domain. |
| **Blocks DE 002?** | **Yes** for import-linter acceptance. |

#### H-27 — GitHub idempotency and concurrency underspecified

| Field | Detail |
|---|---|
| **Document and section** | `docs/TOOL_CONTRACTS.md` §25; `docs/CONNECTOR_ARCHITECTURE.md` §§5.3, 7 |
| **Problem** | “Same tree → same commit” false unless commit metadata fixed. Real Git working-copy isolation and concurrent remote-branch update handling unspecified; only dbt filesystem isolation defined. |
| **Why it matters** | Retry or concurrent workflow activity can create distinct commits, dirty shared checkouts, or race branch updates. |
| **Recommended correction** | One clean clone/worktree per workflow; reconcile before commit; verify expected remote head; reject non-fast-forward ownership conflicts; idempotency by trailer/tree digest not commit SHA determinism. |
| **Blocks DE 002?** | **No**; required before DE 012. |

---

### MEDIUM

#### M-01 — Multi-currency revenue lacks FX or per-currency reconciliation policy

| Field | Detail |
|---|---|
| **Document and section** | `docs/DEMO_COMPANY.md` §§1–8; `docs/QUALITY_STRATEGY.md` §2 `reconciliation_sum` |
| **Problem** | Company bills EUR/USD/GBP; daily revenue mart has unqualified amount fields and no FX-rate source or currency dimension. Exact summed reconciliation across currencies is financially meaningless. |
| **Why it matters** | Likely recruiter/interviewer challenge; undermines synthetic-enterprise realism. |
| **Recommended correction** | Reconcile per transaction currency and expose currency in facts, or add dated FX rates plus transaction/base-currency measures and explicit conversion policy. |
| **Blocks DE 002?** | **No**. |

#### M-02 — Demo narrative counts disagree with enumerated artefacts

| Field | Detail |
|---|---|
| **Document and section** | `docs/EXECUTION_FLOW.md` §§3, 7; `docs/DEMO_COMPANY.md` §§6, 10 |
| **Problem** | Story claims 13 discovered tables with USAGE disabled while listed enabled catalogue has 12. Describes 20 file sets while enumerating 23 models plus YAML files. |
| **Why it matters** | Hard-coded impressive numbers that disagree with model damage recruiter credibility. |
| **Recommended correction** | Derive displayed counts from generated catalogue/manifest; use ranges in narrative until fixtures exist. |
| **Blocks DE 002?** | **No**. |

#### M-03 — Staging deploy scope is inconsistent across documents

| Field | Detail |
|---|---|
| **Document and section** | `docs/MVP_SCOPE.md` §2; `docs/DATA_ENGINEERING_CAPABILITY_MAP.md` §9; `docs/ARCHITECTURE.md` §10; `docs/IMPLEMENTATION_PLAN.md` DE 017 |
| **Problem** | Staging deploy described as V1 gated action, stub/V2, PR/approval boundary only, and real DE 017 deployment interchangeably. |
| **Why it matters** | Changes identity, authorization, rollback, and acceptance scope materially. |
| **Recommended correction** | For recruiter V1, stop at real PR plus authenticated deployment approval with fake deployment result; treat real staging deploy as explicit stretch unless made consistent acceptance criterion. |
| **Blocks DE 002?** | **No**. |

#### M-04 — Snowflake credit cap described as enforced but is estimated only

| Field | Detail |
|---|---|
| **Document and section** | `docs/MVP_SCOPE.md` §5; `docs/TECHNICAL_RISKS.md` R4; `docs/CONNECTOR_ARCHITECTURE.md` §5.1 |
| **Problem** | Query tags attribute cost; statement timeouts bound duration; neither enforces per-workflow Snowflake credit cap. Account-usage reporting lags. |
| **Why it matters** | UI and policy may present estimated budget as hard safety control. |
| **Recommended correction** | Call this estimated preflight budget plus hard time/query limits; use isolated warehouses/resource monitors only if true enforceable credit boundary required. |
| **Blocks DE 002?** | **No**. |

#### M-05 — Capability addition governance contradicts DE-ADR-026

| Field | Detail |
|---|---|
| **Document and section** | `docs/CONNECTOR_ARCHITECTURE.md` §6; DE-ADR-026 |
| **Problem** | One document requires ADR for every new capability; DE-ADR-026 permits additive capabilities without ADR when tests pass unchanged. |
| **Why it matters** | Parallel teams will apply different governance. |
| **Recommended correction** | Make DE-ADR-026 authoritative: additive capabilities require normal review and synchronized docs; semantic/breaking changes require ADR. |
| **Blocks DE 002?** | **No**; fix before parallel waves. |

#### M-06 — Retry contract terminology is inconsistent

| Field | Detail |
|---|---|
| **Document and section** | `docs/CAPABILITY_MODEL.md` §1; `docs/STATE_MODEL.md` §§4.2, 4.6; `docs/TOOL_CONTRACTS.md` shared conventions |
| **Problem** | Retry contracts alternate between `max_attempts`, `max_retries`, and total-attempt notation. `attempt_count < max_retries` ambiguous and likely off-by-one. |
| **Why it matters** | Different implementations can perform different numbers of external calls, undermining bounded retry guarantees. |
| **Recommended correction** | One field, preferably `max_attempts` including initial call; define whether recovered/expired attempts consume it; test exact call counts for every recovery branch. |
| **Blocks DE 002?** | **Yes** — task and capability fields are baselined. |

---

### LOW

#### L-01 — MVP scope omits operation-key approval binding

| Field | Detail |
|---|---|
| **Document and section** | `docs/MVP_SCOPE.md` §2 “Policy & approvals” |
| **Problem** | States approvals bound to artifact hashes only; omits operation identity binding from DE 001R1. |
| **Recommended correction** | Add operation key binding and retry/reconciliation coverage while hashes unchanged; align with `docs/PERMISSION_MODEL.md` §4. |
| **Blocks DE 002?** | **No**. |

#### L-02 — Approval Engine component summary incomplete

| Field | Detail |
|---|---|
| **Document and section** | `docs/ARCHITECTURE.md` §3.20 |
| **Problem** | Responsibility lists `(workflow, task, artifact hashes, requested permission)` but not operation key. |
| **Recommended correction** | Extend binding tuple; cross-ref `docs/PERMISSION_MODEL.md` §4. |
| **Blocks DE 002?** | **No**. |

#### L-03 — Risk register omits operation-level approval binding

| Field | Detail |
|---|---|
| **Document and section** | `docs/TECHNICAL_RISKS.md` R21 |
| **Problem** | Mitigation says “Approvals bound to hashes” only. |
| **Recommended correction** | Add operation identity (`idempotency_key`). |
| **Blocks DE 002?** | **No**. |

#### L-04 — Approval record schema omits operation key field

| Field | Detail |
|---|---|
| **Document and section** | `docs/PERMISSION_MODEL.md` §4 Record row vs Scope row |
| **Problem** | `approvals` schema lists `task_id?` but not `idempotency_key`; Scope claims binding by operation key. |
| **Recommended correction** | Add `idempotency_key` (or explicit denormalized derivation rule) to Record schema. |
| **Blocks DE 002?** | **No** (but should align before DE 002 baseline if approvals schema is included). |

#### L-05 — Environmental denial summary imprecise

| Field | Detail |
|---|---|
| **Document and section** | `docs/STATE_MODEL.md` §1.1 |
| **Problem** | “environmental denials park (`BLOCKED`)" conflates task `PARKED` with workflow `BLOCKED`. |
| **Recommended correction** | Reword: task `PARKED`, workflow `BLOCKED`. |
| **Blocks DE 002?** | **No**. |

#### L-06 — Master workflow architecture freeze lacks DE-ADR-026 cross-reference

| Field | Detail |
|---|---|
| **Document and section** | `.ai/MASTER_WORKFLOW.md` §20 |
| **Problem** | Does not explicitly cross-reference DE-ADR-026 additive contract evolution (unlike `.cursor/rules/20-architecture.mdc`). |
| **Recommended correction** | Add one sentence: architecture baselined; contracts evolve additively per DE-ADR-026 when existing tests pass unchanged. |
| **Blocks DE 002?** | **No**. |

---

## Final recommendation

**REVISE BEFORE DE 002**

The architecture has a strong core thesis: modular monolith, deterministic orchestration, capability abstraction, bounded repair, real/fake connector parity, and evidence-based evaluation. DE 001R1 corrections are implemented consistently. However, independent review identified **4 CRITICAL**, **27 HIGH**, **6 MEDIUM**, and **6 LOW** findings. The CRITICAL and blocking HIGH findings concern contracts DE 002 would baseline — operation identity materialization, lease fencing, ambiguous-retry reconciliation, policy reason aggregation, approvals, authentication/grants, dynamic task expansion, orchestrator serialization, cancellation, capability versioning, and overloaded DE 002 scope.

**Not recommended:** REJECT ARCHITECTURE — the foundation is salvageable with targeted contract corrections.
**Not recommended:** ACCEPT ARCHITECTURE or ACCEPT WITH NON-BLOCKING FOLLOW UPS — blocking findings are too numerous and central.

---

## Whether DE 002 may begin

**No.**

DE 002 must not begin until blocking findings (C-01 through C-04 and HIGH findings marked “Blocks DE 002? Yes”) are corrected in architecture documents and ADRs, then independently re-reviewed.

Minimum pre-DE-002 correction set:

1. Materialized operation identity (resolved inputs, phase run id, recovery context)
2. Lease fencing and ambiguous-failure reconciliation on all retry paths
3. Policy deny reason aggregation and routing consistency
4. Approval subject model (operation/design/budget) with executable COST continuation
5. Authentication/principal/grant-authorization baseline
6. Dynamic fan-out / phase-run materialization semantics
7. Orchestrator phase-run serialization and dependency cascade rules
8. Cancellation propagation and late-result fencing
9. Capability/connector version negotiation
10. Revised DE 002 scope sequencing (kernel → recovery → slice; CI earlier)
11. Connector health snapshot typing; secret boundary clarity; import-layer DAG
12. Artifact provenance for MOCK isolation; canonical Snowflake query tags
13. SQL classifier function/construct coverage and RO identity for reads

---

## ADR changes required

Amend before DE 002 (non-exhaustive; corrections should be reflected in both ADR files and companion docs):

| ADR | Required change |
|---|---|
| **DE-ADR-011** | Materialized operations, phase runs, mapped-task expansion, dependency cascade |
| **DE-ADR-013** | Version negotiation; generic vs platform-specific transformation contracts |
| **DE-ADR-014** | Reconcile context; connector health snapshot; dbt invocation journal; query-tag canonical form; artifact provenance |
| **DE-ADR-015** | Evaluate-all-deny-reasons routing; RO read path; function classification; grant authorization |
| **DE-ADR-016** | Discriminated approval subjects; budget approval fields; operation binding schema |
| **DE-ADR-017** | Atomic budget reservation; clarify secret resolver scope for LLM providers |
| **DE-ADR-018** | Transactional audit atomicity; narrow tamper-resistance claims or add integrity mechanism |
| **DE-ADR-021** | Resequenced DE 002/003; explicit sub-task contracts for parallel waves |
| **DE-ADR-022** | Lease heartbeat/fencing; ambiguous-retry reconciliation; cancellation interaction |
| **DE-ADR-026** | Defer full baseline until corrected contracts pass concurrency/recovery tests; resolve capability-addition governance conflict |

**Retain without structural change:** DE-ADR-008 (modular monolith), DE-ADR-009 (custom orchestration), DE-ADR-010 (no specialist agents), DE-ADR-012 (PostgreSQL), DE-ADR-019 (evaluation harness), DE-ADR-020 (local/cloud boundaries), DE-ADR-023 (bounded repair), DE-ADR-024 (frontend), DE-ADR-025 (Python toolchain).

---

## Technology choices requiring reconsideration

| Area | Current choice | Reconsideration |
|---|---|---|
| **Authentication** | Asserted but unspecified | **Must select** concrete MVP mechanism (e.g. local session/JWT/API key with role claims) before DE 002 baselines audit `actor` fields |
| **Modular monolith** | Retained | No change warranted |
| **PostgreSQL task queue** | Retained | No change warranted at MVP scale |
| **Custom orchestrator** | Retained | No change warranted; add fencing/recovery semantics |
| **dbt integration** | Subprocess `dbtRunner` | Clarify wrapper vs direct CLI; default non-idempotent until proven; operation-level journals |
| **dbt-duckdb offline target** | Evaluate in DE 008 | Retain evidence-gated approach; define fallback if rejected |
| **Snowflake identity for reads** | DEV RW for connector instance | **Use RO identity** for read capabilities |
| **Snowflake cost cap** | Described as enforced | Reframe as estimate + timeouts unless resource monitors added |
| **Temporal / Redis / K8s** | Rejected for V1 | No change warranted |

---

## Remaining open questions

1. **Authentication MVP:** Which local auth mechanism (session cookie, API key, OIDC stub) will DE 002 implement, and how are operator vs approver roles separated in V1?
2. **Dynamic fan-out:** Will mapped tasks be first-class graph nodes with transactional expansion, or will discovery and describe become separate phase runs?
3. **Deploy capability split:** Separate staging/production capabilities vs typed permission resolver — which minimizes policy special cases?
4. **dbt idempotency default:** Will all dbt side-effecting capabilities default to non-idempotent with per-model convergence proofs, or will materialization-specific rules be encoded in capability metadata?
5. **dbt-duckdb adoption criteria:** What exact compatibility thresholds (adapter maturity, SQL portability %, CI runtime) trigger rejection, and what is the credentialless fallback?
6. **Staging deploy in recruiter V1:** Real `AIDE_STAGING` deploy (DE 017) vs fake deploy with approval gate only — which is the acceptance criterion?
7. **Demo repair narrative:** Will F2 (duplicate payments) remain a “discovery” repair or become a generation-validation failure given pre-known duplicates in design?
8. **Audit tamper resistance:** Is transactional same-commit audit sufficient for V1 claims, or must hash-chaining be in scope before “enterprise-grade audit” language is used?
9. **Multi-currency reconciliation:** Per-currency facts vs FX conversion table — which matches demo narrative and recruiter expectations?
10. **Parallel wave contracts:** Will DE 008a/008b and DE 016a/016b receive separate task IDs, branches, and forbidden-file lists before Wave 3?
11. **Human identity rules:** Which deduplication/survivorship assumptions require blocking clarification or design approval vs PR review only?
12. **Live evaluation thresholds:** What minimum E3/E4 success rates and variance bounds are required before demo hardening (DE 018) sign-off?

---

## Reviewer attestation

- Review analysis and findings: **GPT 5.6 Sol High**
- Repository artifact persistence after the review: **Composer 2.5 only**
- Architecture documents: **not modified**
- Product code: **not modified**
- Merge: **not performed**
- Tests run: **none** (documentation review only)
- Validation: consistency greps and cross-reference analysis against commit `b12b61ddeada830597809b9e70d15feca1105625`
