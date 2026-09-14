# PIVOT000 — Data Pilot AI Pivot Feasibility Assessment

**Task:** PIVOT000
**Assessment baseline:** `main` at `565bea18f7aa5eed6b782313f1c67dc2c5de3271`
**Assessment type:** Feasibility and scope audit; no implementation
**Verdict:** **CONDITIONAL GO**

## 1. Executive verdict

The proposed Autonomous Data Engineering Control Plane is technically feasible on the
current foundation, and a narrow prototype does not require a broad rewrite. The repository
already describes itself as a capability-first control plane and has executable foundations
for deterministic orchestration, policy, approvals, durable PostgreSQL state, recovery,
Snowflake, dbt, profiling, modelling, synthetic data, and CI
(`docs/ARCHITECTURE.md`, `src/aide/`, `synthetic/vantara/`, `.github/workflows/ci.yml`).

The direction is internally coherent only if the named Supervisor, Estate Intelligence,
Data Engineering, Reliability, and Verifier components are initially **logical roles or
typed capability groups**, not free-running autonomous agents. One deterministic
orchestrator must continue to own control flow, budgets, policy, approvals, tool dispatch,
and repair limits. The Independent Verifier must be read-only and must not share the
executor's authority to mutate external systems.

The gate is conditional because four contracts need a focused architecture audit before
implementation:

1. the minimal Digital Twin identity, versioning, and evidence model;
2. the boundary between supervisor orchestration and role-specific reasoning;
3. verifier independence and the repair/approval boundary;
4. the Tool Registry's evolution into the single governed Tool Gateway.

No fundamental technical blocker was found. The principal danger is scope: implementing
the strategic catalogue literally would turn the prototype into a new enterprise data
platform rather than a control plane above existing platforms.

## 2. Feasibility assessment

### Direct answers to the critical questions

| # | Question | Answer |
|---|---|---|
| 1 | Is the product technically feasible with the current foundation? | **Yes.** The capability abstraction, connector protocol, deterministic workflow kernel, policy model, durable recovery, and real Snowflake/dbt adapters are directly relevant foundations. The missing work is mostly composition and new bounded domain contracts, not replacement of the platform core. |
| 2 | Is the architecture internally coherent? | **Yes, conditionally.** It is coherent when “agents” are responsibility boundaries implemented as typed capabilities/sub-workflows. Independent autonomous agents with their own tool loops would contradict `docs/AGENT_MODEL.md` and weaken the single policy/audit boundary. |
| 3 | What percentage appears reusable? | **Approximately 65–80% of the current implemented surface is reusable** for the pivot. This is a subsystem-weighted estimate, not a lines-of-code claim. Its midpoint decomposition is about 40% mostly unchanged, 32% reusable with adaptation, 8% to retire, and 20% too incomplete or uncertain to credit yet. |
| 4 | What can remain mostly unchanged? | Core domain identity/effect/provenance contracts; connector base protocol and registry; PostgreSQL task/attempt/audit/budget persistence; lease fencing, reconciliation and cancellation primitives; scoped secret interfaces; Snowflake and dbt adapter internals; deterministic Vantara generator; import boundaries and CI gates. |
| 5 | What needs adaptation? | The capability catalogue, Tool Registry, workflow composition, metadata catalogue, persistence schema, policy/approvals, profiling/modelling inputs, LLM gateway, quality checks, and evaluation must become estate- and evidence-aware. |
| 6 | What should be replaced or retired? | Retire the original all-at-once recruiter-demo roadmap as the active scope; stop treating `OfflineSliceService` as the product composition root; replace replay-only `LlmGateway` as the production gateway while retaining replay as a test adapter; keep Vantara-specific hard-coded designs only as benchmark oracles. |
| 7 | What should not be built in the prototype? | A graph database, multi-agent framework, Temporal/LangGraph migration, broad vendor matrix, enterprise IAM, production writes, streaming, generalized governance catalogue, optimizer, full UI, always-on monitoring service, or unconstrained autonomous repair. |
| 8 | What is the smallest credible prototype? | One Vantara customer-revenue request; one minimal PostgreSQL Digital Twin sourced from Snowflake metadata and dbt artifacts; one deterministic governed workflow; one schema-drift fault; one bounded patch; deterministic independent verification; one evidence bundle. Offline completion plus one real Snowflake/dbt smoke is sufficient. |
| 9 | What is the smallest credible MVP after it? | Harden the same vertical slice, add versioned twin snapshots/lineage/incidents, real GitHub delivery, one periodic/on-demand monitor, typed repair approval, a thin operator/approval/evidence UI, and deterministic evaluation scenarios. Keep Snowflake + dbt as the only real data-platform pair. |
| 10 | Which strategic capabilities can initially be interfaces? | Cross-platform adapters; enterprise catalog/governance integration; specialist role APIs; monitor scheduling; migration and optimization recommendations; external evidence export; graph-store backend; enterprise IAM; production deployment. |
| 11 | Biggest scope-explosion risks? | Treating each role as an autonomous agent, modelling the entire estate ontology, adding vendors to demonstrate “neutrality,” making continuous monitoring a new observability platform, combining diagnose/repair/migrate/optimize in one release, and building enterprise governance/IAM before the single workflow is proven. |
| 12 | Which decisions could cause major rework? | Twin identity/version semantics; provenance and evidence immutability; who owns tool dispatch; verifier trust and write prohibition; repair authorization; workflow occurrence identity; adapter contract granularity; and whether long-lived monitor incidents share the workflow state model. |
| 13 | Does the deterministic orchestrator remain viable? | **Yes.** It is the safest first-MVP control plane. The persisted phase/task model, fencing, reconciliation, and policy routing are more important than agent-framework features. The hard-coded slice composition must be generalized, but the orchestration kernel should remain. |
| 14 | Can PostgreSQL support the first Digital Twin? | **Yes.** Typed asset, relationship, snapshot, observation, incident, and evidence records fit relational tables plus JSONB. Recursive CTEs and indexed adjacency rows are adequate at prototype/MVP scale. |
| 15 | Is a graph database required now? | **No.** Introduce a graph-store port only if measured lineage/path queries at the target estate size cannot meet an agreed latency or operational bound in PostgreSQL. |
| 16 | Is a multi-agent framework required now? | **No.** Typed reasoning capabilities and deterministic sub-workflows provide the required separation without hidden control flow, extra authority, or agent-to-agent text state. |
| 17 | Is Temporal, LangGraph, or another workflow engine required now? | **No.** PostgreSQL-backed durable workflows already cover the first MVP. Re-evaluate Temporal only for multi-node workers, long timers, materially larger concurrency, or demonstrated operational burden. LangGraph is not needed for governed control flow. |
| 18 | Which vendors should be real? | Prototype: Snowflake, dbt Core, PostgreSQL state, and one configurable LLM provider; keep GitHub fake or omit delivery. Revised MVP: add real GitHub. BigQuery, Databricks, Fabric, Airflow/Dagster, Purview/Collibra, BI tools, and graph stores remain deferred; do not build vanity mocks for them. |
| 19 | Can existing Snowflake, dbt, profiling, modelling, policy, recovery, and evaluation work be incorporated cleanly? | Snowflake, dbt, profiling, modelling, policy, and recovery can be incorporated, although dbt still needs canonical Tool Gateway/workflow wiring. Evaluation has a strong documented design but no implemented harness/scenario package yet; it must be added rather than merely wired. |
| 20 | Estimated remaining effort? | Prototype: **76–118 focused engineering hours**. Revised MVP: **86–134 additional hours** after the prototype (**162–252 cumulative**). Showcase-ready hardening: **40–64 additional hours** after MVP (**202–316 cumulative**). These include implementation, deterministic tests, review remediation, and demo evidence, but exclude human wait time and later enterprise expansion. |

