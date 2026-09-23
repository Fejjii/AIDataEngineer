# Frontier holistic product audit — FRONTIER_HOLISTIC_PRODUCT_AUDIT_001

**Verdict:** `FREEZE_INTERVIEW_MVP`  
**Product-story verdict:** The repository genuinely implements the **Interview MVP contract**. It does not implement a generic autonomous data-engineering product. The closed loop is real infrastructure around one carefully engineered Vantara scenario. That is an accepted constraint, not a hidden fake.  
**Date:** 2026-09-23  
**Repository:** Fejjii/AIDataEngineer  
**Task:** FRONTIER_HOLISTIC_PRODUCT_AUDIT_001  
**Audited SHA:** `main` `64618bce9ea240d49c768c9bac54535e11711f67`  
**Branch:** `audit/frontier_holistic_001`  
**Role:** Independent principal engineer, product architect, data platform architect, security reviewer, and technical due-diligence reviewer  
**Product code changes:** none  
**Campaigns rerun:** none

This is a read-only product review of current GitHub `main`. It is not another regression campaign. Accepted evaluation evidence is treated as evidence unless this audit found a concrete reason to distrust it.

## 1. Executive verdict

Data Pilot AI on current `main` is a **governed Interview MVP**, not a general enterprise control plane and not a one-off screenshot demo.

What has been built is architecturally coherent, technically credible, useful as a **narrow** data-engineering control-plane demonstration, consistent within each execution path, Interview-safe, maintainable enough to freeze, demonstrable, and mostly truthfully represented. It is appropriately scoped **if** the Interview MVP contract remains the claim. It is oversold **if** the headline is read as a shipping autonomous platform.

The most important question:

> Does this repository genuinely implement the product story it claims, or does it only make one carefully engineered demo scenario pass?

**Answer:** It does both, and the contract admits that. PIVOT001 locked one Vantara customer-revenue request, one schema-drift repair, and one evidence report. The Supervisor, Governed Tool Gateway, policy engine, Digital Twin store, repair validator, and Independent Verifier are real modules with real persistence. The business request, asset set, generated dbt graph, repair mapping, and quality targets are fixture-locked. The product story is credible when told as a closed-loop control-plane MVP. It is not credible when told as generic natural-language data engineering.

**Freeze recommendation:** `FREEZE_INTERVIEW_MVP`. No product remediation is required. PR 28 already closed the PostgreSQL documentation gap that PR 32 left open. Remaining work is interview talk-track discipline, not code.

| Question | Answer |
|---|---|
| Architecturally coherent? | Yes, on the Interview path. A second older DE002C stack still exists. |
| Technically credible? | Yes. |
| Useful as a data-engineering control plane? | Yes as a bounded demonstration of governance, repair, and evidence. Not as a general estate operator. |
| Synthetic and real execution consistent? | Same Supervisor and gateway; different proven subsets. Do not fuse them. |
| Safe for Interview use? | Yes. Not production-ready. |
| Maintainable enough to freeze? | Yes, with known oversized modules and a leftover slice. |
| Demonstrable? | Yes: CLI, Railway synthetic HTTP, credentialed live smoke. |
| Truthfully represented? | Mostly. A few recruiter phrases need qualification. |
| Appropriately scoped? | Yes against PIVOT001. |
| Ready to freeze? | Yes. |

Finding counts: **P0 = 0**, **P1 = 6**, **P2 = 11**, **P3 = 4**. No finding blocks freeze.

## 2. Audit method and reconciliation

### 2.1 Method

- Started from `origin/main` at the expected SHA `64618bce`.
- Treated implementation code as primary technical truth.
- Treated accepted evaluation evidence as execution evidence.
- Did **not** rerun the 598-test non-live campaign, evaluation suite, tamper suite, failure-injection suite, persistence suite, Railway five-run campaign, Railway restart campaign, live Snowflake suite, live dbt suite, or governed live smoke.
- No targeted runtime verification was required. Residual uncertainties were resolved from code plus accepted reports.

### 2.2 What changed after PR 32

PR 32 (`audit/final_acceptance_001`, still open at review time) audited `main` `0425d3248ceb144043821941f2fef3d2dc370e58` **before** PR 28 merged. This audit does not copy that verdict.

| Item | PR 32 | Current `main` `64618bce` |
|---|---|---|
| Product code | PR 31 live-profiling fix | Unchanged. PR 28 was documentation only. |
| PostgreSQL docs | Still said exclusive PostgreSQL 16 | PR 28 records PostgreSQL 16 or newer; Railway 18.6 is acknowledged |
| Railway restart | PASS on serving SUCCESS | Closed by PR 28 (`PORT=8000`) |
| Live Snowflake / dbt / governed live / live-smoke | PASS on the auditor's credentialed host | Accepted. Product code is the same SHA family. |
| Offline 598-test campaign | 598 passed | Accepted. Not rerun. |
| This audit's extra job | Acceptance / campaign confirmation | Product-truth, demo dependence, architecture coherence, verifier trust, DE credibility, interview claims |

