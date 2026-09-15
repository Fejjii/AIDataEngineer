# Execution Flow — Worked Example

**Task:** DE 001 (hardened by DE 001R2A and DE 001R2B) · **Status:** ACCEPTED

**Interview MVP note:** This is the broader DE001 V1 narrative. The implemented closed loop
does **not** include GitHub delivery, staging deploy, duplicate-payment repair, a product
SPA, or a required live LLM. See `README.md`, `docs/INTERVIEW_DEMO.md`, and
`docs/MVP_SCOPE.md` for what currently runs.

This document traces the canonical MVP workflow end to end and shows, at every step, the
workflow state, the tasks executed (capability@connector), and the **structured state or
artifact** each step produces. Nothing passes between steps except persisted, typed
objects. There is no agent conversation in the integration path.

Demo context: `docs/DEMO_COMPANY.md` (company *Vantara Systems*; Snowflake database
`VANTARA_RAW` with schemas `CRM`, `BILLING`, `PAYMENTS`, `PRODUCT`; DEV database `AIDE_DEV`).

---

## 0. Request

> "Build a customer revenue analytical data product from our CRM and billing data. Customers
> are duplicated in the CRM, so deduplicate them. Reconcile invoices against payments. Keep
> history of plan changes. Add quality tests, document lineage and prepare it for deployment."

| | |
|---|---|
| Actor | Human via UI (`POST /workflows`) |
| Persisted | `workflows` row `wf_7f3a` in state `RECEIVED`; `audit_events`: `REQUEST_RECEIVED` with the redacted text; artifact `A1 request.txt` |

---

## 1. RECEIVED → interpret

| Task | Capability | Connector | Output |
|---|---|---|---|
| t1 | `interpret_requirement` | — (LLM) | `A2 RequirementSpec` |

`RequirementSpec` excerpt:

```json
{
  "goal": "Customer revenue analytical data product",
  "deliverable_type": "ANALYTICAL_DATA_PRODUCT",
  "business_entities": [{"name": "customer"}, {"name": "subscription plan"}, {"name": "invoice"}, {"name": "payment"}],
  "metrics": [{"name": "revenue", "definition": null, "ambiguous": true},
              {"name": "active customer", "definition": null, "ambiguous": true}],
  "history_requirements": "FULL_HISTORY",
  "ambiguities": [
    {"topic": "revenue", "question": "Is revenue recognized on invoice issue, invoice payment, or both?", "options": ["invoiced","paid","both"], "blocking": true},
    {"topic": "active customer", "question": "Define 'active customer'.", "options": ["has an active subscription today","paid an invoice in last 90 days"], "blocking": false}
  ]
}
```

Det rule: a metric without a definition is ambiguous → at least one blocking question →
transition to `CLARIFICATION_REQUIRED` via control capability `emit_clarification`.

---

## 2. CLARIFICATION_REQUIRED ↔ human

| | |
|---|---|
| Persisted | `clarifications` row with two questions; workflow parked; audit `CLARIFICATION_ASKED` |
| Human answers | "Revenue = invoiced amounts, with paid amounts alongside for reconciliation. Active customer = has an active subscription on the date." |
| Task | `interpret_requirement` re-run with `prior_clarifications` → `A3 RequirementSpec v2` (`ambiguities: []`) |
| Transition | → `PLANNING` |

---

## 3. PLANNING (for DISCOVERY)

| Task | Capability | Output |
|---|---|---|
| t3 | `plan_phase(phase=DISCOVERY)` | `A4 Plan(DISCOVERY)` |

The first plan is structural and pins registered contract/connector versions; temporary
connector health is evaluated only after operation materialization:

```json
{"phase":"DISCOVERY","tasks":[
 {"local_id":"d1","capability_id":"discover_assets","connector_id":"snowflake_ro","inputs":{"scope":{"addresses":[["VANTARA_RAW"]],"include_views":false}}}
]}
```

The accepted plan creates phase run generation 1 and one immutable template with
`phase_exit_criteria` requiring only the catalogue snapshot. Its literal input
materializes immediately: validate → resolved-input digest → operation key → policy
→ attempt. After `d1` succeeds, those exit criteria are satisfied, the enumeration run
completes, and the workflow re-enters `PLANNING`. Generation 2 deterministically sorts
the catalogue by canonical asset address and creates one explicit `describe_asset`
template per asset plus `select_relevant_assets` depending on those task ids, with
`phase_exit_criteria` covering catalogue plus selection. Unique `(phase_run_id, local_id)`
constraints prevent duplicate expansion. There is no `assets[*]` insertion into an
active DAG.

