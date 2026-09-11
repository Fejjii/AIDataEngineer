# Workflow: AUDIT (inspect and report only)

Read `.ai/MASTER.md` and `.ai/MASTER_WORKFLOW.md` first.

## Rules

- Read-only toward application code. No product implementation.
- No Git mutations unless the task explicitly authorizes documentation-only commits.
- Use verified facts. Mark unknowns as UNKNOWN. Never print secrets.

## Procedure

1. Confirm repo path, branch, commit, and `git status`.
2. Map relevant modules; cite exact paths.
3. Produce findings: what is true, what is risky, what is unknown.
4. Record durable conclusions in `DECISIONS.md`; queue follow-ups in `TASKS.md`.
5. Regenerate `HANDOFF.md` and `CHANGELOG_SESSION.md`; sync on Local Mac.

## Output

Structured report (facts → risks → recommendations). No silent product changes.