PR 32 remains useful historical execution evidence. It is not the product-architecture review.

### 2.3 Evidence used

Implementation: `src/aide/app/supervisor.py`, `src/aide/app/interview.py`, `src/aide/app/gateway.py`, `src/aide/app/groups.py`, `src/aide/app/runtime.py`, `src/aide/api/app.py`, `asgi.py`, `src/aide/generation/vantara.py`, `src/aide/modelling/*`, `src/aide/twin/*`, `src/aide/repair/*`, `src/aide/verification/evaluate.py`, `src/aide/quality/interview.py`, `src/aide/domain/benchmark.py`, `src/aide/domain/repair.py`, `src/aide/profiling/fixtures.py`, `src/aide/policy/engine.py`, `src/aide/connectors/snowflake/*`.

Accepted evidence: `README.md`, PIVOT001, `docs/MVP_SCOPE.md`, `docs/INTERVIEW_DEMO.md`, `docs/evaluation/FINAL_QA_001.md`, `docs/evaluation/LIVE_ACCEPTANCE_001.md`, `docs/evaluation/DEMO_SCENARIOS_001.md`, PR 32 historical audit, PR 31 run report, PR 28 run report.

## 3. Actual product today

### 3.1 What the code actually runs

The Interview product is `InterviewSupervisor.run_customer_revenue`. It is a deterministic application workflow, not an agent loop.

```text
authenticate + pin contracts
→ interpret_customer_revenue_request (discards caller text)
→ PLANNING
→ DISCOVERY (discover_assets + describe_asset × locked tables)
→ intersect discovery with 10 Vantara addresses
→ pin TwinSnapshot + assemble EstateContext
→ PROFILING (profile_estate)
→ DESIGN (replayed propose_model_design + deterministic decide_architecture)
→ GENERATION (generate_vantara_transformation → create/parse/compile)
→ POLICY_CHECK
→ EXECUTION (manifest DEV load + dbt execute)
→ VALIDATION (dbt tests + interview quality)
→ optional: inject INVOICE_STATUS→STATUS, diagnose, allow-listed repair, revalidate
→ Independent Verifier over supervisor-assembled evidence
→ evidence bundle
```

Every **materialized task** enters `GovernedToolGateway`. Twin pin, requirement interpretation, design acceptance, drift injection, and evidence assembly are supervisor-owned and do not go through the gateway.

### 3.2 Capability inventory

| Capability | Class | Evidence |
|---|---|---|
| Deterministic Supervisor over persisted phases | Implemented and proven | `supervisor.py`; FINAL-QA, Railway, CLI |
| Governed Tool Gateway (validate → policy → intent → execute → reconcile → evidence) | Implemented and proven | `gateway.py`; 36/36 ops on synthetic path; live smoke names RO/DEV/dbt |
| Policy engine and SQL classifier | Implemented and proven on the Interview subset | `policy/engine.py`; evaluation safety |
| Distinct Snowflake RO / DEV identities | Implemented and proven | specs + live probe on PR 31 / PR 32 |
| Fake Snowflake + fake dbt closed loop | Implemented and proven | CLI, Railway, 598-test campaign |
| Real Snowflake inspect + DEV build + tests + quality | Implemented, narrowly proven | live-smoke and governed live; no RAW drift |
| Digital Twin capture, snapshot pin, bounded context | Implemented and proven as persistence | MVP001 + interview pin; profiles/dbt capture unwired |
| Deterministic modelling rule engine | Implemented, narrowly proven | DE007 engine always called with `vantara_modelling_context()` |
| Bounded dbt generation | Implemented and Vantara-specific | `generation/vantara.py` emits a fixed 21-model set |
| Schema-drift detection and one allow-listed repair | Implemented and Vantara-specific | `domain/repair.py`; offline/synthetic only |
| Repair safety (second, broader, wrong table/column, test weaken, prod target) | Implemented and proven offline | FINAL-QA `E-SF-*` |
| Independent Verifier module (pure, no connector imports) | Implemented and proven as module independence | `verification/evaluate.py`; tamper suite |
| Immutable application-audit evidence bundle | Implemented and proven | CLI / Railway 100% completeness |
| Deterministic two-run benchmark | Implemented and proven | AT-23 / E-RP-01 / Railway `determinism=true` |
| Token-gated synthetic HTTP demo | Implemented and proven | LIVE_ACCEPTANCE_001; PR 28 restart |
| Credential-gated live smoke | Implemented and proven when secrets exist | PR 31 / PR 32 |
| Natural-language requirement interpretation | Implemented as a stub | `interpret_customer_revenue_request` deletes `text` |
| Generic estate-to-model generation | Designed only | no non-Vantara generator |
| Live LLM provider | Unreachable in product paths | replay-only `LlmGateway` |
| DE002C safe-SQL slice | Implemented, leftover | `slice.py` + `POST /v1/workflows` |
| GitHub delivery, frontend, monitoring, staging/prod deploy, second repair class | Out of scope | PIVOT001 |
| Databricks, Fabric, Airflow, BigQuery | Out of scope | README future list |
| Cryptographic tamper evidence | Out of scope | documented |

