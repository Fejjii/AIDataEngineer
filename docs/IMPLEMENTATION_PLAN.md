# Implementation Plan

**Task:** DE 001 (corrected by DE 001R1) · **Status:** PROPOSED · ADRs: DE-ADR-020, DE-ADR-021, DE-ADR-026

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
│   ├── policy/                   # permission levels, PolicyEngine rules, SQL classifier, git classifier
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

| Contract | Rule |
|---|---|
| Layers | `api → app → {orchestration, approvals, artifacts, audit, evaluation} → {tools, policy, reasoning, domain} → {capabilities, llm, connectors.base} → persistence/observability/secrets`; lower layers never import higher |
| Connector isolation | only `aide.tools` and `aide.connectors.registry_entries` may import `aide.connectors.<vendor>` |
| Secrets isolation | only `aide.connectors.*`, `aide.llm.providers.*` may import `aide.secrets.provider`; nothing may import a provider from `domain`, `reasoning`, `prompts` |
| No LLM in persistence/policy/quality | `aide.persistence`, `aide.policy`, `aide.quality`, `aide.execution` must not import `aide.llm` or `aide.reasoning` |
| Domain purity | `aide.domain` imports only stdlib + pydantic |
| API thinness | `aide.api` must not import `aide.persistence`, `aide.connectors`, `aide.llm` |

---

## 3. Roadmap — vertical slices

Common fields: **Env** LOCAL/CLOUD · **Cloud** eligibility · **Model** class · **Reasoning** · **Branch** · **Deps** · **Files** (expected) · **Own** (ownership class) · **Par** (parallel eligibility) · **Tests** · **DoD** · **Risk** · **Dur** (agent hours) · **Tok** (S/M/L/XL) · **Gate** (human) · **Git** authority.

Git authority for all implementation tasks: *branch-only; commit + push on the task branch
and open one PR when the task prompt says `GitWrite: authorized`; never merge.*

### DE 002 — Core skeleton and first vertical slice
See §5 for the full definition.
Env LOCAL · Cloud no · Model Grok 4.6 · Reasoning High · Branch `feat/DE002_core_slice` · Deps DE 001 accepted + review gate · Dur 6–8 h (two sessions) · Tok XL · Gate: PR review · Risk M.

### DE 003 — CI, Docker, tooling baseline
Goal: GitHub Actions (ruff, mypy, pytest unit+integration with PostgreSQL service, import-linter, gitleaks, docker build), `Dockerfile`, `docker-compose.yml`, `Makefile`, pre-commit, `scripts/verify-environment.sh`.
Env CLOUD · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `ops/DE003_ci_docker` · Deps DE 002 · Files `.github/workflows/*`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `.pre-commit-config.yaml`, `scripts/` · Own HIGH (CI) · Par: no (touches root tooling) · Tests: CI green on PR · DoD: required checks defined; offline DE 002 tests pass in CI · Risk L · Dur 2–3 h · Tok M · Gate: PR review; branch protection config by human.

### DE 004 — Synthetic enterprise generator and fixtures
Goal: `synthetic/vantara` generator (seeded), PostgreSQL DDL/load, DuckDB fixture builder for fakes (v1/v2 states), `expected/*.json`, `pii_columns.yaml`, Snowflake loader script (not executed in Cloud).
**Prerequisite (must be settled in the task contract before DE 004 starts):** the generator produces the same schema and the same planted problems at three **scale profiles** selected by a parameter — `tiny` (≈ 0.5 % of `docs/DEMO_COMPANY.md` §2 volumes, tens of thousands of rows total, optimized for CI, DuckDB fixture builds in < 30 s and is committable), `demo` (≈ 10 %, hundreds of thousands of rows, optimized for the local recruiter demonstration on a laptop) and `full` (100 %, ≈ 6.9 M rows, optimized for the live Snowflake scale demonstration). Planted-problem *rates* (duplicate %, null %, orphan %, drift version) are invariant across profiles; `expected/<profile>/*.json` is emitted per profile; scenario fixtures and evaluation baselines name the profile they were produced with. Details: `docs/DEMO_COMPANY.md` §11.
Env CLOUD · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `feat/DE004_synthetic_vantara` · Deps DE 002 · Files `synthetic/**`, `tests/unit/synthetic/**` · Own LOW · Par: yes (Lane A) · Tests: determinism (same seed + profile → same hashes), planted-problem assertions hold at every profile (duplicate rates, drift columns), profile volumes within ±5 % of target · DoD: `aide demo build-fixtures --profile tiny|demo|full` produces v1/v2 DuckDB + CSV; `tiny` fixtures used by the test suite; volumes per `docs/DEMO_COMPANY.md` §2 × profile factor within ±5 % · Risk L · Dur 4–6 h · Tok L · Gate: PR review.

