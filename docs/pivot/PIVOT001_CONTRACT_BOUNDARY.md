# PIVOT001 — Data Pilot AI Interview MVP Contract Boundary

**Task:** PIVOT001
**Status:** IMPLEMENTED — MVP001–MVP004 merged to `main`
**Baseline:** `main` at `31343c6aec3b278f4d5a0cd14687b0e73ae0b206` (pre-MVP contract freeze)
**Architecture verdict:** **GO**

## 1. Decision

PIVOT000's four architecture conditions are resolved. The Data Pilot AI Interview MVP can
be built additively on the accepted deterministic orchestration, PostgreSQL recovery,
policy, Snowflake, dbt, profiling, modelling, and Vantara foundations.

The MVP is one governed closed loop:

```text
inspect Vantara
→ pin a minimal TwinSnapshot
→ assemble bounded context
→ plan one customer-revenue change
→ generate and run dbt in isolated Snowflake DEV objects
→ validate and reconcile
→ inject INVOICE_STATUS → STATUS drift
→ diagnose and apply one allow-listed reference correction
→ revalidate
→ independently verify immutable evidence
→ emit one final evidence report
```

This is narrower than the PIVOT000 revised MVP. It does not include a second failure path,
GitHub delivery, a monitor, a real LLM provider, or an operator UI. Those are extension
points or later product work, not interview acceptance criteria.

## 2. Audited implementation baseline

This section records the **pre-MVP001** Git baseline used to freeze the contract. MVP001
through MVP004 are now merged; the repository README and `docs/INTERVIEW_DEMO.md` describe
the implemented closed loop.

Git history and merged code are authoritative where the old backlog differs.

| Foundation | Current fact | MVP disposition |
|---|---|---|
| Snowflake | DE005A and DE005B provide real/fake RO and DEV connectors, live validation, query tags, namespace enforcement, drift support, and reconciliation. The temporary bootstrap RAW write grant was revoked before PIVOT000. | Preserve. `AIDE_DEV_RW` receives no broad `VANTARA_RAW` access. |
| Profiling | DE006 provides deterministic budgets, masking, SQL templates, profile artifacts, relationship inference, and Vantara integration. | Reuse aggregate profile outputs as twin observations. |
| Modelling | DE007 provides deterministic signal extraction, rule selection, design evidence, and typed proposal validation. | Reuse as the only modelling decision engine. |
| dbt | DE008A provides real/fake dbt Core adapters, isolated workspaces, artifacts, failure mapping, journals, and reconciliation; live dbt on Snowflake DEV passed. Canonical Tool Gateway wiring and general generation remain incomplete. | Preserve adapter contracts; wire them through the gateway in MVP002. |
| Recovery and policy | DE002A–C provide operation/attempt identity, deterministic policy, approvals, PostgreSQL state, fencing, and reconcile-before-retry. | Preserve semantics and extend additively. |
| Vantara | DE004 provides deterministic `tiny`, `demo`, and `full` fixtures with v1/v2 schema drift. | Use `tiny` only. |

At the PIVOT001 freeze, no product implementation combined a Digital Twin, canonical
gateway dispatch, dbt generation, bounded repair, verifier, and evidence report. That was
the remaining vertical slice (MVP001–MVP004), not a reason to replace the kernel. Those
tasks are now merged.

## 3. Locked scope

### 3.1 Required

- Real systems: PostgreSQL 16 control state, Snowflake, and dbt Core.
- Synthetic company: Vantara `tiny`, versions v1 and v2.
- One request: customer and revenue data product from CRM, billing, payments, and plans.
- One development target: workflow-scoped objects under `AIDE_DEV`.
- One deterministic modelling path using the existing DE007 engine.
- One injected drift: `BILLING.INVOICES.INVOICE_STATUS` becomes `STATUS`.
- One automatic repair class: an allow-listed column-reference correction.
- One deterministic, read-only verification pass over immutable evidence.
- One machine-readable evidence bundle and one human-readable final report.
- Deterministic offline execution plus one credentialed Snowflake/dbt DEV smoke.

