# Cloud development environment — OPS003

**Task:** OPS003  
**Status:** Validated on a Cursor Cloud VM; dashboard Save remains a human action  
**Date:** 2026-09-11  
**Environment:** `CURSOR_CLOUD`  
**Base commit:** `608f242b683848c5c120e93fdeccaea962f0236e` (`main` after DE 002A)

This document describes the **minimal secure Cursor Cloud development environment** required for later DE 002B / DE 002C *eligibility*. It does **not** reclassify those tasks. It does not implement product functionality.

---

## 1. Purpose

Provide a reproducible Cloud workspace that contains:

- Python 3.12
- `uv` with the committed `uv.lock` as the authority
- PostgreSQL 16 on **localhost only**
- Git and required build tooling
- the existing DE 002A Python toolchain (`uv sync --frozen --all-groups`)

and that contains **no** vendor, Snowflake, production, or staging credentials.

---

## 2. Environment components

| Component | Form | Notes |
|-----------|------|--------|
| Base OS | Cursor default Ubuntu 24.04 image | Validated on this VM |
| Python | 3.12 (system `python3`) | Matches DE-ADR-025 and `.python-version` |
| Package manager | `uv` in `/usr/local/bin` | Official installer; lockfile is not rewritten |
| PostgreSQL | Native 16 (`apt` `postgresql-16`) | Not Docker, not DBaaS, not Kubernetes |
| Git | System `git` | Already present on the Cloud image |
| Build tooling | `build-essential`, `python3.12-dev`, `libpq-dev` | Needed for future compiled extras |
| Product venv | `uv sync --frozen --all-groups` | DE 002A kernel + dev group |

Tracked configuration:

- `.cursor/environment.json` — `name`, `install`, `start` only
- `.cursor/Dockerfile` — **optional custom-image recipe; not wired**
- `scripts/verify_environment.sh` — bootstrap, start, and verify

---

## 3. Cursor configuration contract (validated)

Inspected sources:

- Public schema: `https://cursor.com/schemas/environment.schema.json`
- Cursor Cloud `environment-info` for this run
- `cursor-cloud-propose-environment-json` / `trigger-environment-build` tool schemas

This run’s environment is **dashboard / DB-managed**:

- `environmentJsonPath`: `null`
- `environmentJson` is not exposed for personal environments
- Environment id: `de270025-add6-11f1-bf4b-42ffb4d10ea7`
- Dashboard: `https://cursor.com/dashboard/cloud-agents/environments/e/de270025-add6-11f1-bf4b-42ffb4d10ea7`

Fields **used** in the committed `.cursor/environment.json` are in the public schema:

| Field | Value | Why |
|-------|--------|-----|
| `name` | `AIDataEngineer` | Human-readable environment name |
| `install` | `./scripts/verify_environment.sh --bootstrap` | Idempotent packages + `uv` + locked sync |
| `start` | `./scripts/verify_environment.sh --start` | Per-boot PostgreSQL on localhost |

Fields **not** set, with reason:

| Field | Reason |
|-------|--------|
| `$schema` | Public schema rejects undeclared properties |
| `build` / `image` / `snapshot` | Custom image not build-tested (no nested Docker). Snapshot IDs are environment-specific and must not be committed. Dashboard draft-build/propose tools accept only `install`, `start`, and (on trigger) `snapshot`. |
| `ports` | PostgreSQL must not be published |
| `egressAllowlist` / `egressMode` | Egress stays unrestricted until live keys exist; do not invent a tightening here |
| Secrets in JSON | Forbidden |

After this file is merged, a committed `.cursor/environment.json` becomes the **highest-precedence** Cloud environment source for new agents. Until then, the personal dashboard environment remains authoritative.

---

## 4. Bootstrap lifecycle

```text
1. Cursor provisions the VM from the default (or later saved) snapshot
2. Repository revision is checked out
3. install  → scripts/verify_environment.sh --bootstrap
      apt packages (idempotent)
      uv if missing
      uv sync --frozen --all-groups
      start PostgreSQL (so a snapshot can include a ready cluster)
4. start    → scripts/verify_environment.sh --start
      listen_addresses = localhost
      local/peer + loopback trust for the OS user role (no password in Git)
      create role/database if missing
      wait until 127.0.0.1:5432 is ready
5. Agent work
6. Future agent: scripts/verify_environment.sh   # default --verify
```

`install` is idempotent and terminates. `start` is idempotent: it reloads or starts the existing cluster and does not create a second cluster.

With **environment builds**, `install` is snapshotted and may not rerun on later boots; **`start` must restore PostgreSQL** because the process does not survive the snapshot.

---

## 5. PostgreSQL behaviour

- Version: PostgreSQL 16 (Ubuntu package).
- Bind: `listen_addresses = 'localhost'` via `/etc/postgresql/16/main/conf.d/aide-cloud.conf`.
- Authentication (ephemeral Cloud only):
  - Unix socket `peer` for the OS user `ubuntu`
  - TCP `127.0.0.1/32` and `::1/128` `trust` for that role only
  - **no password** stored in the repository
