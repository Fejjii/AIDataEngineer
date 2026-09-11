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

## Index (newest first)

| Task ID | Session ID | Status | Branch | Report |
|---------|------------|--------|--------|--------|
| OPS001 | OPS001-SESSION-20260911T152424Z | SUCCESS | `ops/OPS001_unified_handoff` | [report](OPS001/OPS001-SESSION-20260911T152424Z.md) |