### 3.2 Explicitly excluded

Databricks, Fabric, Airflow, Power BI, Tableau, graph databases, Temporal, LangGraph,
multi-agent frameworks, enterprise IAM, production writes, staging deployment, GitHub
delivery, migration and optimization engines, streaming, generalized monitoring, a large
frontend, a second business use case, and any second automated repair class.

Extension points may be documented as ports or versioned capability kinds. They receive no
implementation, vendor adapter, migration, UI, or acceptance burden in MVP001–MVP004.

## 4. Decision registry

| ID | Locked decision | Accepted contracts affected |
|---|---|---|
| C-01 | Store the minimal Digital Twin in PostgreSQL using exactly five core entity contracts. | Additive to DE-ADR-012 and DE-ADR-026. |
| C-02 | Pin one immutable `TwinSnapshot` per workflow and assemble bounded, authorized context from it. | Additive to DE-ADR-011 and DE-ADR-015. |
| C-03 | Make Supervisor a deterministic application responsibility; role names are capability groups, not agents. | Narrows DE-ADR-009 and DE-ADR-010 without changing them. |
| C-04 | Make the Independent Verifier read-only; deterministic checks alone produce pass/fail. | Additive to DE-ADR-019. |
| C-05 | Evolve Tool Registry into the sole Governed Tool Gateway for every connector execution. | Strengthens DE-ADR-013 without changing operation/recovery semantics. |
| C-06 | Permit exactly one automatic repair application for one allow-listed schema-drift reference correction. | MVP restriction within DE-ADR-023's broader upper bounds. |
| C-07 | Use a manifest-mediated dual load for the Vantara RAW-to-DEV handoff; do not broaden DEV grants. | Corrects the active MVP permission description; preserves DE-ADR-014/015. |
| C-08 | Finalize one immutable evidence bundle with the minimum required evidence classes. | Additive to DE-ADR-018 and DE-ADR-019. |
| C-09 | Replace the old active implementation roadmap with MVP001 → MVP004 while retaining completed DE history. | Supersedes DE-ADR-021's active sequencing; recorded by DE-ADR-028. |
| C-10 | Require executable tests for every decision in this registry. | Narrows the acceptance gate; no runtime contract change. |

Only C-09 changes an accepted architectural contract. DE-ADR-028 records that roadmap and
scope supersession. C-01 through C-08 and C-10 are compatible restrictions or additive
contracts under DE-ADR-026.

## 5. Minimal Enterprise Data Digital Twin (C-01)

### 5.1 Core entities

The core is provider-neutral. Snowflake and dbt details live in versioned extension
payloads. All records are append-only after publication; corrections create a new version
or observation.

