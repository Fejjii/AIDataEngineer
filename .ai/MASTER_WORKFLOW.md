# AIDataEngineer Master Development Workflow

**Version:** 1.0
**Project:** AI Data Engineer
**Task prefix:** DE / compact DE000
**Canonical branch:** `main`
**Canonical local path:** `~/Developer/AIDataEngineer`

This document is the single master standard for local Cursor work, Cursor Cloud, GitHub,
model routing, handoff, synchronization, and parallel agents. It is development operating
policy, not product architecture.

Installing or updating this workflow must not implement product functionality.

---

## 1. Core operating principles

1. The repository and verified execution evidence have higher authority than chat history.
2. Tracked governance files define durable project rules.
3. `HANDOFF.md` is the current operational state (gitignored).
4. `CHANGELOG_SESSION.md` is the latest execution record only (gitignored).
5. Chat transcripts are context, not durable project truth.
6. Every claim must be based on verified repository, test, CI, or runtime evidence.
7. Unknown or unverified facts must be marked explicitly as UNKNOWN.
8. Safety rules take precedence over speed and convenience.
9. A blocker must be synchronized immediately rather than waiting for task completion.
10. Architecture may not be silently changed after it is approved.

---

## 2. Source-of-truth hierarchy

When information conflicts, use this order:

1. Safety, security, and secret-handling constraints in tracked project rules
2. Current repository code and configuration
3. Automated test, CI, and validation evidence
4. Deployment or runtime evidence
5. `.ai/DECISIONS.md`
6. `.ai/ARCHITECTURE.md` (current: ACCEPTED)
7. `.ai/TASKS.md`
8. `.ai/MASTER_WORKFLOW.md` and other tracked `.ai/` policy
9. Current `HANDOFF.md`
10. Current `CHANGELOG_SESSION.md`
11. ChatGPT or Cursor conversation text

Never change code merely to make an outdated document appear correct. Update the document
to reflect verified reality.

Truth planes:

| Plane | Authority |
|-------|-----------|
| Protected `main` after merge | Canonical integrated product code |
| Task-owned branch + working tree | In-flight code for that task |
| Local `.ai/private/`, `.ai/local/`, root handoffs | Private development context |
| Tracked `.ai/*.md` and `.cursor/rules/` | Sanitized durable policy, visible to Cloud |
| iCloud copies of handoff files | Transport only, never a repository |
| Chat history | Disposable context |

---

## 3. Canonical paths

```text
~/Developer/AIDataEngineer
~/Developer/AIDataEngineer/HANDOFF.md
~/Developer/AIDataEngineer/CHANGELOG_SESSION.md
~/Library/Mobile Documents/com~apple~CloudDocs/AI-Projects/AIDataEngineer/
~/.local/bin/sync-aidataengineer-handoff.sh
~/Library/LaunchAgents/com.sofien.aidataengineer-handoff-sync.plist
```

If the active repository is under Desktop, Documents, Downloads, iCloud Drive, Dropbox, or
another consumer sync folder, stop and set status `REVIEW_REQUIRED` with a relocation plan.

---

## 4. Task lifecycle

Every Cursor task follows this lifecycle.

### Inspect

Before changing anything, verify:

- absolute repository path is `~/Developer/AIDataEngineer`;
- current branch and commit;
- Git status and uncommitted work;
- relevant project rules and the current task;
- Git authority and deployment authority for this task;
- environment (LOCAL / CURSOR_CLOUD / GITHUB_ACTIONS / application env);
- safety posture.

Do not overwrite or discard unrelated work.

### Start

1. Set `HANDOFF.md` to `IN_PROGRESS`.
2. Record task, phase, baseline commit, goal, definition of done, and exclusions.
3. Replace `CHANGELOG_SESSION.md` for this execution session.
4. On Local Mac, run the sync script and verify copies.

### Implement in scoped phases

At each major phase boundary, update both operational files and sync. Continue only when
the next phase is safe and authorized.

### Validate

Use the narrowest relevant checks first, then broader regression checks. Record exact
command, exit status, result counts, skipped checks, and honest gaps.

### Finish

Set `READY` only when the stated scope is complete and validated. Otherwise use
`REVIEW_REQUIRED`, `BLOCKED`, or `FAILED`. Always regenerate both operational files.

When Git writes are authorized, also create or update the tracked run report on the task
branch per `docs/agent/CLOUD_HANDOFF.md` and record the PR number when applicable.

---

## 5. Handoff status model

Use only:

```text
IN_PROGRESS
REVIEW_REQUIRED
BLOCKED
FAILED
READY
```

Do not use `DRAFT`.

