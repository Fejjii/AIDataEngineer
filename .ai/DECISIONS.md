# AIDataEngineer — Decisions

Durable ADR log. IDs: `DE-ADR-NNN`. Architecture product decisions belong to DE 001;
DE 000 records operating-system decisions only.

---

## DE-ADR-001 — Adopt hybrid local/Cloud development operating system

- **Date:** 2026-09-11
- **Status:** Accepted
- **Context:** Bootstrap DE 000 must install a workflow that will govern local Cursor,
  Cursor Cloud, GitHub, model routing, handoff, and later parallel agents.
- **Decision:** Distill proven AlphaTrade and OnePilot *workflow* mechanisms into this
  repository. Do not copy those products' trading, tenant, or application behavior.
- **Alternatives considered:** Chat-only process (rejected: not durable); OnePilot's full
  Cloud sanitizer/publisher in DE 000 (deferred until Cloud work starts).
- **Consequences:** Tracked `.ai/` + `.cursor/rules/`; gitignored handoffs; iCloud copies
  two files only; `main` is canonical; one writer per branch.

## DE-ADR-002 — Track sanitized governance; ignore private context and generated handoffs

- **Date:** 2026-09-11
- **Status:** Accepted
- **Decision:** Track `.ai/*.md` and `.cursor/rules/`. Ignore `.ai/private/`, `.ai/local/`,
  `HANDOFF.md`, `CHANGELOG_SESSION.md`, `.env*`, and local IDE state.
- **Consequences:** Fresh clones receive operating rules. Bootstrap source documents never
  enter Git. Cloud agents can read tracked policy but not private sources.

## DE-ADR-003 — Architecture is not designed in DE 000

- **Date:** 2026-09-11
- **Status:** Accepted
- **Decision:** `ARCHITECTURE.md` remains `NOT YET DESIGNED`. Owner is DE 001. No product
  backend, frontend, connectors, schemas, APIs, or orchestration in DE 000.
- **Consequences:** Implementation models must not invent architecture during bootstrap.
  Current product architecture status lives in `.ai/ARCHITECTURE.md` (DE 001: DESIGNED — PROPOSED).

## DE-ADR-004 — Model routing hierarchy

- **Date:** 2026-09-11
- **Status:** Accepted
- **Decision:** Adopt the compact policy in `.ai/MODEL_ROUTING.md`: lowest-cost model with
  high probability of success; escalate for complexity, ambiguity, blast radius, security,
  architecture, or repeated failure; never escalate merely because a task is long.
- **Consequences:** Composer 2.5 is the default coding workforce. Fable/Astra are reserved
  for architecture, security, and independent review.

## DE-ADR-005 — Branch naming, one writer, no agent push to main

- **Date:** 2026-09-11
- **Status:** Accepted
- **Decision:** `feat|fix|refactor|docs|ops/<compact_task_id>_<scope>`. One writer per
  branch. Agents never directly push `main` in normal development. Merges require review.
- **Consequences:** Parallel agents need separate task IDs and branches.

## DE-ADR-006 — Parallel agent limits

- **Date:** 2026-09-11
- **Status:** Accepted
- **Decision:** Default max 2 concurrent implementation agents; 3 only when scopes are
  clearly independent. Require explicit file ownership and integration order. Sequential
  if overlap is unclear. No parallel agents in DE 000.
- **Consequences:** High-conflict files (architecture, security, orchestration, migrations)
  have at most one writer at a time.

## DE-ADR-007 — Deferred sanitized Cloud handoff bridge

- **Date:** 2026-09-11
- **Status:** Accepted
- **Decision:** Do not install `docs/agent/CLOUD_HANDOFF.md` sanitizer scripts in DE 000.
  Local iCloud transport is enough for now. Cloud eligibility requires tracked GitHub
  state only. Revisit before the first Cloud implementation task.
- **Consequences:** First Cloud task may need a small ops follow-up to add a sanitized
  tracked handoff if private root `HANDOFF.md` proves insufficient.

---

# Product architecture decisions (DE 001)

Full records: `docs/adr/DE-ADR-0NN-*.md`. Status **PROPOSED** until the operator accepts
DE 001. DE 001R1 amended DE-ADR-011, 014, 015, 016, 022, 024 and added DE-ADR-026.
DE 001R2A amended DE-ADR-011, 013–018, 021, 022, 026 and added DE-ADR-027 after
independent GPT 5.6 Sol High review. DE 001R2B amended DE-ADR-011, 014–016, 020–022
to close residual verification findings (approval rejection routes, staging materialize-
then-approve, DE 002A Cloud eligibility, discovery exit criteria, READ_ONLY identity,
reconciliation exhaustion, lock scope, resume semantics, `CONTRACT_VERSION_UNAVAILABLE`
emitter, retry summary).