```text
TwinAsset
  asset_id: UUID                         # stable internal identity
  asset_version: positive integer        # monotonic per asset
  kind: DATASET | FIELD | TRANSFORMATION | TEST
  source_authority: SourceAuthorityRef
  environment: DEVELOPMENT
  native_key: string                     # authority-scoped stable key when available
  canonical_locator: tuple[string, ...]  # current provider locator
  parent_asset_id: UUID | null
  platform_type: string                  # e.g. snowflake.table, dbt.model
  attributes: versioned JSON object
  first_observed_at, observed_at: timestamp
  evidence_ref_id: UUID

TwinRelationship
  relationship_id: UUID
  relationship_version: positive integer
  kind: CONTAINS | TRANSFORMS_FROM | TESTS | MATERIALIZED_FROM
  from_asset_id, to_asset_id: UUID
  source_authority: SourceAuthorityRef
  environment: DEVELOPMENT
  confidence: 1.0 for declared facts; [0, 1) for labelled inference
  attributes: versioned JSON object
  observed_at: timestamp
  evidence_ref_id: UUID

TwinObservation
  observation_id: UUID
  subject_asset_id: UUID
  kind: SCHEMA | PROFILE_SUMMARY | FRESHNESS | EXECUTION_RESULT | TEST_RESULT | DRIFT
  source_authority: SourceAuthorityRef
  environment: DEVELOPMENT
  value: versioned JSON object
  observed_at: timestamp
  effective_at: timestamp | null
  fresh_until: timestamp | null
  confidence: [0, 1]
  evidence_ref_id: UUID

TwinSnapshot
  twin_snapshot_id: UUID
  schema_version: positive integer
  environment: DEVELOPMENT
  captured_at: timestamp
  capture_cutoff: timestamp
  asset_versions: sorted tuple[(asset_id, asset_version)]
  relationship_versions: sorted tuple[(relationship_id, relationship_version)]
  observation_ids: sorted tuple[UUID]
  evidence_reference_ids: sorted tuple[UUID]
  source_authorities: sorted tuple[SourceAuthorityRef]
  manifest_sha256: 64-lowercase-hex

EvidenceReference
  evidence_ref_id: UUID
  evidence_type: string
  artifact_id: UUID | null
  immutable_uri: string | null
  media_type: string
  sha256: 64-lowercase-hex
  size_bytes: non-negative integer
  execution_mode: REAL | MOCK
  source_authority: SourceAuthorityRef
  producer_operation_key: string | null
  producer_attempt_id: UUID | null
  created_at: timestamp
```

`SourceAuthorityRef` identifies the configured authority, its contract version, and its
scope. It is not a claim that one vendor is globally authoritative.

### 5.2 Stable identity and versioning

1. The store first matches `(source_authority, environment, kind, native_key)` when the
   source supplies a stable native key.
2. Otherwise it matches
   `(source_authority, environment, kind, canonical_locator, incarnation)`.
3. A repeated capture of the same object preserves `asset_id`; any changed fields create
   the next `asset_version`.
4. A rename preserves `asset_id` only when authoritative rename evidence or a declared
   dbt identity proves continuity. A heuristic candidate is an observation, never identity
   proof.
5. Drop and recreate at the same locator creates a new incarnation and `asset_id` when
   continuity cannot be proven. The system must not guess.
6. A snapshot names exact versions. Updating an asset never mutates a prior snapshot.

### 5.3 Provenance, authority, freshness, and environment

- Snowflake metadata is authoritative for physical schemas and columns.
- dbt `manifest.json` is authoritative for transformation/test definitions and declared
  lineage.
- dbt `run_results.json` and gateway results are authoritative for that invocation's
  execution/test outcome.
- DE006 profiling is authoritative only for its computed profile at its stated observation
  time and input digest.
- Inferred relationships and LLM outputs are labelled hypotheses. They cannot override a
  declared or directly observed fact.
- Conflicting authoritative observations coexist. Context assembly blocks when a required
  fact has an unresolved conflict; it never silently selects the newest record.
- Freshness is evaluated at snapshot pin time from the observation kind's configured
  policy. An expired required observation blocks planning or triggers a deterministic
  refresh before a new snapshot is pinned.
- All MVP twin records are `DEVELOPMENT`. Cross-environment snapshots and joins are invalid.
- `REAL` and `MOCK` evidence may not be mixed in a live-verification verdict.

PostgreSQL tables and indexed adjacency rows are sufficient. No graph query API or graph
store abstraction is required for this use case.

## 6. Pinned context assembly (C-02)

The Supervisor pins a complete `TwinSnapshot` before planning. It also pins the existing
capability/connector contract snapshot. A workflow never follows a mutable “latest”
pointer after that point.

Context assembly is deterministic around one typed relevance proposal:

1. Intersect snapshot membership with the trusted principal's server-derived grants,
   connector scope, and `DEVELOPMENT` environment.
2. Build deterministic candidates from request terms, asset names, declared lineage, and
   existing profile summaries.