- Database: `aide_dev` owned by role `ubuntu`
- Data: local cluster under `/var/lib/postgresql/` — **ephemeral**; never production data
- Not used: hosted Postgres, RDS, Neon, Cloud SQL, Kubernetes, public `0.0.0.0` listen, published `ports`

DE 002B integration tests may later create their own databases; this role is `CREATEDB`.

---

## 6. uv behaviour

- `uv.lock` is authoritative. Bootstrap and verify use `uv sync --frozen --all-groups`.
- Python is the system 3.12 interpreter (`requires-python = ">=3.12,<3.13"`).
- Bootstrap must not rewrite the lockfile.
- `uv` is installed to `/usr/local/bin` (no shell-profile mutation).

---

## 7. Security boundaries

1. **Fail closed** on required vendor secrets: if a forbidden name is set, verification fails and **does not print the value**.
2. Documentation and scripts mention **environment-variable names only**.
3. No Snowflake, GitHub sandbox product token, staging, or production credentials in the snapshot.
4. PostgreSQL is loopback-only.
5. Cursor’s GitHub credential for *this* product repository is not a substitute for `GITHUB_TOKEN_AIDE` (DE 012). Verification does not treat the platform Git credential as a product secret.
6. Do not bake `.env` files into snapshots. `.env*` remains gitignored.
7. MOCK / REAL provenance rules in the architecture are unchanged; this environment does not attach live connectors.

---

## 8. Secret policy

**Allowed in tracked files:** variable **names**.

**Forbidden in tracked files, Dockerfiles, environment JSON, run reports, and logs:**

- passwords, tokens, private keys, connection strings with credentials
- Snowflake material
- GitHub personal or product tokens (`GITHUB_TOKEN_AIDE`)
- staging / production credentials
- private bootstrap sources (`.ai/private/`)

Forbidden names checked by `scripts/verify_environment.sh` (presence only):

`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_PRIVATE_KEY`, `SNOWFLAKE_PRIVATE_KEY_DEV`, `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_WAREHOUSE_DEV`, `SNOWFLAKE_ROLE`, `GITHUB_TOKEN_AIDE`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `AWS_SECRET_ACCESS_KEY`, `AZURE_OPENAI_API_KEY`

Live secret **entry** remains a human gate (`REVIEW_REQUIRED`). Never paste values into agent chat.

---

## 9. How a future Cloud Agent verifies readiness

From the repository root:

```bash
python3 --version
uv --version
uv sync --frozen --all-groups
pg_config --version
./scripts/verify_environment.sh
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```

`--bootstrap` / `--start` are for environment setup. Agents that already have packages should run `--verify` (default) before DE 002B work.

If PostgreSQL is down after a snapshot boot, run `--start` (or rely on Cursor `start`).

---

## 10. Limitations

- Nested Docker / Compose is **not** part of this snapshot (DE 003 owns CI Docker).
- Custom `.cursor/Dockerfile` is **not** the active base image (unvalidated).
- Dashboard `propose-environment-json` cannot persist `build.dockerfile`; Save applies `install`/`start` plus a VM snapshot.
- Warm-fork git checkouts can be stale; agents that need a named SHA must `git fetch`.
- Canonical Mac path `~/Developer/AIDataEngineer` does not apply; Cloud worktrees use `/workspace`.
- iCloud / `.ai/private/` are absent (expected).
- DE 002B and DE 002C remain **LOCAL** in `.ai/TASKS.md` until a later governance task.

---

## 11. What remains Local

- Secret and private-key **entry**
- Live Snowflake (DE 005 live), live dbt-on-Snowflake, live sandbox GitHub PRs
- Snowflake account-usage queries (DE 014 local portion)
- Staging execution (DE 017)
- Live end-to-end demo rehearsal (DE 018)
- Production (disabled in V1)
- iCloud handoff sync and private bootstrap sources
- Mac Docker as a **fallback** if a Cloud agent cannot obtain localhost PostgreSQL 16

---

## 12. Human steps in Cursor (cannot be fully automated)

Dashboard Save and environment activation cannot be performed by the agent.

1. Review this PR. Do not merge until CI is green and the diff contains no secrets.
2. Open the personal environment  
   [de270025-add6-11f1-bf4b-42ffb4d10ea7](https://cursor.com/dashboard/cloud-agents/environments/e/de270025-add6-11f1-bf4b-42ffb4d10ea7).
3. If a snapshot / draft build was proposed in the Environment panel, **click Save**.
4. Confirm a **new** Cloud Agent (after Save) can run:
   - `uv --version`
   - `./scripts/verify_environment.sh`
5. After merge, new agents read `.cursor/environment.json` from Git (highest precedence). Confirm `install`/`start` still succeed on a fresh boot.
6. Do **not** attach Snowflake or staging secrets to this environment.
7. A later governance task (not this one) may retarget DE 002B / DE 002C to CLOUD after the operator accepts this environment.

If Save is skipped, this branch still documents the recipe, but follow-up Cloud agents may boot the previous snapshot **without** `uv` / PostgreSQL 16.