### 3.3 Dead, leftover, or obsolete

| Item | Status |
|---|---|
| `capture_profile_observations` / `capture_dbt_artifacts` | Implemented, called only from unit tests |
| DE002C `OfflineSliceService` + `ToolRegistry` | Reachable via CLI `aide slice` and `POST /v1/workflows` |
| `vantara_model_design` helper | Test / replay fixture builder, not the supervisor path |
| Generic `require_demo_models=False` modelling branch | Unreachable from Interview |
| V1 `aide eval` / scenarios S03–S11 | Design only |

## 4. Product value assessment

The system solves a **real** enterprise problem — the expensive work between Snowflake, dbt, and humans — but only for **one scripted slice** of that problem.

| Flow step | Value class | Comment |
|---|---|---|
| Business request → data product | Simulated request, real execution machinery | Caller text is ignored. The locked requirement is executed. |
| Estate understanding | Narrowly real | Discovery and describe run. Selection is a 10-table intersect. |
| Profiling | Real on both fake and live paths | PR 31 made live `profile_estate` finish under the gateway timeout. |
| Modelling | Real decision engine, simulated codegen link | Architecture class is rule-selected. SQL is a template. |
| Generation | Real artifacts, fixture-authored | Credible customer-revenue layering; not generated from design content. |
| Execution | Real | Fake or real dbt in workflow-scoped `AIDE_DEV`. |
| Testing | Real | Generated dbt tests execute. |
| Quality | Real and narrow | Presence, grain, invoice/payment totals. |
| Incident diagnosis | Real classifier, scripted incident | `SCHEMA_MISMATCH` from injected or expected rename. |
| Repair | Real validator, one mapping | AST-bounded column reference only. |
| Verification | Real module, completeness-oriented | See §10. |
| Evidence | Real | Digests, required sections, restart survival. |
| Human intervention reduction | Real for this scenario | The scenario is designed so a human is unnecessary. |

**Where value is real:** governance, identity split, intent/reconcile, repair bounds, fail-closed policy, evidence, and a coherent dbt layering for one revenue mart.

**Where value is simulated:** understanding arbitrary intent, choosing relevant assets, inventing a model graph, diagnosing unknown incidents, and SCD2 history.

That split is acceptable for an Interview MVP. It is the wrong split for a V1 product claim.

## 5. Architecture assessment

Responsibility boundaries on the Interview path are real, not merely documented.

```text
Business request
  → InterviewSupervisor
      → Digital Twin pin (PostgreSQL)
      → bounded EstateContext
      → modelling engine + replayed design
      → Governed Tool Gateway
          → PolicyEngine
          → Snowflake RO / DEV
          → dbt
      → tests + quality
      → drift classify → repair validator → one patch → revalidate
      → Independent Verifier (pure function)
      → EvidenceBundle (PostgreSQL)
```

Confirmed:

- Supervisor advances state from persisted typed outcomes.
- Gateway is the sole connector execution path for Interview tasks.
- Composition root `aide.app.interview` may import vendor connectors; Supervisor and capability groups may not.
- Repair cannot weaken tests or apply a second class.
- Verifier cannot import gateway, connectors, or repair writers.
- PostgreSQL is the only control-plane store.

Contradictions and hidden coupling:

- Twin pin and many evidence artifacts are written by the supervisor, not the gateway. That is documented application responsibility, but it weakens “every action is a governed tool call.”
- Modelling and generation do not read the pinned Twin. The Twin is a governance/evidence object, not the planning substrate.
- DE002C still uses `ToolRegistry` and direct connector calls. It is a second architecture in the same process.
- Successful Interview rows often remain `workflows.state=VALIDATION` while HTTP reports `VERIFIED`. Tests allow this. `_finalize_status` only writes `FAILED` or `BLOCKED`.

These are Interview-acceptable. They are not architecture theatre. They are also not a finished V1 control plane.

## 6. Generic versus Vantara-specific analysis

