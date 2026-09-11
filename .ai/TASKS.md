# AIDataEngineer — Tasks

Persistent backlog. Human IDs: `DE 000`. Compact IDs: `DE000`.
Legend — Priority: P0 (critical) … P3 (low). Status: TODO / IN_PROGRESS / DONE / BLOCKED.

---

## DE 000 — Repository bootstrap and development operating system

- Compact ID: `DE000`
- Priority: P0
- Status: DONE
- Owner: local Cursor agent (Composer 2.5 Standard, medium reasoning)
- Environment: LOCAL
- Branch: `main` (bootstrap only; no architecture branch)
- Dependencies: none
- Risk: Low
- Goal: Install Git, ignore rules, tracked governance, model routing, environments,
  handoff system, Cursor rules, private GitHub remote, and iCloud transport. No product code.
- Validation: Path `~/Developer/AIDataEngineer`; `main`; private sources ignored; governance
  files exist; GitHub origin private or clearly gated; no secrets tracked; handoff regenerated.
- Recommended model: Composer 2.5 Standard
- Completion evidence: Recorded in the DE 000 `HANDOFF.md` after the bootstrap commit.

## DE 001 — MVP architecture

- Compact ID: `DE001`
- Priority: P0
- Status: IN_PROGRESS → documents drafted; awaiting **review gate** (see below)
- Owner: local Cursor agent (Claude Fable 5.1, high reasoning)
- Environment: LOCAL (requires private bootstrap sources; produces the architecture baseline)
- Branch: `docs/DE001_mvp_architecture` (operator assignment supersedes the earlier
  `feat/` proposal)
- Dependencies: DE 000
- Risk: High (architectural blast radius)
- Goal: Design system boundaries, agent responsibilities, tool contracts, permission
  tiers, approval gates, audit logging, Snowflake/dbt/GitHub connector contracts, and
  repository structure. Produce `.ai/ARCHITECTURE.md`. Do not implement the product.
- Explicit exclusions: No backend/frontend implementation, no live connectors, no schemas
  applied to real warehouses.
- Validation: Architecture document set complete under `docs/` and `docs/adr/`;
  `.ai/ARCHITECTURE.md`, `.ai/DECISIONS.md`, `.ai/TASKS.md` updated; self-review performed.
- Recommended model: Claude Fable 5.1 High. Independent GPT 6 Astra review after the draft.
- Estimated duration: 2–4 hours
- Estimated token class: L
- Completion evidence: 18 docs + 18 ADRs authored 2026-09-11 (see session HANDOFF);
  corrected by DE 001R1 (below) before independent review.
- **Review gate (part of DE 001 acceptance, TODO):** independent GPT 6 Astra (High/Max)
  review of `docs/ARCHITECTURE.md` and companions against `docs/TECHNICAL_RISKS.md` and
  the checklist in the Engineering Practices Delta §7. Operator accepts or requests
  revisions; on acceptance set `.ai/ARCHITECTURE.md` status to `ACCEPTED` and ADRs to
  `ACCEPTED`. Only then may DE 002 start. Do not merge `docs/DE001_mvp_architecture`
  before acceptance.

## DE 001R1 — Architecture correction before independent review

- Compact ID: `DE001R1`
- Priority: P0
- Status: DONE (documents corrected; uncommitted on `docs/DE001_mvp_architecture`)
- Owner: local Cursor agent (Claude Fable 5.1, high reasoning)
- Environment: LOCAL · Branch: `docs/DE001_mvp_architecture` · Dependencies: DE 001 draft
- Risk: High (architectural semantics)
- Goal: Correct six architecture findings without implementing product code:
  (1) `PermissionLevel` is an unordered set of grants — one canonical definition,
  `ConnectorSpec.allowed_permissions` replaces `permission_ceiling`, all checks are set
  membership; (2) operation identity (`idempotency_key`, no attempt number) separated from
  attempt identity (`TaskAttempt`), reconcile-before-retry crash-recovery protocol,
  non-idempotent operations never auto-repeated after an ambiguous result; (3) deterministic
  policy denial routing by deny class (`ENVIRONMENTAL` → `PARKED`/`BLOCKED`,
  `SCOPE`/`SECURITY` → fail closed, approval-eligible → `APPROVAL_REQUIRED`) resolving the
  `CONNECTOR_UNAVAILABLE` vs `POLICY_CHECK → FAILED` contradiction; (4) DE 002 contract
  **baseline** with additive evolution instead of a permanent freeze (DE-ADR-026);
  (5) DE 004 scale-profile prerequisite and DE 008 dbt-duckdb evaluation note;
  (6) consistency sweep of all DE 001 documents and ADRs.
