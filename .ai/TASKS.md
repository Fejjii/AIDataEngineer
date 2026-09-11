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
- Status: TODO
- Owner: unassigned
- Environment: LOCAL (requires private bootstrap sources and architecture freeze)
- Proposed branch: `feat/DE001_mvp_architecture`
- Dependencies: DE 000
- Risk: High (architectural blast radius)
- Goal: Design system boundaries, agent responsibilities, tool contracts, permission
  tiers, approval gates, audit logging, Snowflake/dbt/GitHub connector contracts, and
  repository structure. Produce `.ai/ARCHITECTURE.md`. Do not implement the product.
- Explicit exclusions: No backend/frontend implementation, no live connectors, no schemas
  applied to real warehouses.
- Validation: Architecture document complete; ADRs recorded; independent higher-tier
  review recommended before implementation.
- Recommended model: Claude Fable 5.1 High (architecture inside Cursor). Independent
  GPT 6 Astra review after the draft.
- Estimated duration: 2–4 hours
- Estimated token class: L