| Item | Classification | Why |
|---|---|---|
| 10 locked tables (`DEMO_SELECTED_ADDRESSES`) | Acceptable Interview MVP constraint | `propose_relevant_assets` intersects a fixed address list |
| `interpret_customer_revenue_request` ignores `text` | Acceptable Interview MVP constraint | Honest if not sold as NL understanding |
| `INVOICE_STATUS` → `STATUS` on `VANTARA_RAW.BILLING.INVOICES` | Acceptable Interview MVP constraint | PIVOT001 C-06 |
| Fixed 21-model tuple | Acceptable Interview MVP constraint | Also technical debt if treated as a generator |
| Hardcoded generated SQL in `generation/vantara.py` | Technical debt | Design is a name-set gate, not a compiler |
| Quality SQL against `mart_customer_revenue_daily` | Acceptable Interview MVP constraint | Scenario-specific verifier of that mart |
| Repair allow-list in `domain/repair.py` | Acceptable Interview MVP constraint | Domain constants, not a hidden branch in the gateway |
| `project_id="vantara_project"` | Acceptable Interview MVP constraint | |
| Replay fixture `recorded_vantara.json` | Acceptable Interview MVP constraint | Determinism requires it |
| `KNOWN_RELATIONSHIP_PAIRS` | Acceptable if unused in production inference | File comment says evaluation/test baseline only |
| Scenario-specific policy rules | Not found | Policy is generic; repair allow-list is the scenario lock |
| Scenario-specific gateway | Not found | Gateway is generic |
| Scenario leakage into `groups.py`, `supervisor.py`, `quality/interview.py`, `domain/benchmark.py` | Technical debt | Expected for an Interview composition, not an architectural violation |

**No architectural violation and no product blocker** were found in the hardcoding search. The product is allowed to be Vantara-specific. The risk is rhetorical: calling that specificity a generic capability.

## 7. Digital Twin assessment

The Enterprise Data Digital Twin is **genuine control-plane state** and **not** the thing that decides the model.

What is real:

- Five contracts persist in PostgreSQL: asset, relationship, observation, snapshot, evidence reference.
- Records are append-only.
- One snapshot is pinned per workflow.
- Context assembly is grant-filtered, bound-checked, and fail-closed.
- Snapshot and estate digests are required by repair and verifier.

What is a demo abstraction:

- Pin filters the catalogue to `vantara_selected_addresses()`.
- Request terms are hardcoded `("customer", "revenue", "invoice", "payment")`.
- `capture_profile_observations` and `capture_dbt_artifacts` never run on the Interview path.
- Modelling, generation, and quality do not load the snapshot.
- Environment is `DEVELOPMENT` only.

At 100 assets the default context caps (12 top-level, 120 fields, 64 relationships, 32 observations, 64 KiB) fail closed. At 1000 assets, pin/load would also become an O(n) per-row fetch problem. That is not a freeze defect. It is proof the Twin is sized for the Interview slice.

**Use in an interview:** “We persist a pinned estate snapshot so later plan, repair, and evidence cannot silently follow a moving catalogue.”  
**Do not say:** “The Twin understands the enterprise and drives modelling.”

## 8. Supervisor and Gateway assessment

Governance is real.

- Phase templates are fixed. There is no dynamic tool selection.
- Gateway persists policy, dispatch intent, attempt, fence, result, and evidence.
- Ambiguous non-`SIDE_EFFECT_FREE` failures acquire recovery and reconcile before retry.
- Repair budget is persisted and restart-tested.
- Approvals exist as contracts; the Interview path does not require a human approval for the allow-listed repair.

Limits and unused machinery:

- Default capability semantics are `SIDE_EFFECT_FREE`, so parse/compile/test skip recovery and fail closed. Recovery matters for `execute_transformation`, `load_manifest_sources`, and `create_transformation`.
- Local handler `reconcile` always returns `NoEffect`.
- Gateway `reconcile` records `ALLOW` / `source=recovery` without re-running the full policy engine.
- DE002B primitives are used by the gateway, not bypassed by the Supervisor.
- `ToolRegistry` + `slice.py` are redundant relative to the Interview story and still reachable.

Unreachable-for-Interview does not mean dead. It means do not demo it and do not extend it during freeze.

## 9. Data engineering assessment

As a senior data engineer, the generated project is a **credible demo warehouse**, not a credible general modelling compiler.

Strengths:

- Correct layering: sources → staging views → intermediates → snapshot-shaped customer → dims/facts → daily revenue mart.
- Customer conformance uses billing as grain, CRM crosswalk, and website-domain dedup.
- Currency and website normalization are explicit.
- Contact email/phone are masked as `'***'` in staging.
- Facts join to `dim_customer` / `dim_plan`.
- Mart full-outer-joins invoiced and paid amounts at customer × date.
- Quality checks the mart grain and reconciles invoice-line and payment totals to ±0.01.
- Staging invoice SQL is the only file the repair may touch.

Weaknesses that matter for credibility:

- `generate_vantara_transformation` ignores design content beyond the required name set.
- `snap_customer_conformed` sets `valid_to` null and `is_current` true. This is SCD2 **shape**, not Type-2 history.
- `int_subscription_plan_history` is a pass-through of current subscriptions.
- `dim_date` is distinct invoice issue dates, not a date spine.
- Unknown-customer `-1` member is hardcoded.
- Quality does not prove SCD correctness, dedup business rules, or refund handling.

Outside the fixture, a reviewer would accept this as “a hand-authored reference project executed by a control plane.” A reviewer would reject “the system designed and generated this from estate signals.”

## 10. Synthetic versus real proof matrix