### DE 005 — Real Snowflake connector
Goal: `connectors/snowflake/real.py`, identities `snowflake_ro`/`snowflake_dev`, error mapper with recorded fixtures, dialect, DEV namespace creation, `aide connectors check`; run contract tests live.
Env LOCAL · Cloud no (credentials) · Model Grok 4.6 · Reasoning High · Branch `feat/DE005_snowflake_connector` · Deps DE 002 · Files `src/aide/connectors/snowflake/**`, `tests/connectors/contract/test_snowflake*.py`, `src/aide/connectors/snowflake/README.md` · Own LOW (vendor dir) · Par: yes (Lane B) · Tests: contract suite fake+real; error mapping; allow-list enforcement; timeout · DoD: discovery/describe/profile/validate/execute/create work on DEV; `RAW` loaded via DE 004 loader · Risk M · Dur 4–6 h · Tok L · Gate: `REVIEW_REQUIRED` for secret entry (env var names: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`, `SNOWFLAKE_WAREHOUSE_DEV`); PR review.

### DE 006 — Profiling and relationship inference
Goal: `profiling/` templates, `profile_dataset`, `sample_dataset` (masking), `infer_relationships`, PROFILING phase template + planner inputs; UI-agnostic profile artifacts.
Env CLOUD · Cloud yes (fakes) · Model Grok 4.6 · Reasoning Medium · Branch `feat/DE006_profiling` · Deps DE 002, DE 004 · Files `src/aide/profiling/**`, `src/aide/orchestration/phases/profiling.py`, `tests/**/profiling/**` · Own MEDIUM · Par: yes · Tests: budget enforcement; masking; key/relationship detection on fixtures (P1, P3, P10 detected) · DoD: profiles for all 9 demo assets in offline mode < 60 s · Risk M · Dur 4–6 h · Tok L · Gate PR.

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
Goal: full rule set R1–R20, SQL classifier property tests + adversarial corpus, Approval Engine with hash binding/expiry, `request_approval`, audit timeline endpoints, redaction processors + leakage scan test, injection heuristics, S08/S09/S11.
Env CLOUD · Cloud yes · Model Grok 4.6 · Reasoning High · Branch `feat/DE011_policy_approvals` · Deps DE 002 (+ DE 008 for exec paths) · Files `src/aide/policy/**`, `src/aide/approvals/**`, `src/aide/audit/**`, `src/aide/api/routers/{approvals,audit}.py`, `tests/security/**` · Own HIGH (security) — one writer · Par: yes but no other task may touch `policy/`, `approvals/`, `secrets/` concurrently · Tests: property tests; negative rules; approval invalidation · DoD: all security tests pass; independent **Fable 5.1 review** of `policy/` and `approvals/` before merge · Risk H · Dur 6–8 h · Tok L · Gate: security review + PR.

### DE 012 — GitHub connector and delivery chain
Goal: `connectors/github` real (git CLI + REST) + fake; `prepare_git_change`, `prepare_pull_request`; delivery phase template pre-approval; secret scan on diff; `deploy` contract stub returning `POLICY_DENIED` for PROD.
Env LOCAL for live PR (token) · Cloud yes for fake part · Model Grok 4.6 · Reasoning Medium · Branch `feat/DE012_github_delivery` · Deps DE 008 · Files `src/aide/connectors/github/**`, `src/aide/delivery/**`, tests · Own LOW/MEDIUM · Par: yes · Tests: protected branch denial; force-push impossible; idempotent re-run; live PR to a sandbox repo · DoD: demo creates a PR with artifact set and generated body · Risk M · Dur 4–6 h · Tok L · Gate: `REVIEW_REQUIRED` for token (`GITHUB_TOKEN_AIDE`), PR.

### DE 013 — Lineage and documentation
Goal: `lineage/` (manifest + sqlglot column lineage with coverage), `generate_documentation` capability + validators, docs artifacts, lineage JSON for UI.
Env CLOUD · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `feat/DE013_lineage_docs` · Deps DE 008 · Files `src/aide/lineage/**`, `src/aide/reasoning/generate_documentation.py`, prompts, tests · Own MEDIUM · Par: yes · Tests: expected edges from `docs/DEMO_COMPANY.md` §9; docs reference only existing columns · DoD: lineage + docs artifacts for demo · Risk L · Dur 3–5 h · Tok M · Gate PR.

### DE 014 — Observability and cost accounting
Goal: model/tool call tables and writers, price table, per-workflow caps enforcement wiring, OTel spans, metrics endpoint, warehouse metrics capabilities (`get_execution_metrics`, `get_cost_metrics`) real+fake.
Env CLOUD (fake) / LOCAL (Snowflake account usage) · Cloud yes · Model Composer 2.5 · Reasoning Medium · Branch `feat/DE014_observability` · Deps DE 002, DE 005 · Files `src/aide/observability/**`, `src/aide/connectors/snowflake/metrics.py`, `src/aide/api/routers/metrics.py`, tests · Own MEDIUM · Par: yes · Tests: cost computation from usage fixtures; cap enforcement; redaction in logs · DoD: metrics panel data for demo; caps trigger COST approval in S11 · Risk L · Dur 4–6 h · Tok M · Gate PR.

### DE 015 — Evaluation harness and scenarios
Goal: `aide eval run/report`, scenario loader, scorers for all metrics, recorded LLM fixtures for S01–S11 (incl. S06b/S06c/S08b), baseline file, CI regression gate.
Env CLOUD · Cloud yes (offline) · Model Muse Spark 1.3 (multi-step) or Composer 2.5 · Reasoning Medium · Branch `feat/DE015_evaluation` · Deps DE 010, DE 012, DE 013, DE 014 · Files `src/aide/evaluation/**`, `evaluation/**`, `tests/evaluation/**`, CI job · Own LOW · Par: yes · Tests: deterministic offline scores; report schema · DoD: S01–S11 pass offline in CI < 10 min; report artifact published · Risk M · Dur 6–8 h · Tok L · Gate PR.

### DE 016 — Frontend V1
Goal: SPA per `docs/MVP_SCOPE.md` §2 (request, clarification, plan, timeline, artifacts, validation, repairs, approvals, connectors, metrics); SSE; built into image.
Env CLOUD · Cloud yes · Model Gemini 3.1 Pro (design/visual) + Composer 2.5 (implementation) · Reasoning Medium · Branch `feat/DE016_frontend_v1` · Deps DE 011 (approval API), DE 014 (metrics API) · Files `frontend/**`, `src/aide/api/static_mount.py` · Own LOW · Par: yes · Tests: vitest components; Playwright smoke against offline backend · DoD: full demo drivable from UI offline · Risk M · Dur 8–12 h (two sessions) · Tok XL · Gate PR.

### DE 017 — Staging deploy capability and monitors stub
Goal: `dbt_staging` connector instance (identity `AIDE_STAGING_DEPLOY`, `allowed_permissions={STAGING_DEPLOY}`), `deploy(STAGING, DBT_RUN_TARGET)` with approval binding, `releases` intent row + release marker + `reconcile(release_id)` (`docs/STATE_MODEL.md` §4.6; ambiguous outcome parks, never auto-repeats), `register_monitor`/`check_monitor`, MONITORING phase, S10, S06c.
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
Wave 0  (sequential, LOCAL)        DE 002 ─► DE 003
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
| DE 001 accepted (architecture baseline) | shared vocabulary; but no code conventions yet | 0 Cloud; 1 LOCAL |
| **DE 002 + DE 003 merged** | package layout, domain types, capability/connector contracts (baseline, §5.2), persistence, CI, fakes and fake LLM exist; import-linter enforces boundaries | **2 agents** (one may be Cloud) — Wave 1 |
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

## 5. DE 002 — exact definition

**Title:** Core skeleton and first vertical slice: request → structured plan → metadata
discovery → safe SQL generation → development execution → validation → structured result.

**Environment:** LOCAL (sets conventions; optional live Snowflake smoke; private context
may be consulted). **Cloud eligibility:** no. **Model:** Grok 4.6. **Reasoning:** High.
**Branch:** `feat/DE002_core_slice`. **Duration:** 6–8 agent hours in two sessions
(A: skeleton ≈ 3 h; B: slice ≈ 4 h) with a phase handoff between them. **Token class:**
XL. **Parallelization:** none — single writer; DE 003 starts only after DE 002 merges.
**Git authority:** branch-only; commit/push on the task branch and open one PR if the
prompt says `GitWrite: authorized`; never merge. **Deployment authority:** none.

### 5.1 Scope

Session A — skeleton:
1. `pyproject.toml` (uv, Python 3.12, ruff, mypy strict, pytest, import-linter contracts), `src/aide` package with the directories in §1 (empty `__init__` where not yet needed), `Makefile`, `.env.example`, `README.md` (truthful: what runs).
2. `domain/`: `Workflow`, `WorkflowState` enum + transition table (full table from `docs/STATE_MODEL.md` §3, tests for reachability), `Task` (with `idempotency_key` = operation identity), `TaskAttempt` (attempt identity, `docs/STATE_MODEL.md` §4.2b), `TaskStatus` (incl. `PARKED`), `ArtifactRef`, `RequirementSpec`, `Plan`, `FailureClass` (incl. `AMBIGUOUS_OUTCOME`), **`PermissionLevel` — the single canonical definition (`aide.domain.permissions`), a `StrEnum` with no ordering**, `RiskLevel`, `TargetEnv`, `ValidationReport` (minimal), `WorkflowSummary` (minimal).
3. `capabilities/`: `CapabilitySpec`, registry + decorator, catalogue view; specs for `interpret_requirement`, `plan_phase`, `discover_assets`, `describe_asset`, `select_relevant_assets`, `generate_sql_query`, `classify_sql`, `validate_query`, `execute_query`, `create_dataset`, `emit_clarification` (contracts per `docs/TOOL_CONTRACTS.md`).
4. `connectors/base/`: `Connector` protocol (incl. `reconcile`), `ConnectorSpec` (with `allowed_permissions: frozenset[PermissionLevel]`), `CallContext` (both identities), `ReconcileResult`, `@implements`, status enum, health, contract test kit (incl. `fail_after_effect` crash-recovery scenario); `connectors/snowflake/fake.py` (DuckDB-backed, minimal fixtures — a tiny hand-written 3-table dataset until DE 004; `reconcile` for `create_dataset`), `errors.py` with the code table; `registry_entries.py`.
5. `policy/`: imports `PermissionLevel` from `aide.domain` (no second definition); `PolicyEngine` with rules R0 (startup), R1–R13b and R20, reason-code → deny-class map and routing (`docs/PERMISSION_MODEL.md` §3.1); `sql_classifier.py` on sqlglot with Snowflake dialect; unit tests incl. an initial adversarial corpus.
6. `tools/`: Tool Registry wrapper (validate → policy → route → attempt intent → execute with timeout → validate → audit/telemetry; reconciliation entry point for the Scheduler).
7. `llm/`: `LLMProvider` protocol, one real adapter (provider from settings), structured output helper, prompt loader (Jinja2 sandboxed, versioned files), `FakeProvider` (fixture replay by fingerprint), cost accounting row writer with a price table.
8. `persistence/`: SQLAlchemy models + Alembic initial migration for `workflows`, `workflow_events`, `tasks`, `task_attempts`, `artifacts`, `policy_decisions`, `audit_events`, `model_calls`, `tool_calls`, `connector_status`; repositories; unit of work; in-memory fakes for unit tests.
9. `observability/`: structlog JSON config with redaction processor; minimal OTel setup (no-op exporter).
10. `secrets/`: `SecretRef`, `EnvSecretProvider`, redaction registry.
11. `config/`: `Settings`; `connectors.yaml` loader; `AIDE_MODE=offline|live`.
12. `cli/`: `aide api`, `aide worker`, `aide workflow submit|show`, `aide connectors check`.
13. `docker-compose.yml` with PostgreSQL only (DE 003 finalizes CI/Docker).

Session B — slice:
14. `orchestration/`: Orchestrator with transition enforcement (incl. `POLICY_CHECK` routing precedence and `BLOCKED`/`PARKED` handling), phase controller for `RECEIVED → PLANNING → DISCOVERY → PLANNING → GENERATION(light) → POLICY_CHECK → EXECUTION → VALIDATION → COMPLETED`, worker loop with `SKIP LOCKED` claiming, leases, lease reaper + reconciliation protocol (`docs/STATE_MODEL.md` §4.6), `$from` placeholder resolution, phase templates for POLICY_CHECK/EXECUTION/VALIDATION (light).
15. `reasoning/`: `interpret_requirement`, `plan_phase`, `select_relevant_assets`, and `generate_sql_query` (contract in `docs/TOOL_CONTRACTS.md` §10a: one read-only SELECT or one `CREATE TABLE AS SELECT` into the DEV namespace) — full dbt generation is DE 008; this slice proves the generate → classify → EXPLAIN → execute → validate loop with plain SQL.
16. `discovery/`: catalogue builder from `discover_assets` + `describe_asset`.
17. `execution/`: Execution Engine with caps and environment binding.
18. `quality/` (minimal): `row_count_nonzero`, `schema_conformance` (columns exist), `unique` on declared key; `ValidationReport` writer.
19. `app/`: `submit_request`, `get_workflow`, `list_events`, `get_artifact`, `resume_workflow` (from `BLOCKED`; parked tasks → `READY`), `resolve_ambiguous_attempt` (minimal); `api/`: `POST /workflows`, `GET /workflows/{id}`, `GET /workflows/{id}/events`, `GET /artifacts/{id}`, `GET /connectors`, `GET /capabilities`; SSE optional.
20. Offline end-to-end test: request *"Create a development table listing customers with their number of invoices"* against the fake warehouse → `COMPLETED` with a created DEV table, a `ValidationReport` all-pass, audit timeline complete, no secret in any output (leakage scan).
21. Optional live smoke (LOCAL only, skipped without env): the same against real Snowflake DEV if credentials exist — **not** required for DoD.

### 5.2 Contract baseline established by DE 002 (stability policy — DE-ADR-026)

DE 002 establishes the **architecture baseline** for these contracts; it does not freeze
every field forever. The Snowflake (DE 005) and dbt (DE 008) integrations are expected to
exercise them and may reveal needed adjustments.

Baseline contracts: `PermissionLevel`, `CapabilitySpec`, `Connector`/`ConnectorSpec`/
`CallContext`/`ReconcileResult`/`@implements`, `PolicyRequest`/`PolicyDecision` (incl.
reason codes, deny classes, routing), `Task`/`TaskAttempt` record fields, transition table,
`ArtifactRef`, `LLMRequest`/`LLMProvider`, `AuditEvent`, `ModelCall`/`ToolCall` telemetry
rows, `Settings` tree, CLI command names.

| Change kind | Examples | Requirement |
|---|---|---|
| **Breaking** | remove/rename a field; change a field's type or semantics; make an optional field required; remove an enum member or a reason code; change the meaning or guard of an existing transition; remove a CLI command or flag; change a capability's input/output schema incompatibly | **ADR in `docs/adr/` + entry in `.ai/DECISIONS.md` + architecture review by a higher-tier model before merge**; `CapabilitySpec.version` bump where applicable; migration note |
| **Additive / backward compatible** | add an optional field with a default; add an enum member or reason code that existing consumers handle through their default branch (a new reason code must be added to the deny-class map — the exhaustiveness test enforces this); add a capability, rule, validator, CLI command or flag; add a telemetry column; widen accepted input | Allowed in the implementing task **when all existing tests remain valid and pass unchanged** (no test may be edited to accommodate the change except to add cases); recorded in the PR body and, when it touches a documented contract, mirrored into `docs/` in the same PR |
| **Internal** | refactors behind the contract; performance; fakes; error messages | No process beyond normal review |

Rules of thumb: if a downstream consumer compiled against the previous baseline would
break, it is a breaking change. Transition-table and permission-model changes are always
treated as breaking. After DE 011 merges, `PolicyRequest`/`PolicyDecision`, approval and
audit contracts additionally require the security review noted in DE 011.

### 5.3 Tests (DoD requires all green)

- Unit: transition table properties (reachability, exits, illegal transitions raise; `POLICY_CHECK` routing precedence); policy rules R0, R1–R13b positive/negative; reason-code → deny-class map is exhaustive; `PermissionLevel` ordering comparisons raise `TypeError` and no permission code path uses `<`/`>`/`max`; SQL classifier corpus (≥ 40 statements incl. destructive/multi/dynamic/security/unparseable); registry duplicate id fails; startup fails when an advertised capability's permission ∉ `allowed_permissions`; Tool Registry rejects invalid input/output; redaction fixture corpus; `FakeProvider` replay determinism; `$from` resolution; `idempotency_key` is a pure function of `(workflow_id, phase, local_id, capability@version, inputs_digest)` and identical across attempts (property test).
- Integration (PostgreSQL via compose/testcontainers): task claiming with two workers (no double execution); attempt intent row exists before handler invocation; lease expiry → reconcile → `EffectFound` adopts the result with exactly one external effect (`fail_after_effect`); lease expiry with `NoEffect` → new attempt, same key; non-idempotent capability with `Unknown` → `AMBIGUOUS_OUTCOME`, task `PARKED`, workflow `BLOCKED`, handler call count = 1; `resolve_ambiguous_attempt` resumes; environmental deny → `PARKED`/`BLOCKED` → resume re-evaluates policy; optimistic version conflict; artifact immutability; audit sequence monotonic.
- Connector contract: fake Snowflake passes the kit incl. crash recovery; error mapper table tests.
- End-to-end offline: §5.1 item 20; asserts states visited in order, task count bounds, plan-time pre-check rejects an injected destructive plan fixture and the planner replans, execution-time injected destructive SQL → `FAILED` with `POLICY_DENY_SECURITY` audit alert, leakage scan clean.
- Static: ruff, mypy --strict, import-linter contracts pass.

### 5.4 Synthetic dependencies

A minimal hand-written fixture (`synthetic/minimal/`: `CUSTOMERS`, `INVOICES`, `PAYMENTS`,
≈ 1 000 rows each, one planted duplicate group) loaded into the DuckDB fake; recorded LLM
fixtures for the offline test (created once with a live model in LOCAL, redacted,
committed under `evaluation/fixtures/llm/DE002_slice/`). DE 004 replaces the minimal
fixture with Vantara at the `tiny` scale profile (see DE 004 prerequisite in §3).

### 5.5 Explicit exclusions

No dbt, no GitHub, no repair loop, no approvals beyond the enum and policy outcomes, no
frontend, no real Snowflake requirement, no CI finalization (DE 003), no profiling beyond
`describe_asset` row counts.

### 5.6 Definition of done

All §5.3 tests green locally; `aide workflow submit --offline` completes the slice;
`README.md` documents exact commands; `.ai/TASKS.md` updated; handoff regenerated; PR
opened (if authorized) with scope, tests, risks, and the contract baseline list (§5.2); no
breaking deviation from `docs/ARCHITECTURE.md` without an ADR.

### 5.7 Risks specific to DE 002

Over-building the skeleton (mitigate: only the directories/types listed); sqlglot Snowflake
dialect gaps (mitigate: fail closed + corpus); DuckDB transpilation limits (mitigate:
minimal SQL in slice); dbt/Python version check deferred to DE 008 but Python 3.12 pinned now.