| Status | Meaning |
|--------|---------|
| `IN_PROGRESS` | Work is active and can continue safely without human intervention. |
| `REVIEW_REQUIRED` | A human decision, approval, credential, or protected action is required. Stop before the protected action. |
| `BLOCKED` | A technical or environmental issue prevents safe progress after scoped diagnostics. |
| `FAILED` | The task or a critical validation failed. Leave the repository safe and documented. |
| `READY` | Stated scope is complete, validated, synchronized, and ready for the next task. |

Never mark a task complete when a required approval, merge, deployment, verification, or
external access step is still pending.

---

## 6. Local development workflow

Use LOCAL when the task needs private AI context, Mac tooling, local credentials, iCloud
synchronization, local Docker, or controlled live access.

Typical loop:

```text
ChatGPT or operator issues a bounded task
→ Local Cursor inspects repo and rules
→ HANDOFF = IN_PROGRESS
→ Sync iCloud
→ Implement on a task-owned branch
→ Validate
→ Update TASKS.md / DECISIONS.md
→ Regenerate HANDOFF + CHANGELOG_SESSION
→ Sync iCloud
→ Operator reviews
```

Local Cursor is not automatically authorized to bypass branch protection, force-push,
print secrets, or mutate production systems.

---

## 7. Cursor Cloud workflow

Use CURSOR_CLOUD when the task is reproducible entirely from tracked GitHub state, no
local private files are required, no production secrets are required, and the task can
operate on an isolated branch.

Cloud agents:

- read tracked `.ai/` governance, `.cursor/rules/`, and repository code;
- must not assume `.ai/private/`, `.ai/local/`, root `HANDOFF.md`, iCloud, local `.env`,
  or Git stash exist;
- work on their own task branch from the authorized base SHA;
- commit and push only on that branch when the task authorizes Git writes;
- **create one tracked run report** at
  `docs/agent/runs/<TASK_ID>/<SESSION_ID>.md` before push (mandatory);
- open a pull request into `main`;
- do not merge `main`;
- do not write iCloud;
- may regenerate `HANDOFF.md` / `CHANGELOG_SESSION.md` in the Cloud worktree for continuity,
  but must **never stage** those gitignored files;
- summarize evidence in the PR body and in the run report.

Tracked run reports are defined in `docs/agent/CLOUD_HANDOFF.md`. Allowed run-report
statuses: `SUCCESS`, `PARTIAL`, `BLOCKED`, `FAILED`, `REVIEW_REQUIRED`. Private operational
handoffs retain `IN_PROGRESS`, `REVIEW_REQUIRED`, `BLOCKED`, `FAILED`, `READY`.

Cloud execution is not allowed for a task that forbids it.

---

## 8. GitHub workflow

- `main` is the canonical integrated product branch.
- Future implementation tasks use isolated branches.
- Agents must never directly push to `main` during normal development.
- Merges require human review. CI must be green when CI exists.
- Do not bypass branch protection or use admin merge paths.
- Verify remote merge state before claiming a merge gate complete.

Pull request workflow:

1. Branch from the intended `main` SHA.
2. Implement and validate on the branch.
3. Push the task branch.
4. Open a PR targeting `main` with task ID, scope, tests, and risks.
5. Human reviews diff, CI, security impact, and architecture drift.
6. Human merges.
7. Local fetches merged state before the next task.

---

## 9. Branch policy

Naming:

```text
feat/<task_id>_<scope>
fix/<task_id>_<scope>
refactor/<task_id>_<scope>
docs/<task_id>_<scope>
ops/<task_id>_<scope>
```

Use compact identifiers in branch names: `DE000`, `DE001`.

Examples: `feat/DE001_mvp_architecture`, `fix/DE012_snowflake_retry`.

Ownership:

- One writer per branch.
- The active task owns the branch until PR integration or explicit abandonment.
- Parallel agents require separate task IDs and branches.
- Do not create an architecture branch during DE 000.

Canonical `main` receives product code only through reviewed merges.

---

## 10. Task identifiers

Human-facing: `DE 000`, `DE 001`, `DE 002`.

Compact (filenames, branches): `DE000`, `DE001`, `DE002`.

Record history in `.ai/TASKS.md`. Record architectural decisions in `.ai/DECISIONS.md`
as `DE-ADR-NNN`.

Each task must declare: title, status, goal, definition of done, scope, exclusions,
dependencies, risk, owner, environment, recommended model, expected files, forbidden
files when needed, and validation criteria.

Do not reuse task IDs. Close or supersede explicitly.

---

## 11. Git authority and Cloud authority

| Action | Default authority |
|--------|-------------------|
| Inspect, plan, implement on a task branch | Agent, within task scope |
| Commit / push on the owned feature branch | Only if the task explicitly authorizes Git writes |
| Push to `main` | Forbidden in normal development |
| Merge to `main` | Human |
| Force-push, rebase onto protected history, history rewrite | Forbidden unless the operator explicitly requests it |
| Create GitHub repository | Only when the current task authorizes it |
| Deploy, mutate hosting, change production config | Human (deployment authority) |
| Cloud agent launch | Only when the task is Cloud-eligible |

