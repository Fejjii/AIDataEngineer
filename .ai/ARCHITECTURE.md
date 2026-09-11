# AIDataEngineer — Architecture

## Current status

**ACCEPTED** (operator acceptance 2026-09-11)

Designed by DE 001; corrected by DE 001R1; independently reviewed by GPT 5.6 Sol High;
blocking contract findings hardened by DE 001R2A; residual consistency findings U-01–U-10
closed by DE 001R2B; operator accepted 2026-09-11. Composer 2.5 only persisted the
independent review/verification artifacts. Implementation (DE 002+) may proceed per
`.ai/TASKS.md`. The architecture freeze in `.ai/MASTER_WORKFLOW.md` §20 applies — read per
DE-ADR-026: the *architecture* is baselined and breaking deviations need an ADR; *contracts*
may evolve additively when existing tests stay valid.

## Authoritative documents

Full architecture lives in tracked `docs/` (readable by Cloud agents):

| Document | Content |
|---|---|
| `docs/ARCHITECTURE.md` | Components, boundaries, responsibility matrix, ownership map |
| `docs/MVP_SCOPE.md` | Recruiter-ready V1 boundary and acceptance criteria |
| `docs/CAPABILITY_MODEL.md`, `docs/TOOL_CONTRACTS.md` | Typed capability catalogue and per-capability contracts |
| `docs/CONNECTOR_ARCHITECTURE.md` | Connector protocol, fakes, status, V1 connectors |
| `docs/STATE_MODEL.md` | Workflow state machine, transition table, task graph |
| `docs/AGENT_MODEL.md` | Orchestrator, planner, reasoning capabilities (no specialist agents) |
| `docs/PERMISSION_MODEL.md` | Permissions, policy rules, approvals, security, failure classes, repair loop |
| `docs/DATA_MODELLING_STRATEGY.md`, `docs/QUALITY_STRATEGY.md` | Deterministic modelling rules and validation |
| `docs/OBSERVABILITY.md`, `docs/EVALUATION_STRATEGY.md` | Telemetry, audit, cost; benchmarks and metrics |
| `docs/TECH_STACK.md`, `docs/TECHNICAL_RISKS.md` | Technology decisions; risk register |
| `docs/IMPLEMENTATION_PLAN.md` | Repository layout, module boundaries, roadmap DE 002–DE 019, parallel lanes, DE 002 definition |
| `docs/DEMO_COMPANY.md` | Synthetic enterprise *Vantara Systems* |
| `docs/adr/` | DE-ADR-008 … DE-ADR-027 |

## Compact implementation contract (for implementation models)

**Shape.** Modular monolith, Python 3.12 package `aide`, FastAPI API, in-process asyncio
worker (separable), PostgreSQL 16 for all state (SQLAlchemy 2 + Alembic), Vite/React/TS
SPA built last, Typer CLI. No microservices, Kubernetes, Kafka, Redis, vector DB,
LangGraph/LangChain, or multi-agent framework in V1.

**Control.** Deterministic state machine includes cancellation intent/shutdown before
terminal cancellation. Each phase occurrence has `phase_run_id`, monotonic generation,
pinned contract snapshot and immutable task templates. Templates may contain `$from` but
cannot have operation identity, policy, approval or attempts. After dependencies finish,
inputs resolve and validate; canonical `resolved_input_digest` and an operation key
including phase run and pinned versions persist atomically. A new planning boundary after
discovery enumeration creates explicit sorted fan-out tasks. Phase reduction/advance is
serialized by PostgreSQL transaction advisory lock and exhaustive dependency propagation.
Claims use renewable leases and monotonic fencing epochs; stale results are rejected.
Every ambiguous side effect (timeout, response loss, crash, lease expiry, fail-after-effect)
reconciles before retry with bounded `EffectFound|NoEffect|InProgress|Unknown`.

**Capabilities.** The orchestrator reasons about typed capabilities, never vendors.
`CapabilitySpec` = id@version, kind (deterministic | reasoning | control), input/output
Pydantic schemas and schema versions, permission, risk, typed approval rule, timeout,
`max_attempts`, effect semantics, failure classes, validators, audit and connector
requirement. Tool Registry wrapper enforces
validate → policy → execute → validate → audit on every call. Connectors advertise
supported contract versions; each ships real + fake + error mapper + contract tests,
typed health and complete reconciliation context.