### Strategic capability feasibility

| Strategic capability | Feasibility now | First treatment |
|---|---|---|
| Enterprise Data Digital Twin | Feasible with additive contracts | Minimal versioned asset/relationship/observation/evidence model in PostgreSQL |
| Metadata and lineage graph | Feasible | Snowflake metadata + dbt manifest edges; PostgreSQL adjacency queries |
| Supervisor Agent | Feasible if deterministic | Existing orchestrator plus one bounded planning capability |
| Estate Intelligence Agent | Feasible as capability group | Read-only context assembly, selection, profiling, drift assessment |
| Data Engineering Agent | Feasible as capability group | Existing modelling plus dbt generation/execution workflow |
| Reliability Agent | Feasible in one fault path | Deterministic classification plus one bounded repair sub-workflow |
| Independent Verifier | Feasible with trust separation | Read-only deterministic validator over immutable evidence |
| Governed Tool Gateway | Feasible by adapting Tool Registry | One path for validation, policy, approval, dispatch, output validation, audit, and evidence |
| Durable workflows | Already substantially implemented | Extend phase templates; retain PostgreSQL scheduler/recovery |
| Deterministic policy and approvals | Already substantially implemented | Add twin/repair subjects and persist complete gateway decisions |
| Cross-platform adapters | Contract exists | Prove neutrality by contract, not by adding vendors |
| Evidence and evaluation | Partly implemented/documented | Add evidence bundle and one executable scenario |
| Continuous monitoring and bounded repair | Feasible but not as broad prototype scope | One explicit drift check in prototype; one bounded periodic/on-demand monitor in MVP |
| Synthetic enterprise benchmark | Already strong | Reuse Vantara `tiny` v1/v2 as the first benchmark |

## 3. Current architecture summary

The accepted architecture is already close to the strategic direction:

- `docs/ARCHITECTURE.md` defines an “AI Data Engineering control plane,” separates
  reasoning from deterministic execution, and makes capabilities vendor-neutral.
- `docs/CAPABILITY_MODEL.md` and `docs/TOOL_CONTRACTS.md` define versioned typed
  capabilities and a Tool Registry that is intended to be the only route to external
  systems.
- `docs/CONNECTOR_ARCHITECTURE.md` defines real/fake adapters, health, contract-version
  advertisements, immutable call identity, and reconcile-before-retry semantics.
- `docs/STATE_MODEL.md` defines persisted workflow phases and phase-scoped task DAGs.
- `docs/PERMISSION_MODEL.md` defines deterministic deny aggregation, typed approvals,
  bounded repair, and fail-closed routing.
- `docs/AGENT_MODEL.md` deliberately avoids autonomous specialist agents in favour of
  typed reasoning capabilities.
- `docs/EVALUATION_STRATEGY.md` defines deterministic offline scenarios and rejects an
  LLM judge for pass/fail.

