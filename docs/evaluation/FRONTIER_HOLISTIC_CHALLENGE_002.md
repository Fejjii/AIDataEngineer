# Frontier holistic challenge — FRONTIER_HOLISTIC_CHALLENGE_002

**Verdict:** `FREEZE_AFTER_DOCS_ONLY`  
**Model:** Claude Fable 5.1 (Frontier; not Grok, Composer, or a fallback)  
**Environment:** Cursor Cloud  
**Date:** 2026-09-23  
**Repository:** Fejjii/AIDataEngineer  
**Task:** FRONTIER_HOLISTIC_CHALLENGE_002  
**Audited SHA:** `main` `64618bce9ea240d49c768c9bac54535e11711f67`  
**Branch:** `audit/frontier_holistic_002`  
**Role:** Final independent principal engineer, product architect, data platform architect, security reviewer, technical due-diligence reviewer  
**Product code changes:** none  
**Campaigns rerun:** none  
**Targeted commands run:** one offline fixture count (§9.3), no database, no credentials, no live host calls

This report challenges PR 33 (`FRONTIER_HOLISTIC_PRODUCT_AUDIT_001`, Grok 4.6, verdict `FREEZE_INTERVIEW_MVP`, P0 0 / P1 6 / P2 11 / P3 4). It does not assume PR 33 is correct and it does not invent defects because production features are absent. Every finding cites code on the audited SHA.

## 1. Executive verdict

Data Pilot AI on `main` `64618bce` is a real, narrow, governed Interview MVP. The Supervisor, Governed Tool Gateway, policy engine, PostgreSQL Twin store, AST-bounded repair validator, and evidence bundle are genuine modules with real persistence and adversarial tests. The offline "fake" connectors are DuckDB-backed executors that run the real generated SQL, so the schema-drift failure is a real SQL failure, not a scripted flag. Nothing found mutates `VANTARA_RAW`, production, or staging. No P0 exists.

The product should freeze. It should not freeze on the current documentation. PR 33 concluded "no closure required". Direct inspection found five material gaps that PR 33 missed, all closable with documentation and talk-track corrections, none requiring product code:

1. The deployed demo host exposes anonymous self-service session issuance plus the legacy DE002C workflow endpoint. The "token-mandatory HTTP" story is true only for `/v1/interview/demo`.
2. The `POLICY_CHECK` phase is a placeholder: the bound capability returns `ALLOW` unconditionally on both fake and real connectors and the Supervisor feeds it `SELECT 1`.
3. The generated revenue mart sums EUR, USD, and GBP amounts into one number (about 50 % / 34 % / 16 % of invoices in the `tiny` fixture), never nets 190 refunds, and ignores the recorded design's `snapshot` / `incremental` materializations. All 23 tests, 25 quality checks, both reconciliations, and the Independent Verifier PASS anyway.
4. The Independent Verifier can only ever PASS the one drift-repair scenario; a no-drift run (including every live run) never invokes it. Several required evidence sections are Supervisor-synthesized booleans.
5. The benchmark table counts two metrics from one counter (`policy_evaluations = governed_tool_operations = len(intent_ids)`), counts eight in-process function calls as governed tool operations, counts 23 `not_null` tests and 21 table-existence checks, and credits 690 minutes to steps two of which the system does not perform generically.

Finding counts: **P0 = 0**, **P1 = 6**, **P2 = 12**, **P3 = 4**. Minimal closure is documentation only (§20). The Interview MVP is credible when the story is told as "governed closed loop over one locked scenario" and is over-stated as currently written in three places (§17).

| Question | Answer |
|---|---|
| Is the architecture real or theatre? | Real on the Interview path: gateway, policy, intents, reconcile, repair bounds, evidence digests. One phase (`POLICY_CHECK`) is theatre. |
| Is any execution path unsafe? | No RAW / prod / staging write exists. Anonymous DE002C submission on the public host is a resource-abuse exposure, not a data-plane risk. |
| Is the data engineering credible? | Layering and governance yes. The mart is numerically wrong as revenue (mixed currency, gross of refunds). |
| Is the verifier independent? | Independent of execution authority. Not independent of the Supervisor that assembles its evidence. Scenario-bound. |
| Is the benchmark credible? | Counts are measured and stable. Their composition is not disclosed and two of them are the same number. |
| Should it freeze? | Yes, after documentation corrections. No product code is justified. |

## 2. Model confirmation and method

- Active model: **Claude Fable 5.1**. Recorded before any repository read. Gate passed.
- Environment: **Cursor Cloud**. No local state, no credentials, no Snowflake or Railway secrets requested.
- Base: `origin/main` fetched and verified equal to `64618bce9ea240d49c768c9bac54535e11711f67`.
- Method: implementation code first (`src/aide/**`, `synthetic/**`, `pyproject.toml`), then accepted evidence (`FINAL_QA_001.md`, `LIVE_ACCEPTANCE_001.md`, PR 31 run report, PR 28, PR 32 diff, PR 33 diff), then recruiter documents (`README.md`, `INTERVIEW_DEMO.md`, `MVP_SCOPE.md`, PIVOT001, `EVALUATION_STRATEGY.md`, `STATE_MODEL.md`, `DATA_MODELLING_STRATEGY.md`, `DEMO_COMPANY.md`).
- No campaign was rerun. Accepted deterministic results are treated as evidence; nothing found gives a reason to distrust them as *measurements*. Several findings concern what those measurements *mean*.
- One targeted offline command was run (§9.3) to quantify a data-engineering finding from the committed `tiny` fixture. It touched no database.

## 3. Agreement and disagreement with PR 33

### 3.1 PR 33 P1 findings

| PR 33 | Finding | This audit | Correct class | Freeze blocker? |
|---|---|---|---|---|
| F-01 | Caller requirement text is discarded | **Agree.** `interpret_customer_revenue_request` executes `del text` (`src/aide/app/groups.py`). | Interview limitation + documentation | No |
| F-02 | dbt generation is a locked template; `ModelDesign` is a name-set gate | **Agree and sharpen.** The "LLM proposal" is a static JSON file re-stamped with the decision digest (`src/aide/llm/replay.py::_recorded_vantara_design`). Generation ignores the design's `snapshot` / `incremental` materializations (§9). | Interview limitation + technical debt | No |
| F-03 | Verifier scores Supervisor-assembled completeness, not warehouse semantics | **Agree and sharpen.** Verifier is scenario-bound and never runs on a no-drift or live workflow (§11). | Misclassified as P1 "verification"; it is a **product-claim** issue | No |
| F-04 | Offline closed loop and live smoke prove different subsets | **Agree on fact, disagree on severity.** README, `INTERVIEW_DEMO.md`, and `LIVE_ACCEPTANCE_001.md` already state this. It is a talk-track discipline item. | Documentation, **P2** | No |
| F-05 | SCD2 / plan history are structural placeholders | **Agree and extend.** Add mixed-currency mart, un-netted refunds, `IS_DELETED` ignored in survivorship, unused `-1` unknown member (§9). | Interview limitation; DE-credibility risk | No |
| F-06 | Twin is pinned evidence/context, not the planning substrate | **Agree.** Also: profile and dbt observations are never captured on the product path, so `MVP_SCOPE.md` §4 criterion 1 is not met as written. | Architecture-claim + documentation | No |