---

## 4. DISCOVERY

Enumeration run (generation 1) — exit: catalogue snapshot.

| Tasks | Capability@Connector | Output |
|---|---|---|
| d1 | `discover_assets@snowflake_ro` | `A5 MetadataCatalog snapshot` (13 tables in 5 schemas; `USAGE` disabled) |

That run's `phase_exit_criteria` are satisfied. Workflow → `PLANNING` → description run
(generation 2) — exit: catalogue + selection.

| Tasks | Capability@Connector | Output |
|---|---|---|
| d2.1–d2.13 (concurrent) | `describe_asset@snowflake_ro` | 13 describe snapshots (columns, types, comments flagged untrusted) |
| d3 | `select_relevant_assets` (LLM) | `A6 AssetSelection` (10): `CRM.ACCOUNTS`, `CRM.CONTACTS`, `CRM.ACCOUNT_CROSSWALK`, `BILLING.CUSTOMERS`, `BILLING.SUBSCRIPTIONS`, `BILLING.INVOICES`, `BILLING.INVOICE_LINES`, `PAYMENTS.PAYMENTS`, `PAYMENTS.REFUNDS`, `PRODUCT.PLANS`; excluded `CRM.OPPORTUNITIES`, `SUPPORT.TICKETS` with reasons |

Det subset check passes (all selected ∈ snapshot). Orchestrator calls
`plan_phase(PROFILING)` → `PLANNING` → `PROFILING`.

---

## 5. PROFILING

| Tasks | Capability@Connector | Output |
|---|---|---|
| p1–p10 (concurrent) | `profile_dataset@snowflake_ro` | 10 `DatasetProfile` artifacts |
| p11 | `infer_relationships@snowflake_ro` | `A16 RelationshipCandidates` |
| p12–p14 | `sample_dataset@snowflake_ro` (n=20, masked) | 3 masked samples for design reasoning |

Findings surfaced as **facts** (Det):

- `CRM.ACCOUNTS.ACCOUNT_ID` uniqueness 1.0; but `lower(trim(WEBSITE_DOMAIN))` uniqueness 0.93 → 7% duplicate account groups.
- `BILLING.CUSTOMERS.CRM_ACCOUNT_ID` null ratio 0.031; inclusion in `CRM.ACCOUNTS.ACCOUNT_ID` 0.962.
- `PAYMENTS.PAYMENTS.(INVOICE_ID, PAYMENT_REF)` uniqueness 0.985 → duplicate payment rows.
- `BILLING.INVOICES.CURRENCY` top values `EUR`, `eur`, `€`.
- `PRODUCT.PLANS` has `VALID_FROM/VALID_TO` → history exists in source.
- `BILLING.INVOICES` v2 columns: `STATUS` (comment: "renamed from INVOICE_STATUS in 2026-07 extract") — comment is untrusted text, recorded as hint only.

Transition → `PLANNING` → `DESIGN`.

---

## 6. DESIGN

| Tasks | Capability | Output |
|---|---|---|
| g1 | *Det* `ModellingDecisionEngine.decide()` (no LLM) | `A17 ArchitectureDecision` |
| g2 | `propose_model_design` (LLM, constrained by A17) | `A18 ModelDesign` |
| g3 | *Det* design validators | `A19 DesignValidationReport` |

`ArchitectureDecision` (from the rule table in `docs/DATA_MODELLING_STRATEGY.md`):

```json
{"layering":"STAGING_INTERMEDIATE_MARTS","presentation":"STAR_SCHEMA",
 "history":{"dim_customer":"SCD2","dim_plan":"SCD2","dim_date":"STATIC"},
 "facts":[{"name":"fct_invoice_line","grain":["invoice_line_id"],"load":"INCREMENTAL_MERGE"},
          {"name":"fct_payment","grain":["payment_id"],"load":"INCREMENTAL_MERGE"}],
 "marts":[{"name":"mart_customer_revenue_daily","grain":["customer_sk","date_day"]}],
 "data_vault":{"recommended":false,"reason":"single warehouse, 4 sources, no multi-source integration-layer audit requirement"},
 "signals":{"history_requirements":"FULL_HISTORY","source_count":4,"volume_class":"M","consumers":["BI"],"latency":"DAILY"},
 "approval_required":false}
```