| Capability | Fake SF + fake dbt (offline / Railway) | Real SF | Real dbt on SF | Notes |
|---|---|---|---|---|
| Full drift → repair → verifier PASS | Proven | Not run | Not run | Live must not mutate RAW |
| `INVOICE_STATUS` → `STATUS` injection | Proven (v1 fixture) | Not applicable | Not applicable | Live RAW is already v2 `STATUS` |
| 21-model generate / compile / run / test | Proven | Proven without drift | Proven | Live uses `fixture_version=v2` |
| Quality + reconciliation | Proven | Proven | Proven | |
| Gateway + policy | Proven | Proven | Proven | |
| Twin pin | Proven | Proven as part of governed live | — | Profiles still not captured into Twin |
| Independent Verifier | Proven | `independent_verifier_ran=false` | — | Accepted live contract |
| Least-privilege grants | N/A | Proven (PR 31 / 32) | — | `SHOW GRANTS`, no GRANT/REVOKE |
| Deterministic two-run benchmark | Proven | Not claimed | Not claimed | |
| HTTP token / input rejection | Proven on Railway | N/A | N/A | |
| Restart persistence | Proven on Railway | N/A | N/A | |

**Do not combine incorrectly:**

1. Offline verifier PASS + live smoke PASS ≠ live closed-loop PASS.
2. Offline v1 drift + live v2 estate ≠ one estate version.
3. Railway PASS + live Snowflake PASS ≠ Railway talks to Snowflake. Railway reports `live_smoke=NOT_RUN`.
4. FINAL-QA-001 `E-LP-LIVE=NOT_TESTED` is historical. Later PR 31 / PR 32 proved live least privilege. This audit supersedes the evaluation README sentence that still says live least-privilege is unproven.

## 11. Verifier trust analysis

The Independent Verifier is **independent as a module**. It is **not independent as an investigator**.

What is true:

- `evaluate_verifier` is a pure function. No I/O, no gateway, no connectors, no workflow writes.
- Import contracts prevent the verifier package from obtaining execution power.
- Tamper tests fail missing sections, digest mismatch, wrong workflow/snapshot, mixed provenance, and rehashed execution mode.
- Optional advisory text cannot change the verdict.

Trust assumptions:

1. The Supervisor honestly assembled `VerifierEvidencePack`.
2. Artifact bytes were not altered by a DBA after digest persistence, or a DBA alteration is out of threat model.
3. `quality_passed`, `repair_in_scope`, and `post_repair_validation_passed` are truthful supervisor-derived flags.
4. Completeness of required evidence types is a proxy for “the scripted loop happened.”
5. Digests prove identity and integrity of stored blobs, not semantic correctness of SQL.

Can upstream manufacture PASS? **Yes, if the Supervisor writes a complete, digest-consistent pack for the allow-listed repair.** That is the accepted design: the verifier marks homework it cannot change, it does not re-run dbt. Logically incorrect warehouse data can still PASS if tests and the two reconciliation queries pass.

`_claimed_hash_matches` returns true when either side is `None`. Completeness can be filled by supervisor-synthesized sections. Timing and cost checks are almost vacuous.

**Interview phrasing:** “The verifier cannot mutate the workflow or dispatch tools. PASS means the immutable evidence for this contract is complete and consistent. It does not mean a third party re-executed the warehouse.”

## 12. Security architecture assessment

**Interview-safe. Not production-ready.**

| Area | Interview | Production |
|---|---|---|
| RO vs DEV identity classes | Real | Requires continuing DBA grant hygiene |
| Secret handling | Env `SecretRef` only | No vault/rotation |
| RAW boundary | Fake path + live grant probe | Live smoke must stay credential-gated; do not restore RAW writes |
| HTTP demo | Token mandatory; empty body only | Public URL is a demo switch, not a product API |
| Policy bypass | Interview tasks use gateway | DE002C handlers call connectors via `ToolRegistry`; dbt quality opens an auxiliary Snowflake session; SSE `/v1/workflows/{id}/events` has no session check |
| Client grant forgery | Rejected | Same |
| Evidence mutation | Digest fail-closed; append-only triggers | DBA/superuser can disable triggers |
| Supply chain | `uv.lock` | No SBOM / release signing |

Do not treat Railway environment name `production` as product `PRODUCTION_WRITE`.

## 13. Operations assessment

| Topic | Real limit |
|---|---|
| PostgreSQL lifecycle | Alembic on boot; Railway runs 18.6; CI/Compose stay 16 |
| Workflow recovery | Gateway reconcile + lease fencing exist; Interview success does not move the row to `COMPLETED` |
| Restart | Proven for one app replica; Postgres stays up |
| Snowflake timeout | 180 s gateway deadline; live profile budget 150 s after PR 31 |
| dbt cleanup | Live path drops workflow DEV schemas in `finally` |
| Concurrency | In-process demo lock. Two replicas can both run demos. |
| Observability | PostgreSQL audit. No product metrics, alerts, or on-call. |
| Rollback | Replace the app container. Volume teardown is destructive. |
| Cost controls | Budget ledger exists; offline tokens/credits are `UNAVAILABLE` |