The pivot therefore changes the **scope and centre of gravity**, not the fundamental
execution architecture. The centre moves from “generate one pipeline” to “maintain a
versioned view of estate state, decide a governed change, execute it through adapters, and
attach evidence.” The primary new domain boundary is the Digital Twin; the primary product
change is to make every workflow read from and write observations back to that twin.

The potential contradiction is the strategic agent list. If those names imply independent
tool-using loops, the design stops being coherent. If they are named responsibility
boundaries implemented by capabilities and sub-workflows under the deterministic
orchestrator, the design remains coherent and extensible.

## 4. Current implementation maturity

The baseline is a tested **foundation and partial vertical slice**, not a complete MVP.

| Area | Evidence in current `main` | Maturity |
|---|---|---|
| Domain contracts | `src/aide/domain/` contains permissions, principal/grants, states, operation identity, attempts, effects, artifacts, failures, approvals, and costs. | Strong reusable kernel |
| Capability model | `src/aide/capabilities/spec.py`, `registry.py`, `v1_kernel.py`, and `io.py` implement typed contracts and an in-memory registry. | Strong base; catalogue is still centred on the DE002C slice and does not canonically register the implemented dbt surface |
| Tool Registry | `src/aide/tools/registry.py` validates input, evaluates policy, dispatches a handler, and validates output. | Partial; does not itself persist complete policy/tool/evidence records or own approval/recovery orchestration described in architecture |
| Connector Registry | `src/aide/connectors/base/` implements specifications, health, call/recovery context, reconciliation results, and registry checks. | Strong reusable abstraction |
| Orchestration | `src/aide/orchestration/` implements materialization, compatibility, phase coordination, task claims, fencing, cancellation, and recovery. | Strong kernel; product composition remains concentrated in the large, fixed `src/aide/app/slice.py` |
| Persistence | `src/aide/persistence/models.py`, repositories, audit/budget modules, and two Alembic revisions persist workflow, phase, task, attempt, approval, artifact, health, recovery, audit, and budget state. | Strong base; no Digital Twin, telemetry, evaluation, repair-attempt, or monitor domain yet |
| Policy and approvals | `src/aide/policy/`, `src/aide/approvals/`, and `src/aide/domain/approvals.py` implement deterministic decisions and typed matching/routing. | Strong kernel; broader rule hardening and new repair/twin approval subjects remain |
| Authentication and secrets | `src/aide/auth/`, `src/aide/app/sessions.py`, and `src/aide/secrets/` implement local opaque sessions, CSRF, server-derived grants, scoped secret refs/resolvers. | Credible local MVP boundary; enterprise IAM is intentionally absent |
| Snowflake | `src/aide/connectors/snowflake/` contains real/fake adapters, SQL dialect/safety support, RO/DEV isolation, health, query tags, error mapping, drift, and reconciliation. | Substantial and live-validated |
| dbt | `src/aide/connectors/dbt/` contains real/fake adapters, isolated subprocess execution, workspace handling, artifacts, journal, error mapping, and reconciliation. | Substantial connector foundation; generation and canonical workflow/Tool Gateway binding are not implemented |
| Profiling | `src/aide/profiling/` contains budgets, masking, deterministic SQL, profile artifacts, join candidates, and an offline Vantara integration. | Substantial; needs twin-backed generic inputs and observation persistence |
| Modelling | `src/aide/modelling/`, `src/aide/reasoning/propose_model_design.py`, and the design prompt implement deterministic rules, signals, evidence, validators, and a Vantara design. | Substantial; separate generic product logic from benchmark-specific oracle data |
| LLM gateway | `src/aide/llm/gateway.py`, `replay.py`, prompts, and reasoning capabilities provide structured replay. | Test adapter only; no real provider, redaction/accounting pipeline, or production retries |
| Synthetic estate | `synthetic/vantara/` contains deterministic profiles, v1/v2 fixtures, expected outputs, PII map, and PostgreSQL/Snowflake/DuckDB exports. | Strong benchmark foundation |
| Quality | `src/aide/quality/checks.py` validates the DE002C query result. | Early; not the documented Quality Engine |
| Recovery | `src/aide/orchestration/recovery.py`, `worker.py`, cancellation and integration tests cover ambiguous outcomes and stale workers. | Strong reusable kernel |
| Evaluation | `docs/EVALUATION_STRATEGY.md` is detailed, but `src/aide/evaluation/`, `evaluation/`, and `tests/evaluation/` do not exist. | Design only |
| Monitoring, repair, lineage, delivery, observability | Their architecture is documented, but corresponding product packages are absent (dbt can extract manifest lineage internally). | Not implemented as control-plane components |
| API/CLI | `src/aide/api/app.py` and `src/aide/cli/` expose local session, workflow submit, events, connector health, fixture building, and the offline slice. | Thin prototype surface, not an operator control plane |
| Tests and CI | `tests/` has 369 collectable tests across unit, PostgreSQL integration, connector contract, security, offline dbt, profiling and modelling. `.github/workflows/ci.yml` runs lint, strict types, imports, gitleaks, migrations, full/integration pytest, and Docker smoke. | Strong engineering gate; no pivot end-to-end evaluation |

Run reports provide stronger evidence than the backlog status alone:

- `docs/agent/runs/DE002C/DE002C-SESSION-20260912T065651Z-73a1.md` records a completed
  authenticated offline workflow, 145 tests, and 74 PostgreSQL integration tests at that
  milestone.
- `docs/agent/runs/DE005B/DE005B-SESSION-20260914T075329Z.md` records live Snowflake RO/DEV
  validation, while also documenting unrelated local PostgreSQL integration errors.
- `docs/agent/runs/DE007/DE007-R1-FOLLOWUP-SESSION-20260912T210147Z-bc01a0968e.md`
  records 86 modelling tests and a green full CI run for the accepted modelling work.
- `docs/agent/runs/DE008A/DE008A-LIVE-SESSION-20260914T103928Z.md` records real dbt Core
  against Snowflake DEV, artifact capture, reconciliation, failure classification, and
  cleanup. It explicitly leaves Tool Registry wiring to later work.

This evidence supports feasibility, but it does not prove the proposed control-plane
workflow. No executable test currently combines a Digital Twin, dbt generation, policy,
repair, independent verification, and evidence evaluation.

## 5. Reuse assessment

### Method

The reuse estimate is weighted by **implemented responsibility**, not raw lines of code.
Generated fixture volume and long vendor adapters would otherwise distort a lines-of-code
percentage. Each audited subsystem was classified by whether its externally meaningful
contract and tests survive the pivot:

- **mostly unchanged:** contract and implementation remain valid;
- **adapt:** core remains, but inputs, outputs, persistence, or composition change;
- **retire/replace:** product responsibility is superseded or should remain only as a test
  harness.

The 65–80% range reflects uncertainty before the Digital Twin and Tool Gateway contracts
are fixed. A midpoint classification is 40% mostly unchanged, 32% reusable with
adaptation, 8% to retire, and 20% too incomplete or uncertain to credit. The lower bound
assumes more operation/evidence identity changes propagate into the kernel. The upper
bound assumes additive twin/evidence contracts preserve the existing operation, attempt,
connector, and artifact semantics as intended by
`docs/adr/DE-ADR-026-contract-stability.md`.

### Reusable foundation

The highest-value reusable parts are not the demo-specific SQL; they are the safety and
durability mechanisms that a control plane needs:

1. persisted operation and attempt identity;
2. task claims, leases, fencing, and reconcile-before-retry;
3. deterministic policy and typed approvals;
4. transitive artifact provenance and append-only audit;
5. versioned capabilities and connector advertisements;
6. real/fake Snowflake and dbt parity;
7. deterministic profiling/modelling evidence;
8. the Vantara v1/v2 benchmark and CI infrastructure.

These foundations reduce the pivot from “build an autonomous platform” to “add a bounded
estate model and compose one new vertical workflow.”

## 6. Component disposition table

