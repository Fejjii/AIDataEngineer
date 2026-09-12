# Implementation Plan

**Task:** DE 001 (corrected by DE 001R1, DE 001R2A and DE 001R2B) · **Status:** ACCEPTED · ADRs: DE-ADR-020, DE-ADR-021, DE-ADR-026

Contents: §1 repository layout and ownership · §2 module boundaries · §3 roadmap as
vertical slices · §4 parallel lanes and when Cloud agents become safe · §5 DE 002 exact
definition.

---

## 1. Repository layout

```text
AIDataEngineer/
├── .ai/                          # governance (tracked *.md; private/ local/ ignored)
├── .cursor/rules/
├── .github/workflows/            # CI
├── docs/                         # architecture (this set), adr/
├── pyproject.toml  uv.lock  .python-version
├── Dockerfile  docker-compose.yml  Makefile
├── .env.example
├── src/aide/
│   ├── api/                      # FastAPI app, routers, DTOs, SSE, auth  (thin)
│   ├── app/                      # application services / use cases, unit of work
│   ├── domain/                   # core typed models: Workflow, Task, Artifact, RequirementSpec,
│   │                             #   Plan, ModelDesign, ValidationReport, FailureClass, enums
│   ├── orchestration/            # orchestrator, transition table, phase templates, scheduler,
│   │                             #   worker loop, placeholder resolution
│   ├── capabilities/             # CapabilitySpec, registry, decorators, shared I/O schemas
│   ├── tools/                    # Tool Registry wrapper: validation → policy → execute → validate → audit
│   ├── reasoning/                # LLM-backed capabilities: context assemblers, output schemas, validators
│   ├── llm/                      # LLM Gateway: providers, structured output, prompt loader, cost, fake
│   ├── prompts/                  # versioned prompt templates  <capability>/<vN>.md.j2
│   ├── connectors/
│   │   ├── base/                 # Connector protocol, ConnectorSpec, @implements, status, contract test kit
│   │   ├── snowflake/  dbt/  github/  postgres/   # each: real.py fake.py errors.py config.py [dialect.py] README.md
│   │   └── registry_entries.py
│   ├── policy/                   # PolicyEngine rules and SQL/Git classifiers; imports domain PermissionLevel
│   ├── approvals/                # Approval Engine
│   ├── discovery/                # metadata catalogue building
│   ├── profiling/                # profile SQL templates, relationship inference
│   ├── modelling/                # signals, rule table, ArchitectureDecision, design validators
│   ├── generation/               # dbt file templates, project conventions, generation validators
│   ├── quality/                  # Quality Engine checks, report
│   ├── execution/                # Execution Engine, resource caps, environment binding
│   ├── repair/                   # Failure Classifier, Repair Engine
│   ├── artifacts/                # Artifact Manager, blob store interface
│   ├── delivery/                 # Git/PR/deploy chain
│   ├── lineage/                  # manifest + sqlglot lineage
│   ├── persistence/              # SQLAlchemy models, repositories, alembic/
│   ├── observability/            # structlog config, redaction, OTel, telemetry writers, metrics
│   ├── audit/                    # audit event writer/reader
│   ├── evaluation/               # harness, scorers, report
│   ├── secrets/                  # SecretRef, SecretProvider (env), redaction registry
│   ├── config/                   # Settings tree, connectors.yaml loader, permissions/*.yaml
│   └── cli/                      # Typer commands
├── frontend/                     # Vite + React + TS SPA
├── synthetic/vantara/            # generator, fixtures (v1, v2), expected/, pii_columns.yaml, loaders
├── dbt/vantara_project/          # dbt project skeleton the platform writes into (profiles generated)
├── evaluation/                   # scenarios/*.yaml, baselines/, fixtures/llm/<scenario>/
├── tests/
│   ├── unit/                     # mirrors src/aide
│   ├── integration/              # PostgreSQL-backed, fake connectors
│   ├── connectors/contract/      # parametrized fake/real
│   ├── evaluation/               # offline scenarios (E2)
│   └── security/                 # redaction, leakage, classifier properties, injection corpus
├── infra/                        # compose profiles, optional otel collector config
└── scripts/                      # dev bootstrap, verify-environment, demo helpers
```

### 1.1 Ownership (who may edit; one writer at a time)