These are Interview operational limits, not freeze blockers.

## 14. Performance and scale assessment

No new benchmark was run.

| Load | Expected behavior |
|---|---|
| Current 10-table tiny estate | Offline ~7–30 s; Railway HTTP ~40 s for two runs; live profile ~62 s after PR 31 |
| 100 assets | Context assembly fails closed on default caps; live profiling would need another budget/session design |
| 1000 assets | Same, plus Twin load round-trips and snapshot size |
| Large Snowflake tables | Profiling budgets exist; Interview does not prove warehouse-scale scans |
| Many concurrent workflows | Worker leases help; HTTP demo lock does not |
| Multiple users / companies | Not designed. One local principal, one Vantara company |

Hotspots: `supervisor.py` (~2600 lines), live connection-per-call (mitigated by PR 31 pinned read session), Twin `load_snapshot` per-row fetches, in-process demo mutex.

## 15. Maintainability assessment

| Issue | Files | Severity |
|---|---|---|
| Oversized Supervisor | `src/aide/app/supervisor.py` | P2 |
| Parallel orchestration | `src/aide/app/slice.py`, `src/aide/tools/registry.py` | P2 |
| Duplicate 21-model tuples | `generation/vantara.py`, `modelling/constants.py` | P3 |
| Scenario leakage into app/domain | `groups.py`, `supervisor.py`, `domain/repair.py`, `quality/interview.py` | P2 |
| Unwired Twin capture | `twin/capture.py` | P2 |
| Leftover DE002C HTTP | `asgi.py`, `api/app.py` | P2 |
| Private-method coupling in Supervisor | `_resolved_payload`, `_verifier_pack`, `_store_typed_evidence` | P2 |
| Test-only architecture for some Twin/dbt capture | unit tests only | P3 |

Migration risk is low if freeze holds. The risk is a later agent “generalizing” generation or repair inside these modules.

## 16. Documentation truth matrix

| Claim | Class | Notes |
|---|---|---|
| Autonomous Data Engineering Control Plane | PARTIALLY_PROVEN | Control plane yes; autonomous only inside one scripted loop |
| Companies keep Snowflake, dbt, and existing tools | PARTIALLY_PROVEN | True as architecture. Default demo uses fakes. No Airflow/GitHub |
| Understands the estate | PARTIALLY_PROVEN | Understands 10 selected Vantara tables |
| Pinned Digital Twin | PROVEN | As snapshot persistence, not as planner input |
| Deterministic Supervisor | PROVEN | |
| Governed Tool Gateway for Interview workflow actions | PROVEN | Not true of DE002C HTTP |
| 21 required customer-revenue models | PROVEN | As a fixture, not a generic capability |
| dbt tests, quality, reconciliation | PROVEN | |
| Schema-drift repair `INVOICE_STATUS` → `STATUS` | PROVEN offline/synthetic | NOT_PROVEN on live RAW |
| Independent Verifier, no LLM judge | PROVEN | Module independence; not semantic re-execution |
| Immutable evidence / 100% completeness | PROVEN | Application-audit, not cryptography |
| Offline deterministic benchmark | PROVEN | After documented normalization |
| Credential-gated Snowflake live smoke | PROVEN | Happy path + grants; no drift/verifier |
| Live smoke proves the closed loop | NOT_PROVEN | README already denies this |
| PostgreSQL 16 only | OUT_OF_SCOPE / corrected | Current README: 16 or newer |
| No generic autonomous loop | PROVEN | Matches code |
| Databricks / Fabric / Airflow / BigQuery | DESIGN_ONLY / OUT_OF_SCOPE | Future connectors |
| 690 engineering minutes saved | PARTIALLY_PROVEN | Labelled ESTIMATED |
| SCD2 dimensions | PARTIALLY_PROVEN | Column shape only |
| Digital Twin of the enterprise | NOT_PROVEN | Bounded demo snapshot |

Wording to keep as-is: limitations list, live-smoke split, ESTIMATED label, “application-audit immutability.”

Wording to qualify in speech, not necessarily rewrite now: “Autonomous,” “understands the estate,” “21 models” without “Vantara fixture.”

## 17. Benchmark credibility assessment

| Metric | What it is |
|---|---|
| 10 assets, 21 models, 36 gateway ops, 36 policy evals, 23 tests, 25 quality checks | MEASURED counts of the fixture wiring. Useful as stability signals. Not value KPIs. |
| 1 incident, 1 repair, 0 humans | MEASURED for the scripted incident. |
| Evidence completeness 100% | MEASURED section presence. |
| Deterministic repeatability | MEASURED after UUID/timestamp/schema-name normalization. Meaningful for replay, not for live LLM. |
| Wall clock | MEASURED per host. Not an SLA. |
| 690 minutes | ESTIMATED sum of nine baseline steps. Defensible as a labelled engineering guess. Not a productivity study. |
| Tokens, credits, ROI | UNAVAILABLE. Correctly not invented. |

