# AIDataEngineer — MASTER (AI Collaboration Index)

> Version-controlled project governance for AI assistants (not application code).
> This `.ai/` layer and `.cursor/rules/` are committed so any clone gets the same guidance.
> Generated handoff artifacts (`HANDOFF.md`, `CHANGELOG_SESSION.md`) stay gitignored.
> Machine-local or sensitive material lives under ignored `.ai/local/` or `.ai/private/`.

## Authoritative workflow standard

**`.ai/MASTER_WORKFLOW.md` is the single source of truth for the development operating system.**
When this index or any other workflow doc conflicts with `MASTER_WORKFLOW.md`, follow
`MASTER_WORKFLOW.md` and update the other file.

The repository, Git history, and verified execution evidence have higher authority than chat history.

## Project identity

| Field | Value |
|-------|-------|
| Project name | AI Data Engineer |
| Product name | Data Pilot AI |
| Repository | AIDataEngineer |
| Task prefix | DE |
| Compact task IDs | DE000, DE001, DE002 |
| Canonical branch | `main` |
| Local checkout | `~/Developer/AIDataEngineer` |
| Current phase | Interview MVP (MVP001–MVP004) implemented on `main`; DE 001 architecture ACCEPTED |

## How to use this layer

1. Read this file.
2. Read `MASTER_WORKFLOW.md` for lifecycle, Git, Cloud, environments, and parallel rules.
3. Read `PROJECT_CONTEXT.md` for product north star and current phase.
4. Read `TASKS.md` and `DECISIONS.md`.
5. Read the specialist file for the task type:
   - `AUDIT.md` — inspect / report only
   - `IMPLEMENT.md` — build a scoped feature
   - `BUGFIX.md` — fix a defect
   - `REFACTOR.md` — restructure without behavior change
   - `SECURITY.md` — security hardening and review
   - `RELEASE.md` — release / deploy validation
6. Read `MODEL_ROUTING.md` before selecting or escalating a model.
7. Read `ENVIRONMENTS.md` before choosing Local vs Cloud vs CI.
8. Read `ARCHITECTURE.md`. Status is `ACCEPTED`. DE 002A, DE 002B, and DE 002C are
   Cloud-eligible (DE-ADR-020; OPS004 reclassification).

## Non-negotiable rules (summary)

- Verify repository path, branch, commit, and Git status before changing anything.
- One writer per branch. Never push to `main` during normal development.
- Do not silently change approved architecture.
- Never expose secrets. Never ask anyone to paste a token into chat.
- Git authority and deployment authority are separate. Merges and live actions require human approval.
- Regenerate `HANDOFF.md` and `CHANGELOG_SESSION.md` after success, failure, blocker, partial completion, review requirement, context exhaustion, quota interruption, credential failure, or environment failure.
- Stop safely when blocked. Do not invent access, architecture, or test results.

## Canonical handoff files

Generated per session; gitignored (never committed in ordinary product work):

- Source (repo root): `HANDOFF.md`, `CHANGELOG_SESSION.md`
- iCloud transport (two files only):
  `~/Library/Mobile Documents/com~apple~CloudDocs/AI-Projects/AIDataEngineer/`
- Sync script: `~/.local/bin/sync-aidataengineer-handoff.sh`
- LaunchAgent: `~/Library/LaunchAgents/com.sofien.aidataengineer-handoff-sync.plist`

Normalized self-hash:

```bash
grep -v '^Source File SHA256:' HANDOFF.md | shasum -a 256
grep -v '^Source File SHA256:' CHANGELOG_SESSION.md | shasum -a 256
```