| Path | Owner class | Conflict level |
|---|---|---|
| `docs/`, `.ai/`, `.cursor/rules/` | architecture / governance tasks | HIGH — one writer |
| `src/aide/domain/`, `capabilities/`, `tools/` | core contracts; breaking changes need ADR + architecture review, additive changes allowed (§5.2) | HIGH — one writer |
| `src/aide/orchestration/`, `persistence/alembic/` | orchestration & migrations | HIGH — one writer |
| `src/aide/policy/`, `approvals/`, `secrets/` | security boundary | HIGH — one writer; Fable review |
| `src/aide/connectors/<vendor>/` | connector tasks | LOW — parallel per vendor |
| `src/aide/{discovery,profiling,modelling,generation,quality,repair,lineage,delivery}/` | feature slices | MEDIUM — parallel across different directories |
| `src/aide/reasoning/`, `prompts/` | reasoning capabilities | MEDIUM — per capability file |
| `src/aide/llm/`, `observability/`, `audit/` | platform services | MEDIUM |
| `src/aide/api/`, `app/` | thin layers; additive endpoints | MEDIUM — parallel if new files |
| `frontend/` | UI task | LOW relative to backend |
| `synthetic/`, `evaluation/`, `dbt/` | data/eval tasks | LOW |
| `tests/**` | follows owning module | same as module |
| `.github/workflows/`, `Dockerfile`, `pyproject.toml` | CI/tooling tasks | HIGH — one writer |

---

## 2. Module boundaries (enforced by `import-linter`)

The package DAG is bottom-up; an arrow means "may import":

```text
api, cli
  → app, evaluation
    → orchestration
      → tools, approvals, artifacts services, persistence ports
        → policy, capability registry, connector registry, reasoning bindings
          → capabilities, connectors.base, llm contracts, audit/observability ports,
            secrets contracts
              → domain
```

Vendor connectors, LLM provider adapters and PostgreSQL/audit/observability
implementations are side adapters: they depend only on the contracts below their consumer
and are wired in the composition root. They are never imported by domain or orchestration.

| Contract | Enforced rule |
|---|---|
| Domain bottom | `aide.domain` imports only stdlib + Pydantic; no project package |
| Contract layer | `aide.capabilities` and `aide.connectors.base` may import domain; neither imports policy, tools, orchestration or vendor adapters |
| Policy | may import domain, capabilities and connectors.base health/spec types; never tools, orchestration, LLM or vendors |
| Adapter isolation | vendor connectors import domain/contracts plus their scoped secret resolver; LLM providers import llm/domain contracts plus their separate scoped resolver |
| Tools | may import contract registries, policy, audit/observability ports and implementation bindings; no package below tools imports tools |
| Orchestration | may import domain, tools and persistence ports; never vendor connectors or LLM providers |
| Persistence | repository ports use domain; PostgreSQL implementations import domain/ports only; domain never imports persistence |
| API thinness | API imports app/auth DTOs only; it never imports persistence, connectors, tools or LLM |

Import-linter contracts assert each forbidden edge directly and a test imports every module
to detect composition-root cycles.

---

## 3. Roadmap — vertical slices

Common fields: **Env** LOCAL/CLOUD · **Cloud** eligibility · **Model** class · **Reasoning** · **Branch** · **Deps** · **Files** (expected) · **Own** (ownership class) · **Par** (parallel eligibility) · **Tests** · **DoD** · **Risk** · **Dur** (agent hours) · **Tok** (S/M/L/XL) · **Gate** (human) · **Git** authority.

Git authority for all implementation tasks: *branch-only; commit + push on the task branch
and open one PR when the task prompt says `GitWrite: authorized`; never merge.*

### DE 002A — Contract kernel and executable CI gate
See §5.1. Establish only the bottom-layer contracts, trusted principal/grants, policy
aggregation, typed approvals, SQL classifier, connector version declarations, artifact
provenance and import boundaries. Add minimal GitHub CI immediately for ruff, mypy,
unit/property tests and import-linter. No database scheduler or vertical slice.
Env CLOUD · Cloud yes · Model GPT 5.6 Sol or Grok 4.6 · Reasoning High · Branch
`feat/DE002A_contract_kernel` · Deps DE 001 accepted · Gate PR review · Risk H.

### DE 002B — Persistence, phase-run serialization and recovery primitives
See §5.2. PostgreSQL models/migrations and deterministic scheduler/recovery/cancellation
kernel with fake side effects; no planner/LLM or end-to-end product flow.
Env CLOUD · Cloud yes · Model GPT 5.6 Sol · Reasoning High · Branch
`feat/DE002B_recovery_kernel` · Deps DE 002A merged · Gate PR review · Risk H.

