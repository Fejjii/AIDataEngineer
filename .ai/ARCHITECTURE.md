# AIDataEngineer — Architecture

## Current status

**DESIGNED — PROPOSED, awaiting independent frontier review (DE 001 review gate)**

Designed by DE 001 on 2026-09-11 (Claude Fable 5.1, high reasoning); corrected by DE 001R1
the same day and recovered after a quota interruption (permission sets, idempotency
identity, denial routing, contract baseline, `tiny`/`demo`/`full` profiles, DE 008
dbt-duckdb evaluation). Not yet accepted.
Implementation (DE 002+) must not start until the operator accepts this architecture,
preferably after an independent GPT 6 Astra review. After acceptance, status becomes
`ACCEPTED` and the architecture freeze in `.ai/MASTER_WORKFLOW.md` §20 applies — read per
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
| `docs/adr/` | DE-ADR-008 … DE-ADR-026 |

## Compact implementation contract (for implementation models)

**Shape.** Modular monolith, Python 3.12 package `aide`, FastAPI API, in-process asyncio
worker (separable), PostgreSQL 16 for all state (SQLAlchemy 2 + Alembic), Vite/React/TS
SPA built last, Typer CLI. No microservices, Kubernetes, Kafka, Redis, vector DB,
LangGraph/LangChain, or multi-agent framework in V1.

**Control.** Deterministic orchestrator drives an explicit workflow state machine
(`RECEIVED, CLARIFICATION_REQUIRED, PLANNING, DISCOVERY, PROFILING, DESIGN, GENERATION,
POLICY_CHECK, EXECUTION, VALIDATION, REPAIR, APPROVAL_REQUIRED, DELIVERY, MONITORING,
COMPLETED, BLOCKED, FAILED, CANCELLED`) with an authoritative transition table. Each phase
runs a task DAG (planner-generated or deterministic template), immutable within the phase;
tasks are claimed with `FOR UPDATE SKIP LOCKED` and leased. Each task has a **stable
operation identity** (`idempotency_key` = hash of workflow, phase, local id, capability
version, input digest — never the attempt number); each try is a separate `TaskAttempt`.
On lease expiry the scheduler **reconciles through the connector before re-executing**;
a non-idempotent operation (`deploy`) with an unknown outcome is parked
(`AMBIGUOUS_OUTCOME` → `BLOCKED`) and never repeated automatically. Task state `PARKED`
holds legitimate work that cannot run now; `BLOCKED` resumes into the phase it left.

**Capabilities.** The orchestrator reasons about typed capabilities, never vendors.
`CapabilitySpec` = id@version, kind (deterministic | reasoning | control), input/output
Pydantic schemas, permission, risk, approval rule, timeout, retry, failure classes,
validators, audit spec, connector requirement. Tool Registry wrapper enforces
validate → policy → execute → validate → audit on every call. Connectors advertise
capabilities; each ships real + fake + error mapper + contract tests; status
`AVAILABLE | DEGRADED | UNAVAILABLE | MOCK`.

**AI.** One planner (`plan_phase`) plus reasoning capabilities (`interpret_requirement`,
`select_relevant_assets`, `propose_model_design`, `generate_transformation`,
`generate_sql_query`, `diagnose_failure`, `generate_documentation`, `summarize_for_human`) via a thin LLM
Gateway (own provider protocol, structured outputs, versioned Jinja2 prompt files,
redaction, cost accounting, replay fake). LLM output is a proposal; deterministic code
validates and enforces. Modelling architecture class is chosen by a rule table, not the LLM.

**Policy.** `PermissionLevel` is a **set of distinct grants with no ordering** — one
canonical definition in `aide.domain.permissions`: `READ, DEVELOPMENT_EXECUTE,
DEVELOPMENT_WRITE, GIT_WRITE, STAGING_DEPLOY, PRODUCTION_WRITE, DESTRUCTIVE,
INFRASTRUCTURE, SECURITY`. Every check is set membership: required permission ∈ workflow
grant set (or covered by an approval) and ∈ the connector instance's
`allowed_permissions`; no ceilings, ranks or `<`/`>` comparisons. Pure-function rule set
R0 (startup) + R1–R20; sqlglot SQL classifier (unparseable ⇒ destructive); environment-
bound connector instances with allowed-permission sets and allow-lists; approvals bound to
artifact hashes and to the operation identity. **Denials are routed by class**
(`docs/PERMISSION_MODEL.md` §3.1): `ENVIRONMENTAL` (connector unavailable, secret
unresolved, connector permission missing) → task `PARKED`, workflow `BLOCKED`;
`SCOPE`/`SECURITY` → fail closed (`FAILED`, audit alert for security); approval-eligible →
`APPROVAL_REQUIRED`. The plan validator runs the same rules as a pre-check so the planner
re-plans before tasks exist. PROD, INFRASTRUCTURE, SECURITY disabled in V1.

**Repair.** Only repairable failure classes; evidence → novel-hypothesis proposal →
deterministic validation → rebuild → re-validate; 2 per task, 4 per workflow; never
weaken tests; escalate to `BLOCKED`.

**Security.** `SecretRef` indirection; secrets resolved only inside connectors/LLM
providers; redaction before logs, audit, prompts, artifacts; untrusted metadata delimited;
reasoning capabilities have no tools.

**Contract baseline established in DE 002** (DE-ADR-026; detail in
`docs/IMPLEMENTATION_PLAN.md` §5.2): `PermissionLevel`, `CapabilitySpec`, `Connector` /
`ConnectorSpec` / `CallContext` / `ReconcileResult` / `@implements`, `PolicyRequest` /
`PolicyDecision`, `Task` / `TaskAttempt` fields, transition table, `ArtifactRef`,
`LLMRequest` / `LLMProvider`, `AuditEvent`, telemetry rows, `Settings`, CLI names.
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