Git authority is not deployment authority. A Git write does not authorize a release.

Before any approved Git write: inspect the full diff, exclude unrelated changes, scan for
secrets, run required validation, and update the handoff.

A dirty working tree is not automatically an error. Describe it accurately and preserve it
unless this task owns the changes.

---

## 12. Human approval gates

Stop and set `REVIEW_REQUIRED` before:

- merge to `main`;
- deployment or production config change;
- secret or credential entry;
- production data mutation, deletion, or unrestricted warehouse writes;
- identity, network, or security setting changes;
- destructive Git operations;
- installing privileged software or unexpected LaunchAgents;
- any action the task did not authorize.

Do not ask the operator to paste tokens or secrets into Cursor chat. Name the env var and
the place to enter it.

---

## 13. Failure, context exhaustion, and quota interruption

On failure, blocker, partial completion, context exhaustion, model quota interruption,
credential failure, or environment failure:

1. Stop further speculative changes.
2. Preserve the branch and working tree.
3. Never reset, force-push, or discard unknown work.
4. Record the last successful step, failing command, exit status, and files modified.
5. Run only non-destructive diagnostics.
6. Set the correct status (`BLOCKED`, `FAILED`, or `REVIEW_REQUIRED`).
7. Regenerate `HANDOFF.md` and `CHANGELOG_SESSION.md`.
8. Sync iCloud when on Local Mac.
9. Provide one exact recovery prompt, not multiple speculative paths.

Context exhaustion: persist state in files immediately. Do not leave the only copy of
progress in chat.

Quota interruption: preserve state, recommend the lowest-cost adequate model for the
remaining bounded work, and do not retry the same expensive model in a loop.

---

## 14. Handoff regeneration rules

### Private operational handoffs (Local primary)

Regenerate `HANDOFF.md` after:

- success;
- failure;
- blocker;
- partial completion;
- review requirement;
- context exhaustion;
- model quota interruption;
- credential failure;
- environment failure;
- task start and every major phase boundary.

`HANDOFF.md` is a compact current-state snapshot, not a historical log. Required fields
are defined in `.ai/HANDOFF_TEMPLATE.md`.

Normalized self-hash: hash the document with the entire `Source File SHA256:` line
removed, then write that digest into the field. The sync script verifies actual bytes
independently with SHA256 and `cmp`.

### Tracked run reports (Local and Cloud)

Every agent run that commits to a task branch must add exactly one sanitized run report at
`docs/agent/runs/<TASK_ID>/<SESSION_ID>.md`. See `docs/agent/CLOUD_HANDOFF.md` for required
fields, allowed statuses, session ID format, and parallel coordination extensions.

Run reports are the durable GitHub-visible evidence. Private root handoffs remain
gitignored and are not a substitute for run reports on Cloud branches.

---

## 15. CHANGELOG_SESSION rules

`CHANGELOG_SESSION.md` represents the current execution session only. Do not turn it into
an infinite historical log. Durable history lives in Git, `TASKS.md`, and `DECISIONS.md`.

Required sections are defined in `.ai/SESSION_TEMPLATE.md`.

---

## 16. Local versus Cloud environment selection

```text
Needs private local state, local credentials, Mac tooling, iCloud, or controlled live access?
  YES → LOCAL
  NO  ↓
Reproducible from tracked GitHub state, no production secrets, isolated branch?
  YES → CURSOR_CLOUD candidate
  NO  → LOCAL or redesign the task
Deterministic validation only?
  YES → GITHUB_ACTIONS
Host, production data, or production credential action?
  YES → operator-gated application environment, never implicit agent scope
```

See `.ai/ENVIRONMENTS.md`.

---

## 17. Parallel work rules

Default maximum: **2** concurrent implementation agents.

Allow **3** only when scopes are clearly independent.

Do not launch parallel agents during DE 000.

Parallel tasks require:

- different task IDs;
- different branches;
- **different session IDs** and **one run report each** at
  `docs/agent/runs/<TASK_ID>/<SESSION_ID>.md` (never overwrite);
- explicit owner;
- explicit expected files (declared file ownership);
- explicit forbidden files when needed;
- recorded base commit and implementation commit in each run report (not the report-containing
  commit SHA — obtain report commit and branch tip from Git history);
- declared dependencies;
- defined integration order when branches must merge in sequence;
- no conflicting migrations;
- no conflicting central architecture edits;
- no conflicting orchestration state edits;
- no conflicting security boundary edits;
- relevant tests after integration.

If overlap is unclear, execute sequentially.

After sequential integration, later branches refresh against the merged predecessor.
Prefer merge commits into `main` via PR. Do not rebase protected `main`. On feature
branches, prefer merge from updated `main` over history rewrite unless the operator
explicitly requests a rebase.

