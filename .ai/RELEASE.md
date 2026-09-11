# Workflow: RELEASE / DEPLOY

Read `.ai/MASTER.md`, `.ai/MASTER_WORKFLOW.md`, and `.ai/ENVIRONMENTS.md` first.

Deployment authority is separate from Git authority. Do not deploy unless the task
explicitly authorizes it.

## Pre-merge gate

- Inspect `git status` and the full diff.
- Secret-scan the diff.
- Run the required test/lint suite for the change.
- Confirm CI is green when CI exists.
- Confirm no architecture drift without an ADR.

## Deploy

- Staging before production.
- Production requires human approval, rollback plan, and smoke validation.
- Record the deployed SHA and environment.
- Never use production credentials in chat or handoffs.

## Rollback

Revert through a hotfix PR from current `main`. Do not reset protected `main`.

## Handoff

Regenerate `HANDOFF.md` and `CHANGELOG_SESSION.md` with exact validation evidence.
Set `REVIEW_REQUIRED` if merge or deploy is still pending.
