# Workflow: BUGFIX

Read `.ai/MASTER.md` and `.ai/MASTER_WORKFLOW.md` first.

## Procedure

1. Reproduce: exact command, input, expected vs actual, environment.
2. Write or identify a failing test that encodes the bug.
3. Find root cause; prefer the minimal correct fix.
4. Confirm the new test passes and no regressions appear.
5. Check security and architecture impact.
6. Run required validation; update docs if needed.
7. Regenerate handoff files; sync on Local Mac.

## Rules

- No behavior change beyond the fix scope.
- Never mask errors silently.
- If the fix cannot be verified, set `FAILED`. If a protected action is required, set
  `REVIEW_REQUIRED`. Sync immediately in either case.