The baseline is defensible **as labelled fiction**. The 180-minute “dims/facts/marts with SCD2” line is the weakest row because the code does not implement Type-2 history.

**Show to recruiters?** Yes, if Sofien says “labelled estimate for the steps this loop actually performs” and does not say “we save 11.5 hours in production.” Counts may be shown as “what this run did,” not “how good the product is.”

## 18. Interview claims matrix

### Safe to say

- This is a governed control plane over Snowflake and dbt, not a SQL chatbot.
- One business request becomes a tested DEV data product, then one allow-listed repair, then a deterministic verdict.
- Every Interview connector call goes through a policy gateway that persists intent and evidence.
- RO inspects RAW; DEV writes only workflow-scoped `AIDE_DEV`.
- The verifier cannot dispatch tools or write workflow state.
- Two offline runs match after documented identifier normalization.
- Live Snowflake least privilege and a governed live build were proven on a credentialed host. Live does not recreate RAW drift.
- Production and staging warehouse actions are disabled.

### Say only with qualification

- “Autonomous” — autonomous inside one allow-listed loop.
- “Understands the estate” — pins and profiles ten selected tables.
- “Generates 21 models” — executes a locked Vantara project, not an open-ended generator.
- “Digital Twin” — immutable snapshot used for bounds, repair binding, and evidence.
- “Independent Verifier” — independent of execution authority, not a second warehouse run.
- “690 minutes saved” — versioned estimate.
- “SCD2” — current-row snapshot with SCD2 columns.
- Railway URL — synthetic fakes.

### Do not say

- It understands arbitrary natural-language requests.
- Live Snowflake proved drift, repair, and verifier.
- Railway is production data-plane automation.
- Evidence is cryptographically tamper-proof.
- The Twin is a living enterprise graph.
- Databricks / Fabric / Airflow are implemented.
- Humans are no longer needed for data engineering.
- The benchmark is a productivity study or ROI.

### Best architecture story

Start from the failure mode: a renamed billing column becomes a multi-hour debug because context, policy, execution, and proof live in different tools. Data Pilot AI keeps Snowflake and dbt and inserts a deterministic Supervisor plus a Governed Tool Gateway. Estate context is pinned. Repair is allow-listed and AST-checked. A read-only verifier scores immutable evidence. The interesting idea is not “AI wrote SQL.” It is “the system cannot mark its own homework and cannot apply a broader patch.”

### Best live demonstration story

1. CLI or Railway empty-body demo: request → Twin pin → 21 models → green build → injected rename → one repair → verifier PASS.
2. Show the repair validator rejecting a broader diff from the evaluation tests, not from the HTTP body.
3. If credentials exist: live-smoke for RO/DEV grants and a real DEV build. Say explicitly that drift stays offline.

### Likely senior objections and answers

| Objection | Answer |
|---|---|
| This is just a fixture. | Yes, the scenario is locked. The governance, recovery, and evidence machinery are generic and tested adversarially. |
| The request text is ignored. | Correct. Interview MVP proves the loop, not an NL parser. |
| Generation is templates. | Correct. The control plane executes and governs a reference project. Design validation is a gate. |
| The verifier is not independent. | It cannot execute or mutate. It can be lied to by its pack assembler. That is application-audit independence, not a third-party auditor. |
| Live does not prove repair. | By contract. We do not mutate RAW. |
| 690 minutes is made up. | It is labelled ESTIMATED from a versioned table. We do not show ROI. |
| Why not LangGraph? | Hidden control flow. We wanted persisted phases, policy, and reconcile-before-retry. |
| Will this scale? | Not as-is. Context caps fail closed. That is intentional for the Interview slice. |
| Two stacks in one repo? | DE002C is historical foundation still reachable. Interview is the product. Do not demo `/v1/workflows`. |

## 19. Product gap analysis

Gaps that matter for credibility, interview value, portfolio quality, architecture integrity, or extensibility — **not** a V1 backlog:

| Gap | Why it matters | Build now? |
|---|---|---|
| Talk-track discipline on NL, Twin, verifier, live/offline | Interview credibility | No code. Use this audit. |
| SCD2 is shape-only | DE credibility if overclaimed | No. Qualify. |
| Twin not used for planning | Architecture integrity | No. Document. Later, if ever, as an additive contract. |
| Unwired profile/dbt Twin capture | Future extensibility | No. Do not wire during freeze. |
| DE002C HTTP still live | Recruiter trap / extra attack surface | No deletion during freeze. Do not demo it. |
| Success state stays `VALIDATION` | Polish | No. Tests allow it. |
| No second scenario | Portfolio variety | No. A second scenario would reopen freeze. |

## 20. Known limitations

- One business request and one automatic repair class.
- Requirement text is discarded.
- Generation is a locked Vantara template set.
- Twin does not drive modelling or generation.
- Live RAW is not drifted; verifier closed loop is offline/synthetic.
- Railway is fake Snowflake and fake dbt.
- Evidence is application-audit immutability.
- Engineering minutes are labelled estimates.
- Successful workflow rows may remain `VALIDATION`.
- Multi-replica demo lock is untested.
- DE002C `/v1/workflows` is not the Interview product.

