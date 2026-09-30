# Simply AI recovery and execution adapter

This adapter reuses the prepared DATA_PILOT_ONBOARD_001 workflow mapping. Its
historical branch, registration and completed reports remain unchanged. Current
scope is DATA_PILOT_SIMPLY_ONBOARD_FINAL_ACCEPTANCE_001, not another product objective.

## Sources and ownership

GitHub main is integrated product truth; an explicitly owned task branch and
worktree hold unmerged work. Read `.ai/MASTER_WORKFLOW.md`, the current project
handoff, actual Git state and all open PRs before resuming. Preserve other
executors and historical branches, especially `audit/final_acceptance_001`.
Use one writer per task branch. Private `HANDOFF.md` and `CHANGELOG_SESSION.md`
remain ignored; one sanitized tracked run report follows `CLOUD_HANDOFF.md`.

Simply_AI keeps the task's recovery evidence under
`infrastructure_evidence/data-pilot-final-acceptance-001/`. The task-owned
worktree handoff records its exact path, owner, base SHA, changed files, tests,
active processes, unfinished phase and resume instructions. Retain hashes and
byte counts for validation artifacts. Do not invoke an original-checkout-bound
sync script from an isolated worktree.

## Current checkpoint policy

The operator's POLICY_ACTIVE direction forwarded on 2026-09-30 supersedes
administrative checkpoint, coordinator acknowledgement and synchronization stop
gates. Continue authorized product execution from verified project state with
lightweight local recovery and existing authorized GitHub evidence. Record
Notion as unsynchronized when unavailable; never claim mirror success. Do not
change the SOF-owned checkpoint or impersonate its owner. This exception grants
no merge, deployment, credential, paid-provider or broader product authority.

## Routing and validation

Keep Cursor when it is already executing authorized work. Codex may execute an
explicitly selected or unavailable-Cursor task on a separate owned branch.
Use Grok review when available within authority; otherwise use a fresh,
independent read-only Codex review. Never repeat an ambiguous provider request.
Run bounded relevant tests against isolated synthetic data. Keep independent
business correctness separate from evidence-verifier PASS. Preserve explicit
human UAT as NOT_RUN until the operator actually completes it.

## Recovery

Reconcile fresh main, open PRs, branch ownership and local process evidence.
Resume only the unfinished phase on the existing task branch; do not redispatch
completed onboarding or historical acceptance. A local checkpoint is recovery
state, not approval. Publish authorized changes through one PR with CI and review.
Stop before merge, deployment/redeployment, staging/production actions or new
paid spend. Credentialed live Snowflake remains gated unless separately authorized.
