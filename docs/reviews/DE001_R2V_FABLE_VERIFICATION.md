# DE 001R2V — Focused Independent Architecture Verification

**Task ID:** DE 001R2V (Focused Independent Architecture Verification)
**Review model:** Claude Fable 5.1
**Reasoning level:** High
**Artifact persistence:** Composer 2.5 was used only after the review to write the already-completed verification into this repository. Composer did not perform, delegate, or alter the architecture analysis.
**Branch reviewed:** `docs/DE001_mvp_architecture`
**Commit reviewed:** `d865b12` (`d865b12docs: normalize architecture review formatting`)
**Review date:** 2026-09-11
**Review mode:** READ ONLY (verification artifact only; no architecture, ADR, governance, or product code modified)
**Repository path reviewed:** `/workspace` (Cloud Agent checkout)

## Provenance

- **Review analysis and verdict:** Claude Fable 5.1 High
- **Repository artifact persistence:** Composer 2.5 only

---

## Review scope

Focused independent verification of DE 001R2A contract hardening against the blocking
findings recorded in `docs/reviews/DE001_SOL_ARCHITECTURE_REVIEW.md` (GPT 5.6 Sol High,
commit `b12b61d`). No redesign. No new speculative requirements unless they exposed a
genuine contradiction or implementation blocker.

Documents read:

- `docs/reviews/DE001_SOL_ARCHITECTURE_REVIEW.md`
- All architecture documents under `docs/` (including `EXECUTION_FLOW.md`, `IMPLEMENTATION_PLAN.md`)
- All ADRs DE-ADR-008 … DE-ADR-027 and `docs/adr/README.md`
- `.ai/ARCHITECTURE.md`, `.ai/DECISIONS.md`, `.ai/MASTER.md`, `.ai/MASTER_WORKFLOW.md`,
  `.ai/PROJECT_CONTEXT.md`, `.ai/TASKS.md`, `.ai/AUDIT.md`
- `.cursor/rules/20-architecture.mdc`
- Git diff footprint `b12b61d..d865b12`

Validation method: full read of amended contracts; targeted consistency greps for stale
semantics (`max_retries`, `permission_ceiling`, `idempotent: bool`, `assets[*]`,
`outcome=SUCCEEDED|FAILED` resolver, "first DENY wins", untyped `ConnectorStatus` /
`ConnectorHealth`); cross-reference of the 20 focus areas listed in the DE 001R2V task
contract; assessment of DE 002A/B/C sequencing against `docs/IMPLEMENTATION_PLAN.md` and
`.ai/TASKS.md`.

---

## Original blocking findings verified

The table below records every finding from `DE001_SOL_ARCHITECTURE_REVIEW.md` that was
marked **Blocks DE 002? Yes** (or **Partially** for H-10 baseline). Result reflects whether
DE 001R2A resolved the finding at the documented contract level.