## 21. Ranked findings

| ID | Finding | Severity | Confidence | Affected capability | Blocks freeze? | Action |
|---|---|---|---|---|---|---|
| F-01 | Caller requirement text is discarded | P1 | High | Request interpretation | No | Qualify in interviews. Do not “fix” by adding an LLM. |
| F-02 | dbt generation is a locked template; `ModelDesign` is a name-set gate | P1 | High | Generation | No | Say “reference project executed by the control plane.” |
| F-03 | Verifier scores supervisor-assembled completeness/digests, not warehouse semantics | P1 | High | Verification | No | Use the qualified independence story. |
| F-04 | Offline closed loop and live smoke prove different subsets | P1 | High | Proof / demo | No | Never fuse the two proofs. |
| F-05 | SCD2 / plan history are structural placeholders | P1 | High | Modelling / benchmark | No | Do not claim working Type-2 history. |
| F-06 | Twin is pinned evidence/context, not the planning substrate | P1 | High | Digital Twin | No | Tell the pin/governance story. |
| F-07 | DE002C `ToolRegistry` path remains reachable beside Interview | P2 | High | HTTP / architecture | No | Do not demo `/v1/workflows`. Do not delete in freeze. |
| F-08 | Successful workflows often stay `VALIDATION` while HTTP says `VERIFIED` | P2 | High | State model | No | Accepted by current tests. |
| F-09 | Profile and dbt Twin capture are unimplemented on the product path | P2 | High | Digital Twin | No | Leave unwired. |
| F-10 | `supervisor.py` is an oversized composition root | P2 | High | Maintainability | No | Do not split during freeze. |
| F-11 | HTTP demo lock is process-local | P2 | High | Operations | No | Keep one replica for demos. |
| F-12 | Gateway reconcile does not re-run full policy | P2 | Medium | Recovery | No | Accept for Interview. |
| F-13 | Auxiliary Snowflake session inside real dbt quality | P2 | High | Connector boundary | No | Do not broaden. |
| F-14 | SSE workflow events are unauthenticated | P2 | High | HTTP security | No | Do not advertise the route. |
| F-15 | Evaluation README still says live least-privilege is unproven | P2 | High | Documentation truth | No | This audit supersedes that sentence. Historical FINAL-QA stays frozen. |
| F-16 | 690-minute SCD2 baseline row is stronger than the code | P2 | High | Benchmark | No | Label and qualify. |
| F-17 | Context caps / Twin load will not survive 100–1000 assets | P2 | High | Scale | No | Out of Interview scope. |
| F-18 | Cookie `SameSite=lax` vs docs `Strict` | P3 | High | Auth docs | No | Ignore for freeze. |
| F-19 | Duplicate required-model tuples | P3 | High | Maintainability | No | Tests already lock equality. |
| F-20 | Vacuous verifier timing/cost checks | P3 | High | Verifier | No | Already labelled as metadata. |
| F-21 | `fct_invoices` is generated but outside the 21 required models | P3 | Medium | Generation | No | Harmless extra file. |

## 22. Minimal closure plan

**None required.**

PR 28 already closed the only documentation gap that PR 32 treated as remaining product-adjacent work. This audit is the Interview talk-track source of truth.

Optional later, not freeze work: add one line in `docs/evaluation/README.md` pointing here, so readers do not stop at FINAL-QA-001's credential-gated live row.

## 23. Freeze recommendation

**`FREEZE_INTERVIEW_MVP`**

Do:

- Human-review and merge this audit PR. Do not merge from the agent.
- Treat `main` `64618bce` plus this report as the Interview baseline.
- Use §18 as the recruiter script.

Do not:

- Add a second repair class, vendor, UI, GitHub delivery, or live LLM.
- Mutate `VANTARA_RAW` or change Snowflake grants.
- “Generalize” generation or asset selection.
- Wire Twin capture or split `supervisor.py`.
- Treat Railway `production` as a product production environment.

## 24. WHAT NOT TO BUILD NEXT

Do not start any of the following because they look like the next impressive feature:

- A second business request or generic NL interpreter
- A second automatic repair class, including duplicate payments
- Design-driven dbt codegen
- Graph store or “real” enterprise Twin
- LangGraph / CrewAI / multi-agent rewrite
- Frontend SPA
- GitHub delivery
- Databricks / Fabric / Airflow / BigQuery connectors
- Production or staging deploy
- Monitoring / cost platform
- Cryptographic evidence ledger
- Multi-tenant IAM
- `aide eval` V1 scenario pack
- Refactor of Supervisor “for cleanliness”
- Deleting DE002C as a cleanup crusade
- Raising Twin limits to pretend the estate scaled
- Live RAW drift injection

The Interview MVP is complete when the story is told honestly. More product would make the story worse, not better.