| Classification | Component | Repository evidence | Disposition |
|---|---|---|---|
| KEEP UNCHANGED | Operation/attempt identity, permissions, effects, provenance primitives | `src/aide/domain/identity.py`, `permissions.py`, `effects.py`, `artifacts.py` | Preserve semantics; add references from twin/evidence records |
| KEEP UNCHANGED | Connector base protocol and registry checks | `src/aide/connectors/base/` | Keep vendor-neutral boundary |
| KEEP UNCHANGED | Task fencing, reconciliation and cancellation kernel | `src/aide/orchestration/worker.py`, `recovery.py`, `cancellation.py` | Reuse for all governed side effects |
| KEEP UNCHANGED | Core workflow persistence, audit sequence, budget ledger | `src/aide/persistence/models.py`, `audit.py`, `budget.py` | Add tables; do not rewrite the durable kernel |
| KEEP UNCHANGED | Snowflake adapter internals | `src/aide/connectors/snowflake/` | Use as first real warehouse adapter |
| KEEP UNCHANGED | dbt adapter internals | `src/aide/connectors/dbt/` | Use as first real transformation adapter |
| KEEP UNCHANGED | Scoped secret references/resolvers | `src/aide/secrets/` | Retain separation between connector and LLM scopes |
| KEEP UNCHANGED | Vantara generator and v1/v2 fixtures | `synthetic/vantara/` | Use `tiny` as benchmark; keep `demo/full` outside prototype runs |
| KEEP UNCHANGED | Static analysis, integration-test and CI structure | `pyproject.toml`, `.github/workflows/ci.yml`, `tests/` | Add pivot tests to existing gates |
| KEEP BUT ADAPT | Capability Registry/catalogue | `src/aide/capabilities/` | Add twin, context, verify, evidence, incident and bounded-repair contracts; canonically register dbt capabilities |
| KEEP BUT ADAPT | Tool Registry → governed Tool Gateway | `src/aide/tools/registry.py` | Make it the complete persisted policy/approval/dispatch/validation/audit/evidence boundary |
| KEEP BUT ADAPT | Deterministic orchestrator | `src/aide/orchestration/`, `src/aide/app/slice.py` | Preserve kernel; move fixed slice logic into reusable phase templates/application services |
| KEEP BUT ADAPT | Metadata catalogue | `src/aide/discovery/catalog.py` | Persist normalized, versioned twin assets and observations rather than one isolated catalogue artifact |
| KEEP BUT ADAPT | Persistence | `src/aide/persistence/` | Add minimal twin snapshots, relationships, observations, incidents, verification and evidence references |
| KEEP BUT ADAPT | Policy and approvals | `src/aide/policy/`, `src/aide/approvals/` | Add repair/exception rules and verifier write prohibition; preserve deterministic aggregation |
| KEEP BUT ADAPT | Local auth/grants | `src/aide/auth/`, `src/aide/app/sessions.py` | Keep for MVP; define an external-principal port without implementing enterprise IAM |
| KEEP BUT ADAPT | Profiling and modelling | `src/aide/profiling/`, `src/aide/modelling/` | Read immutable twin snapshots; write observations/design evidence; isolate Vantara-specific oracle logic |
| KEEP BUT ADAPT | LLM gateway and reasoning | `src/aide/llm/`, `src/aide/reasoning/`, `src/aide/prompts/` | Retain replay; add one real provider adapter, accounting, redaction, bounded retries, and role-labelled capabilities |
| KEEP BUT ADAPT | dbt manifest lineage | `src/aide/connectors/dbt/artifacts.py` | Emit twin relationship/evidence records; do not build a separate graph platform |
| REPLACE OR RETIRE | `OfflineSliceService` as product composition | `src/aide/app/slice.py` | Keep as regression fixture temporarily; replace as product entry point with reusable workflow/application services |
| REPLACE OR RETIRE | Replay-only production gateway | `src/aide/llm/gateway.py` | Retain replay adapter; replace production path with a configurable provider protocol |
| REPLACE OR RETIRE | Vantara hard-coded design as product logic | `src/aide/modelling/demo_design.py`, `src/aide/llm/replay.py` | Retain only as benchmark fixture/oracle |
| REPLACE OR RETIRE | Current all-at-once V1 roadmap | `docs/MVP_SCOPE.md`, `docs/IMPLEMENTATION_PLAN.md` | Supersede only after a separate pivot architecture decision; do not implement it in parallel with the pivot |
| ADD | Minimal Enterprise Data Digital Twin | None | Versioned asset, relationship, observation, snapshot and evidence contracts in PostgreSQL |
| ADD | Estate context assembler | None | Deterministic bounded context from a pinned twin snapshot |
| ADD | Supervisor responsibility boundary | Existing orchestration only | A deterministic coordinator plus typed planning capability; not an autonomous agent runtime |
| ADD | Independent Verifier | None | Read-only deterministic verification with separately persisted verdict/evidence |
| ADD | Reliability/repair sub-workflow | Architecture only in `docs/PERMISSION_MODEL.md` | One failure class, one patch type, strict budgets and approval rules |
| ADD | Evidence bundle and one evaluation scenario | Architecture only in `docs/EVALUATION_STRATEGY.md` | Produce machine-readable proof for the prototype acceptance criteria |
| ADD | One monitor check in revised MVP | `register_monitor` is contract-only | On-demand or simple periodic drift/test check; no general monitoring platform |
| DEFER | Graph database | None | Add only after PostgreSQL graph-query evidence fails agreed bounds |
| DEFER | Autonomous multi-agent framework | Explicitly rejected in `docs/AGENT_MODEL.md` | Logical roles remain capabilities/sub-workflows |
| DEFER | Temporal/LangGraph migration | Explicitly deferred/rejected in `docs/adr/DE-ADR-009-custom-orchestration.md` | Re-evaluate from operational evidence, not strategic naming |
| DEFER | Broad vendor support | Future kinds in `docs/CONNECTOR_ARCHITECTURE.md` | Keep interfaces; no BigQuery/Databricks/Fabric/Airflow/catalog/BI implementation |
| DEFER | Enterprise IAM, multi-tenancy and federated governance | `docs/MVP_SCOPE.md` excludes it | External-principal and policy-provider ports only |
| DEFER | Production execution, unrestricted repair, migration and optimization actions | Production is disabled in `docs/PERMISSION_MODEL.md` | Recommendation/evidence interfaces only |

## 7. Gap analysis

### Digital Twin

There is no durable estate model. `MetadataCatalog` is an immutable workflow artifact and
the persistence layer has generic artifacts and connector health, but no canonical asset
identity, relationship history, observation time, source authority, or snapshot semantics.
The first twin must be deliberately small:

- assets: warehouse tables/columns and dbt models/tests;
- relationships: contains, transforms-from, tests, and selected business mapping;
- observations: schema, profile summary, drift, dbt run/test status;
- evidence references: immutable artifacts and operation ids;
- snapshot/version: the exact estate context used by a workflow.

Business glossary, ownership hierarchy, policy taxonomy, data contracts, BI semantics,
infrastructure topology, and complete operational lineage are later extensions.

### Supervisor and roles

The repository has a deterministic orchestrator and replay-backed reasoning capabilities,
but no supervisor domain contract. The gap should be closed by making “Supervisor” the
application-level responsibility that selects a pinned twin snapshot and starts phase
templates. Estate Intelligence, Data Engineering, and Reliability are capability groups
with explicit input/output schemas and permissions. They must not receive their own
unbounded tool loops.

### Tool Gateway

`ToolRegistry.invoke()` is smaller than the architectural promise. It currently validates,
evaluates policy, calls a registered handler, and validates output. The surrounding
`OfflineSliceService` coordinates attempts and persistence. The pivot needs one complete
gateway path so every role receives identical enforcement and evidence. This is adaptation,
not a new agent framework.