### DE 002C — First executable offline safe-SQL slice
See §5.3. Compose the accepted kernels into the bounded request → discovery planning
boundary → safe SQL → DEV fake execution → validation flow.
Env CLOUD · Cloud yes · Model Grok 4.6 · Reasoning High · Branch
`feat/DE002C_safe_sql_slice` · Deps DE 002B merged · Gate PR review · Risk M.

### DE 003 — Docker and CI expansion
Goal: PostgreSQL integration service, gitleaks, Docker build, pre-commit,
`scripts/verify-environment.sh`, artifact publishing and full DE 002B/C integration suite.
The executable unit/static CI gate already exists from DE 002A.
Env CLOUD · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch
`ops/DE003_ci_docker` · Deps DE 002C · Files `.github/workflows/*`, `Dockerfile`,
`docker-compose.yml`, `Makefile`, `.pre-commit-config.yaml`, `scripts/` · Own HIGH (CI) ·
Par no · Gate PR review and human branch-protection configuration · Risk L.

### DE 004 — Synthetic enterprise generator and fixtures
Goal: `synthetic/vantara` generator (seeded), PostgreSQL DDL/load, DuckDB fixture builder for fakes (v1/v2 states), `expected/*.json`, `pii_columns.yaml`, Snowflake loader script (not executed in Cloud).
**Prerequisite (must be settled in the task contract before DE 004 starts):** the generator produces the same schema and the same planted problems at three **scale profiles** selected by a parameter — `tiny` (≈ 0.5 % of `docs/DEMO_COMPANY.md` §2 volumes, tens of thousands of rows total, optimized for CI, DuckDB fixture builds in < 30 s and is committable), `demo` (≈ 10 %, hundreds of thousands of rows, optimized for the local recruiter demonstration on a laptop) and `full` (100 %, ≈ 6.9 M rows, optimized for the live Snowflake scale demonstration). Planted-problem *rates* (duplicate %, null %, orphan %, drift version) are invariant across profiles; `expected/<profile>/*.json` is emitted per profile; scenario fixtures and evaluation baselines name the profile they were produced with. Details: `docs/DEMO_COMPANY.md` §11.
Env CLOUD · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `feat/DE004_synthetic_vantara` · Deps DE 002C · Files `synthetic/**`, `tests/unit/synthetic/**` · Own LOW · Par: yes (Lane A) · Tests: determinism (same seed + profile → same hashes), planted-problem assertions hold at every profile (duplicate rates, drift columns), profile volumes within ±5 % of target · DoD: `aide demo build-fixtures --profile tiny|demo|full` produces v1/v2 DuckDB + CSV; `tiny` fixtures used by the test suite; volumes per `docs/DEMO_COMPANY.md` §2 × profile factor within ±5 % · Risk L · Dur 4–6 h · Tok L · Gate: PR review.