`ModelDesign` (LLM) adds entity mapping, dedup rule for customers (survivorship by most
recent `UPDATED_AT` within normalized-domain group), currency normalization, crosswalk
join, SCD2 change-tracking columns. Det validators confirm: every grain is a profiled
candidate key or has a dedup rule; every referenced column exists; SCD2 units have valid
tracking columns. Policy: `approval_required=false` (no flagged signals) → `PLANNING` → `GENERATION`.

---

## 7. GENERATION

| Tasks | Capability@Connector | Output |
|---|---|---|
| n1–n20 (concurrent per design unit) | `generate_transformation` (LLM) | 20 file sets (the models in `docs/DEMO_COMPANY.md` §6: 10 staging, 4 intermediate, 4 dimensions, 3 facts, 1 mart, 1 snapshot — several share one design unit) + `sources.yml`, `schema.yml` |
| n21 | `classify_sql` on every model (Det) | all read-only SELECT ✔ |
| n22 | `create_transformation@dbt_dev` | `A31 project_state v1` |
| n23 | `compile_transformation@dbt_dev` | `A32 manifest v1`, compiled SQL |
| n24 | `validate_query@snowflake_ro` for each compiled model (EXPLAIN) | validation outputs |

Result: `stg_billing__invoices` EXPLAIN → `valid=false, error: invalid identifier
'INVOICE_STATUS' (000904)`. Because this is *output* of `validate_query` (not a task
failure), the Generation phase records `A33 GenerationValidation` with one failed unit and
the Orchestrator routes the single unit through `REPAIR` **before** execution (cheap repair).

---

## 8. REPAIR (pre-execution, attempt 1 of max 2 for this unit)

| Tasks | Capability | Output |
|---|---|---|
| r1 | `inspect_failure` (Det) | evidence: error 000904, failing compiled SQL, `detect_schema_drift` vs. snapshot from RAW v1 fixture: `removed: INVOICE_STATUS`, `added: STATUS`, `renamed_candidates: [{from: INVOICE_STATUS, to: STATUS, confidence: 0.91}]` |
| r2 | `diagnose_failure` (LLM) | `RepairProposal{root_cause_class: SCHEMA_MISMATCH, hypothesis: "source column renamed INVOICE_STATUS→STATUS", hypothesis_hash: h1, patch: stg_billing__invoices.sql}` |
| r3 | Det validation | hypothesis new ✔, class repairable ✔, patch targets artifact under repair ✔, `classify_sql` ✔, `validate_query` → `valid=true` ✔ |

`A34 stg_billing__invoices.sql v2` created; `repair_attempts` row; audit
`REPAIR_APPLIED`. Back to `GENERATION` steps n22–n24 for the unit only → all valid →
`POLICY_CHECK`.

---

## 9. POLICY_CHECK

Whole-plan evaluation for the upcoming `EXECUTION` phase (Det):

| Check | Result |
|---|---|
| Every EXECUTION task permission ∈ workflow grants (`DEVELOPMENT_EXECUTE`, `DEVELOPMENT_WRITE` both granted) and ∈ its connector's `allowed_permissions` (`dbt_dev`, `snowflake_dev` for DEV writes). Discovery/profiling/EXPLAIN/read queries used `snowflake_ro` (`identity_class=READ_ONLY`) | ✔ |
| All writes target `AIDE_DEV.WF7F3A_*` schemas | ✔ |
| No destructive statements in compiled SQL | ✔ |
| Estimated warehouse cost ≤ per-workflow cap | ✔ (X-Small, est. 0.2 credits) |
| LLM spend so far ≤ cap | ✔ (USD 0.84) |

`policy_decisions` rows persisted per task (`ALLOW`). Transition → `EXECUTION`.

---

## 10. EXECUTION

| Task | Capability@Connector | Output |
|---|---|---|
| e1 | `run_pipeline@dbt_dev` (`dbt build`, target DEV, canonical per-statement tag with workflow, phase run, task, full operation key and attempt id) | `A40 run_results v1` |

Result: models build; **test failure**: `unique_fct_payment_payment_id` fails with 1 811
failures. `run_pipeline` output `ok=false`, `tests[...].status=fail` → classified
`DBT_TEST` → `VALIDATION` records it → `REPAIR`.

---

## 11. VALIDATION (attempt 1)

Quality Engine (Det) evaluates `ValidationReport v1`:

| Check | Status |
|---|---|
| dbt tests | 41 pass, **1 fail** (`fct_payment` uniqueness) |
| Schema conformance of marts vs design | pass |
| Reconciliation: `sum(stg_payments.amount)` vs `sum(fct_payment.amount)` | **fail** (fact over-counts by 2.1%) |
| Row count deltas source→staging | pass |
| Freshness of sources (max loaded_at ≤ 1 day) | pass |