- Validation: consistency greps for old semantics (ceiling, `≤ granted`, `attempt` in key,
  `any DENY → FAILED`, `REVIEW_REQUIRED` in product state, `frozen`) return no product
  hits; cross-reference and ADR link checks; secret scan. Recorded in session HANDOFF.
- Completion evidence: session HANDOFF / CHANGELOG (2026-09-11).

---

# Implementation backlog (from `docs/IMPLEMENTATION_PLAN.md` §3 — authoritative detail there)

Common: Git authority = branch-only; commit/push + one PR only when the task prompt says
`GitWrite: authorized`; never merge. Deployment authority = none unless stated. Statuses
TODO until DE 001 is accepted.

## DE 002 — Core skeleton and first vertical slice
- Compact ID: `DE002` · Priority: P0 · Status: TODO
- Environment: LOCAL · Cloud eligible: no
- Branch: `feat/DE002_core_slice`
- Dependencies: DE 001 accepted (review gate passed)
- Risk: Medium
- Goal: Skeleton (package layout, domain types incl. canonical unordered `PermissionLevel`
  and `Task`/`TaskAttempt`, capability registry, connector protocol with
  `allowed_permissions` + `reconcile` + fake Snowflake, policy engine R0/R1–R13b with
  deny-class routing, Tool Registry, LLM gateway + fake, persistence + migrations,
  observability, secrets, config, CLI) and the slice request → plan → discovery → safe SQL
  generation → DEV execution → validation → structured result, offline against fakes.
  Establishes the contract **baseline** (DE-ADR-026), not a permanent freeze. Full
  definition: `docs/IMPLEMENTATION_PLAN.md` §5.
- Exclusions: dbt, GitHub, repair loop, approvals beyond enums/policy outcomes, frontend,
  real Snowflake requirement, CI finalization.
- Expected files: `pyproject.toml`, `src/aide/**` (listed dirs), `tests/**`,
  `synthetic/minimal/**`, `evaluation/fixtures/llm/DE002_slice/**`, `docker-compose.yml`,
  `Makefile`, `.env.example`, `README.md`.
- Validation: unit (transition properties incl. `POLICY_CHECK` routing precedence, policy
  rules, deny-class map exhaustiveness, `PermissionLevel` unordered, idempotency-key
  stability across attempts, SQL corpus ≥ 40, registry, redaction, fake replay),
  integration (claiming, attempt intent before effect, lease expiry → reconcile → exactly
  one effect, ambiguous non-idempotent → `PARKED`/`BLOCKED` with one handler call,
  environmental deny → park → resume, version conflicts, immutability), connector contract
  (fake incl. crash recovery), offline end-to-end, ruff/mypy strict/import-linter.
  Detail: `docs/IMPLEMENTATION_PLAN.md` §5.3.
- Recommended model: Grok 4.6 · Reasoning: High
- Estimated duration: 6–8 h in two sessions (A skeleton, B slice) · Token class: XL
- Parallelization: none (single writer)

## DE 003 — CI, Docker, tooling baseline
- `DE003` · P0 · TODO · Env CLOUD · Cloud yes · Branch `ops/DE003_ci_docker` · Deps DE 002
- Goal: GitHub Actions (ruff, mypy, pytest unit+integration w/ PostgreSQL, import-linter, gitleaks, docker build), Dockerfile, compose, Makefile, pre-commit, `scripts/verify-environment.sh`.
- Model Composer 2.5 · Reasoning Medium · Risk Low · Duration 2–3 h · Token M · Human gate: PR + branch-protection configuration by operator.