| ID | Original finding (summary) | Result | Primary evidence (post-R2A) | Residual |
|---|---|---|---|---|
| **C-01** | Operation identity computed before inputs materialized | **RESOLVED** | `docs/STATE_MODEL.md` §4 lifecycle, §4.2a (7-step materialization, `aide-op-v2` key with `phase_run_id`, pinned versions, `resolved_input_digest`); `RecoveryContext` | U-02 (approval/deploy flow consistency) |
| **C-02** | Lease/recovery lacks fencing; stale workers can duplicate effects | **RESOLVED** | §4.3 claim epoch, heartbeat, owner/epoch/attempt/cancellation predicates; §4.7 recovery ownership; DE-ADR-022 | U-07 (lock vs cancel prose) |
| **C-03** | Reconcile-before-retry only after lease expiry, not ambiguous normal failures | **RESOLVED** | §4.7 step 3 evidence classes (`DEFINITELY_BEFORE_DISPATCH`, `DEFINITELY_REJECTED_NO_EFFECT`, `OUTCOME_AMBIGUOUS`); `CAPABILITY_MODEL` §4; `PERMISSION_MODEL` §10 | U-06, U-10 (summary-table nits) |
| **C-04** | Security denials masked by earlier scope denials | **RESOLVED** | `PERMISSION_MODEL` §3 evaluate-all-denials; §3.1 `SECURITY > SCOPE > ENVIRONMENTAL`; DE-ADR-015 | — |
| **H-01** | Approval records cannot represent claimed scope | **RESOLVED** (contract) | Typed `OperationApproval` / `DesignApproval` / `BudgetIncreaseApproval`; complete binding in `PERMISSION_MODEL` §4; DE-ADR-016 | U-01, U-02 (flow/table consistency) |
| **H-02** | Workflow grant issuance has no authorization contract | **RESOLVED** | `PrincipalRef`, `GrantAuthorization`, server-side `GrantAuthorizer`; DE-ADR-027 | — |
| **H-03** | `deploy` cannot use single static `required_permission` | **RESOLVED** | Split `deploy_staging` (SD) / `deploy_production` (PW, DISABLED); `TOOL_CONTRACTS` §27 | — |
| **H-04** | Phase DAG immutability contradicts dynamic fan-out | **RESOLVED** | New planning boundary; explicit sorted templates; unique `(phase_run_id, local_id)`; `EXECUTION_FLOW` §3 | U-04 (DISCOVERY exit criteria) |
| **H-05** | Orchestrator phase completion not serialized | **RESOLVED** | `reduce_and_advance` advisory xact lock §4.6; exhaustive dependency cascade §4.3 | U-01, U-08 (wording/table gaps) |
| **H-06** | Cancellation semantics incomplete | **RESOLVED** | `CANCEL_REQUESTED` / `CANCELLING` / `CANCELLED`; cancellation epoch; late-result fencing; `park_unresolved_and_cancel` | U-07 |
| **H-07** | Capability versioning incomplete | **RESOLVED** | `CapabilityImplementation`, `contract_snapshot_id`, pinned versions, `CONTRACT_VERSION_UNAVAILABLE` parking | U-09 (rule emit vs map) |
| **H-08** | `resolve_ambiguous_attempt` can mark success without validated output | **RESOLVED** | §4.8 four paths; no bare human `SUCCEEDED`; S06c | — |
| **H-09** | Plan validation contradicts environmental parking | **RESOLVED** | Structural plan validation excludes health; health evaluated after materialization | — |
| **H-10** | dbt idempotency assumptions unsafe (baseline + dbt) | **RESOLVED** (baseline) | `effect_semantics` replaces `idempotent: bool`; dbt defaults `NON_IDEMPOTENT`; invocation journals §5.2 | dbt-specific completion remains DE 008 scope (as original review stated) |
| **H-11** | SQL classifier cannot support read-only under DEV RW identity | **RESOLVED** (contract) | RO identity for reads; function/construct classification; canonical query tags | U-05 (enforcement + example drift) |
| **H-12** | MOCK artifacts can enter real delivery paths | **RESOLVED** | `ArtifactProvenance`; R20 `MOCK_PROVENANCE_TO_REAL_TARGET` | — |
| **H-13** | Cost approval and cap enforcement non-executable | **RESOLVED** | Atomic budget ledger §4.1; `BudgetIncreaseApproval` with explicit cap/delta | — |
| **H-14** | Audit integrity asserted, not enforced | **RESOLVED** (transactional scope) | Same-transaction audit; locked sequence; insert-only writer role; claims narrowed in DE-ADR-018 | — |
| **H-15** | Vendor-neutral abstraction overstated | **RESOLVED** (baseline) | Generic transformation contracts + platform extensions; extensible `AssetRef` / dialect ids | — |
| **H-16** | DE 002 scope overloaded | **RESOLVED** | DE 002A/B/C sequential split; minimal CI in 002A; DE-ADR-021/026 | U-03 (DE-ADR-020 stale env list) |
| **H-17** | Connector health / degraded model type-inconsistent | **RESOLVED** | `ConnectorHealthSnapshot` with `missing_permissions: frozenset[PermissionLevel]`; R2b | — |
| **H-18** | Secret-resolution ownership contradicts itself | **RESOLVED** | Separate scoped resolver views for connector vs LLM provider adapters | — |
| **H-26** | Module import graph ambiguous | **RESOLVED** | `IMPLEMENTATION_PLAN` §2 acyclic DAG; domain bottom | — |
| **M-06** | Retry contract terminology inconsistent | **RESOLVED** | Canonical `max_attempts` including initial attempt; `TOOL_CONTRACTS` §0 conventions | U-06 (RECONCILING terminal edge) |