### Evidence and verification

Artifacts and audit events exist, but there is no coherent evidence bundle or independent
verdict record. A verifier needs immutable inputs, deterministic checks, explicit coverage,
and no write-capable connector. It may use advisory reasoning to explain a failure, but an
LLM must not decide pass/fail.

### Generation, quality, repair, monitoring and evaluation

- dbt execution exists; generic dbt project generation does not.
- modelling exists; transformation generation and generation validators do not.
- quality is limited to a DE002C query result check.
- repair is documented but has no implementation package or scenario.
- dbt manifest lineage extraction exists inside the connector, but no twin lineage service
  or persisted lineage history exists.
- monitor capabilities are documented/registered only at contract level.
- the evaluation strategy is detailed but no harness/scenario directory exists.

These are the largest remaining functional gaps. They should be implemented only for the
single prototype scenario before being generalized.

### Vendor and identity caveat

The live dbt run report records that the current Snowflake DEV role does not read
`VANTARA_RAW`; the test safely copied source fixtures into a workflow-specific `AIDE_DEV`
schema. The prototype must preserve that least-privilege posture. It must not expand grants
merely to make the demo path easier. The next architecture audit should explicitly choose
between a governed RO-to-DEV handoff and workflow-local source copies.

## 8. Smallest credible prototype

### Prototype statement

Prove that Data Pilot AI can understand one business request using a versioned estate
model, execute one governed Snowflake/dbt change, survive one known failure, verify the
result independently, and produce evidence.

### Fixed scope

**Estate**

- Vantara `tiny` only, with v1 and v2 snapshots;
- Snowflake RO metadata/profiling plus dbt manifest/run artifacts;
- ten selected customer/revenue source assets and only the dbt nodes needed by the request;
- PostgreSQL Digital Twin containing minimal assets, relationships, observations, snapshot
  identity, and evidence references.

**Request**

> Build a customer revenue data product from CRM and billing, deduplicate customers,
> reconcile revenue and payments, and preserve plan history.

Use the existing deterministic modelling rules and one clarification answer fixture. Do
not add general conversational memory or glossary management.

**Governed workflow**

1. Capture Snowflake and dbt metadata into twin snapshot `T1`.
2. Interpret the request and assemble bounded estate context from `T1`.
3. Select relevant assets and produce a constrained model design.
4. Generate only the required dbt staging/intermediate/mart subset.
5. Materialize every operation through the governed Tool Gateway.
6. Run compile/build/tests in an isolated DEV namespace.
7. Inject the v1 → v2 invoice-status schema drift.
8. Classify `SCHEMA_MISMATCH`, create one repair proposal, and apply only an allow-listed
   column-reference patch within a two-attempt task budget.
9. Re-run compile/build/tests.
10. Have the read-only Independent Verifier compare final dbt results, required quality
    assertions, twin snapshot deltas, and operation evidence.
11. Persist an evidence bundle and a final verified/failed verdict.

**Execution modes**

- Required: deterministic offline run using Vantara, fake Snowflake, real dbt Core on
  DuckDB, and replay LLM.
- Required: one real smoke using Snowflake RO and dbt/Snowflake DEV in workflow-scoped
  objects, without production access or new RAW grants.
- Optional only after the two required modes pass: one live LLM run for variance and cost
  measurement.

### Prototype acceptance criteria

1. The twin snapshot contains the expected scoped assets, columns, dbt nodes, lineage edges,
   profile observations, source authority, and artifact references.
2. Every plan records the exact twin snapshot and capability/connector contract snapshot.
3. No role calls a connector outside the Tool Gateway.
4. The injected drift is detected and classified; exactly one bounded repair hypothesis is
   applied; the original artifact remains immutable.
5. dbt compile/build/tests and deterministic revenue/payment assertions pass after repair.
6. The verifier has read-only permissions, cannot dispatch a write capability, and emits a
   verdict from immutable evidence.
7. The evidence bundle links request, twin snapshots, plan, policy decisions, attempts,
   dbt artifacts, failure, repair, validations, and verifier verdict.
8. The same offline scenario is deterministic across repeated runs.

### Explicit prototype limits

No GitHub delivery, staging deploy, frontend, always-on monitor, second business request,
second data vendor, graph database, enterprise catalog, migration, optimization action, or
production credential is needed to pass this gate.

## 9. Revised MVP boundary

The first revised MVP is the hardened version of the prototype, not the complete strategic
document.

### Include

- the minimal Digital Twin with versioned Snowflake assets, dbt resources, lineage,
  profiles, tests, incidents, and evidence;
- one customer-revenue data-product workflow and its schema-drift repair path;
- one additional deterministic quality-failure path for duplicate payments;
- deterministic Supervisor control with Estate Intelligence, Data Engineering, Reliability,
  and Verifier capability groups;
- real Snowflake, dbt Core, PostgreSQL, one real LLM provider, and real GitHub delivery;
- fake/replay equivalents for deterministic CI;
- typed approval for repair when the patch exceeds the prototype's narrow automatic class;
- one on-demand or simple periodic drift/test monitor that opens a bounded incident
  workflow; no general scheduler product;
- thin operator UI: request, pinned estate context, plan, approval, incident/repair, final
  evidence; CLI remains complete;
- deterministic evaluation for happy path, schema drift, duplicate-payment quality
  failure, policy denial, and ambiguous external outcome;