### 3.2 What PR 33 missed

| ID | Missed item | Severity |
|---|---|---|
| C-01 | Anonymous `POST /v1/sessions` issues `OPERATOR + APPROVER` sessions; `POST /v1/workflows` runs the legacy DE002C slice; both are always registered in `asgi.py` and exposed on the public Railway host. PR 33 F-07 / F-14 noted the routes exist but not that session issuance is unauthenticated. | P1 |
| C-02 | `POLICY_CHECK` phase is an always-`ALLOW` stub fed `SELECT 1`. | P1 |
| C-03 | Mixed-currency mart, gross-of-refund `paid_amount`, materialization mismatch. | P1 |
| C-05 | `policy_evaluations` and `governed_tool_operations` are the same counter; composition of tests and quality checks undisclosed. | P1 |
| C-08 | Determinism proof compares normalized structural fingerprints, not the persisted `estate_context_sha256` / `bundle_sha256` that `MVP_SCOPE.md` criterion 13 claims. | P2 |
| C-09 | The `plan` evidence section is a digest of an empty placeholder `Plan(tasks=())`. | P2 |

### 3.3 Disagreements on conclusions

| PR 33 conclusion | This audit |
|---|---|
| "No closure code is justified. Minimal closure plan: none required." | No **code** is justified. **Documentation** closure is required (§20). Verdict changes from `FREEZE_INTERVIEW_MVP` to `FREEZE_AFTER_DOCS_ONLY`. |
| 690 minutes: "Show to recruiters? Yes, if labelled." | **Remove from the README headline table.** Keep only in `docs/EVALUATION_STRATEGY.md` §4 with a composition caveat (§16). |
| "Policy is generic; scenario-specific gateway not found." | True for the gateway. False for the `POLICY_CHECK` phase, which is a stub (§7). |
| Verifier: "Logically incorrect warehouse data can still PASS if tests and the two reconciliation queries pass." | Confirmed with a concrete case that exists in the shipped fixture, not a hypothetical (§9.3). |
| Security: "Interview-safe." | Agree for the data plane. The public host has an un-tested anonymous write path (§12). Still Interview-safe; must be documented. |

PR 33 P2/P3 findings F-07 through F-21 are accepted as stated unless amended above.

## 4. P0 findings

None. Search covered RAW mutation paths, grant SQL, production/staging tokens, gateway bypass, evidence writer access from the verifier, client grant forgery, secret logging, and credential exposure. Every write to Snowflake goes through `snowflake_dev` with `AIDE_DEV` allow-lists; live cleanup drops only workflow-prefixed schemas; the repair writer changes exactly one column reference after an AST diff; the verifier package cannot import gateway, connectors, persistence, orchestration, or repair writers (import-linter contract, `pyproject.toml`).

## 5. P1 findings

| Field | C-01 |
|---|---|
| Severity / confidence | P1 / High |
| Evidence | `src/aide/api/app.py` registers `POST /v1/sessions`, `POST /v1/workflows`, `GET /v1/workflows/{id}/events` unconditionally. `src/aide/app/sessions.py::LocalSessionService.issue` creates a principal with `Role.OPERATOR, Role.APPROVER` for any caller. `asgi.py::create_production_app` always wires `build_offline_stack`. `docs/ops/SYNTHETIC_CLOUD_DEMO.md` says only "`/v1/workflows` remains the earlier DE002C slice". `LIVE_ACCEPTANCE_001.md` tested only `/v1/interview/demo`, `/healthz`, `/readyz`. |
| Affected capability | HTTP demo security story; Railway host reliability |
| Why it matters | Any internet client can obtain a session, satisfy CSRF, and run the DE002C slice, writing workflows, artifacts, sessions, and audit rows to the demo control-plane database with no rate limit. The slice runs fake connectors only, so no data-plane risk exists. The recruiter-facing claim "HTTP demo disabled by default and token-mandatory when enabled" is true for one route and silent about three. |
| Freeze impact | None for product code. Documentation must state the exposure. |
| Recommended action | Docs: add the limitation to `docs/ops/SYNTHETIC_CLOUD_DEMO.md` and README "Safety and governance". Optional post-freeze hardening (not required): env-gate the legacy routes. Do not demo `/v1/workflows`. Live confirmation of the serving host's response to `POST /v1/sessions` requires separate verification; code makes it unconditional. |

| Field | C-02 |
|---|---|
| Severity / confidence | P1 / High |
| Evidence | `src/aide/connectors/snowflake/fake.py:590` and `src/aide/connectors/snowflake/real.py:646`: `evaluate_execution_policy` executes `del payload` and returns `ALLOW / EXECUTE`. `src/aide/app/supervisor.py::_resolved_payload` passes `SqlText(text="SELECT 1")`. `src/aide/generation/validate.py` only `sqlglot.parse`s generated SQL; `aide.policy.sql.classifier` is not called on the Interview path. `docs/STATE_MODEL.md` §POLICY_CHECK describes "Policy Engine evaluation of all EXECUTION tasks; cost estimation; permissions, targets, destructive scan, cost caps". |
| Affected capability | Policy story; state-model truth |
| Why it matters | The dedicated `POLICY_CHECK` phase, one of the eleven phases in the demo sequence, decides nothing. Real controls are the gateway's per-dispatch `PolicyEngine.evaluate` (grants, connector registration, health, environment, approvals), generation parse validation, and the repair AST diff. A senior reviewer reading the phase list would assume the generated SQL is classified before execution. It is not. |
| Freeze impact | None. The generated SQL is a repo-authored template, so the missing classification has no practical risk in the Interview. |
| Recommended action | Docs: mark `POLICY_CHECK` as a placeholder phase in `docs/STATE_MODEL.md` and `docs/INTERVIEW_DEMO.md`; name the three effective controls. Do not wire the classifier during freeze. |

