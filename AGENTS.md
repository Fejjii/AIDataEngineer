# AIDataEngineer agent entrypoint

## Default development policy — 2026-10-01

Inherit the canonical [AI Development Cost Efficiency Protocol](https://github.com/Fejjii/AI_OS/blob/0182dbdf525c619e3daffad9cb7185dd6f3fa9ed/AI_DEVELOPMENT_COST_EFFICIENCY_PROTOCOL.md).

For normal coding: recover source/ownership once; implement; run focused validation
only; commit; push; write one concise handoff; STOP immediately. GitHub Actions owns
full suites, builds, integration/E2E, Docker, repository-wide analysis and evaluations.
A separate cheap interaction checks CI later; never wait/poll CI or deployment.
CI failure means failed-job logs and a new bounded correction task, not a new audit.
One independent review per unchanged stable pushed candidate; Grok when Cursor
capacity is available, otherwise fresh independent Codex; reviewer then stops.
Low reasoning for docs/config/formatting; Medium for routine coding/review; High
for complex/security/concurrency/trading-safety/release work; Extra High exceptional.
One recovery checkpoint only when needed and one final handoff; additional records
only for material recovery risk, state change, conflict or failure. Notion/sync and
acknowledgements never gate normal execution. Simply_AI coordinates conflicts only,
not implementation or mandatory Judge approval. Apply at the next safe boundary;
do not interrupt running tasks. This supersedes older administrative/full-local-suite
requirements only. Preserve privacy, project safety, isolated ownership, existing
publication authority and human merge/deployment gates.

Retain applicable `.ai/` architecture/security and `.cursor/rules/` safety rules.
Use the existing sanitized `docs/agent/runs/<TASK_ID>/<SESSION_ID>.md` report
once where required; private HANDOFF/CHANGELOG remain out of Git.

Older lifecycle text below or in referenced documents is historical where it
conflicts with this normal-development cadence; product safety remains binding.

