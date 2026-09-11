# Workflow: IMPLEMENT

Read `.ai/MASTER.md`, `.ai/MASTER_WORKFLOW.md`, `.ai/PROJECT_CONTEXT.md`,
`.ai/ARCHITECTURE.md`, `.ai/TASKS.md`, and `.ai/DECISIONS.md` first.

Statuses: `IN_PROGRESS`, `REVIEW_REQUIRED`, `BLOCKED`, `FAILED`, `READY`.

## Preconditions

- A task exists in `TASKS.md` with scope, exclusions, risk, environment, and validation.
- Architecture is approved for the slice being built. If `ARCHITECTURE.md` is
  `NOT YET DESIGNED`, do not invent product architecture here — stop or reduce to docs.
- Set `HANDOFF.md` to `IN_PROGRESS` before implementation.

## Rules

- Small, focused, typed changes. Follow existing conventions once they exist.
- Separate business logic, I/O, data access, and external services.
- No hardcoded secrets. Validate inputs at boundaries.
- Do not silently change approved architecture.
- Git writes only when the task authorizes them. Never push to `main`.

## Procedure

1. Inspect related code; confirm the simplest robust approach.
2. Stay inside expected files. Record out-of-scope discoveries in `TASKS.md`.
3. Implement with tests for behavior and failure paths.
4. Run required validation. Report exact results.
5. Update docs if behavior changed.
6. Update `TASKS.md` / `DECISIONS.md` when needed.
7. Regenerate handoff files; sync on Local Mac.