- complete audit/tool/model accounting needed to explain the demonstration.

### MVP extension points only

- `TwinStore`/graph-query port;
- `PrincipalProvider` for external IAM;
- connector kinds for warehouses, transformation, orchestration, catalogs, and BI;
- monitor scheduler port;
- migration and optimization proposal contracts;
- evidence export/signer port;
- specialist sub-workflow interface.

These extension points need contract tests, not vendor implementations.

## 10. Explicit out of scope list

The following are out of scope for both the prototype and first revised MVP unless
explicitly listed in §9:

- complete enterprise estate ingestion;
- BigQuery, Databricks, Fabric, Redshift, Airflow, Dagster, Kafka, Purview, Collibra,
  Unity Catalog, Power BI, Tableau, and Looker adapters;
- a graph database or generalized knowledge graph/ontology;
- multi-agent chat, agent swarms, agent-created tools, or autonomous tool selection;
- Temporal, LangGraph, LangChain, CrewAI, AutoGen, or framework migration;
- microservices, Kubernetes, Kafka, Redis, or a separate vector database;
- production data writes, production deployment, destructive actions, or infrastructure
  and security administration;
- enterprise IAM, multi-tenancy, delegated administration, policy authoring UI, and
  regulatory certification;
- streaming/CDC, ingestion platform, data movement product, and generalized scheduler;
- complete data catalog, marketplace, semantic layer, or BI generation;
- arbitrary code execution or Python/Spark generation;
- broad migration execution, warehouse tuning, cost optimization, and capacity changes;
- unbounded self-healing, test weakening, silent repair, and human-approval bypass;
- cryptographic non-repudiation or tamper-proof evidence ledger;
- full observability platform, incident management product, or 24/7 operations service;
- polished multi-page enterprise UI.

## 11. Architecture decisions requiring later audit

These decisions are deliberately not made by this feasibility assessment:

1. **Twin identity:** stable asset identity across rename, move, connector replacement, and
   source recreation.
2. **Twin time model:** valid time, observed time, snapshot membership, and retention.
3. **Authority/conflict:** precedence when Snowflake, dbt, a catalog, and user assertions
   disagree.
4. **Relationship semantics:** minimum edge types and how inferred, declared, and observed
   edges differ.
5. **Evidence contract:** required hashes, provenance closure, retention, and whether any
   external signing is needed.
6. **Supervisor boundary:** which decisions are deterministic and which are typed reasoning
   proposals.
7. **Verifier independence:** module/process identity, read-only grants, forbidden imports,
   and rules preventing self-attestation by the executor.
8. **Repair authority:** patch classes eligible for automatic application versus typed
   approval, plus rollback/compensation.
9. **Tool Gateway transaction boundary:** ordering and atomicity of policy, approval,
   dispatch intent, audit, telemetry, external correlation, output validation, and twin
   observation.
10. **Long-lived incidents:** whether monitoring opens a new workflow or resumes an existing
    workflow occurrence.
11. **Cross-platform semantics:** smallest generic asset, transformation, lineage, and
    operation contracts that do not collapse to Snowflake/dbt fields.
12. **Workflow-engine triggers:** measured conditions for adopting Temporal or another
    durable engine.
13. **Graph-store triggers:** representative estate sizes, queries, latency targets, and
    operational cost that would justify moving from PostgreSQL.
14. **RAW-to-DEV handoff:** preserve current least privilege without giving the DEV identity
    broad source read access.

Any breaking change to the accepted operation, attempt, approval, provenance, or connector
semantics requires an ADR and architecture review under
`docs/adr/DE-ADR-026-contract-stability.md`.

## 12. Technical risks

| Risk | Likelihood / impact | Control |
|---|---|---|
| Digital Twin becomes a universal ontology | High / High | Fix asset/edge/observation types to the prototype; additions require scenario evidence |
| “Agent” roles acquire independent tool authority | High / Critical | One orchestrator and Tool Gateway; role capabilities are tool-less or receive fixed task inputs |
| Executor verifies its own work | Medium / High | Separate verifier contract, read-only grants, forbidden imports/write capabilities, immutable evidence |
| Tool Gateway remains bypassable through composition code | Medium / Critical | Import rules and integration tests prove all connector dispatch enters one gateway |
| Existing operation identity cannot bind twin/evidence versions | Medium / High | Audit before implementation; prefer additive snapshot/evidence references |
| Snowflake/dbt semantics leak into generic twin contracts | High / High | Keep platform extensions namespaced; require provider-neutral core fields |
| PostgreSQL graph queries are over-generalized too early | Medium / Medium | Implement only required adjacency/path queries; benchmark before adding storage technology |
| Repair changes correct-looking but semantically wrong data | Medium / Critical | One patch class, deterministic reconciliation, immutable before/after evidence, verifier, approval outside class |
| Benchmark-specific logic masquerades as product intelligence | High / High | Keep Vantara expected design/replay in test fixtures; generic production path cannot import benchmark oracle values |
| Real and fake connector evidence diverges | Medium / High | Existing contract parity plus one required live smoke and explicit REAL/MOCK provenance |
| No production LLM gateway or cost telemetry | High / Medium | Add one provider only; structured output, budgets, redaction, replay fallback |
| Monitoring creates an uncontrolled second orchestration system | Medium / High | Monitor emits an observation/incident and starts the same governed workflow |
| Current role/grant documentation differs from live Snowflake reality | Medium / High | Preserve live least privilege; decide RAW-to-DEV handoff before implementation |
| Evaluation remains documentation rather than executable evidence | High / High | Prototype cannot pass without one deterministic end-to-end scenario |