## DE-ADR-008 — Modular monolith application architecture
- **Decision:** One Python package `aide`, one image, one PostgreSQL; API + worker in-process (separable). No microservices/Kubernetes.
- **Rejected:** microservices, serverless-per-capability, Kubernetes from day one.

## DE-ADR-009 — Custom deterministic orchestration; no agent framework
- **Decision:** Plain-Python orchestrator (transition table, phase templates, worker loop). No LangGraph/LangChain/CrewAI/AutoGen.
- **Rejected:** LangGraph (hidden control flow), Temporal (deferred; re-evaluate for multi-node/long-lived workflows), batch schedulers as core.

## DE-ADR-010 — Single orchestrator + reasoning capabilities; no specialist agents
- **Decision:** One planner and eight typed, tool-less reasoning capabilities. Zero specialist agents in V1; future specialists only as sub-workflows meeting `docs/AGENT_MODEL.md` §5.
- **Rejected:** orchestrator + autonomous specialist agents; single monolithic prompt.

## DE-ADR-011 — Workflow = state machine + phase-scoped task DAG
- **Decision:** Persist phase occurrence/generation and pinned contract snapshot. Templates
  have no operation identity; fully resolved validated input precedes digest/key, policy,
  approval and attempts. Fan-out uses a new planning boundary; per-run `phase_exit_criteria`
  let DISCOVERY enumeration complete before description. Resume of PARKED/AWAITING_APPROVAL
  work does not allocate a new phase run. PostgreSQL advisory transaction lock serializes
  coordination only; connector cancel/reconcile I/O is outside the lock. Dependency
  outcomes are exhaustive. Cancellation is intent and controlled shutdown before terminal
  state.
- **Rejected:** ordered list; whole-workflow static DAG; fully dynamic LLM-driven DAG.

## DE-ADR-012 — PostgreSQL + SQLAlchemy 2 + Alembic for all state
- **Decision:** PostgreSQL 16 only stateful service; typed ORM + repositories; JSONB payloads validated by Pydantic; artifacts behind a blob-store interface.
- **Rejected:** SQLite (no SKIP LOCKED), Redis, document store, object storage now.

## DE-ADR-013 — Capability / tool / connector abstraction
- **Decision:** Versioned capability/schema contracts and connector compatibility are
  pinned per phase. Invocation effect semantics replace `idempotent: bool`. Generic
  asset/transformation contracts are separated from platform extensions.
- **Rejected:** vendor-specific tools exposed to planner; free-form function calling over SDKs.

## DE-ADR-014 — Connector protocol with real + fake and product-visible status
- **Decision:** Connectors advertise supported versions, `identity_class` and typed health;
  side effects reconcile from complete immutable context with bounded
  `EffectFound|NoEffect|InProgress|Unknown`. Artifacts carry REAL/MOCK provenance. Warehouse
  READ binds only to `identity_class=READ_ONLY` (`snowflake_ro`; `READ ∉ snowflake_dev`).
  Canonical query tags carry full operation and attempt identity.
- **Rejected:** per-test mocks only; replay-only.

## DE-ADR-015 — Deterministic policy engine and SQL safety classifier
- **Decision:** Every applicable denial rule runs; all reasons persist; authoritative
  severity `SECURITY > SCOPE > ENVIRONMENTAL` drives routing independent of order.
  Approvals evaluate only with no denial. Policy uses trusted principal/server-derived
  grants, typed health, transitive provenance, RO read identity (`identity_class=READ_ONLY`)
  and safe function/construct/scope classification. Plan validity is independent of
  temporary health. Scheduler emits `CONTRACT_VERSION_UNAVAILABLE` for missing pinned
  versions (ENVIRONMENTAL parking, not R1 fail-closed).
- **Rejected:** prompt-only guardrails; LLM safety judge; regex-only filtering; ordered permission hierarchy; uniform DENY → FAILED.

## DE-ADR-016 — Typed approval subjects with complete binding
- **Decision:** `OperationApproval`, `DesignApproval`, `BudgetIncreaseApproval` are distinct.
  Operation binding covers operation/input/artifacts/provenance/capability/connector/target/
  external state/expiry. Design grants no permission; budget authorizes explicit cap/delta.
  All simultaneous mandatory subjects approve; rejection has subject-specific routing
  including legal `APPROVAL_REQUIRED → PLANNING|COMPLETED|BLOCKED|FAILED`.
