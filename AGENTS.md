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