| Field | C-03 |
|---|---|
| Severity / confidence | P1 / High |
| Evidence | `src/aide/generation/vantara.py::mart_customer_revenue_daily` sums `fct_invoice_line.amount` and `fct_payment.amount` with no currency grain or conversion. `tiny/v1` invoices: EUR 2952, USD 2121, GBP 990, `eur` 73, `€` 64 (6200 rows). `stg_payments__refunds` (190 rows, 103 447.13) is never referenced downstream. `snap_customer_conformed` and `fct_payment` are `materialized='table'` while `recorded_vantara.json` records `snapshot` and `incremental`. `int_customer_deduplicated` omits the `IS_DELETED` filter that `DEMO_COMPANY.md` P1 specifies. `fct_invoice_line` left-joins `dim_customer` without coalescing to the `-1` member, so the unknown member is never used. `src/aide/quality/interview.py` reconciles mart to `fct_invoice_line` and `fct_payment`, not to source. |
| Affected capability | Data engineering credibility; verifier semantics |
| Why it matters | The "customer revenue mart" reports one `invoiced_amount` across three currencies and a `paid_amount` gross of refunds. Every test, quality check, reconciliation, and the verifier PASS. This is the concrete instance of "PASS is completeness and consistency, not correctness". A data engineer reading the mart SQL will raise it within minutes. |
| Freeze impact | None for the governance claim. The Interview contract is the drift-repair loop, not a finished revenue model. |
| Recommended action | Docs and talk track: state that the mart is a currency-agnostic gross sum, refunds are staged not netted, SCD2 is shape only. Do not fix the SQL during freeze; a change would alter the deterministic fingerprint and re-open MVP004 evidence. |

| Field | C-04 |
|---|---|
| Severity / confidence | P1 / High |
| Evidence | `src/aide/verification/evaluate.py` requires `repair_applied`, `repair_in_scope`, `failure_class == "SCHEMA_MISMATCH"`, and `original_failure` / `repair_*` evidence for PASS. `run_customer_revenue` calls `_run_verifier` only inside `_run_repair_and_verify`. `run_governed_live_interview` sets `include_schema_drift=False`; `run_credentialed_live_interview_smoke` reports `independent_verifier_ran=False`. `_run_verifier` stores `dbt_parse`, `dbt_compile`, `dbt_tests`, `post_repair_validation` as `{"ok": bool}` bodies; `quality_passed`, `post_repair_validation_passed` are in-memory flags; `reconciled = status == "SUCCEEDED" and completed_at is not None`. `_claimed_hash_matches` returns `True` when either side is `None`. |
| Affected capability | "Independently verifies results" |
| Why it matters | The verifier is a deterministic consistency check over a pack the Supervisor assembles, hard-wired to one scenario. It cannot verify a no-drift data product and has never scored REAL evidence outside tests. Module independence (import contracts, pure function, tamper tests) is real and valuable; investigator independence is not claimed by the code but is implied by the name. |
| Freeze impact | None. |
| Recommended action | Talk track and README wording: "cannot mark its own homework" is acceptable; "independently verifies results" needs the qualifier "the evidence for this scenario is complete, digest-consistent, and reconciled". State that live runs do not invoke the verifier. |

| Field | C-05 |
|---|---|
| Severity / confidence | P1 / High |
| Evidence | `src/aide/app/benchmarking/runner.py:300-301`: `governed_tool_operations=len(intent_ids)` and `policy_evaluations=len(intent_ids)`. Eight of 36 intents bind to `LocalHandlerBinding` pure functions (four `plan_phase` returning `Plan(tasks=())`, `propose_model_design` replay, `generate_transformation`, `propose_repair`, `validate_repair`). `_schema_yml` declares 22 single-column `not_null` tests plus one `invoice_status` `not_null` = 23. `evaluate_interview_quality` emits 21 `model_present` checks + `mart_non_empty` + `mart_grain_unique` + two fact-to-mart sums = 25. `AUTOMATED_ENGINEERING_STEPS` credits `find_relevant_sources` 60 (fixed ten-address intersect), `decide_model_design` 60 (recorded fixture), `write_dims_facts_marts … with SCD2` 180 (not SCD2). |
| Affected capability | Benchmark credibility |
| Why it matters | "36 governed tool operations, 36 policy evaluations" reads as two independent measurements; it is one counter reported twice. "23 tests, 25 quality checks" reads as test depth; it is presence checks. The 690-minute figure is labelled ESTIMATED but sits in the README "Benchmark results" table where recruiters read productivity. |
| Freeze impact | None. |
| Recommended action | Docs: footnote composition of each count in README and `INTERVIEW_DEMO.md`; remove the 690-minute line from the README table and keep it in `EVALUATION_STRATEGY.md` §4 with the three caveats. Optional later code: separate the counters. |

| Field | C-06 |
|---|---|
| Severity / confidence | P1 / High |
| Evidence | `groups.py::interpret_customer_revenue_request` discards text; `propose_relevant_assets` intersects a fixed address list; `llm/replay.py` returns `recorded_vantara.json` for any architecture decision; `_pin_twin` hardcodes request terms `("customer","revenue","invoice","payment")` and `mandatory_asset_ids = all datasets`; `_verifier_pack` hardcodes `business_request="Build a customer revenue analytical data product"`. |
| Affected capability | "Understands the estate", "LLM may propose", "converts business intent" |
| Why it matters | Combines PR 33 F-01 / F-02 / F-06 into the one recruiter-facing risk: the request-to-plan link is simulated end to end. The execution, governance, repair, and evidence machinery below it are real. |
| Freeze impact | None. |
| Recommended action | Talk track (§17). README first paragraph already hedges "governed executor"; keep. Change `MVP_SCOPE.md` §4 criterion 4 wording from "selects … from objective signals" to "validates a recorded design against objective signals". |

## 6. Product claims challenge matrix

| Claim | Classification | Basis |
|---|---|---|
| Data Pilot AI is a control plane | **CREDIBLE_WITH_QUALIFICATION** | Gateway, policy, intents, reconcile, evidence, PostgreSQL state are real (`gateway.py`). Qualification: one locked workflow; `POLICY_CHECK` phase is a stub; DE002C parallel stack still reachable. |
| Data Pilot AI is autonomous | **OVERSTATED** | Fixed template sequence in `supervisor.py`; `plan_phase` returns an empty plan; no tool choice, no request interpretation, one allow-listed repair. Autonomous only in "zero human interventions inside a scripted loop". |
| Data Pilot AI understands the estate | **OVERSTATED** | Discovery, describe, and profiling are real; selection is a fixed ten-table intersect; context assembly runs but nothing downstream reads it except for its digest; profile and dbt observations never enter the Twin. |
| Data Pilot AI generates data models | **CREDIBLE_WITH_QUALIFICATION** | It emits, parses, compiles, and executes 22 dbt files with tests. Qualification: files are hand-authored templates keyed on fixture version; design content beyond the name set is ignored; materializations in the design are not honoured. |
| Data Pilot AI repairs incidents | **CREDIBLE_WITH_QUALIFICATION** | Real SQL failure in DuckDB or Snowflake, real classifier, real AST-bounded patch, real revalidation, persisted budget. Qualification: exactly one incident class on one column of one file; incident is self-injected; live RAW is never drifted. |
| Data Pilot AI independently verifies results | **OVERSTATED** | See C-04. Module-independent, scenario-bound, completeness-and-consistency oriented, never invoked without drift. |