Two failures, both `DATA_QUALITY`/`DBT_TEST`, both repairable → `REPAIR`.

---

## 12. REPAIR (post-execution, attempt 1 of 2 for `fct_payment`)

| Tasks | Output |
|---|---|
| r4 `inspect_failure` | failing rows sample (masked, 20 rows): same `INVOICE_ID`, `PAYMENT_REF`, `AMOUNT`, differing `LOADED_AT` → late re-delivery of payment batches |
| r5 `diagnose_failure` (LLM) | `RepairProposal{root_cause_class: DATA_QUALITY, hypothesis: "duplicate payment events delivered across batches; dedupe on (invoice_id, payment_ref) keeping latest loaded_at", hypothesis_hash: h2, patch: int_payments_deduplicated.sql}` |
| r6 Det validation | new hypothesis ✔; patch touches direct upstream of failing model within the same phase ✔; `classify_sql` ✔; `validate_query` ✔ |

Rebuild selection (`dbt build --select int_payments_deduplicated+`) → tests pass →
`VALIDATION` attempt 2: all checks pass, reconciliation delta 0.00%. `ValidationReport v2`
persisted. Repair counters: task 1/2, workflow 2/4.

Transition → `PLANNING(DELIVERY)` → `DELIVERY`.

---

## 13. DELIVERY (one phase run)

Lineage, Git and the staging deploy are templates in the **same** DELIVERY phase run.
`deploy_staging` is materialized after the PR exists; policy then requires
`OperationApproval` bound to that already computed operation identity. There is no
pre-approval versus post-approval phase split and no `approval_id` in capability input.

| Tasks | Capability@Connector | Output |
|---|---|---|
| v1 | `get_lineage@dbt_dev` (column-level) | `A50 lineage.json` |
| v2 | `generate_documentation` (LLM; scope MODEL, COLUMN, RUN_SUMMARY, PR_BODY) | docs artifacts; Det checks every referenced model/column exists |
| v3 | `get_execution_metrics@snowflake_ro`, `get_cost_metrics@snowflake_ro` | `A55 metrics` (credits 0.23, 63 queries, 0 spilled) |
| v4 | `register_monitor` ×3 (freshness on sources, test suite on marts, cost threshold) | monitor artifacts |
| v5 | `prepare_git_change@github` | branch `aide/wf7f3a_customer_revenue`, commit `c0ffee1`, pushed (secret scan clean) |
| v6 | `prepare_pull_request@github` | PR #17 (draft=false), body = `A54 PR_BODY` |
| v7 | `deploy_staging@dbt_staging(strategy=DBT_RUN_TARGET, release_id=rel_01)` materializes; policy `REQUIRE_APPROVAL`; task `AWAITING_APPROVAL` | operation key + resolved-input digest committed; `OperationApproval` subject `ap_01` PENDING |

Transition → `APPROVAL_REQUIRED`. The DELIVERY phase run remains the active occurrence.

---

## 14. APPROVAL_REQUIRED

| | |
|---|---|
| UI shows | PR link, diff summary, validation, lineage, cost, repair history and complete `deploy_staging` subject for `AIDE_STAGING` (operation key, input digest, artifacts, connector, target) |
| Human | Approves `ap_01` (identity recorded) |
| Det check | Complete operation subject unchanged, artifact provenance REAL, approval unexpired, approver role trusted ✔ |
| Transition | → originating DELIVERY phase run; task `v7` returns `READY`; the **same** materialized operation continues |

If the human rejects the staging subject: task `CANCELLED(APPROVAL_REJECTED)`; workflow →
`COMPLETED` with outcome `DELIVERED_PR_ONLY` (PR remains for manual handling); nothing is
deployed. Other rejection classes follow `docs/PERMISSION_MODEL.md` §4 (`BLOCKED` or
`FAILED`); they are legal transitions in `docs/STATE_MODEL.md` §3.

---

## 15. DELIVERY continues → MONITORING → COMPLETED

| Task | Capability@Connector | Output |
|---|---|---|
| v7 (same operation) | `deploy_staging@dbt_staging` dispatches with the already persisted `release_id` | `release_id`, `rollback_ref` (previous manifest artifact) |
| v9 | `check_monitor` ×3 once | initial monitor states |
| — | Orchestrator | `MONITORING` state recorded with monitor ids; V1 immediately proceeds to `COMPLETED` with outcome `DELIVERED_STAGING` |

