# Unified agent handoff — tracked run reports

**Version:** 1.1  
**Project:** AI Data Engineer  
**Task prefix:** DE (product) · OPS (operations)  
**Authority:** `.ai/MASTER_WORKFLOW.md` (operating system); this document defines the tracked
run-report contract for Local and Cloud agents.

This file is **tracked** and sanitized. It contains no secrets, tokens, passwords, private
keys, bootstrap source contents, or sensitive environment values.

---

## 1. Two-plane handoff model

| Plane | Location | Tracked | Audience |
|-------|----------|---------|----------|
| **Operational (private)** | Repo root `HANDOFF.md`, `CHANGELOG_SESSION.md` | No (gitignored) | Local Mac operator; iCloud transport |
| **Run report (public)** | `docs/agent/runs/<TASK_ID>/<SESSION_ID>.md` | Yes | GitHub, Cloud agents, reviewers, parallel coordination |

**Local agents** regenerate private operational files **and** commit one run report per session
when the task authorizes Git writes.

**Cloud agents** cannot rely on private files. They **must** create a run report on the task
branch before push/PR. They may still regenerate private handoffs in the worktree for
continuity, but those files must never be staged.

Private paths remain gitignored:

- `HANDOFF.md`
- `CHANGELOG_SESSION.md`
- `.ai/private/`
- `.ai/local/`

---

## 2. Run report path (collision-safe)

Every agent run creates exactly **one** report at:

```text
docs/agent/runs/<TASK_ID>/<SESSION_ID>.md
```

Examples:

```text
docs/agent/runs/OPS001/OPS001-SESSION-20260911T152424Z.md
docs/agent/runs/DE002A/DE002A-SESSION-20260911T090000Z.md
```

**Collision rules:**

- `<TASK_ID>` is the compact task identifier (`OPS001`, `DE002A`, `DE000`, …).
- `<SESSION_ID>` must be **unique per run**. Never overwrite an existing report.
- Prefer `<TASK_ID>-SESSION-<UTC-timestamp>` (compact ISO 8601, no colons: `YYYYMMDDTHHMMSSZ`).
- Cloud agents may append a short Cursor run suffix when two runs start in the same second:
  `…Z-bc01a091`.
- Parallel agents on the **same task** must use different session IDs and **different branches**
  (one writer per branch). If two agents share a task ID, they still require distinct session
  IDs and branches — file ownership must not overlap.

---

## 3. Allowed run-report statuses

Use **only** these terminal or handoff statuses in run reports:

```text
SUCCESS
PARTIAL
BLOCKED
FAILED
REVIEW_REQUIRED
```

Do **not** use `IN_PROGRESS`, `READY`, or `DRAFT` in run reports. Active work belongs in
private `HANDOFF.md` (status `IN_PROGRESS`) until the run ends.

| Status | Meaning |
|--------|---------|
| `SUCCESS` | Stated scope complete and validated; ready for human review/merge when applicable. |
| `PARTIAL` | Some scoped work landed safely; remaining scope documented with clear next steps. |
| `BLOCKED` | Technical or environmental issue prevents safe progress after scoped diagnostics. |
| `FAILED` | Task or critical validation failed; repository left safe and documented. |
| `REVIEW_REQUIRED` | Human decision, approval, credential, or protected action required before continuing. |

Private operational handoffs (`HANDOFF.md`) retain their own status model:
`IN_PROGRESS`, `REVIEW_REQUIRED`, `BLOCKED`, `FAILED`, `READY`.

---

## 4. Required run-report fields

Each report **must** include all sections below. Write `None` rather than omitting a section.

1. **Task ID**
2. **Session ID**
3. **Environment** (`LOCAL`, `CURSOR_CLOUD`, `GITHUB_ACTIONS`, …)
4. **Model**
5. **Reasoning level**
6. **Branch**
7. **Base commit** (SHA at branch creation or task start)
8. **Implementation commit** (SHA of the commit that contains the substantive scoped work —
   not the SHA of a commit that only updates the run report)
9. **Report status** (from §3)
10. **Goal**
11. **Scope completed**
12. **Files changed** (created, modified, removed — paths only)
13. **Tests executed** (exact commands or `None`)
14. **Test results** (honest outcomes; never claim pass without evidence)
15. **Validation** (checks run and outcomes)
16. **Errors**
17. **Blockers**
18. **Important decisions**
19. **Architecture deviations** (`None` unless ADR-worthy)
20. **Open questions**
21. **Human action required**
22. **Recommended next task**
23. **PR number** (when applicable; otherwise `None`)