## 7. Generic infrastructure versus Vantara application

Classification: **a mixture** — generic governance kernel (gateway, policy engine, recovery, Twin store, repair validator, evidence bundle, verifier shape) wrapped by a Vantara-specific application layer (`supervisor.py`, `groups.py`, `generation/vantara.py`, `quality/interview.py`, `domain/repair.py`, `modelling/vantara.py`, `profiling/fixtures.py`).

| Item | Evidence | Class |
|---|---|---|
| Fixed table addresses | `vantara_selected_addresses()`, `demo_selected_assets()`, `_pin_twin` fails closed if any is missing | Acceptable Interview constraint |
| Fixed business request | `interpret_customer_revenue_request`, `INTERVIEW_REQUEST`, hardcoded `business_request` in verifier pack | Acceptable Interview constraint |
| Fixed generated SQL | `generation/vantara.py` | Acceptable Interview constraint; technical debt if described as a generator |
| Fixed model graph | `INTERVIEW_REQUIRED_MODELS` duplicated in `modelling/constants.py` | Technical debt (P3) |
| Fixed repair mapping | `ACCEPTED_FROM_COLUMN`, `ACCEPTED_TO_COLUMN`, `ACCEPTED_ARTIFACT_PATH` in `domain/repair.py` | Acceptable Interview constraint (PIVOT001 C-06) |
| Fixed quality rules | `quality/interview.py` targets `mart_customer_revenue_daily` | Acceptable Interview constraint |
| Fixed verifier assumptions | `evaluate_verifier` requires `SCHEMA_MISMATCH` and `repair_applied` | **Architecture problem** as a claim: the "Independent Verifier" is a scenario verifier. Not a freeze blocker. |
| Fixture-specific modelling | `vantara_modelling_context()`, `_align_invoice_status` rewrites `STATUS → INVOICE_STATUS` for v1 | Acceptable Interview constraint |
| Fixture-specific context | Request terms and mandatory asset IDs hardcoded in `_pin_twin` | Technical debt |
| Placeholder policy phase | `evaluate_execution_policy` stubs | **Architecture problem** (C-02); docs closure |
| Scenario-specific gateway or policy engine | Not found | — |

No freeze blocker in this category.

## 8. Digital Twin verdict

What is real: five append-only contracts in PostgreSQL with immutability triggers (`9c3045032ed2` migration), one pinned snapshot per workflow, `build_twin_snapshot` digest, grant-filtered and bound-checked `assemble_estate_context`, snapshot and context digests bound into repair inputs and verifier checks, drift recorded as a `TwinObservation`.

What is not: `capture_profile_observations` and `capture_dbt_artifacts` have no callers outside `twin/capture.py` and unit tests; the snapshot contains only Snowflake discovery/describe metadata; the assembled `EstateContext` is consumed by nothing but its own digest; modelling, generation, repair proposal, and quality never load the snapshot.

| Question | Answer |
|---|---|
| Useful control-plane primitive? | **Yes.** Pinned identity plus digest binding is what makes repair and verifier inputs non-drifting. |
| Actually a planning substrate? | **No.** Planning is the hardcoded template sequence; design is a recorded fixture. |
| "Enterprise Digital Twin" defensible? | **Not as a product noun.** "Pinned estate metadata snapshot with append-only observations" is defensible. `MVP_SCOPE.md` §4 criterion 1 ("dbt models/tests, declared lineage, schema/profile/test observations") is not met on the product path and should be corrected. |

## 9. Supervisor and Governed Tool Gateway verdict

### 9.1 What holds

- Every materialized task passes `GovernedToolGateway.execute`: validate → policy → intent + attempt + fence → execute outside the DB transaction → output validation → evidence reference → audit. `_write_txn` context var prevents connector I/O inside a write transaction.
- Non-adopted results become `STALE` without evidence. Non-`SIDE_EFFECT_FREE` failures acquire recovery and reconcile before any retry.
- Supervisor advances only via `reduce_and_advance` with version and generation fencing; illegal transitions raise.
- Repair budget is reloaded from persisted `RepairEvent` rows before propose/apply/revalidate (`_validate_repair_payload` raises if not).
- Capability groups are pure functions with no handles.

### 9.2 Paths that weaken the claimed model

| Path | Evidence | Class |
|---|---|---|
| `POLICY_CHECK` phase stub | C-02 | Architecture claim; docs |
| Twin pin, drift injection, requirement interpretation, design acceptance, evidence assembly, bundle finalization are Supervisor-owned writes, not gateway calls | `_pin_twin`, `_record_drift`, `_store_typed_evidence`, `_persist_evidence_bundle` | Documented application responsibility (PIVOT001 §7). Weakens "every action is a governed tool call" but not "every connector action". |
| Real dbt quality opens a second `RealSnowflakeConnector(SNOWFLAKE_DEV)` and calls private `_session_call` | `connectors/dbt/real.py:354-379` | Connector-in-connector coupling inside a governed call (PR 33 F-13). P2. |
| Live cleanup `DROP SCHEMA IF EXISTS AIDE_DEV.<wf>_* CASCADE` runs through `_dev_sql` outside the gateway | `live_probe.py::drop_workflow_dev_schemas`, called from `run_governed_live_interview` `finally` | Side-effecting connector call outside the gateway. DEV-only, workflow-scoped, but PIVOT001 §9 says none may bypass. Should be a documented exception. P2. |
| Legacy `ToolRegistry` + `OfflineSliceService` reachable via HTTP | C-01 | P1 (as exposure) |
| Gateway `reconcile` records `{"decision": "ALLOW", "source": "recovery"}` without re-running the policy engine | `gateway.py:271` | Accepted for Interview (PR 33 F-12). P2. |
| Successful workflows never reach `COMPLETED`; `_finalize_status` writes only `BLOCKED` / `FAILED` | `supervisor.py::_finalize_status` | State-model gap (PR 33 F-08). P2. |

Verdict: the governance boundary is real for connector execution. The phase-level policy story is not.

## 10. Data engineering verdict

Reviewed `generation/vantara.py` as the shipped warehouse.

