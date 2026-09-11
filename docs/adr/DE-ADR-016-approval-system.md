# DE-ADR-016 — Typed approval subjects with complete binding

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1, DE 001R2A, DE 001R2B)

## Context
Production/staging deploys, destructive actions, flagged designs and cost overruns require
human approval. An approval must not be reusable for different content.

## Decision
Approval subjects are a discriminated union:

- `OperationApproval`: operation key, resolved-input digest, artifact/provenance closure,
  capability/connector identity and versions, target, permission, relevant external-state
  digest and expiry;
- `DesignApproval`: design/validation/invariant hashes and expiry, with no permission;
- `BudgetIncreaseApproval`: ledger scope/version, unit, prior cap, explicit authorized new
  cap and delta, and expiry.

Operation approval covers attempts/reconciliation only while every bound field remains
identical. All fields are rechecked at decision and before an attempt. Design approval is
acceptance evidence, never a grant. Budget approval only updates the cap atomically.

One policy gate may require multiple subjects. Execution waits for all mandatory approvals.
Any rejection immediately prevents execution, invalidates sibling pending requirements and
follows subject-specific routing in `docs/PERMISSION_MODEL.md` §4, including legal
workflow transitions `APPROVAL_REQUIRED → PLANNING | COMPLETED | BLOCKED | FAILED`.
Decisions require a trusted principal with approver role; production remains disabled in V1.

## Alternatives
- Approve "the workflow" once: rejected — content can change after approval.
- Approve via chat message to the agent: rejected — not an authenticated, auditable action.

## Consequences
- Repairs or relevant external-state changes invalidate operation approval automatically.
- UI must render each subject and aggregate status independently.
