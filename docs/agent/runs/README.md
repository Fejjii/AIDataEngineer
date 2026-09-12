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
| DE007 | DE007-R1-SESSION-20260912T201100Z-bc01a096 | PARTIAL | `feat/DE007_modelling` | [report](DE007/DE007-R1-SESSION-20260912T201100Z-bc01a096.md) |
| DE007 | DE007-SESSION-20260912T185800Z-bc01a096 | PARTIAL | `feat/DE007_modelling` | [report](DE007/DE007-SESSION-20260912T185800Z-bc01a096.md) |
| DE006 | DE006-R1-SESSION-20260912T183120Z-bc01a0968e | SUCCESS | `feat/DE006_profiling` | [report](DE006/DE006-R1-SESSION-20260912T183120Z-bc01a0968e.md) |
| DE006 | DE006-SESSION-20260912T165821Z-bc01a0968e | SUCCESS | `feat/DE006_profiling` | [report](DE006/DE006-SESSION-20260912T165821Z-bc01a0968e.md) |
| DE005A | DE005A-SYNC-SESSION-20260912T163700Z-bc01a096 | SUCCESS | `feat/DE005_snowflake_connector` | [report](DE005A/DE005A-SYNC-SESSION-20260912T163700Z-bc01a096.md) |
| DE005A | DE005A-R1-SESSION-20260912T154100Z-bc01a096 | REVIEW_REQUIRED | `feat/DE005_snowflake_connector` | [report](DE005A/DE005A-R1-SESSION-20260912T154100Z-bc01a096.md) |
| DE005A | DE005A-SESSION-20260912T143632Z-bc01a096 | REVIEW_REQUIRED | `feat/DE005_snowflake_connector` | [report](DE005A/DE005A-SESSION-20260912T143632Z-bc01a096.md) |
| DE004 | DE004-SESSION-20260912T154500Z-r1 | SUCCESS | `feat/DE004_synthetic_vantara` | [report](DE004/DE004-SESSION-20260912T154500Z-r1.md) |
| DE004 | DE004-SESSION-20260912T144500Z-fe83 | SUCCESS | `feat/DE004_synthetic_vantara` | [report](DE004/DE004-SESSION-20260912T144500Z-fe83.md) |
| DE003 | DE003-SESSION-20260912T093000Z-bc01a094 | SUCCESS | `ops/DE003_ci_docker` | [report](DE003/DE003-SESSION-20260912T093000Z-bc01a094.md) |
| DE002A | DE002A-SESSION-20260911T160142Z | SUCCESS | `feat/DE002A_contract_kernel` | [report](DE002A/DE002A-SESSION-20260911T160142Z.md) |
| OPS001 | OPS001-SESSION-20260911T152424Z | SUCCESS | `ops/OPS001_unified_handoff` | [report](OPS001/OPS001-SESSION-20260911T152424Z.md) |