### DE 005 — Real Snowflake connector
Goal: `connectors/snowflake/real.py`, identities `snowflake_ro`/`snowflake_dev`, error mapper with recorded fixtures, dialect, DEV namespace creation, `aide connectors check`; run contract tests live.
Env LOCAL · Cloud no (credentials) · Model Grok 4.6 · Reasoning High · Branch `feat/DE005_snowflake_connector` · Deps DE 002C · Files `src/aide/connectors/snowflake/**`, `tests/connectors/contract/test_snowflake*.py`, `src/aide/connectors/snowflake/README.md` · Own LOW (vendor dir) · Par: yes (Lane B) · Tests: contract suite fake+real; error mapping; allow-list enforcement; timeout · DoD: discovery/describe/profile/validate/execute/create work on DEV; `RAW` loaded via DE 004 loader · Risk M · Dur 4–6 h · Tok L · Gate: `REVIEW_REQUIRED` for secret entry (env var names: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`, `SNOWFLAKE_WAREHOUSE_DEV`); PR review.

### DE 006 — Profiling and relationship inference
Goal: `profiling/` templates, `profile_dataset`, `sample_dataset` (masking), `infer_relationships`, PROFILING phase template + planner inputs; UI-agnostic profile artifacts.
Env CLOUD · Cloud yes (fakes) · Model Grok 4.6 · Reasoning Medium · Branch `feat/DE006_profiling` · Deps DE 002C, DE 004 · Files `src/aide/profiling/**`, `src/aide/orchestration/phases/profiling.py`, `tests/**/profiling/**` · Own MEDIUM · Par: yes · Tests: budget enforcement; masking; key/relationship detection on fixtures (P1, P3, P10 detected) · DoD: profiles for all 9 demo assets in offline mode < 60 s · Risk M · Dur 4–6 h · Tok L · Gate PR.

### DE 007 — Modelling decision engine and design
Goal: `modelling/` signals + rule table + `ArchitectureDecision`; `propose_model_design` reasoning capability + validators; DESIGN phase; design approval flag path.
Env CLOUD · Cloud yes (recorded LLM fixtures; live optional) · Model Grok 4.6 · Reasoning High · Branch `feat/DE007_modelling` · Deps DE 006 · Files `src/aide/modelling/**`, `src/aide/reasoning/propose_model_design.py`, `src/aide/prompts/propose_model_design/v1.md.j2`, tests · Own MEDIUM · Par: yes · Tests: rule table unit tests per rule id; signal extraction from fixtures; validator rejections; demo decision matches `docs/DATA_MODELLING_STRATEGY.md` §6 · DoD: `ModelDesign` for demo validates; rule ids rendered · Risk M · Dur 5–7 h · Tok L · Gate PR.

### DE 008 — dbt connector, generation and execution
Goal: `connectors/dbt` real (subprocess `dbtRunner`) + fake (DuckDB); `generate_transformation` + generation validators + templates; `create/compile/execute_transformation`, `run_pipeline`, `run_tests`; GENERATION/POLICY_CHECK/EXECUTION phase templates; per-workflow working copy; `reconcile` for all side-effecting dbt capabilities.
**Architecture note (DE 008a must evaluate and record):** run **real dbt Core** (`dbtRunner` subprocess) against an **offline DuckDB-compatible target** (`dbt-duckdb` adapter over the DE 004 fixtures) for the integration and connector-contract test layers, so real parsing, Jinja, materializations and generic tests are exercised without Snowflake credentials, while **retaining the deterministic lightweight fake for unit tests** (speed, fault injection, `fail_after_effect`). Record the evaluation (adapter maturity vs pinned `dbt-core`, Snowflake→DuckDB portability of generated SQL, CI run time) in the DE 008 handoff. **Do not mandate `dbt-duckdb` if compatibility evidence rejects it.** If adopted, add it to `docs/CONNECTOR_ARCHITECTURE.md` §5.2 as an additive change. See `docs/CONNECTOR_ARCHITECTURE.md` §5.2.
Env LOCAL · Cloud no (dbt + Snowflake live validation) · Model Grok 4.6 · Reasoning High · Branch `feat/DE008_dbt_generation` · Deps DE 005, DE 007 · Files `src/aide/connectors/dbt/**`, `src/aide/generation/**`, `src/aide/reasoning/generate_transformation.py`, prompts, `dbt/vantara_project/**`, phase templates, tests · Own MEDIUM/LOW · Par: limited (large) · Tests: fake dbt contract incl. crash recovery; generation validators (forbidden Jinja, ref resolution, YAML columns); dbt-duckdb integration run if adopted; live `dbt build` on DEV · DoD: demo S01 builds green live and offline; dbt-duckdb evaluation recorded · Risk H · Dur 8–12 h (split into two sessions: connector; generation) · Tok XL · Gate PR.

### DE 009 — Quality Engine
Goal: `quality/` check catalogue, generators from `ModelDesign`, `ValidationReport`, VALIDATION phase; dbt result parsing; reconciliation checks.
Env CLOUD · Cloud yes · Model Grok 4.6 · Reasoning Medium · Branch `feat/DE009_quality_engine` · Deps DE 007 (design types), DE 008 (run_results shape; can start from contract) · Files `src/aide/quality/**`, phase template, tests · Own MEDIUM · Par: yes · Tests: each check on DuckDB fixtures incl. negative; tests-not-weakened validator; report schema · DoD: demo final validation passes; F2 detected · Risk M · Dur 5–7 h · Tok L · Gate PR.

### DE 010 — Failure classification and bounded repair
Goal: `repair/` classifier tables (Snowflake, dbt), evidence bundle (`inspect_failure`), `diagnose_failure` capability + validators, Repair Engine with budgets, REPAIR phase, scenarios S02/S03/S04/S07 offline.
Env CLOUD · Cloud yes (fault injection in fakes) · Model Grok 4.6 · Reasoning High · Branch `feat/DE010_repair` · Deps DE 008, DE 009 · Files `src/aide/repair/**`, `src/aide/reasoning/diagnose_failure.py`, prompts, phase template, `tests/**/repair/**`, `evaluation/scenarios/S02..S07` · Own MEDIUM · Par: yes · Tests: classifier mapping; budget properties; hypothesis novelty; S07 termination · DoD: F1 and F2 auto-repaired offline with recorded LLM; live once · Risk M · Dur 6–8 h · Tok L · Gate PR.

### DE 011 — Policy hardening, approvals, audit API, security tests
Goal: extend the kernel rule set, SQL adversarial corpus, typed Approval Engine/UI API,
audit timeline, redaction/leakage tests and injection heuristics; preserve evaluate-all
denial aggregation and complete subject binding.
Env CLOUD · Cloud yes · Model Grok 4.6 · Reasoning High · Branch `feat/DE011_policy_approvals` · Deps DE 002C (+ DE 008 for exec paths) · Files `src/aide/policy/**`, `src/aide/approvals/**`, `src/aide/audit/**`, `src/aide/api/routers/{approvals,audit}.py`, `tests/security/**` · Own HIGH (security) — one writer · Par: yes but no other task may touch `policy/`, `approvals/`, `secrets/` concurrently · Tests: property tests; negative rules; full binding invalidation · DoD: all security tests pass; independent security review before merge · Risk H · Gate: security review + PR.

### DE 012 — GitHub connector and delivery chain
Goal: GitHub real/fake connector for `prepare_git_change` and
`prepare_pull_request`; delivery template and secret scan. It does not advertise
`deploy_production`; that separate capability is globally disabled in V1.
Env LOCAL for live PR (token) · Cloud yes for fake part · Model Grok 4.6 · Reasoning Medium · Branch `feat/DE012_github_delivery` · Deps DE 008 · Files `src/aide/connectors/github/**`, `src/aide/delivery/**`, tests · Own LOW/MEDIUM · Par: yes · Tests: protected branch denial; force-push impossible; idempotent re-run; live PR to a sandbox repo · DoD: demo creates a PR with artifact set and generated body · Risk M · Dur 4–6 h · Tok L · Gate: `REVIEW_REQUIRED` for token (`GITHUB_TOKEN_AIDE`), PR.

### DE 013 — Lineage and documentation
Goal: `lineage/` (manifest + sqlglot column lineage with coverage), `generate_documentation` capability + validators, docs artifacts, lineage JSON for UI.
Env CLOUD · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `feat/DE013_lineage_docs` · Deps DE 008 · Files `src/aide/lineage/**`, `src/aide/reasoning/generate_documentation.py`, prompts, tests · Own MEDIUM · Par: yes · Tests: expected edges from `docs/DEMO_COMPANY.md` §9; docs reference only existing columns · DoD: lineage + docs artifacts for demo · Risk L · Dur 3–5 h · Tok M · Gate PR.

### DE 014 — Observability and cost accounting
Goal: model/tool call tables, price table, atomic LLM cap ledger, estimated warehouse
budget reporting, OTel, metrics endpoint and warehouse metrics capabilities.
Env CLOUD (fake) / LOCAL (Snowflake account usage) · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `feat/DE014_observability` · Deps DE 002C, DE 005 · Files `src/aide/observability/**`, `src/aide/connectors/snowflake/metrics.py`, `src/aide/api/routers/metrics.py`, tests · Own MEDIUM · Par: yes · Tests: cost computation from usage fixtures; atomic reservation/settlement; redaction · DoD: metrics panel data; budget cap triggers explicit new-cap approval in S11 · Risk L · Gate PR.

### DE 015 — Evaluation harness and scenarios
Goal: `aide eval run/report`, scenario loader, scorers for all metrics, recorded LLM fixtures for S01–S11 (incl. S06b/S06c/S08b), baseline file, CI regression gate.
Env CLOUD · Cloud yes (offline) · Model Muse Spark 1.3 (multi-step) or Composer 2.5 · Reasoning Medium · Branch `feat/DE015_evaluation` · Deps DE 010, DE 012, DE 013, DE 014 · Files `src/aide/evaluation/**`, `evaluation/**`, `tests/evaluation/**`, CI job · Own LOW · Par: yes · Tests: deterministic offline scores; report schema · DoD: S01–S11 pass offline in CI < 10 min; report artifact published · Risk M · Dur 6–8 h · Tok L · Gate PR.

### DE 016 — Frontend V1
Goal: SPA per `docs/MVP_SCOPE.md` §2 (request, clarification, plan, timeline, artifacts, validation, repairs, approvals, connectors, metrics); SSE; built into image.
Env CLOUD · Cloud yes · Model Gemini 3.1 Pro (design/visual) + Composer 2.5 (implementation) · Reasoning Medium · Branch `feat/DE016_frontend_v1` · Deps DE 011 (approval API), DE 014 (metrics API) · Files `frontend/**`, `src/aide/api/static_mount.py` · Own LOW · Par: yes · Tests: vitest components; Playwright smoke against offline backend · DoD: full demo drivable from UI offline · Risk M · Dur 8–12 h (two sessions) · Tok XL · Gate PR.

### DE 017 — Staging deploy capability and monitors stub
Goal: `dbt_staging` connector instance, `deploy_staging(DBT_RUN_TARGET)` with complete
`OperationApproval` binding, release intent/marker and `reconcile(RecoveryContext)`
(`docs/STATE_MODEL.md` §4.7), monitors and S10/S06c. Ambiguous outcome parks; no bare human
success or automatic repeat.
Env LOCAL · Cloud no · Model Grok 4.6 · Reasoning High · Branch `feat/DE017_staging_deploy` · Deps DE 011, DE 012 · Files `src/aide/delivery/deploy.py`, `src/aide/connectors/dbt/deploy.py`, monitors, tests · Own MEDIUM · Par: no (touches approval-bound execution) · Tests: approval binding negative tests; rollback ref recorded · DoD: demo deploys to `AIDE_STAGING` after approval; PROD denied · Risk H · Dur 4–6 h · Tok L · Gate: `REVIEW_REQUIRED` for staging identity secret; PR + Fable review of deploy path.

### DE 018 — End-to-end demo hardening
Goal: live rehearsal of S04 on Snowflake DEV + GitHub sandbox; warehouse pre-warm; demo script; offline fallback packaging; performance tuning; README with real setup commands and limitations.
Env LOCAL · Cloud no · Model Grok 4.6 (fixes) / GPT 5.6 Sol (hard debugging) · Reasoning High · Branch `fix/DE018_demo_hardening` · Deps all above · Files any (fix scope) — expected files listed per finding · Own: sequential, single writer · Tests: full suite + E3 ×3 + E4 ×1 · DoD: five-minute demo runs live and offline; README truthful · Risk M · Dur 6–10 h · Tok L · Gate PR.

### DE 019 — Independent production-readiness and security review
Goal: review security, reliability, concurrency, data integrity, observability, test depth against this architecture; produce findings and follow-up tasks.
Env LOCAL (may read private context) · Cloud no · Model Claude Fable 5.1 Max, then GPT 6 Astra independently · Reasoning Max/High · Branch `docs/DE019_readiness_review` · Deps DE 018 · Files `docs/reviews/**`, `.ai/TASKS.md`, `.ai/DECISIONS.md` · Own HIGH · Par: no · DoD: findings triaged into tasks; no CRITICAL open · Risk — · Dur 2–4 h · Tok L · Gate: human accepts findings.

---

## 4. Parallel development

### 4.1 Waves and lanes

```text
Wave 0  (sequential)               DE 002A [CLOUD] ─► DE 002B [CLOUD] ─► DE 002C [CLOUD] ─► DE 003 [CLOUD]
Wave 1  (2 agents)                 DE 004 [CLOUD]        ∥ DE 005 [LOCAL]
Wave 2  (2 agents)                 DE 006 [CLOUD]        ∥ DE 008a dbt connector [LOCAL]
Wave 3  (up to 3 agents)           DE 007 [CLOUD]        ∥ DE 008b generation/exec [LOCAL] ∥ DE 011 [CLOUD, security lane]
Wave 4  (up to 3 agents)           DE 009 [CLOUD]        ∥ DE 012 [LOCAL/CLOUD]            ∥ DE 013 [CLOUD]
Wave 5  (up to 3 agents)           DE 010 [CLOUD]        ∥ DE 014 [CLOUD]                  ∥ DE 016a frontend scaffold [CLOUD]
Wave 6  (2 agents)                 DE 015 [CLOUD]        ∥ DE 016b frontend features [CLOUD]
Wave 7  (sequential, LOCAL)        DE 017 ─► DE 018 ─► DE 019
```

Integration order inside a wave: merge the smallest/most upstream first (listed left to
right); later lanes refresh from `main` before PR.

### 4.2 When Cloud agents become safe

| Milestone | Why it unlocks parallelism | Agents |
|---|---|---|
| DE 001 accepted | corrected architecture contract; no code conventions yet | 1 agent |
| **DE 002A merged** | kernel contracts and unit/static CI locked before persistence | still 1 agent |
| **DE 002A/B/C + DE 003 merged** | contracts, fenced recovery, first slice, PostgreSQL integration and expanded CI proven | **2 agents** (one may be Cloud) — Wave 1 |
| **Wave 2 merged** (two connectors exercising the protocol, phase templates stable) | connector protocol proven against Snowflake + dbt — the point where contract fields are considered exercised; additive adjustments from DE 005/DE 008 landed | **3 agents** (two Cloud) — Waves 3–6 |
| DE 011 merged | security boundary stable; UI and eval can rely on approval/audit APIs | frontend + evaluation lanes |

Never in parallel: two tasks touching `orchestration/`, `domain/`, `capabilities/`,
`tools/`, `policy/`, `approvals/`, `persistence/alembic/`, or CI at the same time.

### 4.3 Cloud eligibility rule for product tasks

Cloud-eligible when: only tracked state needed; fakes and recorded LLM fixtures suffice
for tests; no credentials; task branch isolated; expected files declared. Live LLM in
Cloud only if an explicitly granted provider key is configured for the Cloud environment
(otherwise recorded fixtures). Not eligible: real Snowflake/dbt-live/GitHub-token tasks
(DE 005, DE 008, DE 012 live part, DE 017, DE 018).

### 4.4 Workstream manifest

Before launching any wave with > 1 agent, create `.ai/local/WORKSTREAMS.md` (ignored)
with: baseline `main` SHA, lane id, task id, branch, environment, model, reasoning,
allowed paths, forbidden paths, dependencies, integration order, required tests, status.
Record the intended merge order in `.ai/TASKS.md`.

---

## 5. DE 002 — authoritative sequenced definition

DE 002 is an umbrella of three sequential, independently reviewed tasks. No task begins
before its predecessor merges. This prevents executable workflow code from silently
inventing recovery/concurrency contracts while still delivering the same first slice.

### 5.1 DE 002A — contract kernel and minimal CI

**Scope**

1. Python/tooling skeleton and the acyclic import-linter rules in §2.
2. Pure domain contracts: `PrincipalRef`, server-side `GrantAuthorization`,
   `PermissionLevel`, workflow/cancellation states, phase/task template/materialized task,
   attempts/dispatch evidence, typed approval subjects, artifact provenance, failure and
   effect-semantics enums.
3. Capability and connector base contracts: contract/schema version advertisements,
   immutable contract snapshot, health snapshot, `CallContext`, `RecoveryContext`,
   four-way `ReconcileResult`, `max_attempts`.
4. Pure policy kernel: evaluate all denials, persist all reasons, severity/routing,
   approval-after-denial rule, MOCK isolation and typed approval matching.
5. SQL classifier kernel: extensible dialect ids, provider-neutral asset addresses,
   Snowflake round-trip parsing, canonical scope and safe function/construct classification.
6. Local opaque-session/auth and CSRF contract plus scoped secret resolver interfaces; no
   connector or database implementation.
7. Minimal CI on the branch: ruff, mypy strict, unit/property tests, import-linter and
   documentation contract checks.

**Tests:** operation identity cannot exist before resolved validated input; same operation
stable across attempts and distinct phase runs; policy rule-order permutation and
SECURITY dominance; simultaneous approval aggregation; approval rejection routes
`APPROVAL_REQUIRED → PLANNING|COMPLETED|BLOCKED|FAILED`; principal/grant forgery
rejection; SQL adversarial corpus; warehouse READ binds only to `identity_class=READ_ONLY`
(R4b; `READ ∉ snowflake_dev.allowed_permissions`); version compatibility;
`CONTRACT_VERSION_UNAVAILABLE` emission predicate (pinned version absent → that reason,
not `UNKNOWN_TARGET`) and ENVIRONMENTAL mapping; MOCK provenance; exact `max_attempts`;
retry summary vs evidence rule (no blind retry of `CONNECTOR_FAILURE` /
`TRANSIENT_PROVIDER` / `TIMEOUT` on side-effecting ops); `NoEffect` with exhausted
`max_attempts` → `FAILED`.

**Exclusions:** SQLAlchemy/Alembic, worker, LLM provider, vendor connector, API feature
surface, vertical slice, Docker integration.

### 5.2 DE 002B — persistence and recovery primitives

**Scope**

1. PostgreSQL models/migrations/repositories for workflows, sessions/grants,
   `phase_runs`, templates, materialized tasks, attempts, approvals, artifacts,
   connector health, recovery/unresolved effects, audit sequence/events and budget ledger.
2. Transactional materialization lifecycle and write-once constraints.
3. Serialized phase reducer/advance using transaction advisory lock plus uniqueness and
   expected generation/version checks; exhaustive dependency propagation.
4. Worker kernel: `SKIP LOCKED`, claim epoch, renewable heartbeat, owner+epoch
   finalization, stale-result rejection, atomic recovery ownership.
5. Ambiguous-failure protocol for normal and crash paths with bounded `InProgress`;
   fake side-effect connector and fail-before/after-effect injection.
6. Cancellation intent/shutdown/reconciliation and explicit unresolved parking.
7. Same-transaction audit events and atomic budget reservation/settlement.

**Tests:** two coordinators create one next phase run; resume of PARKED/AWAITING_APPROVAL
does not allocate a second occurrence; two workers cannot finalize one claim; stale worker
after replacement updates nothing; timeout/connection loss/response loss/fail-after-effect/
lease expiry all reconcile before retry; `NoEffect` with exhausted `max_attempts` fails
rather than remaining in `RECONCILING`; every reconcile branch and attempt count;
cancellation records ownership under the serialization lock then performs connector
cancel/reconcile I/O outside it; required dependency cascade; audit rollback
atomicity/sequence; concurrent budget reservation; scheduler parks
`CONTRACT_VERSION_UNAVAILABLE` (does not fail closed) and resume re-evaluates.

**Exclusions:** LLM planning, discovery/generation business flow, real connectors, frontend.

### 5.3 DE 002C — first executable offline safe-SQL slice

**Scope:** compose DE 002A/B with replay LLM, versioned prompts, fake Snowflake, minimal
API/CLI/application services and flow:

```text
authenticated request + server-authorized grants
→ planning
→ DISCOVERY enumeration phase run
→ planning boundary
→ explicit sorted describe tasks + selection phase run
→ safe SQL generation
→ materialization → policy → fake DEV execution
→ deterministic validation → structured result
```

Implement `interpret_requirement`, `plan_phase`, `discover_assets`, `describe_asset`,
`select_relevant_assets`, `generate_sql_query`, `classify_sql`, `validate_query`,
`execute_query`, `create_dataset`, minimal quality checks, connector status/capability
queries and read-only SSE. The fake supplies complete version/recovery/provenance behavior.

**Tests:** offline end to end; unavailable connector parks without invalidating the plan;
fan-out boundary creates deterministic unique tasks; enumeration phase run exits on
catalogue-only `phase_exit_criteria` before description/selection exist; SQL read uses RO
binding (`snowflake_ro` / `identity_class=READ_ONLY`; `snowflake_dev` rejected); canonical
query tag round-trip includes full operation and attempt ids; ambiguous success cannot
pass without validated output; leakage scan.

**Exclusions:** dbt, GitHub, repair loop, real Snowflake, frontend, production deploy,
enterprise IAM. `deploy_staging` is a contract only; no staging execution.

### 5.4 Contract baseline (DE-ADR-026)

DE 002A baselines pure contracts only after its deterministic CI is green. DE 002B
baselines persistence/recovery semantics only after concurrency/failure integration tests.
DE 002C baselines composition only after the offline slice passes. Baseline includes
principal/grants, phase runs/materialization, operation/attempt identity, fencing,
cancellation, version snapshots, connector health/recovery, typed approvals, policy
aggregation, artifact provenance, audit and budget ledger.

Breaking changes require ADR + `.ai/DECISIONS.md` + architecture review. Additive changes
are allowed when old tests remain unchanged and passing and docs update in the same PR.
An additive capability does not require an ADR unless it changes existing semantics or an
architecture boundary. DE 005/008 may add compatible implementations; in-flight pinned
contracts are never silently upgraded.

### 5.5 Definition of done

Each subtask passes its listed tests and review before merge; no later subtask compensates
for a red predecessor. After DE 002C, the offline command completes the slice and the
repository reports exact test evidence. DE 003 then expands Docker/PostgreSQL CI; it does
not create the first contract gate.
