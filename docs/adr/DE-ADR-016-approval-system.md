# DE-ADR-016 — Approvals bound to artifact hashes

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1)

## Context
Production/staging deploys, destructive actions, flagged designs and cost overruns require
human approval. An approval must not be reusable for different content.

## Decision
`Approval` records reference workflow, task, kind (`DESIGN | COST | GIT | DEPLOY |
DESTRUCTIVE`), requested permission, and the sha256 of every artifact the action would
use. Hashes are re-verified at decision time and at execution time; any change invalidates
the approval. Approvals expire (default 7 days). Approver roles are distinct from
requesters; production approvals (when enabled) require a distinct role. The workflow
parks in `APPROVAL_REQUIRED` and resumes to a kind-specific state.

An approval is bound to one **logical operation** (the task's `idempotency_key`), not to
one execution attempt (DE 001R1): retries and crash reconciliation of the same operation
with unchanged artifact hashes are covered; a new operation needs a new approval. Approval
eligibility is by permission membership (`STAGING_DEPLOY`; `DESTRUCTIVE` in DEV), never by
rank.

## Alternatives
- Approve "the workflow" once: rejected — content can change after approval.
- Approve via chat message to the agent: rejected — not an authenticated, auditable action.

## Consequences
- Repairs after an approval request invalidate the approval automatically.
- UI must show exactly what is approved (action, target, artifacts, validation, cost).