- **Rejected:** workflow-level approval; chat-based approval.

## DE-ADR-017 — Thin LLM gateway, structured outputs, versioned prompts
- **Decision:** Thin versioned gateway plus atomic worst-case budget reservation/settlement.
  Provider adapters use separate scoped, non-enumerable secret resolver views.
- **Rejected:** LangChain/LlamaIndex; LiteLLM (deferred as adapter); Instructor (unneeded).

## DE-ADR-018 — Observability: audit, telemetry tables, OpenTelemetry, structlog
- **Decision:** State mutation and audit event commit in one PostgreSQL transaction;
  locked unique per-workflow sequence; runtime writer cannot update/delete. Claim is
  transactional application audit, not cryptographic tamper evidence. Telemetry/OTel remain.
- **Rejected:** Langfuse/LangSmith as primary store; logs only.

## DE-ADR-019 — In-repo evaluation harness; no LLM judge for pass/fail
- **Decision:** `aide eval` drives YAML scenarios through Application Services; deterministic offline replay in CI as regression gate; live modes report distributions; time-saved from versioned baseline, labelled estimate.
- **Rejected:** prompt-eval frameworks as primary; LLM judges.

## DE-ADR-020 — Local vs Cloud development boundaries for product work
- **Decision:** Cloud-eligible iff tracked state + fakes/fixtures suffice + no credentials + declared files + isolated branch. **DE 002A is CLOUD** (pure contracts + minimal CI; no credentials or local persistence). **DE 002B and DE 002C remain LOCAL.** Other LOCAL: DE 005, 008, 012-live, 017, 018, 019. Architecture fully in tracked `docs/`.

## DE-ADR-021 — Parallel development lanes and unlock milestones
- **Decision:** Sequential foundation is DE 002A kernel+CI (CLOUD) → DE 002B recovery persistence
  (LOCAL) → DE 002C slice (LOCAL) → DE 003 CI expansion (CLOUD). Two agents only after all merge.

## DE-ADR-022 — In-process worker with PostgreSQL task queue
- **Decision:** `SKIP LOCKED` plus renewable lease/claim epoch; owner+epoch finalization;
  atomic recovery ownership fences stale workers. Every ambiguous side effect reconciles
  before retry; proven `NoEffect` retries only within `max_attempts` else `FAILED`; bounded
  `InProgress` cannot become absence. Cancellation lock covers coordination only; connector
  cancel/reconcile I/O is outside it.
- **Rejected:** Celery/RQ/arq + Redis; Temporal (deferred); blind re-run after lease expiry.

## DE-ADR-023 — Bounded self-repair loop
- **Decision:** Repairable classes only; evidence → novel-hypothesis proposal → deterministic validation → rebuild → re-validate; 2/task, 4/workflow, 2 rejected proposals; never weaken tests; escalate to `BLOCKED`.
- **Rejected:** retry-until-green; no auto-repair.

## DE-ADR-024 — Minimal Vite + React + TypeScript SPA
- **Decision:** Vite/React/TS SPA, React Query, SSE, Tailwind permitted, served by API image; CLI covers all flows first.
- **Rejected:** Next.js; HTMX+Jinja (viable, less demonstrable); Streamlit.

## DE-ADR-025 — Python 3.12, uv, ruff, mypy strict, pytest
- **Decision:** Python 3.12 pinned (re-verify adapter support at DE 002); uv + committed lock; ruff; mypy --strict; import-linter; pytest/asyncio/hypothesis/testcontainers; gitleaks; Node LTS + pnpm pinned.
- **Rejected:** Poetry/pip-tools; latest Python; black+isort+flake8.

## DE-ADR-026 — Contract stability: sequenced DE 002 baseline, compatible evolution afterwards
- **Decision:** DE 002A/B/C baseline pure, recovery and composition contracts only after
  their respective tests. Breaking changes require ADR + decision entry + architecture
  review. Additive capability changes need normal review/docs unless semantics or a
  boundary change. In-flight phase runs remain pinned.
- **Rejected:** freeze every field at DE 002; no explicit policy.

## DE-ADR-027 — Trusted local principal and server-authorized workflow grants
- **Decision:** Operator-provisioned local account, opaque PostgreSQL session, HttpOnly
  same-site cookie, CSRF on mutations, same-origin read-only SSE. Middleware creates
  `PrincipalRef`; clients cannot set actor/roles/effective grants. Server derives grants
  from trusted principal, role and environment policy. One V1 human may hold distinct
  operator+approver roles; production stays disabled.
- **Rejected:** caller-supplied grants; browser token storage; enterprise IAM in MVP.