| Area | Assessment |
|---|---|
| Staging | Credible: one view per source, explicit column aliases, PII masked to `'***'`, currency and domain normalization. |
| Intermediate | `int_customer_deduplicated` survivorship = latest `updated_at`; omits `IS_DELETED` filter that `DEMO_COMPANY.md` P1 requires (2 deleted rows in `tiny`). `int_payments_deduplicated` correctly dedups on `(invoice_id, payment_ref)`. `int_subscription_plan_history` is a pass-through despite "keep history of plan changes" in the requirement. |
| Customer conformance | Billing grain with CRM crosswalk; reasonable. Unknown member `-1` defined in `dim_customer` but facts never coalesce to it, so unmatched invoices carry `NULL customer_sk`. |
| Dimensions | `dim_customer` has SCD2 columns with `valid_to NULL`, `is_current TRUE` for every row: shape only. `dim_date` is distinct invoice issue dates; payment dates absent. |
| Facts | Correct grains. `fct_payment` inner-joins invoices, silently dropping orphan payments. |
| Revenue mart | **Incorrect as revenue**: sums three currencies (§5 C-03), gross of refunds, `paid_amount` and `invoiced_amount` at customer × date with a `NULL` customer group. |
| Grain / relationships | Grain checked only for the mart. No `unique`, `relationships`, or `accepted_values` tests; 23 `not_null` tests only. |
| Quality / reconciliation | Presence plus two fact-to-mart sums. Not source-to-mart. `expected/*.json` totals exist in `synthetic/vantara/expected/tiny/` and are unused by quality. |
| Schema drift / repair | Credible and real: DuckDB or Snowflake raise on the missing column; classifier maps to `SCHEMA_MISMATCH`; AST diff restricts the patch to one reference in `stg_billing__invoices.sql`; tests cannot be weakened. |
| SCD behaviour | Not implemented. |
| Date modelling | Partial. |
| Deduplication | Implemented for accounts and payments, with the survivorship omission above. |
| Refund handling | Staged, never applied. |

Credible claims: layered dbt project, masked staging, dedup intermediates, drift detection and bounded repair, tests executed in DEV. Claims needing qualification: "revenue mart", "reconciliation", "SCD2 dims", "quality checks".

### 10.1 Targeted verification command

```text
python3 (csv count) over synthetic/vantara/fixtures/tiny/v1/csv/billing/invoices.csv,
crm/accounts.csv, payments/refunds.csv
→ invoices 6200: EUR 2952, USD 2121, GBP 990, eur 73, € 64
→ accounts 138: IS_DELETED true 2; empty WEBSITE_DOMAIN 0
→ refunds 190, sum 103447.13
```

Offline, deterministic, committed fixture; no database or credentials.

## 11. Synthetic versus real proof matrix

| Path | What it proves | What it does not prove |
|---|---|---|
| Offline fake Snowflake (DuckDB-backed, `bind_vantara_fixtures`) | Discovery, describe, profiling, drift injection via real `ALTER TABLE RENAME`, detect via describe diff | Snowflake dialect behaviour, grants, timeouts |
| Offline fake dbt (DuckDB-backed, real compiled SQL executed) | Generated SQL parses, compiles, runs, tests, quality; drift causes a real execution failure; repair makes it pass | dbt Core behaviour, Snowflake adapter, warehouse timing |
| Railway synthetic path | Same fakes on PostgreSQL 18.6 over HTTP; token gate on one route; single-replica lock; restart persistence; five PASS runs | Any Snowflake or dbt reality; legacy route exposure (untested) |
| Real Snowflake RO (PR 31 / PR 32 host) | `CURRENT_ROLE`, discovery, describe, profile under 150 s, `SHOW GRANTS` least-privilege probe | Drift, repair, verifier |
| Real Snowflake DEV | Workflow-scoped `AIDE_DEV` writes, namespace rejection, reconcile, cleanup, manifest dual-load reconciliation | RAW isolation beyond grant metadata; multi-workflow concurrency |
| Real dbt on Snowflake | parse / compile / run / test / isolated fail / cleanup with `fixture_version=v2` | v1 `INVOICE_STATUS` path (RAW is already v2) |
| Governed live Interview | Supervisor → gateway → RO / DEV / dbt with policy ALLOW and persisted evidence, `include_schema_drift=False` | Drift, repair, verifier, evidence bundle (`independent_verifier_ran=False`) |
| Schema drift scenario | Offline only, v1 fixture | Live drift |
| Repair | Offline only | Live repair |
| Independent Verifier | Offline only, drift scenario only | Any no-drift or live workflow |

Do not combine: offline verifier PASS + live governed PASS ≠ live verified loop; v1 drift + v2 live estate ≠ one estate; Railway PASS ≠ Snowflake involvement.

## 12. Independent Verifier verdict

**Classification: CREDIBLE_WITH_QUALIFICATION** for "read-only, deterministic, cannot mutate or dispatch". **OVERSTATED** for "independently verifies results".

| Question | Answer | Evidence |
|---|---|---|
| Truly independent? | Of execution authority, yes. Of the evidence assembler, no. | Import-linter contract; `_verifier_pack` is a Supervisor method |
| Detects semantic wrongness? | No. | C-03 passes every check |
| Can upstream construct evidence that naturally leads to PASS? | Yes, and the Supervisor does exactly that by design: it writes `{"ok": true}` bodies and flags, then scores them. | `_run_verifier` |
| Completeness treated as correctness? | Partly. `required_evidence_present`, `post_repair_validation` (three booleans), `reconciled` (status == SUCCEEDED). | `evaluate.py` |
| Do digests prove the claims? | They prove artifact bodies were not altered after persistence and that repair pre/post hashes agree. They do not prove SQL semantics or that dbt artifacts (manifest, run_results) are referenced; the bundle's `dbt_artifacts` section is `{"parse": bool, "compile": bool}`. | `_persist_evidence_bundle` |
| Wrong warehouse output can still create a valid bundle? | Yes. | C-03 |
| Independence claim technically credible? | As "cannot mark its own homework" (cannot change the verdict inputs it evaluates), yes. As "third party", no. | — |

Additional: `_claimed_hash_matches(None, x)` is permissive; `timing_present` / `cost_present` are near-vacuous; verifier never runs without drift.

## 13. Security architecture verdict