## DE 004 — Synthetic enterprise generator and fixtures (Vantara)
- `DE004` · P0 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE004_synthetic_vantara` · Deps DE 002 (parallel Lane A with DE 005)
- Goal: seeded generator, PostgreSQL DDL/load, DuckDB fixtures v1/v2, `expected/*.json`, `pii_columns.yaml`, Snowflake loader script.
- **Prerequisite (settle in the task contract before start):** scale profiles `ci` (≈ 0.5 %, CI/tests), `demo` (≈ 10 %, offline recruiter demo), `full` (100 %, live Snowflake) with invariant planted-problem rates and per-profile `expected/` — `docs/DEMO_COMPANY.md` §11, `docs/IMPLEMENTATION_PLAN.md` §3 DE 004.
- Model Composer 2.5 · Reasoning Medium · Risk Low · Duration 4–6 h · Token L · Files `synthetic/**`, tests.

## DE 005 — Real Snowflake connector
- `DE005` · P0 · TODO · Env LOCAL · Cloud no · Branch `feat/DE005_snowflake_connector` · Deps DE 002 (parallel Lane B with DE 004)
- Goal: real connector, identities `snowflake_ro`/`snowflake_dev`, error mapper w/ recorded fixtures, dialect, DEV namespace, `aide connectors check`, live contract tests.
- Model Grok 4.6 · Reasoning High · Risk Medium · Duration 4–6 h · Token L · Human gate: `REVIEW_REQUIRED` for secret entry (env var names only: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`, `SNOWFLAKE_WAREHOUSE_DEV`).

## DE 006 — Profiling and relationship inference
- `DE006` · P0 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE006_profiling` · Deps DE 002, DE 004
- Model Grok 4.6 · Reasoning Medium · Risk Medium · Duration 4–6 h · Token L.

## DE 007 — Modelling decision engine and design
- `DE007` · P0 · TODO · Env CLOUD · Cloud yes (recorded LLM) · Branch `feat/DE007_modelling` · Deps DE 006
- Model Grok 4.6 · Reasoning High · Risk Medium · Duration 5–7 h · Token L.

## DE 008 — dbt connector, generation and execution
- `DE008` · P0 · TODO · Env LOCAL · Cloud no · Branch `feat/DE008_dbt_generation` · Deps DE 005, DE 007 (008a connector may start after DE 005)
- **Architecture note:** DE 008a must evaluate real dbt Core (`dbtRunner`) against an offline DuckDB-compatible target (`dbt-duckdb`) for integration/contract tests, keeping the deterministic lightweight fake for unit tests; record the evaluation — `docs/CONNECTOR_ARCHITECTURE.md` §5.2, `docs/IMPLEMENTATION_PLAN.md` §3 DE 008. Also: `reconcile` for all side-effecting dbt capabilities.
- Model Grok 4.6 · Reasoning High · Risk High · Duration 8–12 h (two sessions) · Token XL.

## DE 009 — Quality Engine
- `DE009` · P0 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE009_quality_engine` · Deps DE 007, DE 008 (contract)
- Model Grok 4.6 · Reasoning Medium · Risk Medium · Duration 5–7 h · Token L.

## DE 010 — Failure classification and bounded repair
- `DE010` · P0 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE010_repair` · Deps DE 008, DE 009
- Model Grok 4.6 · Reasoning High · Risk Medium · Duration 6–8 h · Token L.

## DE 011 — Policy hardening, approvals, audit API, security tests
- `DE011` · P0 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE011_policy_approvals` · Deps DE 002 (+ DE 008 for exec paths)
- Exclusive ownership of `policy/`, `approvals/`, `secrets/`, `audit/` while active.
- Model Grok 4.6 · Reasoning High · Risk High · Duration 6–8 h · Token L · Human gate: independent Fable 5.1 security review before merge.

## DE 012 — GitHub connector and delivery chain
- `DE012` · P0 · TODO · Env LOCAL (live PR) / CLOUD (fake) · Branch `feat/DE012_github_delivery` · Deps DE 008
- Model Grok 4.6 · Reasoning Medium · Risk Medium · Duration 4–6 h · Token L · Human gate: `REVIEW_REQUIRED` for `GITHUB_TOKEN_AIDE`.

## DE 013 — Lineage and documentation
- `DE013` · P1 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE013_lineage_docs` · Deps DE 008
- Model Composer 2.5 · Reasoning Medium · Risk Low · Duration 3–5 h · Token M.

## DE 014 — Observability and cost accounting
- `DE014` · P1 · TODO · Env CLOUD (fake) / LOCAL (account usage) · Branch `feat/DE014_observability` · Deps DE 002, DE 005
- Model Composer 2.5 · Reasoning Medium · Risk Low · Duration 4–6 h · Token M.

## DE 015 — Evaluation harness and scenarios S01–S11
- `DE015` · P1 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE015_evaluation` · Deps DE 010, DE 012, DE 013, DE 014
- Model Muse Spark 1.3 or Composer 2.5 · Reasoning Medium · Risk Medium · Duration 6–8 h · Token L.

## DE 016 — Frontend V1
- `DE016` · P1 · TODO · Env CLOUD · Cloud yes · Branch `feat/DE016_frontend_v1` · Deps DE 011, DE 014
- Model Gemini 3.1 Pro + Composer 2.5 · Reasoning Medium · Risk Medium · Duration 8–12 h (two sessions) · Token XL.

## DE 017 — Staging deploy capability and monitors stub
- `DE017` · P1 · TODO · Env LOCAL · Cloud no · Branch `feat/DE017_staging_deploy` · Deps DE 011, DE 012
- Includes `releases` intent row, release marker and `reconcile(release_id)`; an ambiguous deploy outcome parks (`AMBIGUOUS_OUTCOME` → `BLOCKED`) and is never auto-repeated (`docs/STATE_MODEL.md` §4.6).
- Model Grok 4.6 · Reasoning High · Risk High · Duration 4–6 h · Token L · Human gate: staging identity secret; Fable review of deploy path.

## DE 018 — End-to-end demo hardening
- `DE018` · P1 · TODO · Env LOCAL · Cloud no · Branch `fix/DE018_demo_hardening` · Deps all above
- Model Grok 4.6 / GPT 5.6 Sol for hard debugging · Reasoning High · Risk Medium · Duration 6–10 h · Token L.

## DE 019 — Independent production-readiness and security review
- `DE019` · P1 · TODO · Env LOCAL · Cloud no · Branch `docs/DE019_readiness_review` · Deps DE 018
- Model Claude Fable 5.1 Max, then GPT 6 Astra independently · Reasoning Max/High · Duration 2–4 h · Token L · Human gate: operator accepts findings.

## Parallel waves and integration order

```text
Wave 0  DE 002 → DE 003                       (sequential, LOCAL)
Wave 1  DE 004 [CLOUD] ∥ DE 005 [LOCAL]       (2 agents; merge DE 004 first)
Wave 2  DE 006 [CLOUD] ∥ DE 008a [LOCAL]      (2 agents; merge DE 006 first)
Wave 3  DE 007 ∥ DE 008b ∥ DE 011             (3 agents; merge 007 → 008b → 011)
Wave 4  DE 009 ∥ DE 012 ∥ DE 013              (merge 009 → 013 → 012)
Wave 5  DE 010 ∥ DE 014 ∥ DE 016a             (merge 014 → 010 → 016a)
Wave 6  DE 015 ∥ DE 016b                      (merge 015 → 016b)
Wave 7  DE 017 → DE 018 → DE 019              (sequential, LOCAL)
```

Two agents become safe after DE 002 + DE 003 merge; three after Wave 2 merges. Create
`.ai/local/WORKSTREAMS.md` before any multi-agent wave.