**AI.** One planner (`plan_phase`) plus reasoning capabilities (`interpret_requirement`,
`select_relevant_assets`, `propose_model_design`, `generate_transformation`,
`generate_sql_query`, `diagnose_failure`, `generate_documentation`, `summarize_for_human`) via a thin LLM
Gateway (own provider protocol, structured outputs, versioned Jinja2 prompt files,
redaction, cost accounting, replay fake). LLM output is a proposal; deterministic code
validates and enforces. Modelling architecture class is chosen by a rule table, not the LLM.

**Identity and policy.** A local opaque server session produces trusted `PrincipalRef`;
clients request but never set effective grants, which the server derives from actor,
roles and environment policy. `PermissionLevel` is a **set of distinct grants with no ordering** — one
canonical definition in `aide.domain.permissions`: `READ, DEVELOPMENT_EXECUTE,
DEVELOPMENT_WRITE, GIT_WRITE, STAGING_DEPLOY, PRODUCTION_WRITE, DESTRUCTIVE,
INFRASTRUCTURE, SECURITY`. Every check is set membership: required permission ∈ workflow
grant set (or covered by an approval) and ∈ the connector instance's
`allowed_permissions`; no ceilings/ranks. Every applicable denial rule runs; all reasons
persist; routing severity is `SECURITY > SCOPE > ENVIRONMENTAL`; approval requirements
are evaluated only with no denial. SQL read capabilities bind to `identity_class=READ_ONLY`
(`snowflake_ro`) and classify functions/constructs/scope with dialect round-trip parsing. Typed
`OperationApproval|DesignApproval|BudgetIncreaseApproval` subjects have kind-specific
binding and rejection semantics. **Denials are routed by class**
(`docs/PERMISSION_MODEL.md` §3.1): `ENVIRONMENTAL` (connector unavailable, secret
unresolved, connector permission missing) → task `PARKED`, workflow `BLOCKED`;
`SCOPE`/`SECURITY` → fail closed (`FAILED`, audit alert for security); approval-eligible →
`APPROVAL_REQUIRED`. The plan validator runs the same rules as a pre-check so the planner
re-plans before tasks exist. PROD, INFRASTRUCTURE, SECURITY disabled in V1.

**Repair.** Only repairable failure classes; evidence → novel-hypothesis proposal →
deterministic validation → rebuild → re-validate; 2 per task, 4 per workflow; never
weaken tests; escalate to `BLOCKED`.

**Security.** `SecretRef` indirection with separate non-enumerable resolver scopes for
connector and LLM provider adapters; transitive REAL/MOCK artifact provenance blocks mock
evidence from real Git/deploy; redaction before logs/audit/prompts/artifacts.

**Contract baseline is sequenced:** DE 002A pure kernel + minimal CI (**CLOUD**); DE 002B
PostgreSQL phase-run/fencing/recovery/cancellation primitives (**LOCAL**); DE 002C first
offline safe-SQL slice (**LOCAL**); DE 003 expands Docker/integration CI (**CLOUD**).
No phase baselines semantics before its deterministic
tests pass. Baseline includes principal/grants, materialization identity, versions, typed
health/reconciliation, approvals, policy aggregation, provenance, audit and budget ledger.
**Breaking** changes (remove/rename/retype fields, change semantics or transitions, remove
enum members) require an ADR + architecture review. **Additive, backward-compatible**
changes (optional fields with defaults, new enum members/reason codes, new capabilities,
rules, commands, columns) are allowed when all existing tests remain valid and pass
unchanged. Snowflake (DE 005) and dbt (DE 008) are expected to exercise and additively
adjust these contracts; nothing is frozen "forever" before that.

**Before DE 004:** the synthetic generator must support scale profiles `tiny` /
`demo` / `full` (`tiny` = CI, `demo` = local recruiter demonstration, `full` =
Snowflake scale demonstration) with invariant planted-problem rates
(`docs/DEMO_COMPANY.md` §11).
**In DE 008:** evaluate real dbt Core against an offline DuckDB-compatible target
(`dbt-duckdb`) for integration tests while keeping the lightweight deterministic fake for
unit tests. Do not adopt that path if compatibility evidence rejects it
(`docs/CONNECTOR_ARCHITECTURE.md` §5.2).

## Rules for implementation tasks

- Consume this architecture; do not rediscover or silently change it.
- Breaking deviation → ADR in `docs/adr/` + entry in `.ai/DECISIONS.md` + higher-tier review;
  additive evolution per DE-ADR-026.
- Respect module boundaries (`docs/IMPLEMENTATION_PLAN.md` §2, enforced by import-linter).
- High-conflict areas (`orchestration/`, `domain/`, `capabilities/`, `tools/`, `policy/`,
  `approvals/`, `secrets/`, migrations, CI, `docs/`) have one writer at a time.