| Area | Interview-safe? | Production-ready? | Evidence |
|---|---|---|---|
| RO vs DEV separation | Yes | Requires DBA grant hygiene | `SNOWFLAKE_RO` / `SNOWFLAKE_DEV` specs; live `SHOW GRANTS` probe (PR 31 / PR 32) |
| RAW restrictions | Yes | Same | RO allow-list includes RAW; DEV allow-list is `AIDE_DEV` only; no GRANT SQL anywhere |
| DEV namespace restrictions | Yes | Same | Workflow-prefixed schemas; namespace rejection test |
| Secret handling | Yes | No vault / rotation | Env names only; `RedactionPolicy`; leakage test |
| Policy boundaries | Yes for connector dispatch | Phase-level policy is a stub (C-02) | `gateway.py`, `fake.py:590`, `real.py:646` |
| HTTP demo | Yes for `/v1/interview/demo` | No | Token compare with `hmac.compare_digest`; empty body only |
| Legacy HTTP paths | **Exposed** (C-01) | No | `/v1/sessions` anonymous; `/v1/workflows` fake slice; SSE unauthenticated |
| Session / auth assumptions | Local single-operator model | No | `LocalSessionService.issue` grants `OPERATOR + APPROVER` to any caller; cookie `SameSite=lax` |
| Event streaming | Low sensitivity | No | Phase names by workflow UUID, no auth |
| Direct connector construction | Contained | — | Composition roots; `dbt/real.py` builds a DEV connector inside a governed call; `live_probe` cleanup |
| DBA threat model | Out of model | No | Append-only triggers are DB-side; a superuser can disable them; evidence is application-audit, documented |
| Evidence mutation | Fail-closed on digest mismatch | Not cryptographic, documented | Tamper suite |
| Supply chain | `uv.lock` | No SBOM / signing | — |

Interview-safe: yes. Production-ready: no, and the repository says so.

## 14. Reliability and operations verdict

| Topic | Finding | Matters for Interview? |
|---|---|---|
| Workflow recovery | Gateway reconcile + lease fencing exist and are tested offline; Interview success leaves rows in `VALIDATION` | Only as a demo question |
| Ambiguous side effects | `SIDE_EFFECT_FREE` capabilities fail closed; `NON_IDEMPOTENT` / `EXTERNALLY_DEDUPLICATED` reconcile first | No |
| Restart model | Proven on one Railway replica | No |
| PostgreSQL lifecycle | `alembic upgrade head` on every container boot with no advisory lock; two replicas booting together could race a migration | Only if replicas > 1 |
| Migration behaviour | Runs 16.14 and 18.6; no `server_version` assertion | No |
| dbt cleanup | Live path drops workflow schemas in `finally`, outside the gateway | No |
| Snowflake timeout | 180 s gateway deadline; 150 s live profiling budget after PR 31 | No |
| Concurrency | In-process `asyncio.Lock`; second replica would run concurrently | Keep one replica |
| Logging / metrics / alerting | PostgreSQL audit only | No |
| Rollback | Redeploy container; volume teardown destructive | No |
| Deployment coupling | Railway `PORT=8000`; `production` is the host environment name | Talk-track only |
| Legacy route abuse | Anonymous DB writes possible (C-01) | Yes: demo-host reliability; document and monitor |

## 15. Performance and scale verdict

Reasoned from code and accepted measurements; no benchmark run.

| Load | Expected behaviour | Limit |
|---|---|---|
| 10 assets (today) | Offline 20–30 s per run; Railway ~40 s for two runs; live profiling ~62 s | Fine |
| 100 assets | `EstateContextLimits` (12 top-level, 120 fields, 64 relationships, 32 observations, 64 KiB) → `CONTEXT_BOUND_EXCEEDED`, fail closed. `_pin_twin` requires exactly the ten locked addresses, so anything else already fails with `LOCKED_ASSETS_MISSING`. | Fails closed by design |
| 1000 assets | Same, plus `load_snapshot` row fetches and one describe per asset serially in `DISCOVERY` | Not reachable |
| Large Snowflake tables | Profiling budgets and sampling exist; no evidence beyond `tiny` | Unknown |
| Many concurrent workflows | Worker leases and fencing support it; supervisor loop is per-call; HTTP demo lock serializes | Untested |
| Multiple users / companies | Not designed: one local principal, one company, fixed request | Out of scope |

Bottlenecks: `supervisor.py` in-process loop, serial describe tasks, per-row Twin load, in-process lock. All fail closed or serialize; none silently degrade.

## 16. Maintainability verdict

| Issue | Files | Severity | Recommend refactor now? |
|---|---|---|---|
| Oversized composition root | `src/aide/app/supervisor.py` (2 627 lines) | P2 | No |
| Duplicate orchestration stack | `app/slice.py`, `tools/registry.py`, `orchestration/phases/*` | P2 | No; document, do not demo |
| Unwired Twin capture | `twin/capture.py` | P2 | No |
| Placeholder capability with real alternative unused | `evaluate_execution_policy` stub vs `slice.py::evaluate_execution_policy_handler` (also a stub) | P2 | No; document |
| Scenario constants in domain/app | `domain/repair.py`, `groups.py`, `quality/interview.py` | P2 | No |
| Duplicate 21-model tuples | `generation/vantara.py`, `modelling/constants.py` | P3 | No; test locks equality |
| Private-method coupling | `_session_call` from dbt connector; `_resolved_payload`, `_verifier_pack` | P2 | No |
| Test-only features | `fail_next`, `fail_after_effect`, `mark_in_progress` on fakes | P3 | No; they are failure-injection hooks |
| Extra generated model outside the 21 | `fct_invoices` | P3 | No |
| Migration risk | Low while frozen | — | — |

The main maintainability risk that could break a demo is a later agent "generalizing" generation, selection, or the verifier inside these modules. Freeze protects against that.

## 17. Documentation truth matrix

| Claim (recruiter-facing) | Class | Notes |
|---|---|---|
| "Autonomous Data Engineering Control Plane" | PARTIALLY_PROVEN | Control plane proven on one path; "autonomous" overstated (§6) |
| "understands the estate" | NOT_PROVEN | Fixed selection; context unused downstream |
| "Enterprise Data Digital Twin in PostgreSQL … assets, relationships, observations, snapshots, evidence refs" | PARTIALLY_PROVEN | Snowflake metadata only; no profile / dbt observations |
| "Deterministic Supervisor" | PROVEN | |
| "Governed Tool Gateway … sole execution path for workflow actions" | PROVEN | Cleanup DROP outside gateway is the exception |
| "Every gateway call persists a deterministic risk decision" | PROVEN | Per-dispatch |
| `POLICY_CHECK` phase as described in `STATE_MODEL.md` | DESIGN_ONLY | Stub in code |
| "Deterministic modelling engine … rule table" | PARTIALLY_PROVEN | Rule engine runs; design is a recorded fixture |
| "21 required customer-revenue models" | PROVEN | As fixture |
| "dbt tests, quality checks, and reconciliation" | PARTIALLY_PROVEN | 23 `not_null`; 21 presence; fact-to-mart sums |
| "SCD2 dims" | NOT_PROVEN | Shape only |
| "Revenue mart" | PARTIALLY_PROVEN | Mixed currency, gross of refunds |
| "Schema-drift detection `INVOICE_STATUS → STATUS`" | PROVEN (offline) | |
| "Bounded automatic repair; tests cannot be weakened" | PROVEN (offline) | |
| "Read-only Independent Verifier; deterministic PASS/FAIL" | PROVEN as module; OVERSTATED as "verifies results" | |
| "100 % evidence completeness" | PROVEN as section presence | ~10 of 24 sections are Supervisor-synthesized summaries |
| "Two offline runs produce identical … digests" (`MVP_SCOPE.md` §4.13) | PARTIALLY_PROVEN | Compares normalized fingerprints, not persisted `estate_context_sha256` / `bundle_sha256` (`runner.py::_normalized_*`) |
| "Credential-gated Snowflake live smoke … governed path" | PROVEN | No drift, no verifier |
| "HTTP demo disabled by default; token mandatory when enabled" | PARTIALLY_PROVEN | True for `/v1/interview/demo`; legacy routes always on |
| "PostgreSQL 16 or newer" | PROVEN | PR 28 |
| "No LLM judge" | PROVEN | |
| "No generic autonomous loop" | PROVEN | |
| "690 estimated engineering minutes" | PARTIALLY_PROVEN as a labelled estimate | Over-credits three steps |
| Databricks / Fabric / Airflow / BigQuery | OUT_OF_SCOPE | Correctly labelled |
| `docs/evaluation/README.md` "does not prove live Snowflake least privilege" | Stale | Superseded by PR 31 / PR 32 |

