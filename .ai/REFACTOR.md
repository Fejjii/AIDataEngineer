# Workflow: REFACTOR (no behavior change)

Read `.ai/MASTER.md` and `.ai/MASTER_WORKFLOW.md` first.

## Rules

- Behavior must be preserved. Public APIs and outputs unchanged.
- No functional, security, or architecture-policy changes unless the task says so.
- Keep diffs scoped.

## Procedure

1. Establish a green baseline before touching code.
2. Refactor in small steps; keep tests green after each step.
3. Improve naming, reduce nesting/duplication, strengthen typing.
4. Re-run required validation.
5. Note structural decisions in `DECISIONS.md` if significant.
6. Regenerate handoff files; sync on Local Mac.