Final `WorkflowSummary` (Det-assembled, LLM-narrated via `summarize_for_human`):
tasks 71, model calls 19, tokens in/out 212k/38k, LLM cost USD 1.92, warehouse 0.23
credits, repairs 2 (both automatic), human interventions 2 (clarification, approval),
first-attempt build success: no, final success: yes, elapsed 14 min.

---

## 16. What moved between steps

| From → To | Object type | Storage |
|---|---|---|
| Request → interpret | text artifact | `artifacts` |
| interpret → planner | `RequirementSpec` | `artifacts` (typed JSON) |
| planner → scheduler | `Plan` → `tasks` rows | `tasks` |
| discovery → profiling → design | `MetadataCatalog`, `DatasetProfile`, `RelationshipCandidates` | immutable snapshot tables |
| design → generation | `ArchitectureDecision`, `ModelDesign` | `artifacts` |
| generation → execution | files → `project_state_id` | Artifact Manager + dbt working copy |
| execution → validation | `run_results`, `ValidationReport` | `artifacts`, `validation_reports` |
| validation → repair | `FailureClassification`, evidence bundle | `task_attempts`, `repair_attempts` |
| delivery → approval | materialized operation key, input digest, artifact hashes, PR url | `approvals` (subject binds to operation; not capability input) |
| everything → audit/telemetry | events | `audit_events`, `model_calls`, `tool_calls` |

No step consumes an LLM's free text. Every LLM output is a validated typed artifact.

---

## 17. Failure branches not shown above

| Situation | Path |
|---|---|
| `select_relevant_assets` returns an asset not in catalogue | `OUTPUT_INVALID` → retry once with violation → still invalid → `BLOCKED` with human question "which assets?" |
| Repair hypothesis repeats | proposal rejected; second `diagnose_failure` with `forbidden_hypotheses`; if still repeated → escalate: workflow `BLOCKED`, evidence and both proposals shown |
| Repair budget exhausted | `BLOCKED` with `RepairExhausted` summary |
| Snowflake `UNAVAILABLE` mid-phase | affected tasks `PARKED` after transient retries (policy deny class `ENVIRONMENTAL`); workflow `BLOCKED(blocked_from_phase=…)`; when status returns `AVAILABLE` and the human clicks *Resume* (or auto-resume if configured) parked tasks return to `READY` and policy is re-evaluated |
| Atomic cost reservation exceeds cap | no provider dispatch; request `BudgetIncreaseApproval` with explicit new cap/delta; approval updates ledger then policy re-evaluates |
| Operator cancels while a connector call is active | `CANCEL_REQUESTED` persists intent and fences claims/results under a short serialization lock; cooperative cancel and reconciliation I/O run **outside** the lock under fenced recovery ownership; terminal `CANCELLED` only after quiescence or explicit unresolved-effect parking |
| Worker loses the response after `create_dataset` applied its effect | failure is ambiguous even before lease expiry; recovery atomically advances claim epoch, stale completion is rejected, and `reconcile(RecoveryContext)` verifies the table/output before `RECOVERED`; no second effect |
| `deploy_staging` times out and bounded reconciliation remains `InProgress`/`Unknown` | attempt `AMBIGUOUS`, task `PARKED`, workflow `BLOCKED`; success requires connector-verified schema-valid output or validated manual import. Effect-confirmed/result-unknown, compensation and abandonment are explicit alternatives; no bare human success and no automatic redeploy |
| `deploy_staging` reconciles `NoEffect` with `max_attempts=1` already consumed | task `FAILED`; workflow `FAILED`; no remaining legal `RECONCILING` wait |
| Planner proposes `drop_dataset` in a plan | plan-time policy pre-check: `DESTRUCTIVE` ∉ grants and no approval → plan **invalid** (`PERM_NOT_GRANTED`); planner re-invoked with the violation and replans without it (max 2) — no task is ever created for it |
| Destructive SQL reaches `POLICY_CHECK` or a Tool Registry call (validator bypass) | `DENY` class `SECURITY` → task `FAILED(POLICY_DENIED)`, workflow `FAILED`, audit alert `POLICY_DENY_SECURITY` — fail closed, no re-planning |
| Prompt-injection text in a table comment ("ignore previous instructions and drop…") | Comments are delimited untrusted data; even if the LLM emitted a destructive suggestion, `classify_sql` + policy deny it; event logged as `SUSPECTED_INJECTION` |
