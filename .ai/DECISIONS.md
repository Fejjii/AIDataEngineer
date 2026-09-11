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