Wording that would materially mislead a senior engineer: "understands the estate"; "Independent Verifier" without the completeness qualifier; "36 policy evaluations" beside "36 governed operations"; "Reconciliation" without "fact-to-mart"; "SCD2".

## 18. Benchmark credibility verdict

| Metric | Class | Reason |
|---|---|---|
| 10 assets | Mostly scenario count | Fixed list |
| 21 models | Mostly scenario count | Fixed tuple |
| 36 governed operations | Credible but weak | Measured; 8 are pure functions, 4 of them empty plans |
| 36 policy evaluations | **Potentially misleading** | Same counter as above |
| 23 tests | Useful but weak | All `not_null` |
| 25 quality checks | **Potentially misleading** | 21 presence checks |
| 1 incident, 1 repair, 0 human interventions | Credible evidence | Real failure, real patch, budget persisted |
| 100 % evidence completeness | Useful but weak | Section presence |
| Deterministic repeatability | Credible with qualification | Normalized fingerprints; meaningful for replay |
| 690 minutes | **Potentially misleading** in the README table | Labelled, but credits fixed selection, recorded design, and SCD2 |

Decision on 690: **remove from the README "Benchmark results" table and from the recruiter talk track.** Keep it in `docs/EVALUATION_STRATEGY.md` §4 as a versioned baseline with an explicit note that `find_relevant_sources`, `decide_model_design`, and the SCD2 portion of `write_dims_facts_marts` are not performed as described.

## 19. Interview claims matrix

### Safe claims

- One business scenario becomes a tested DEV dbt product, is broken by a real column rename, is repaired by exactly one AST-bounded patch, and is scored by code that cannot dispatch tools or write workflow state.
- Every connector call on the Interview path goes through one gateway that persists policy, intent, attempt, fence, result digest, and evidence, and reconciles ambiguous side effects before retry.
- RO reads RAW; DEV writes only workflow-scoped `AIDE_DEV`; no GRANT SQL exists; live least privilege was proven from grant metadata on a credentialed host.
- The offline fakes are DuckDB-backed executors running the real generated SQL, not canned responses.
- Two offline runs match on a documented normalized fingerprint.
- Production and staging are disabled; evidence is application-audit, not cryptographic.

### Claims requiring qualification

- "Control plane" → over one locked scenario.
- "Autonomous" → zero human steps inside a fixed sequence.
- "Digital Twin" → pinned metadata snapshot bound into repair and verifier by digest.
- "Generates models" → executes a repo-authored 22-file dbt project; design is a recorded fixture validated by rules.
- "Independent Verifier" → independent of execution, dependent on the Supervisor's evidence pack, scenario-bound, never run live.
- "Reconciliation" → fact-to-mart sums, not source-to-mart.
- "Revenue mart" → currency-agnostic gross sum.
- "36 policy evaluations" → one per gateway dispatch, same number as operations.
- Railway URL → fakes; `live_smoke=NOT_RUN`.

### Claims to avoid

- Understands arbitrary requests. Understands the estate. LLM proposes the design. SCD2 history. Verified live closed loop. Cryptographic evidence. 690 minutes saved. Databricks / Fabric / Airflow. Multi-tenant.

### Best architecture story

"A renamed billing column normally costs hours because context, permission, execution, and proof live in different tools and heads. This system pins the estate snapshot, routes every warehouse and dbt call through one gateway that records intent before it acts and reconciles before it retries, allows exactly one AST-checked repair, and lets a read-only module fail the run if any digest, section, or reconciliation is missing. The interesting property is not that code wrote SQL; it is that the system cannot widen its own patch and cannot mark its own homework."

### Best demonstration story

1. `uv run aide interview demo`: request → Twin pin → 22 files → green build → injected rename → `SCHEMA_MISMATCH` → one patch → green → verifier PASS, twice.
2. Show `tests/evaluation/test_safety.py` rejecting a second repair and a broader diff.
3. Show `src/aide/verification/evaluate.py` and the import-linter contract.
4. If credentials exist: `uv run aide interview live-smoke` for grants and a real DEV build; state that drift stays offline.

### Top senior-engineer objections and honest responses

| Objection | Response |
|---|---|
| The request text is ignored. | Yes. The Interview proves the governed loop, not an NL parser. |
| Generation is a template and the design is a fixture. | Yes. The control plane executes and governs a reference project; validation gates it. |
| The mart mixes currencies. | Yes. The Interview contract is drift → repair → evidence. A production mart needs a currency grain and refund netting; that is deferred and documented. |
| `POLICY_CHECK` is a stub. | Yes. Per-dispatch gateway policy is the non-bypassable control; the whole-plan check is V1 design. |
| The verifier trusts the Supervisor. | Yes. It is application-audit independence: it cannot execute or mutate. A third-party re-execution is out of scope. |
| Anyone can hit `/v1/sessions` on your demo host. | Yes; it reaches only fake connectors and the demo database. It is a documented legacy path and should be gated before the URL is promoted further. |
| 36 policy evaluations equals 36 operations. | Same counter. The number shows every dispatch was evaluated, not two independent facts. |
| Live never proves repair. | By contract: RAW is not mutated. |
| Will it scale? | No; context caps fail closed. That is deliberate for the slice. |

## 20. Minimal closure plan

All items are documentation or talk track. No product code, tests, grants, deployment, or infrastructure.