3. Optionally invoke `select_relevant_assets` with candidate summaries and IDs only.
4. Reject any proposed ID outside the eligible candidate set.
5. Expand only `CONTAINS`, `TRANSFORMS_FROM`, and `TESTS` relationships, at most two hops.
6. Sort by stable identity and build a canonical `EstateContext`; record its SHA-256.
7. Validate freshness, authority conflicts, completeness, and bounds before planning.

Hard default bounds for the interview scenario:

| Item | Limit |
|---|---:|
| Top-level datasets and transformations | 12 |
| Fields | 120 |
| Relationships | 64 |
| Observations | 32 |
| Relationship depth | 2 |
| Canonical serialized context | 64 KiB |

The MVP context contains no source rows or unmasked samples. If required context does not
fit, assembly returns `CONTEXT_BOUND_EXCEEDED` and the workflow blocks; it does not silently
truncate mandatory evidence. Every downstream plan, model design, repair, and verifier
input records both `twin_snapshot_id` and `estate_context_sha256`.

## 7. Deterministic Supervisor and capability groups (C-03)

Supervisor is an application service responsibility over the accepted orchestrator. It:

- authenticates the request and obtains server-authorized grants;
- pins the twin and capability/connector snapshots;
- invokes context assembly;
- materializes phase templates and typed reasoning tasks;
- owns policy, risk, approval, retry, repair, and budget counters;
- dispatches every connector operation through the Governed Tool Gateway;
- advances state only from persisted typed results;
- requests independent verification and finalizes the evidence report.

It does not plan in prose, choose tools dynamically, or run an autonomous loop.

Logical capability groups organize ownership; they are not principals, processes, agents,
or tool authorities:

| Group | Permitted responsibilities | Prohibited |
|---|---|---|
| Estate Intelligence | Capture scoped Snowflake/dbt facts, profile, detect drift, propose relevant asset IDs. | Writes to external systems; unbounded estate traversal; direct connector access. |
| Data Engineering | Interpret the one request, consume DE007 modelling decisions, propose/generate bounded dbt artifacts, request DEV execution. | Selecting vendor SDK calls; changing policy/tests; production or staging actions. |
| Reliability | Classify failure, assemble failure evidence, propose the one repair, request deterministic revalidation. | Applying an unvalidated patch; recursive repair; changing repair limits. |

Reasoning capabilities remain typed, tool-less functions. They receive a bounded context,
return a proposal, and cannot call one another, mutate workflow state, or access connector
objects.

## 8. Independent Verifier (C-04)

The verifier evaluates:

- the pinned `TwinSnapshot` and `EstateContext` digest;
- the request and deterministic plan;
- risk and policy decisions;
- gateway dispatch intents, results, and reconciliation;
- dbt manifest, compiled SQL, and run results;
- deterministic quality and revenue/payment reconciliation results;
- original failure, before/after code hashes, repair validation, and final validation.

Trust boundary:

1. Verification runs in a read-only database transaction over finalized records.
2. The verifier module has no Tool Gateway, connector registry, vendor adapter, approval,
   workflow mutation, or repair writer dependency.
3. The verifier cannot dispatch any capability, including nominally read-only connectors.
4. It returns a typed result. A separate append-only evidence writer persists that result;
   the verifier cannot alter evidence it evaluated.
5. Optional LLM explanation runs only after deterministic checks and is stored as
   `advisory_explanation`. It cannot change any check or verdict.

`VerifierResult.verdict` is exactly `PASS` or `FAIL`. Missing, stale, digest-mismatched,
mixed-provenance, unapproved, unreconciled, or out-of-scope evidence deterministically
fails. The result includes stable reason codes and the complete check list.

## 9. Governed Tool Gateway (C-05)

The existing Tool Registry evolves conceptually into one application boundary. It retains
the accepted operation identity, attempt identity, fencing, and reconcile-before-retry
contracts.

Every connector call, including reads, dbt commands, cancellation, and reconciliation,
follows this lifecycle:

```text
1. validate request
2. resolve trusted principal, operation, capability, connector, version, and target identity
3. evaluate all policy rules
4. persist deterministic risk decision
5. bind and verify typed approval when required
6. transactionally record dispatch intent, attempt, fence, and audit event
7. execute connector outside the database transaction
8. validate and canonicalize result
9. reconcile every ambiguous side effect before any retry
10. persist result and immutable evidence references
11. append resulting twin observations
12. append audit completion and expose the typed outcome
```

Steps 6, 10, 11, and their audit events use existing transactional application-state
guarantees where they share PostgreSQL state. External execution is never held inside a
database transaction. A crash after dispatch resumes at reconciliation, not execution.

No connector execution may bypass the gateway. Future import-linter contracts must prevent
application services, orchestration, capability groups, repair, and verification from
importing vendor execution classes. Only connector registration/composition and the
gateway binding may hold connector instances. Direct adapter tests remain allowed.

The gateway returns only typed outcomes and evidence references. It never returns a mutable
vendor client to its caller.

## 10. Repair boundary (C-06)

The only automatically applicable repair is:

```text
failure class: SCHEMA_MISMATCH
asset: VANTARA_RAW.BILLING.INVOICES
allowed mapping: INVOICE_STATUS → STATUS
change: one column-reference replacement in one generated dbt SQL model
target: workflow-scoped development artifact only
```

Automatic application requires every condition:

- a fresh authoritative drift observation proves the old field is absent and the new field
  is present;
- the configured allow-list contains the exact source asset and old/new pair;
- normalized old/new physical types are equal;
- the pre-image artifact hash matches the repair proposal;
- the parsed diff changes only that field reference;
- no model grain, join, filter, grouping, materialization, macro, YAML, test, permission,
  target, or source data changes;
- compile and static validators pass before execution;
- the original artifact and failure evidence remain immutable.

Limits:

| Counter | MVP limit |
|---|---:|
| Connector attempts per retryable operation | Existing capability value, at most 2 for this workflow; ambiguous side effects reconcile first |
| Repair proposals for the failure | 2 |
| Automatically applied repairs per task | 1 |
| Automatically applied repairs per workflow | 1 |
| Post-repair full revalidation runs | 1 |
| Recursive repairs | 0 |

An invalid second proposal, failed revalidation, unknown outcome, different failure class,
second drift, or any broader diff transitions the workflow to `BLOCKED`. The system may
persist an advisory repair proposal for human review, but the interview workflow cannot
apply it. Tests cannot be removed, weakened, skipped, or have thresholds relaxed.

## 11. RAW-to-DEV handoff (C-07)

The prototype uses a **manifest-mediated dual load**, matching the already validated
DE008A posture:

1. The deterministic Vantara `tiny` export and manifest are immutable, hashed benchmark
   inputs.
2. Environment setup loads that export into `VANTARA_RAW` for RO inspection.
3. A typed gateway operation loads the same pinned export into a workflow-scoped
   `AIDE_DEV` source namespace using the DEV identity.
4. The handoff evidence records fixture digest, selected tables, target namespace, schema
   hashes, row counts, load result, and reconciliation result.
5. The verifier proves that RAW observations and DEV source observations match the pinned
   manifest for the selected tables before accepting transformation results.

This is a synthetic-benchmark handoff, not a general ingestion or replication feature.
Runtime dbt reads the workflow-local DEV sources. `AIDE_DEV_RW` keeps no `SELECT`,
`CREATE`, or write grant on `VANTARA_RAW`; `snowflake_ro` remains the only product identity
that reads RAW. A stored procedure, share, secure-view estate, or data-movement engine is
not introduced for the interview.

## 12. Minimum evidence bundle (C-08)

`EvidenceBundle` is a versioned immutable manifest of references, not a copy of mutable
logs. Finalization canonicalizes the manifest, computes its SHA-256, and prevents update or
deletion through the runtime writer.

Required sections:

1. request and clarification fixture;
2. `TwinSnapshot` and `EstateContext` digests;
3. deterministic plan and pinned capability/connector snapshot;
4. policy and risk decisions;
5. tool dispatch intents, attempts, results, and reconciliation;
6. generated model/code before and after repair, with hashes;
7. dbt compile/build/test artifacts;
8. deterministic quality and revenue/payment reconciliation;
9. injected failure and drift observation;
10. repair proposal, validation, diff, and application result;
11. final validation;
12. deterministic verifier result and optional advisory explanation;
13. cost and timing metadata: wall time, per-step duration, Snowflake query timing and
    measured/estimated flag, dbt timing, model tokens/cost when present, retry and repair
    counts.

Every reference carries REAL/MOCK provenance and a digest. Live verdicts require a complete
REAL execution chain for Snowflake/dbt/tool evidence. A missing required section makes the
bundle incomplete and the verifier returns `FAIL`.

The final report renders this same manifest; it does not invent additional status.
Cryptographic signing, external evidence export, and tamper-proof storage are deferred.

## 13. Active implementation sequence (C-09)

```text
PIVOT001 accepted
        │
        ▼
MVP001 Digital Twin
        │
        ▼
MVP002 Supervisor and Tool Gateway flow
        │
        ▼
MVP003 Repair and Verifier
        │
        ▼
MVP004 End-to-end benchmark and demo hardening
```

| Task | Scope and executable exit | High-conflict ownership | Effort |
|---|---|---|---:|
| MVP001 Digital Twin | Add the five contracts, PostgreSQL persistence/migration, Snowflake/dbt capture, snapshot pinning, bounded context assembly, and authority/freshness tests. | Sole writer for `domain`, twin package, persistence models/migration, and twin contract tests. | 14–22 h |
| MVP002 Supervisor and Tool Gateway flow | Add deterministic application composition, canonical gateway lifecycle, bounded dbt generation, manifest-mediated DEV preparation, pre-drift build, validation/reconciliation, and bypass tests. | After MVP001 merges; sole writer for `app`, `orchestration`, `tools`, capability registry, generation, and relevant import contracts. | 20–30 h |
| MVP003 Repair and Verifier | Add the exact drift injection, classifier path, allow-listed AST patch, limits, full revalidation, read-only verifier, evidence bundle, and negative security tests. | After MVP002 merges; sole writer for repair, verification, evidence, policy additions, and their persistence additions. | 18–28 h |
| MVP004 End-to-end benchmark and demo hardening | Add one deterministic offline scenario, repeatability gate, one live Snowflake/dbt DEV smoke, CLI/demo script, final report rendering, and truthful limitations. | After MVP003 merges; sole integration writer. No architecture, migration, or core contract redesign. | 14–22 h |
| **Total** | Focused implementation, tests, live smoke, and remediation; excludes human review waits and deferred features. | Sequential critical path. | **66–102 h** |

Completed DE002A–DE008A work remains historical foundation. Unstarted DE009–DE019 tasks are
not active prerequisites; their broader scopes move to the deferred backlog and may be
re-cut only after MVP004 evidence.

### Parallelization plan

MVP001 through MVP004 do not run concurrently. Each consumes and tests the contract or
composition created by its predecessor, and MVP001–MVP003 own shared high-conflict
domain, persistence, orchestration, tool, policy, or evidence boundaries.

Within one task, one writer owns the implementation branch. Read-only review, test
analysis, or fixture verification may run concurrently. After MVP003 merges, MVP004 may
split credential-free offline benchmark analysis from a human-controlled live smoke only
when they use distinct task IDs/branches, do not edit the same files, and integrate the
offline branch first. The default remains one implementation writer.

## 14. Executable acceptance contract (C-10)

Every decision has at least one required executable test. Exact test paths may follow the
repository convention, but the named behavior may not be weakened.

