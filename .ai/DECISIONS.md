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
DE 001 (after independent frontier review). Date for all: 2026-09-11. DE 001R1 (same day)
amended DE-ADR-011, 014, 015, 016, 022, 024 and added DE-ADR-026; amendments are marked below.

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
- **Decision:** Deterministic workflow states with authoritative transition table; per-phase DAG (planner or template), immutable within phase; `SKIP LOCKED` claims, leases. *(Amended DE 001R1)* Each task has a stable operation identity (`idempotency_key`, never including the attempt number) and per-try `TaskAttempt` records; task state `PARKED` for legitimate work that cannot run now; `BLOCKED` resumes into the phase it left; `POLICY_CHECK` routes by deny class.
- **Rejected:** ordered list; whole-workflow static DAG; fully dynamic LLM-driven DAG.

## DE-ADR-012 — PostgreSQL + SQLAlchemy 2 + Alembic for all state
- **Decision:** PostgreSQL 16 only stateful service; typed ORM + repositories; JSONB payloads validated by Pydantic; artifacts behind a blob-store interface.
- **Rejected:** SQLite (no SKIP LOCKED), Redis, document store, object storage now.

## DE-ADR-013 — Capability / tool / connector abstraction
- **Decision:** Immutable typed `CapabilitySpec`; Tool Registry wrapper enforces validate → policy → execute → validate → audit; connectors advertise capabilities; reasoning capabilities catalogued with same discipline and no external effects.
- **Rejected:** vendor-specific tools exposed to planner; free-form function calling over SDKs.

## DE-ADR-014 — Connector protocol with real + fake and product-visible status
- **Decision:** Stable protocol; every connector ships real, deterministic fake with fault injection, error mapper, `SecretRef` config, contract tests, README; environment-bound instances with an explicit `allowed_permissions` set (membership, no ordering — *amended DE 001R1*, replaces "permission ceiling") and allow-list; status `AVAILABLE|DEGRADED|UNAVAILABLE|MOCK` (`UNAVAILABLE` parks dependent tasks). *(Amended DE 001R1)* Every connector implements `reconcile(capability, idempotency_key)` for side-effecting capabilities and propagates the operation identity into the external system; fakes support `fail_after_effect`. Fakes on DuckDB via sqlglot.
- **Rejected:** per-test mocks only; replay-only.

## DE-ADR-015 — Deterministic policy engine and SQL safety classifier
- **Decision:** Pure-function rule set R0 (startup) + R1–R20 on every call, persisted, fail-closed; sqlglot classifier (unparseable ⇒ destructive); defence in depth with identities and namespaces; property/adversarial tests mandatory. *(Amended DE 001R1)* `PermissionLevel` is one canonical, **unordered** set of nine distinct grants; all checks are set membership (workflow grants ∪ approval; connector `allowed_permissions`); ceilings and rank comparisons are forbidden and tested against. Every deny reason code maps to a deny class with deterministic routing: `ENVIRONMENTAL` → `PARKED`/`BLOCKED`; `SCOPE`/`SECURITY` → fail closed (`FAILED`, audit alert); approval-eligible → `APPROVAL_REQUIRED`. Plan validation runs the rules as a pre-check; no routing around denials once tasks exist.
- **Rejected:** prompt-only guardrails; LLM safety judge; regex-only filtering; ordered permission hierarchy; uniform DENY → FAILED.

## DE-ADR-016 — Approvals bound to artifact hashes
- **Decision:** Approval kinds `DESIGN|COST|GIT|DEPLOY|DESTRUCTIVE`; bound to artifact sha256; re-verified at decision and execution; expiry; distinct approver roles. *(Amended DE 001R1)* Bound to the logical operation (`idempotency_key`), so retries/reconciliation of the same operation are covered; eligibility by permission membership.
- **Rejected:** workflow-level approval; chat-based approval.

## DE-ADR-017 — Thin LLM gateway, structured outputs, versioned prompts
- **Decision:** Own `LLMProvider` protocol + official SDK adapters; JSON-schema structured output + one repair retry; sandboxed Jinja2 prompt files versioned; redaction; provider-reported usage × versioned price table; replay fake.
- **Rejected:** LangChain/LlamaIndex; LiteLLM (deferred as adapter); Instructor (unneeded).

## DE-ADR-018 — Observability: audit, telemetry tables, OpenTelemetry, structlog
- **Decision:** Append-only `audit_events`; `model_calls`/`tool_calls`/`workflow_metrics`; structlog JSON with redaction; OTel spans with optional OTLP exporter; redacted prompt/completion artifacts with retention.
- **Rejected:** Langfuse/LangSmith as primary store; logs only.

## DE-ADR-019 — In-repo evaluation harness; no LLM judge for pass/fail
- **Decision:** `aide eval` drives YAML scenarios through Application Services; deterministic offline replay in CI as regression gate; live modes report distributions; time-saved from versioned baseline, labelled estimate.
- **Rejected:** prompt-eval frameworks as primary; LLM judges.

## DE-ADR-020 — Local vs Cloud development boundaries for product work
- **Decision:** Cloud-eligible iff tracked state + fakes/fixtures suffice + no credentials + declared files + isolated branch. LOCAL: DE 002, 005, 008, 012-live, 017, 018, 019. Architecture fully in tracked `docs/`.

## DE-ADR-021 — Parallel development lanes and unlock milestones
- **Decision:** Waves per `docs/IMPLEMENTATION_PLAN.md` §4; 2 agents after DE 002 + DE 003 merge; 3 after Wave 2 merges; high-conflict areas single-writer; workstream manifest before multi-agent waves.

## DE-ADR-022 — In-process worker with PostgreSQL task queue
- **Decision:** asyncio worker claims task rows (`SKIP LOCKED`), leases, thread pools for blocking SDKs, subprocess dbt; `aide worker` separable. *(Amended DE 001R1)* Attempt intent is persisted before the handler runs; on lease expiry the worker reconciles through the connector before any re-execution; found effect → adopted (`RECOVERED`); absent → retry with the same operation identity; unknown outcome of a non-idempotent capability (`deploy`) → `AMBIGUOUS_OUTCOME`, parked for a human, never auto-repeated.
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

## DE-ADR-026 — Contract stability: baseline in DE 002, compatible evolution afterwards *(DE 001R1)*
- **Decision:** DE 002 establishes the architecture **baseline** for core contracts (`docs/IMPLEMENTATION_PLAN.md` §5.2), not a permanent freeze. Breaking changes (remove/rename/retype fields, semantic or transition changes, removed enum members) require an ADR + `.ai/DECISIONS.md` entry + higher-tier architecture review. Additive, backward-compatible changes are allowed inside the implementing task when all existing tests remain valid and pass unchanged, and are mirrored into `docs/` in the same PR. Contracts count as exercised after DE 005 and DE 008 merge.
- **Rejected:** freeze every field at DE 002; no explicit policy.