| # | File | Change | Closes |
|---|---|---|---|
| 1 | `README.md` | Remove the 690-minute row from "Benchmark results"; footnote composition of 36 / 36 / 23 / 25; qualify "understands the estate" and the verifier row; add legacy-route note under "Safety and governance". | C-01, C-04, C-05, C-06 |
| 2 | `docs/INTERVIEW_DEMO.md` | Same metric footnotes; note that `POLICY_CHECK` is a placeholder phase and that the verifier runs only on the drift scenario. | C-02, C-04, C-05 |
| 3 | `docs/MVP_SCOPE.md` | Criterion 1: restrict to Snowflake schema metadata and drift observations. Criterion 4: "validates a recorded design". Criterion 13: "identical normalized fingerprints". Note the mart is currency-agnostic and gross of refunds. | C-03, C-06, C-08, Twin |
| 4 | `docs/STATE_MODEL.md` | Mark `POLICY_CHECK` whole-plan check as V1 design; Interview implementation is a placeholder task. | C-02 |
| 5 | `docs/ops/SYNTHETIC_CLOUD_DEMO.md` | State that `/v1/sessions`, `/v1/workflows`, and SSE are always registered, unauthenticated-self-service, reach fake connectors only, and write to the demo database; recommend gating before wider promotion. | C-01 |
| 6 | `docs/EVALUATION_STRATEGY.md` §4 | Add the three-step caveat to the 690 baseline. | C-05 |
| 7 | `docs/evaluation/README.md` | Replace the stale "does not prove live least privilege" sentence; link PR 31 / PR 32 evidence and this report. | PR 33 F-15 |
| 8 | `docs/PERMISSION_MODEL.md` or PIVOT001 §9 | Record the live cleanup `DROP SCHEMA` and grant probe as the two documented non-gateway connector calls. | §9.2 |

Optional, explicitly **not** required for freeze and not to be done by the freeze task: env-gate the legacy HTTP routes; separate the two benchmark counters.

## 21. WHAT NOT TO BUILD NEXT

- A natural-language request interpreter or live LLM provider.
- Design-driven dbt code generation, or "fixing" the mart's currency, refund, SCD2, or unknown-member behaviour. Any change alters the deterministic fingerprint and re-opens MVP004 evidence.
- Wiring the SQL classifier into `POLICY_CHECK`, or wiring profile / dbt capture into the Twin.
- A second repair class, second scenario, second vendor, graph store, agent framework, frontend, GitHub delivery, monitoring, cost platform, cryptographic ledger, multi-tenant IAM, or `aide eval`.
- Live RAW drift injection.
- Splitting `supervisor.py` or deleting DE002C "for cleanliness".
- Raising Twin or context limits to appear to scale.
- Rerunning the accepted campaigns to "confirm" this report; they measure the same things and would pass.

## 22. Final freeze recommendation

**`FREEZE_AFTER_DOCS_ONLY`**

The implementation is complete for the PIVOT001 contract and safe for Interview use. It should not freeze on documentation that (a) presents one counter as two metrics, (b) presents a placeholder phase as a policy check, (c) presents a currency-mixed gross sum as a reconciled revenue mart, (d) presents a scenario-bound consistency check as independent result verification, and (e) is silent about anonymous legacy endpoints on the public host. Apply §20, human-review, merge, and freeze. Do not start product work.

## Appendix A. Full finding register

| ID | Severity | Confidence | Evidence | Capability | Freeze impact | Action |
|---|---|---|---|---|---|---|
| C-01 | P1 | High | `api/app.py`, `app/sessions.py`, `asgi.py` | HTTP security story | Docs | §20 #1, #5 |
| C-02 | P1 | High | `snowflake/fake.py:590`, `snowflake/real.py:646`, `supervisor.py::_resolved_payload` | Policy story | Docs | §20 #2, #4 |
| C-03 | P1 | High | `generation/vantara.py`, `quality/interview.py`, `tiny/v1` fixture | DE credibility | Docs / talk track | §20 #3 |
| C-04 | P1 | High | `verification/evaluate.py`, `supervisor.py::_run_verifier`, `interview.py` | Verifier claim | Docs / talk track | §20 #1, #2 |
| C-05 | P1 | High | `benchmarking/runner.py:300`, `generation/vantara.py::_schema_yml`, `quality/interview.py`, `domain/benchmark.py` | Benchmark | Docs | §20 #1, #2, #6 |
| C-06 | P1 | High | `groups.py`, `llm/replay.py`, `supervisor.py::_pin_twin` | Request → plan | Talk track | §20 #3 |
| C-07 | P2 | High | `twin/capture.py` callers | Twin | Docs | §20 #3 |
| C-08 | P2 | High | `benchmarking/runner.py::_normalized_*` | Determinism wording | Docs | §20 #3 |
| C-09 | P2 | High | `groups.py::plan_interview_phase`, `_verifier_pack` plan digest | Evidence "plan" section | Talk track | None |
| C-10 | P2 | High | `supervisor.py::_finalize_status` | State model | None | Accept (PR 33 F-08) |
| C-11 | P2 | High | `dbt/real.py:354`, `live_probe.py::drop_workflow_dev_schemas` | Gateway exception | Docs | §20 #8 |
| C-12 | P2 | High | `app/slice.py`, `tools/registry.py` | Parallel stack | None | Do not demo (PR 33 F-07) |
| C-13 | P2 | High | `twin/context.py` limits, `_pin_twin` | Scale | None | Accept (PR 33 F-17) |
| C-14 | P2 | High | `benchmarking/service.py` lock; `docker-entrypoint.sh` | Replicas / migration race | None | Keep one replica (PR 33 F-11) |
| C-15 | P2 | Medium | `gateway.py:271` | Reconcile policy | None | Accept (PR 33 F-12) |
| C-16 | P2 | High | `supervisor.py` size and private coupling | Maintainability | None | Do not split (PR 33 F-10) |
| C-17 | P2 | High | `docs/evaluation/README.md` | Stale docs | Docs | §20 #7 |
| C-18 | P2 | High | `api/app.py` SSE | HTTP | Docs | §20 #5 (PR 33 F-14) |
| C-19 | P3 | High | `api/app.py` `samesite="lax"` vs docs | Auth docs | None | Ignore (PR 33 F-18) |
| C-20 | P3 | High | duplicate model tuples | Maintainability | None | Ignore (PR 33 F-19) |
| C-21 | P3 | High | `_claimed_hash_matches`, timing / cost checks | Verifier | None | Ignore (PR 33 F-20) |
| C-22 | P3 | Medium | `fct_invoices`, `stg_payments__refunds` unused | Generation | None | Ignore (PR 33 F-21) |

## Appendix B. Items requiring separate verification (Cloud cannot perform)

- Live response of the serving Railway deployment to `POST /v1/sessions` and `POST /v1/workflows` (code makes both unconditional; no host call was made from this audit).
- Whether `evaluate_execution_policy` on the real connector is reached in the governed live path (code binds it identically; PR 31 / PR 32 evidence shows 36 ALLOW decisions on synthetic runs).

Neither changes the verdict.