Findings from the original review marked **Blocks DE 002? No** (H-19–H-25, H-27, M-01–M-05,
L-01–L-06) were outside DE 001R2A blocking scope. DE 001R1 low-severity summary gaps
(L-01–L-06) were verified closed in post-R2A documents.

Stale-semantics greps on post-R2A docs (excluding immutable review artifacts) found no live
contradictions for `max_retries`, `permission_ceiling`, ordinal permission comparison,
attempt-in-operation-key, uniform DENY→FAILED, `assets[*]` runtime insertion, or untyped
connector health enums.

---

## Focus-area verification (20 contract areas)

| # | Focus area | Verdict |
|---|---|---|
| 1 | Materialized operation identity | **PASS** |
| 2 | `phase_run` identity and task materialization | **PASS** |
| 3 | Lease heartbeat and fencing | **PASS** |
| 4 | Stale worker protection | **PASS** |
| 5 | Reconciliation before retry for ambiguous side effects | **PASS** (U-10 summary nit) |
| 6 | Deterministic policy denial aggregation | **PASS** |
| 7 | Typed approval subjects and approval binding | **PASS** (U-01, U-02 consistency) |
| 8 | Trusted `PrincipalRef` and server authorized grants | **PASS** |
| 9 | Dynamic fan-out semantics | **PASS** (U-04 exit-criteria gap) |
| 10 | Phase completion serialization and dependency propagation | **PASS** |
| 11 | Cancellation and late result handling | **PASS** (U-07 clarity nit) |
| 12 | Capability, schema and connector version pinning | **PASS** |
| 13 | Staging versus production deployment permission semantics | **PASS** |
| 14 | Ambiguous success resolution requiring validated output | **PASS** |
| 15 | Connector health versus structural plan validation | **PASS** |
| 16 | Canonical `max_attempts` semantics | **PASS** (U-06 edge case) |
| 17 | SQL and Snowflake safety contracts | **PASS** (U-05 enforcement + examples) |
| 18 | Module import dependency graph | **PASS** |
| 19 | DE 002A, DE 002B and DE 002C sequencing | **PASS** (U-03 stale ADR) |
| 20 | Consistency between ADRs, architecture documents and `.ai` governance files | **Mostly consistent** (residuals below) |

---

## Unresolved findings

