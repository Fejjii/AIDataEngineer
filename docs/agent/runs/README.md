# Agent run reports

Tracked, sanitized execution records for Local and Cloud agents.

**Spec:** [`../CLOUD_HANDOFF.md`](../CLOUD_HANDOFF.md)

## Layout

```text
docs/agent/runs/
  README.md                 ← this file
  <TASK_ID>/
    <SESSION_ID>.md         ← one report per agent run (never overwrite)
```

## Rules

- One **Task ID**, one **branch**, one **Session ID**, one **run report** per agent run.
- Session IDs must be unique; parallel agents on different tasks use different `<TASK_ID>/`
  directories.
- Private handoffs (`HANDOFF.md`, `CHANGELOG_SESSION.md`) stay gitignored at repo root.
- Never commit secrets or sensitive environment values.
- Reports store **Base commit** and **Implementation commit**, not the SHA of the commit that
  contains the report. Use Git history for the authoritative report commit and branch tip:
  `git log -1 --format=%H -- docs/agent/runs/<TASK_ID>/<SESSION_ID>.md`

## Index (newest first)

| Task ID | Session ID | Status | Branch | Report |
|---------|------------|--------|--------|--------|
| DE003 | DE003-SESSION-20260912T093000Z-bc01a094 | SUCCESS | `ops/DE003_ci_docker` | [report](DE003/DE003-SESSION-20260912T093000Z-bc01a094.md) |
| DE002A | DE002A-SESSION-20260911T160142Z | SUCCESS | `feat/DE002A_contract_kernel` | [report](DE002A/DE002A-SESSION-20260911T160142Z.md) |
| OPS001 | OPS001-SESSION-20260911T152424Z | SUCCESS | `ops/OPS001_unified_handoff` | [report](OPS001/OPS001-SESSION-20260911T152424Z.md) |