---

## 18. File ownership

Each task contract must list expected files and, when useful, forbidden files.

High-conflict files (architecture docs, CI, shared schemas, security boundaries,
orchestration state, migrations) have at most one writer at a time.

No file-level lock daemon is installed. Enforcement is the task contract plus one writer
per branch. Violation is a blocker, not a race to overwrite.

---

## 19. Integration ordering

When multiple branches exist:

1. Record the intended merge order in `TASKS.md` before launch.
2. Merge the first branch through PR + human review + CI.
3. Refresh remaining branches from the new `main`.
4. Resolve conflicts on the remaining task branch, not on `main`.
5. Re-run relevant tests after each integration.
6. Do not interleave conflicting migrations.

---

## 20. Architecture freeze

After DE 001 architecture is accepted:

- cheaper implementation models must not silently change it;
- deviations require an ADR and, for material changes, a higher-tier review;
- implementation tasks consume the architecture; they do not rediscover it.

Architecture status is `ACCEPTED` (`.ai/ARCHITECTURE.md`; operator acceptance 2026-09-11). Implementation (DE 002+) may proceed per `.ai/TASKS.md`.

Acceptance baselines the architecture; contracts evolve additively under DE-ADR-026 when
existing tests remain valid and pass unchanged. Breaking semantic changes still require an
ADR and architecture review.

---

## 21. Security boundaries and secret handling

Never place in handoffs, changelogs, tracked governance, logs, prompts, or screenshots:

- API keys, tokens, passwords, private keys;
- connection strings with credentials;
- unredacted authorization headers;
- production data extracts;
- bootstrap source documents that were designated private.

Secrets live in environment variables or a secret manager. Variable names may be
referenced; values may not.

When a secret is required: `REVIEW_REQUIRED`, name the env var, tell the operator where
to enter it, never ask for the value in chat.

Least privilege. Fail closed on ambiguous permissions. Production mutations require
approval. Bootstrap sources remain in ignored `.ai/private/`.

---

## 22. Model selection and escalation

See `.ai/MODEL_ROUTING.md`.

Principle: use the lowest-cost model with a high probability of success.

Escalate because of complexity, ambiguity, blast radius, security risk, architectural
impact, or repeated failure. Do not escalate merely because a task is long.

Do not use Fable or Astra for routine implementation.

Do not allow cheaper implementation models to silently change approved architecture.

Prefer standard speed for autonomous work. Pay for Fast only when latency has clear value.

---

## 23. Human review and CI validation

Human review is required for merge to `main`, security-sensitive changes, architecture
changes, and production actions.

When CI exists, PRs must pass it before merge. Never claim CI passed if it was not run.
Distinguish local, CI, staging, and production evidence. Include commit SHA for remote
validation.

Until application CI exists, local deterministic checks plus honest reporting are required.

---

## 24. Rollback principles

Before merge: fix or abandon the task branch. `main` stays clean.

After merge: open a revert or hotfix branch from current `main` and PR it. Do not reset
or force-push protected `main`.

After deployment: record last known good SHA and release identifier. Revert through the
same controlled release path and validate before declaring recovery complete.

---

## 25. iCloud handoff transport

Copy only `HANDOFF.md` and `CHANGELOG_SESSION.md`. Never synchronize secrets, `.git`,
source code, virtualenvs, or the repository.

The sync script must: fail on errors; use absolute quoted paths; copy atomically; verify
copies with SHA256 and `cmp`; remain idempotent; skip identical files without rewriting
timestamps.

On Local Mac, run:

```bash
~/.local/bin/sync-aidataengineer-handoff.sh
```

---

## 26. Testing standard

1. Identify the smallest relevant validation set.
2. Run targeted tests during implementation.
3. Run broader affected regressions before completion.
4. Never claim a suite passed if it was not run.
5. Record skipped tests and the reason.
6. Treat flaky evidence conservatively.

For DE 000, validation is deterministic bootstrap checks, ignore verification, secret
scan, and GitHub remote confirmation — not product tests.

---

## 27. Standard operating loop

1. Operator or ChatGPT reviews the latest `HANDOFF.md` and GitHub evidence.
2. Select one task, model, reasoning level, environment, and size.
3. Cursor verifies repository state against the task contract.
4. Cursor creates or enters the task-owned branch.
5. Cursor implements only the scoped work.
6. Cursor runs required validation.
7. Cursor updates `TASKS.md` / `DECISIONS.md` when local.
8. Cursor regenerates HANDOFF and CHANGELOG regardless of success or block.
9. Cursor creates the tracked run report on the task branch when Git writes are authorized.
10. Local: sync to iCloud. Cloud: commit/push branch and open PR when authorized.
11. Human reviews and merges protected `main`.
12. Next bounded task.