| ID | Severity | Original finding (where applicable) | Document and section | Problem | Why it still matters | Exact correction required | Blocks DE 002A? |
|---|---|---|---|---|---|---|---|
| **U-01** | HIGH | H-01, H-05 | `docs/STATE_MODEL.md` §3 transition table vs `docs/PERMISSION_MODEL.md` §4 rejection routing | Table allows only `APPROVAL_REQUIRED → COMPLETED / PLANNING` on rejection; §4 defines budget → `BLOCKED`, staging without fallback → `BLOCKED`, required destructive/Git → `FAILED` | Transition table is authoritative with reachability tests; illegal transitions under documented rejection paths | Add `APPROVAL_REQUIRED → BLOCKED` and `→ FAILED` guards; update §1 diagram | **NO** (must fix before DE 002B baselines table) |
| **U-02** | HIGH | C-01, H-01 | `docs/TOOL_CONTRACTS.md` §27; `docs/EXECUTION_FLOW.md` §13–15; `docs/STATE_MODEL.md` §2 DELIVERY, §4.5 | `approval_id` in `deploy_staging` input creates circular dependency with operation key; pre/post-approval DELIVERY split materializes approval and operation in different phase runs | Flagship staging deploy path; incompatible implementations if copied from narrative | Remove `approval_id` from capability input; model deploy as template in same phase run with policy-driven `AWAITING_APPROVAL`; rewrite narrative | **NO** (DE 017 / DE 002B template) |
| **U-03** | MEDIUM | H-16 | `docs/adr/DE-ADR-020-local-vs-cloud-development.md` vs `docs/IMPLEMENTATION_PLAN.md` §5.1, `.ai/TASKS.md` | ADR lists "DE 002" as LOCAL; DE 002A is CLOUD-eligible | Rule-following Cloud agent must stop on governance contradiction | Amend DE-ADR-020 and `.ai/DECISIONS.md` mirror: DE 002A CLOUD; DE 002B/C LOCAL | **YES** if DE 002A launched in CLOUD without ADR fix; **NO** if LOCAL |
| **U-04** | MEDIUM | H-04 | `docs/STATE_MODEL.md` §2 DISCOVERY, §3 guard vs §4.2/§4.5 and `EXECUTION_FLOW` §3 | Enumeration phase run cannot satisfy state-level guard requiring catalogue + selection before `DISCOVERY → PLANNING` | DE 002C first slice depends on two-run fan-out boundary | Per-run exit criteria via `Plan.phase_exit_criteria`, or split DISCOVERY states | **NO** (before DE 002C; DE 002B if state split chosen) |
| **U-05** | MEDIUM | H-11 | `docs/EXECUTION_FLOW.md` §4–5, §7, §13; `PERMISSION_MODEL` §2.1; `TOOL_CONTRACTS` §10 | RO rule is prose-only; `READ ∈ snowflake_dev.allowed_permissions`; narrative binds reads to `snowflake_dev` | DE 002C test "SQL read uses RO binding" lacks deterministic predicate | Fix example bindings to `snowflake_ro`; enforce via identity class or remove READ from RW instance | **NO** (before DE 002C) |
| **U-06** | LOW | C-03, M-06 | `docs/STATE_MODEL.md` §4.3, §4.7; `docs/TOOL_CONTRACTS.md` §27 | No `RECONCILING → FAILED` when `NoEffect` and `attempt_count ≥ max_attempts` | `deploy_staging` has `max_attempts=1` | Add terminal FAILED branch for exhausted budget after authoritative `NoEffect` | **NO** |
| **U-07** | LOW | H-06 | `docs/STATE_MODEL.md` §2 CANCELLING vs §4.6 | Prose implies connector calls under serialization lock | Implementers may hold lock during slow I/O | Clarify lock scope; cancel/reconcile outside lock under recovery ownership | **NO** |
| **U-08** | LOW | H-05 | `docs/STATE_MODEL.md` §1.1, §3, §4.2 vs `BLOCKED` resume | "PLANNING before every phase" and "every executable phase creates new run" conflict with direct transitions and resume | Phase-run allocation ambiguous for template-driven phases | Reword §1.1 and §4.2 exception for resume | **NO** |
| **U-09** | LOW | H-07, C-04 | `docs/PERMISSION_MODEL.md` §3 R1–R21 vs §3.1 ENVIRONMENTAL list | `CONTRACT_VERSION_UNAVAILABLE` mapped but no runtime rule emits it | Exhaustiveness vs emission gap | Add R1b or document scheduler-emitted parking reasons | **NO** |
| **U-10** | LOW | C-03 | `docs/TOOL_CONTRACTS.md` §36 vs §0 / `PERMISSION_MODEL` §10 | Matrix says CONNECTOR_FAILURE/TRANSIENT/TIMEOUT retryable without side-effect qualifier | Copy-paste risk for implementers | Align Retryable cells with reconcile-first rule | **NO** |

**Carry-over (original review, not DE 001R2A blocking scope, unchanged):** M-03 staging-deploy
scope across capability map vs DE 017; M-01 multi-currency; M-02 demo counts; H-19–H-25;
H-27 GitHub idempotency. These do not block DE 002A/B/C.

---

## Newly discovered genuine blocking contradiction

**None for DE 002A contract kernel**, provided DE-ADR-020 is amended before launching DE
002A as a **CLOUD** task (U-03). U-01 and U-02 are genuine contradictions between corrected
contracts and the transition table / delivery narrative; they block **DE 002B** baseline of
the transition table and DELIVERY template, not DE 002A pure contracts.

---

## ADR corrections still required

