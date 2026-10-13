# Data Pilot AI Codex Cloud instructions

These instructions apply to every Codex Cloud task in this repository.

## Execution visibility

GitHub issue #44 is the persistent Codex Cloud run ledger.

At task start, post one concise START receipt to issue #44 with:
task purpose, starting SHA, branch, environment, model, reasoning, and intended validation.

Before stopping for any blocker, post one concise BLOCKED receipt to issue #44 with:
current SHA, completed work, exact blocker, failed command or gate, repository changes, and exact next action.

On successful completion, post one concise DONE receipt to issue #44 with:
starting SHA, final SHA, branch, files changed, tests run, PR and CI state, remaining blockers, and terminal result.

For work longer than fifteen minutes, post a concise CHECKPOINT receipt when a meaningful phase completes.

Never include secrets, credentials, private payloads, tokens, connection strings with credentials, or verbose logs.

If posting to issue #44 fails, preserve the same sanitized receipt in the task branch before stopping and state that the ledger update failed.

## Codex Cloud environment

Codex Cloud is rootless. Do not use the Cursor Cloud bootstrap path that requires sudo or native PostgreSQL installation.

Do not run:
scripts/verify_environment.sh --bootstrap

Do not treat absence of local PostgreSQL as a product defect.

Normal Codex Cloud dependency setup is:
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen --all-groups

Run unit and other database independent tests locally in Codex Cloud.

PostgreSQL integration and migration validation may use GitHub CI, which provisions PostgreSQL 16.

Do not connect Codex Cloud development tasks to the Railway production PostgreSQL instance.

The Cursor Cloud environment remains allowed to use scripts/verify_environment.sh --bootstrap because that environment has the required system privileges.

## Repository safety

Recover current main and open PRs before editing.

Preserve active Cursor work and unrelated branches.

Use an isolated task branch for repository changes.

Do not merge or deploy unless the task explicitly authorizes it.

## Notion Agent Reports

Applies to all current active repos (SOF AI, DataPilot AI, AlphaTrade AI) and every future Simply AI project from day one.

After completing ANY task, prompt, or investigation, every Codex and Cursor agent writes a report to the Notion database `Agent Reports`.

- Database page: https://app.notion.com/p/845cabc602864dcbb4b6898c1ca73197
- Data source: `collection://187c021b-1ed0-45f6-b15a-e246fcea9f79`
- Parent page: `Simply AI Handoff`

This report is in addition to the GitHub issue #44 ledger receipt and the tracked run report at `docs/agent/runs/<TASK_ID>/<SESSION_ID>.md`. It does not authorize a merge, a deploy, or a production change.

### Properties

Fill every property below. Keep the property text short. Put the untrimmed transcript in the page body, not in the properties.

For work in this repository, set `Repo` to `DataPilot AI`. The same report is required for the other projects named in the scope line. Use the database's existing `Repo` select value for that project. The current values are `SOF`, `Simply AI`, `AlphaTrade AI`, and `DataPilot AI`. SOF AI uses `SOF`. A future Simply AI project uses `Simply AI` unless the operator later adds a dedicated option. Do not invent a select option.

- `Task Name`: short name of the task, prompt, or investigation
- `Date`: date of the work
- `Agent`: `Cursor`, `Codex`, `Grok Bot`, or `Other`
- `Repo`: `DataPilot AI` for this repository
- `Status`: `Done`, `Blocked`, or `In progress`
- `Summary`
- `Findings`
- `Files`
- `Conditions Checked`
- `Likely Culprits`
- `Next Steps`
- `PR / Agent Link`: pull request URL or agent-run URL
- `Full Transcript Included`: checkbox. Set it only when the complete verbatim output is stored on the entry.
- `Transcript Source`: URL of the original agent run, when one exists

### Page body

Put the COMPLETE raw output and transcript VERBATIM in the entry page body, or in one or more child pages titled `Full transcript`. Include code snippets, file paths, command outputs, test results, and ranked findings lists. Trim nothing. Redact only secret values. Keep the names of those secrets.

### No Notion access

If the agent has no Notion access, append that same full verbatim output to its final message and to the PR body under the heading `Findings report — full transcript`, so the orchestrator can file it. Do not claim that a Notion entry exists in that case.