| Test ID | Decision | Required executable assertion |
|---|---|---|
| AT-01 | C-01 | Repeated capture preserves `asset_id`; changed facts increment version; prior versions remain immutable. |
| AT-02 | C-01 | Unproven rename/recreation creates a new identity; authoritative rename evidence preserves identity. |
| AT-03 | C-01 | Snapshot digest is stable under input ordering and changes for any member/version change. |
| AT-04 | C-01, C-02 | Authority conflict, stale required observation, mixed environment, or REAL/MOCK contamination blocks context or live verification. |
| AT-05 | C-02 | One workflow pins one snapshot; later captures cannot change its context or plan digest. |
| AT-06 | C-02 | Asset IDs outside grants/scope and reasoner-invented IDs are rejected; bound overflow blocks without silent truncation. |
| AT-07 | C-02 | Repeated assembly from identical inputs yields byte-identical canonical context and digest. |
| AT-08 | C-03 | Capability groups cannot mutate workflow state or receive connector/tool handles; only Supervisor advances phases. |
| AT-09 | C-03 | The fixed customer-revenue request produces a deterministic valid phase sequence using the existing modelling decision. |
| AT-10 | C-04 | Import/security test proves verifier cannot import or obtain gateway, connector, workflow mutation, approval, or repair writers. |
| AT-11 | C-04 | Missing, stale, digest-mismatched, unreconciled, or out-of-scope evidence produces deterministic `FAIL`; complete evidence produces `PASS`. |
| AT-12 | C-04 | Changing advisory LLM text cannot change deterministic checks or verdict. |
| AT-13 | C-05 | Spy connectors prove every execute/cancel/reconcile call has a persisted gateway dispatch intent and audit/evidence trail. |
| AT-14 | C-05 | Crash-after-effect and response-loss paths reconcile before retry; stale claim results cannot persist evidence or observations. |
| AT-15 | C-05 | Import-linter and integration tests reject connector dispatch from application, orchestration, repair, and verification modules. |
| AT-16 | C-06 | The exact `INVOICE_STATUS` → `STATUS` reference-only patch applies once and preserves all unrelated parsed SQL and test artifacts. |
| AT-17 | C-06 | Different mapping/type, second patch, broader AST diff, test weakening, failed revalidation, or recursive repair blocks with no second application. |
| AT-18 | C-07 | Live grant probe proves DEV cannot read or write RAW; RO cannot write; transformations read only the workflow DEV namespace. |
| AT-19 | C-07 | RAW and DEV selected-table schema/row evidence reconcile to the same pinned fixture manifest digest. |
| AT-20 | C-08 | Bundle schema rejects each missing required section; canonical bundle digest is stable; referenced artifact digest mismatch fails. |
| AT-21 | C-08 | Cost/timing metadata records measured versus estimated values without affecting correctness verdict. |
| AT-22 | C-09 | Roadmap contract check asserts only MVP001–MVP004 are active and dependency edges are acyclic and sequential. |
| AT-23 | C-10 | Offline end-to-end scenario runs twice with identical plan, context, repair, validation, verifier, and evidence digests. |
| AT-24 | C-10 | Credentialed smoke proves inspect → DEV build → drift → repair → verifier report with no production/staging action or new RAW grant. |

MVP004 passes only when AT-01 through AT-24 pass at the appropriate level, documentation
validation passes, gitleaks reports no leaks, and the final evidence report identifies
limitations honestly.

## 15. Final scope review

- The contract is smaller than the PIVOT000 revised MVP: no duplicate-payment repair,
  GitHub, monitor, UI, or real-LLM requirement.
- No speculative enterprise feature enters MVP001–MVP004.
- Existing Snowflake, dbt, profiling, modelling, policy, recovery, and Vantara work is
  preserved.
- Each task has a runnable exit and can merge before the next begins.
- Shared domain, persistence, orchestration, gateway, policy, repair, verification, and
  integration areas have one sequential owner.
- PostgreSQL remains the only control-plane state store.
- Snowflake and dbt Core remain the only real data-platform integrations.
- Production, staging, infrastructure, security, and destructive actions remain disabled.