**Do not** record the SHA of the commit that contains the run report itself. That creates a
self-reference loop: updating the report to store the branch tip adds another commit and changes
the tip again.

Obtain these from Git history instead:

- **Authoritative report commit:** `git log -1 --format=%H -- docs/agent/runs/<TASK_ID>/<SESSION_ID>.md`
- **Current branch tip:** `git rev-parse <branch>` on the task branch

The report stores stable task identifiers (`Base commit`, `Implementation commit`, `Report
status`, `PR number`). Ephemeral tip SHAs belong in Git metadata, not in the report body.

### Parallel-agent extensions (required when launching or coordinating parallel work)

Add these subsections under **Parallel coordination** when more than one agent may run:

- **Declared file ownership** (expected files this task may touch)
- **Forbidden files** (when relevant; otherwise `None`)
- **Dependencies** (task IDs or merges required first)
- **Integration order** (when relevant; otherwise `None`)

---

## 5. Run report template

Copy into `docs/agent/runs/<TASK_ID>/<SESSION_ID>.md`:

```markdown
# Run report — <TASK_ID>

| Field | Value |
|-------|-------|
| Task ID | <TASK_ID> |
| Session ID | <SESSION_ID> |
| Environment | <LOCAL\|CURSOR_CLOUD\|…> |
| Model | <model> |
| Reasoning level | <low\|medium\|high\|max> |
| Branch | <branch> |
| Base commit | <sha> |
| Implementation commit | <sha of substantive work commit> |
| Report status | <SUCCESS\|PARTIAL\|BLOCKED\|FAILED\|REVIEW_REQUIRED> |
| PR number | <number or None> |

## Goal

## Scope completed

## Files changed

## Tests executed

## Test results

## Validation

## Errors

## Blockers

## Important decisions

## Architecture deviations

## Open questions

## Human action required

## Recommended next task

## Parallel coordination

- **Declared file ownership:**
- **Forbidden files:**
- **Dependencies:**
- **Integration order:**
```

Never include secrets, tokens, passwords, private keys, private bootstrap material, or
sensitive environment values. Reference environment-variable **names** only.

---

## 6. Workflow integration

### Local agent finish checklist

1. Regenerate `HANDOFF.md` and `CHANGELOG_SESSION.md`.
2. Run `~/.local/bin/sync-aidataengineer-handoff.sh` and verify SHA256 + `cmp`.
3. Create the run report on the task branch; record `Implementation commit` (substantive work
   SHA) and `Base commit`. Do not record the report-containing commit SHA.
4. Commit and push the task branch (when Git writes are authorized).
5. Open or update PR; record PR number in the run report if not known at first commit.
   Do not add commits solely to update a branch-tip SHA inside the report.

### Cloud agent finish checklist

1. Create the run report on the task branch (mandatory before push).
2. Optionally regenerate private handoffs locally in the worktree (never stage them).
3. Commit and push only task-scoped tracked changes.
4. Open PR targeting `main`; add PR number to the run report when known (one content update
   is acceptable; never chase branch-tip SHAs in the report).
5. Do not merge `main`; do not write iCloud.

### Human review

Reviewers use run reports plus PR diff as durable evidence. Private handoffs supplement Local
Mac continuity only.

---

## 7. Validation expectations (ops tasks)

For governance-only tasks (no product code):

- Confirm `docs/agent/CLOUD_HANDOFF.md` and `docs/agent/runs/` exist.
- Confirm private paths remain in `.gitignore`.
- Secret scan on changed tracked files.
- Confirm no two reports share the same `<TASK_ID>/<SESSION_ID>` path.
- Confirm governance documents agree (no conflicting handoff instructions).

---

## 8. Related documents

- `.ai/MASTER_WORKFLOW.md` — master operating system
- `.ai/HANDOFF_TEMPLATE.md` — private operational handoff template
- `.ai/SESSION_TEMPLATE.md` — private session changelog template
- `.ai/TASKS.md` — task contracts and parallel integration order
- `.cursor/rules/50-handoff.mdc` — Cursor rule summary