| ADR | Required change | Blocks DE 002A? |
|---|---|---|
| **DE-ADR-020** | Update LOCAL vs CLOUD task list: DE 002A Cloud-eligible (pure contracts, no persistence, no credentials); DE 002B/C remain LOCAL; update Consequences bullet; mirror in `.ai/DECISIONS.md` | **YES** for CLOUD launch only |
| **DE-ADR-011** | Optional one-sentence amendment only if U-04 is resolved by splitting DISCOVERY states | **NO** (only if that option chosen) |

DE-ADR-011, 013–018, 021, 022, 026, 027 are consistent with post-R2A companion documents
and require no structural correction for DE 002A.

---

## Assessment of DE 002A, DE 002B and DE 002C sequencing

**Safe and internally consistent.** `docs/IMPLEMENTATION_PLAN.md` §3/§5, `.ai/TASKS.md`
Wave 0, DE-ADR-021, and DE-ADR-026 agree on:

```text
DE 002A (contract kernel + minimal CI, CLOUD)
  → DE 002B (persistence, fencing, recovery, cancellation, LOCAL)
  → DE 002C (offline safe-SQL slice, LOCAL)
  → DE 003 (CI expansion)
```

- DE 002A baselines pure contracts only after its deterministic unit/property/static CI is green.
- DE 002B baselines persistence/recovery only after concurrency/failure integration tests.
- DE 002C baselines composition only after the offline slice passes.
- Two parallel agents unlock only after DE 002A/B/C + DE 003 merge (DE-ADR-021).

**Preconditions before each gate:**

| Gate | Must close first |
|---|---|
| DE 002A (CLOUD) | U-03 (DE-ADR-020 amendment) |
| DE 002B | U-01, U-02, U-04 (if state split), U-06, U-07, U-08 |
| DE 002C | U-04, U-05 |

U-01/U-02 do not block DE 002A because DE 002A scope explicitly excludes persistence,
worker, DELIVERY templates, and vertical slice (`IMPLEMENTATION_PLAN` §5.1).

---

## Final verdict

**ACCEPT WITH NON BLOCKING FOLLOW UPS**

The DE 001R2A hardening resolved all four CRITICAL and every HIGH finding originally marked
"Blocks DE 002? Yes" at the contract level. Ten residual consistency items (two HIGH, three
MEDIUM, five LOW) remain between corrected contracts and the transition table, delivery
narrative, ADR-020 environment list, and summary tables. None block DE 002A pure-contract
baseline except U-03 when DE 002A is run in CLOUD without amending DE-ADR-020.

---

## Whether DE 002A may begin

**Yes.**

The DE 002A contract kernel (`PrincipalRef`/grants, materialization identity,
attempts/dispatch evidence, typed approvals and matching, policy aggregation, health
snapshot, `CallContext`/`RecoveryContext`, four-way `ReconcileResult`, `max_attempts`,
effect semantics, provenance, SQL classifier kernel, import graph) is internally consistent
and aligned with amended ADRs.

**Precondition:** amend DE-ADR-020 (U-03) before launching DE 002A as a CLOUD task, or run
DE 002A LOCAL until the ADR is updated.

---

## Recommended next task

**DE 001R2B — architecture consistency corrections** (docs-only, single writer on
`docs/DE001_mvp_architecture`): apply U-01 through U-10 exactly as specified in the
unresolved findings table; re-run stale-semantics greps; then **operator acceptance**
(statuses → `ACCEPTED`) and launch **DE 002A** per `docs/IMPLEMENTATION_PLAN.md` §5.1.

DE 001R2B and DE 002A may run back-to-back; DE 002A touches no `docs/`, so R2B can overlap
once DE-ADR-020 is amended.

---

## Reviewer attestation

- Review analysis and verdict: **Claude Fable 5.1 High**
- Repository artifact persistence: **Composer 2.5 only**
- Architecture documents: **not modified**
- ADR files: **not modified**
- `.ai` governance files: **not modified**
- Product code: **not modified**
- Merge: **not performed**
- Tests run: **none** (documentation verification only)
- Validation: full read of post-R2A documents, targeted consistency greps, cross-reference
  against `DE001_SOL_ARCHITECTURE_REVIEW.md` blocking findings, commit `d865b12`