## 13. Scope control rules

1. One business request, one synthetic estate, one warehouse vendor, one transformation
   vendor, and one injected fault in the prototype.
2. Vendor neutrality is proven by contract boundaries and fakes, not by connector count.
3. Every new capability must be required by a prototype acceptance criterion.
4. Every role is a capability group or sub-workflow under the deterministic orchestrator.
5. No role receives unrestricted connector access, dynamic tool creation, or an
   orchestrator-independent loop.
6. The Twin stores observed facts and labelled hypotheses; it does not become a generalized
   enterprise knowledge platform.
7. PostgreSQL remains the only stateful control-plane service until measured evidence
   triggers a storage/workflow change.
8. The first verifier is deterministic and read-only; an LLM can explain but cannot set the
   verdict.
9. Automatic repair is limited to one named failure class and one allow-listed patch shape
   in the prototype. Everything else proposes or blocks.
10. Existing REAL/MOCK provenance and reconcile-before-retry rules are not weakened for
    demo convenience.
11. No new vendor, UI surface, or monitor type enters scope without removing equivalent
    effort or adding a separately approved task.
12. Prototype completion is judged by executable evidence, not by the number of strategic
    components named in code.
13. Architecture extension points are interfaces plus contract tests only; no speculative
    implementations.
14. Production, infrastructure, security, destructive, and broad migration actions remain
    disabled.

## 14. Effort estimate

Estimates are focused engineering hours from the assessed baseline. They include design
details needed for the bounded scope, implementation, deterministic tests, security/static
checks, review remediation, and walkthrough evidence. They exclude human approval wait,
credential provisioning, vendor outages, and all later enterprise expansion.

### Prototype

| Work package | Hours |
|---|---:|
| Focused twin/supervisor/verifier/Tool Gateway contract audit and ADRs | 10–16 |
| Minimal PostgreSQL Twin records and Snowflake/dbt ingestion | 12–20 |
| Supervisor workflow and estate-context composition | 10–16 |
| Constrained dbt generation plus canonical Tool Gateway wiring | 16–24 |
| One drift classifier/repair path and independent verifier | 16–24 |
| Evidence bundle, deterministic scenario, live smoke and hardening | 12–18 |
| **Prototype total** | **76–118** |

### First revised MVP

| Additional work after prototype | Hours |
|---|---:|
| Twin snapshot/lineage/incident hardening and query bounds | 16–24 |
| Duplicate-payment quality path and broader repair approval | 12–20 |
| Real GitHub delivery and evidence linkage | 8–14 |
| One bounded monitor cycle using the same workflow engine | 10–16 |
| Thin operator/approval/evidence UI and complete CLI | 18–28 |
| Policy, audit, model/tool accounting and security hardening | 14–22 |
| Five deterministic evaluation scenarios and reliability hardening | 8–10 |
| **Additional revised MVP total** | **86–134** |
| **Cumulative from current baseline** | **162–252** |

### Showcase-ready version

| Additional work after revised MVP | Hours |
|---|---:|
| UX/demo narrative polish and evidence visualization | 14–22 |
| Repeated offline/live rehearsals, performance and failure hardening | 16–24 |
| Setup documentation, fallback packaging and final security/readiness review | 10–18 |
| **Additional showcase total** | **40–64** |
| **Cumulative from current baseline** | **202–316** |

The estimate intentionally excludes additional data vendors, enterprise governance,
production deployment, generalized migration/optimization, and full continuous operations.

## 15. CONDITIONAL GO decision

**CONDITIONAL GO**

The architecture is feasible, the existing implementation provides a substantial
foundation, and a narrow prototype can be delivered without a broad rewrite. No graph
database, multi-agent framework, or workflow-engine migration is required.

Implementation should not begin until a focused follow-up architecture audit resolves the
four conditions from §1 and records them as accepted additive contracts or ADRs. That audit
must preserve the current deterministic orchestration, operation identity, policy,
approval, provenance, and recovery guarantees unless a reviewed breaking ADR explicitly
justifies otherwise.

## 16. Recommended next action

Run one documentation-only architecture task, provisionally **PIVOT001 — Prototype
Contract Boundary**, with no product implementation. Its output should:

1. define the minimal Twin asset/relationship/observation/snapshot/evidence contracts;
2. define Supervisor and role capability boundaries without autonomous agent runtimes;
3. define the read-only Independent Verifier and repair approval matrix;
4. define the complete Tool Gateway lifecycle and forbidden bypass imports;
5. choose the governed Snowflake RO-to-dbt DEV handoff;
6. update the roadmap to the prototype and revised MVP boundaries in this assessment;
7. provide contract tests and acceptance scenarios to be implemented in later tasks;
8. record graph-store, workflow-engine, multi-agent, and additional-vendor triggers as
   deferred decisions.

After human acceptance of that contract audit, implementation should proceed as small
vertical tasks against the prototype sequence in §8, with one writer for twin contracts,
orchestration, policy, and persistence migrations.
