# Remote Development Readiness — OPS002

**Task:** OPS002  
**Status:** Assessment only (no environment implemented; no task-assignment changes)  
**Date:** 2026-09-11  
**Environment surveyed:** Cursor Cloud (`CURSOR_CLOUD`)  
**Base commit:** `b7d0e014a33d79047880ad4142d8107b4814a45f` (`main` after OPS001)  
**Authority consumed:** `.ai/ARCHITECTURE.md` (ACCEPTED), `.ai/MASTER_WORKFLOW.md`, `.ai/TASKS.md`, `.ai/ENVIRONMENTS.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/TECH_STACK.md`, `docs/CONNECTOR_ARCHITECTURE.md`, `docs/adr/DE-ADR-020-local-vs-cloud-development.md`, `docs/agent/CLOUD_HANDOFF.md`

This document does **not** change existing task environment assignments in `.ai/TASKS.md`. Recommendations below are advisory. A later governance task may reclassify tasks after the operator accepts this assessment and the prerequisite infrastructure exists.

---

## 1. Current state

### 1.1 Product and governance

| Fact | Evidence |
|------|----------|
| Architecture ACCEPTED | `.ai/ARCHITECTURE.md`; operator acceptance 2026-09-11 |
| Product code absent | No `src/`, `tests/`, `pyproject.toml`, `uv.lock`, `Dockerfile`, `docker-compose.yml`, or `.github/workflows/` on `main` |
| CI absent | No GitHub Actions workflows |
| Cloud handoff exists | `docs/agent/CLOUD_HANDOFF.md` (OPS001, merged on expected base) |
| DE 002A is Cloud-eligible | DE-ADR-020; `.ai/TASKS.md` |
| DE 002B / DE 002C assigned LOCAL | DE-ADR-020; implementation plan §3 / §5 |
| Other LOCAL assignments | DE 005, DE 008, DE 012 live, DE 014 account-usage, DE 017, DE 018, DE 019 |
| Parallel constraint | OPS002 must not touch DE 002A owned product or governance files |

### 1.2 This Cursor Cloud VM (verified 2026-09-11)

Surveyed on run `bc-01a09129-512e-71ba-8a2e-8509e4c3a488` (phone-launched). Personal environment, no committed `.cursor/environment.json` (`environmentJsonPath` null). Booted from environment build `bld-20260911-f6efe713-a4b8-4bf5-a3f8-957e0e283079` with `gitSetup=reuse` and `warmFork=warm_fork`.

| Capability | Present? | Notes |
|------------|----------|-------|
| Python 3.12 | Yes | `python3` 3.12.3 (matches DE-ADR-025 target minor) |
| uv | **No** | Not on PATH |
| Docker / Compose / socket | **No** | Nested Docker not available in this snapshot |
| PostgreSQL client or server | **No** | No `psql`, nothing listening on 5432 |
| dbt CLI | **No** | Expected as a Python extra after DE 002 / DE 008 |
| DuckDB CLI | **No** | In-process library is enough later; not a system service |
| Snowflake client / CLI | **No** | `snowflake-connector-python` is a future package, not a VM service |
| Git + GitHub push on task branch | Yes | `git` 2.43; Cloud GitHub access for this repo |
| Node LTS + pnpm | Yes | Node 22 + pnpm 10.33.3 (frontend is later; unused now) |
| Live secrets | **No** | No `SNOWFLAKE_*`, `GITHUB_TOKEN_AIDE`, or LLM provider names in the process environment |
| Egress | Unrestricted | `egress.restricted = false` |
| Disk / RAM | 247 GiB free / ~16 GiB RAM / 4 vCPU | Adequate for `tiny`/`demo` fixtures later |
| Canonical Mac path | N/A | Worktree is `/workspace` (expected for Cloud) |
| iCloud / `.ai/private/` | Absent | Expected; Cloud must not assume them |
| Snapshot git freshness | Stale until fetch | Reused checkout was `97f4bd0`; expected `main` is `b7d0e01`. Agents that depend on latest `main` must `git fetch origin main` |

`.gitignore` tracks `.cursor/rules/` only and ignores `.cursor/*`. A committed `.cursor/environment.json` is therefore **blocked until a later ops task** adds an ignore exception. This assessment must not edit `.gitignore`.

### 1.3 Why LOCAL exists today

DE-ADR-020: Cloud-eligible iff tracked GitHub state + fakes/fixtures suffice + no credentials + declared files + isolated branch. LOCAL is used when work needs Mac tooling, local Docker, local `.env`, iCloud, private bootstrap sources, or live vendor credentials.

That rule remains correct. Several LOCAL labels are **conservative defaults from before a Cloud PostgreSQL/uv snapshot existed**, not proofs that the work is Mac-only.

### 1.4 Execution layers (do not collapse these)

| Layer | Meaning | Default venue |
|-------|---------|----------------|
| Cloud development | Write/review code in Cursor Cloud on an isolated branch | Cursor Cloud |
| Cloud testing | Deterministic unit/integration tests with fakes and/or local PostgreSQL | Cursor Cloud and/or GitHub Actions |
| Live credential validation | Opt-in calls to real Snowflake / GitHub / LLM using scoped secrets | Human-gated; LOCAL by default |
| Staging execution | `deploy_staging` against `AIDE_STAGING` | APPLICATION_STAGING; never implicit Cloud |
| Production execution | Disabled in V1 | Human only; never agent-implicit |

---

## 2. Target state (phone-first)

Operator launches Cloud agents from a phone, reviews PRs on GitHub, and uses the Mac only for:

1. secret entry into a secret store (never into chat);
2. live Snowflake / sandbox GitHub validation;
3. staging rehearsal;
4. iCloud private-handoff sync.

**Simplest environment that unlocks that** (implement later, not in OPS002):

1. Keep using **Cursor Cloud** as the remote workspace (already paid, already phone-launchable, already branch-isolated).
2. Add a **snapshot** with `uv` + **native PostgreSQL 16** (apt/package, not Docker, not DBaaS).
3. Add **GitHub Actions** in DE 002A / DE 003 for the merge gate (lint, types, unit, then Postgres integration).
4. Keep vendor CLIs as **Python packages** (`snowflake-connector-python`, `dbt-core`, DuckDB).
5. Put non-production secrets only in **Cursor dashboard / GitHub Environment** stores, referenced by env-var **names**.
6. Do **not** add Kubernetes, Temporal, hosted Postgres, object-storage SaaS, or always-on Snowflake to the default Cloud image.

Docker belongs first in **GitHub Actions** (DE 003), not in the minimal Cloud snapshot. Nested Docker in Cloud Agents is possible with a custom Dockerfile, but it is extra moving parts for a repo that does not yet have a `Dockerfile`. Native Postgres covers DE 002B/C.

---

## 3. Task-by-task classification

Legend for **recommended target:** `CLOUD` = development + tests fully Cloud-executable with fakes/fixtures and no live secrets; `HYBRID` = Cloud for code/tests, LOCAL (or explicitly granted Cloud secrets) for live validation; `LOCAL` = cannot be reproduced safely in Cloud even with a Postgres/uv snapshot.

OPS002 does **not** retarget `.ai/TASKS.md`. “Recommended target” is the future assignment after prerequisites.

### 3.1 DE 002B — Persistence and recovery primitives

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL (`feat/DE002B_recovery_kernel`) |
| Current Local reason | PostgreSQL models, advisory locks, `SKIP LOCKED`, fencing, crash/concurrency integration tests; DE-ADR-020 assumed local Docker/Postgres |
| Capability that requires Local **today** | A running PostgreSQL 16 and a way to start it (local Docker / testcontainers). Not Mac-specific. |
| Reproducible in secure Cloud? | **Yes**, once Postgres 16 is in the Cloud snapshot or CI service container. Tests use fake side-effect connectors, not Snowflake. |
| Required Cloud services | Cursor Cloud workspace; GitHub Actions (after DE 003) with a Postgres service |
| Required containers | None in the minimal path. Optional later: `postgres:16` via Compose/testcontainers |
| Required databases | PostgreSQL 16 (empty test DB per run; Alembic migrations) |
| Required credentials | None. Local `postgres` trust/peer or a generated test password in the snapshot only |
| Secret management | None |
| Network | Loopback to Postgres. No vendor egress |
| Cost | Included in Cursor VM + GHA minutes. **Low** |
| Security | Test DB has no production data. Do not reuse live warehouse credentials |
| Cloud development | Yes |
| Cloud testing | Yes (after Postgres) |
| Live credential validation | N/A |
| Staging / production execution | N/A |
| **Recommended target** | **CLOUD** after OPS003 (uv + Postgres snapshot) and DE 002A merge. **HYBRID** until that snapshot exists (Mac Docker remains the fallback). |

### 3.2 DE 002C — First executable offline safe-SQL slice

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL |
| Current Local reason | Composes DE 002B persistence with fake Snowflake, replay LLM, API/CLI. Marked LOCAL because it sits on the LOCAL persistence kernel, not because it needs live vendors |
| Capability that requires Local **today** | Same Postgres dependency as DE 002B. Fake warehouse is DuckDB-in-process (Python package). Replay LLM needs recorded fixtures, not provider keys |
| Reproducible in secure Cloud? | **Yes**, after DE 002B’s Cloud Postgres path exists |
| Required Cloud services | Cursor Cloud + (later) GHA |
| Required containers | None minimal |
| Required databases | PostgreSQL 16 (app state) + in-process DuckDB (fake warehouse) |
| Required credentials | None |
| Secret management | None |
| Network | Loopback only |
| Cost | **Low** |
| Security | MOCK provenance must stay MOCK; no live Git/deploy |
| Cloud development / testing | Yes / yes |
| Live / staging / production | N/A / contract-only `deploy_staging` / disabled |
| **Recommended target** | **CLOUD** after DE 002B merge + OPS003. Until then keep LOCAL as written. |

### 3.3 DE 005 — Real Snowflake connector

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL · Cloud no |
| Current Local reason | Live connector identities `snowflake_ro` / `snowflake_dev`; human gate for `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`, `SNOWFLAKE_WAREHOUSE_DEV` |
| Capability that requires Local | **Live** session to Snowflake DEV using a private key. Implementation of `real.py`, error mapper, dialect, and fake-backed contract tests do **not** need live access |
| Reproducible in secure Cloud? | **Partially.** Code + fake contract tests: yes. Live contract tests: only if a **DEV-only** key is provisioned in the Cloud secret store with allow-listed account/warehouse, never PROD |
| Required Cloud services | Cursor Cloud; optional later GHA `workflow_dispatch` live job |
| Required containers | None |
| Required databases | None in Cloud. Snowflake DEV schemas `AIDE_DEV_*` for live tests only |
| Required credentials | Live layer only: the four env-var **names** above (RO vs DEV identities separately). No production keys |
| Secret management | Operator enters values in Cursor/GitHub secret stores. Never chat, Git, handoffs, or run reports. Key material must not be logged |
| Network | Live layer: egress to the configured Snowflake account host. Default Cloud tests: no Snowflake egress |
| Cost | Cloud tests **low**. Live X-Small warehouse: **low–medium** depending on suspend settings (R4) |
| Security | Distinct RO vs DEV identities; READ binds only to `identity_class=READ_ONLY`. Cloud must not receive STAGING/PROD keys. Unrestricted egress on this VM is a residual risk if live keys are added |
| Cloud development | Yes |
| Cloud testing | Yes (fake + recorded error fixtures) |
| Live credential validation | LOCAL default; Cloud only after explicit secret grant |
| Staging / production | No |
| **Recommended target** | **HYBRID** |

### 3.4 DE 008 — dbt connector, generation and execution

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL · Cloud no |
| Current Local reason | “dbt + Snowflake live validation.” Architecture already requires evaluating **real dbt Core** against **offline `dbt-duckdb`** for integration/contract tests, keeping a lightweight fake for unit tests |
| Capability that requires Local | **Live** `dbt build` on Snowflake DEV. Not required for unit fake or the dbt-duckdb evaluation |
| Reproducible in secure Cloud? | **Mostly yes.** `dbt-core` + `dbt-duckdb` are Python packages; subprocess `dbtRunner` does not need Docker. Live Snowflake dbt remains LOCAL/HYBRID like DE 005 |
| Required Cloud services | Cursor Cloud; GHA for offline dbt-duckdb job |
| Required containers | None for offline. Optional later: none |
| Required databases | DuckDB files from DE 004 fixtures; Postgres for app state; Snowflake DEV only for live |
| Required credentials | None for offline evaluation. Live: same DEV Snowflake secrets as DE 005 plus generated `profiles.yml` from `SecretRef` in the subprocess env only |
| Secret management | Same as DE 005 for live; no secrets for dbt-duckdb |
| Network | Offline: none. Live: Snowflake egress |
| Cost | Offline **low**. Live warehouse **low–medium** |
| Security | Working copies under `.aide/work/<workflow_id>/`; subprocess isolation; never commit resolved profiles. MOCK dbt artifacts must not feed real Git/deploy |
| Cloud development / testing | Yes / yes (fake + dbt-duckdb) |
| Live credential validation | LOCAL / optional granted Cloud |
| Staging / production | Staging is DE 017; PROD disabled |
| **Recommended target** | **HYBRID** (split 008a offline connector+duckdb eval to Cloud; live DEV build stays Local) |

### 3.5 DE 012 — GitHub connector and delivery chain (live portion)

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL (live PR) / CLOUD (fake) |
| Current Local reason | Live `prepare_git_change` / `prepare_pull_request` needs `GITHUB_TOKEN_AIDE`; human gate |
| Capability that requires Local | Token that can open PRs on a **sandbox** repo. The agent’s default GitHub credential for *this* product repo is **not** a substitute (wrong identity, wrong blast radius, easy to hit `main`) |
| Reproducible in secure Cloud? | Fake: already Cloud. Live: only with a dedicated fine-grained token scoped to a sandbox repo, no admin, no force-push, branch pattern `aide/*` |
| Required Cloud services | Cursor Cloud; GitHub API |
| Required containers | None |
| Required databases | None |
| Required credentials | `GITHUB_TOKEN_AIDE` (sandbox only) |
| Secret management | Dashboard/GitHub Environment; never the operator’s personal PAT with org admin |
| Network | `api.github.com` (and git HTTPS) |
| Cost | **Low** |
| Security | Protected-branch denial tests; secret scan on generated diffs; MOCK provenance blocks real PRs from fake artifacts (R10/R15) |
| Cloud development / testing | Yes / yes (fake) |
| Live credential validation | LOCAL default; Cloud optional with sandbox token |
| Staging / production | `deploy_production` not advertised in V1 |
| **Recommended target** | **HYBRID** (keep the current split; do not move live PR creation to Cloud until a sandbox token exists) |

### 3.6 DE 014 — Observability and cost accounting (local portion)

| Field | Assessment |
|-------|------------|
| Current assignment | CLOUD (fake) / LOCAL (Snowflake account usage) |
| Current Local reason | `get_cost_metrics` against `WAREHOUSE_METERING_HISTORY` / account usage views; lag and `complete=false` semantics |
| Capability that requires Local | Live account-usage queries (typically extra grants, still DEV-scoped — not PROD) |
| Reproducible in secure Cloud? | Fake cost fixtures and ledger tests: yes. Live usage views: same as DE 005 live |
| Required Cloud services | Cursor Cloud; Postgres for telemetry tables |
| Required containers | None |
| Required databases | PostgreSQL (audit/telemetry). Snowflake usage views only for live |
| Required credentials | Live: DEV Snowflake identity with usage-view grants — **name** `SNOWFLAKE_*` as in DE 005, plus whatever grant the connector README will document. No extra production identity |
| Secret management | Same as DE 005; redaction of SQL/artifacts (R13/R14) |
| Network | Live Snowflake egress only for the local portion |
| Cost | Fake **low**. Live **low** if warehouse auto-suspends |
| Security | Estimates vs measured credits must stay labelled (`estimated=true`). Do not pull account usage into prompts |
| Cloud development / testing | Yes / yes (fake) |
| Live credential validation | LOCAL |
| Staging / production | N/A |
| **Recommended target** | **HYBRID** (already correctly split; keep live usage LOCAL) |

### 3.7 DE 017 — Staging deploy capability and monitors stub

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL · Cloud no |
| Current Local reason | `deploy_staging` with complete `OperationApproval`, release marker, `reconcile`; staging identity secret; Fable review of deploy path |
| Capability that requires Local | **Staging execution** against `AIDE_STAGING` / `AIDE_STAGING.__AIDE_RELEASES`. Ambiguous outcomes must park; humans cannot mark success without validated output |
| Reproducible in secure Cloud? | **Code + negative approval tests + fake reconcile:** yes. **Actual staging run:** no, not in default Cloud |
| Required Cloud services | Cursor Cloud for implementation |
| Required containers | None for tests |
| Required databases | Fake/Postgres for unit tests; Snowflake staging for live |
| Required credentials | Staging identity (separate from DEV). Never placed in the default Cloud snapshot |
| Secret management | Human gate; staging secret store distinct from DEV and from Cloud agent defaults |
| Network | Staging Snowflake (and only then) |
| Cost | Implementation **low**. Staging warehouse **low–medium** |
| Security | Highest of the analyzed set after live Snowflake. MOCK provenance must not authorize staging. Approval binding must be complete. Do not grant Cloud agents `STAGING_DEPLOY` by default |
| Cloud development / testing | Yes / yes (fakes, approval negatives) |
| Live credential validation | LOCAL |
| Staging execution | LOCAL / APPLICATION_STAGING |
| Production execution | Denied in V1 |
| **Recommended target** | **HYBRID** for code; **LOCAL** for staging execution. Do not retarget the whole task to CLOUD |

### 3.8 DE 018 — End-to-end demo hardening

| Field | Assessment |
|-------|------------|
| Current assignment | LOCAL · Cloud no |
| Current Local reason | Live rehearsal of S04 on Snowflake DEV + GitHub sandbox; warehouse pre-warm; README with real setup commands |
| Capability that requires Local | Live five-minute demo (warehouse warm, live PR, live dbt). Offline fallback packaging and full offline suite do **not** |
| Reproducible in secure Cloud? | Offline demo + CI suite: yes after prior tasks. Live rehearsal: LOCAL |
| Required Cloud services | Cursor Cloud; GHA for offline eval |
| Required containers | App compose only after DE 003 — optional for Cloud agents |
| Required databases | Postgres + DuckDB offline; Snowflake DEV live |
| Required credentials | Union of DE 005 + DE 012 live, not staging/prod |
| Secret management | Same boundaries; demo README lists env-var **names** only |
| Network | Live vendors only on the Local rehearsal |
| Cost | Offline **low**. Live demo **low–medium** (pre-warm) |
| Security | Prefer offline as primary demo (R16). Live is evidence, not the default Cloud path |
| Cloud development / testing | Yes / yes (offline) |
| Live credential validation | LOCAL |
| Staging / production | Demo may show staging only under DE 017 rules; PROD denied |
| **Recommended target** | **HYBRID** (offline Cloud; live rehearsal LOCAL) |

### 3.9 Summary table

| Task | Current env | Blocking Local capability | After OPS003 Postgres+uv | Recommended target | Immediate move? |
|------|-------------|---------------------------|--------------------------|--------------------|-----------------|
| DE 002B | LOCAL | PostgreSQL integration tests | Unblocked | **CLOUD** | No (needs snapshot) |
| DE 002C | LOCAL | Depends on DE 002B Postgres | Unblocked after 002B | **CLOUD** | No |
| DE 005 | LOCAL | Live Snowflake identities | Code/tests unblocked | **HYBRID** | Code/tests only, not live |
| DE 008 | LOCAL | Live dbt-on-Snowflake | Offline dbt-duckdb unblocked | **HYBRID** | Offline portion only |
| DE 012 live | LOCAL | Sandbox GitHub token | Fake already Cloud | **HYBRID** | Fake already Cloud |
| DE 014 local | LOCAL | Account usage views | Fake already Cloud | **HYBRID** | Fake already Cloud |
| DE 017 | LOCAL | Staging identity + execution | Tests unblocked | **HYBRID** code / **LOCAL** staging | No live staging |
| DE 018 | LOCAL | Live demo rehearsal | Offline unblocked | **HYBRID** | Offline only |

**Do not move to Cloud even after OPS003:** live Snowflake, live GitHub token use, staging deploy, production, secret entry, iCloud sync, DE 019 private-context review.

---

## 4. Required infrastructure (minimal)

Ordered from simplest to only-if-needed. **Do not implement here.**

### 4.1 Must have (OPS003 — recommended next)

| Piece | Role | Simplest form |
|-------|------|----------------|
| Python 3.12 | Runtime | Already on this snapshot |
| uv | Lock + venv | Install in snapshot `install`; commit `uv.lock` from DE 002A |
| PostgreSQL 16 | App state + DE 002B/C tests | `apt` package on the VM; listen on localhost; ephemeral test DB |
| GitHub access | Clone/push/PR | Already present for this repo |
| Secret management | Names only until live tasks | Cursor dashboard + GitHub Environments; `.env` gitignored |
| Persistent workspace | Fast phone launches | Existing warm-fork snapshot; keep it, but fetch `main` when the task names a SHA |
| Branch isolation | One writer per task branch | Already policy |
| Committed environment config | Reproducible Cloud boots | `.cursor/environment.json` + `.cursor/Dockerfile` **after** a `.gitignore` exception for those two paths |

### 4.2 Add with DE 002A / DE 003 (CI, not a second cloud)

| Piece | Role | Simplest form |
|-------|------|----------------|
| GitHub Actions | Merge gate | Workflow on PRs: ruff, mypy, unit (002A); Postgres service, gitleaks, image build (003) |
| Artifact storage | Test reports, coverage, eval | `actions/upload-artifact` |
| Logs / test reports | Review from phone | GHA logs + junit/coverage artifacts |
| Docker | Image + optional testcontainers | **GHA first**. Cloud nested Docker only if a later task proves testcontainers need it |

### 4.3 Language/tooling as packages (no extra services)

| Piece | Role | Simplest form |
|-------|------|----------------|
| DuckDB | Fake warehouse / dbt-duckdb | Python dependency |
| dbt Core | Real transform engine | Python extra; subprocess |
| Snowflake client | Live connector | `snowflake-connector-python`; no SnowSQL required |

### 4.4 Explicitly not required now

- Hosted Postgres (RDS/Cloud SQL/Neon)
- Kubernetes / extra VMs
- Redis, Kafka, object-storage SaaS (architecture uses Postgres + blob interface later)
- Always-on Snowflake warehouse in the Cloud image
- Vault / enterprise IAM
- Installing Docker on the default Cloud snapshot before DE 003

### 4.5 Proposed snapshot shape (for OPS003; not applied)

```text
OS image (current Cloud base)
  Python 3.12
  uv
  PostgreSQL 16 (localhost, test role, no durable product data)
  git, build-essential (already present)
install: uv sync --frozen   # once lockfile exists
start:   ensure postgres is up (service), non-blocking
secrets: none by default
egress:  keep unrestricted until live keys exist; then tighten to GitHub + PyPI + (optional) Snowflake host
```

Credential boundaries:

```text
Cloud snapshot          → zero vendor secrets
Cloud dashboard (opt-in)→ DEV Snowflake and/or sandbox GitHub only, per-task grant
GitHub Actions default  → no live warehouse; fixtures only
GitHub Environment live → workflow_dispatch / labelled jobs only
Local Mac .env          → operator-held DEV + optional staging
Staging secret store    → DE 017 human gate
Production              → disabled
```

---

## 5. Security model

1. **Fail closed.** Missing secrets → connector `UNAVAILABLE` / `SECRET_UNRESOLVED:<NAME>` (already architecture).
2. **Names, never values** in docs, PRs, run reports, prompts, screenshots.
3. **Layered identities.** `snowflake_ro` ≠ `snowflake_dev` ≠ staging. Cloud default gets none of them.
4. **MOCK isolation.** Fake evidence cannot authorize real Git or deploy (DE-ADR-014).
5. **Sandbox GitHub.** `GITHUB_TOKEN_AIDE` scoped to a throwaway repo; never org-admin; never force-push; never `main`.
6. **No production in Cloud agents.** V1 production write is disabled anyway.
7. **Egress.** Today unrestricted. Before any live key is attached, restrict egress to required hosts or keep live keys Local-only.
8. **Snapshot reuse.** Warm-fork is good for speed; treat reused git state as possibly stale; never bake `.env` into snapshots.
9. **Human gates** unchanged: merge, secret entry, staging, production, identity/network changes.
10. **Phone-first** does not mean “paste keys into the mobile agent chat.”

---

## 6. Migration sequence

Do not retarget tasks until the named prerequisite is merged.

| Step | Task | What lands | Unlocks |
|------|------|------------|---------|
| 0 | DE 002A (in parallel; do not touch) | Contracts + minimal CI | Kernel on `main` |
| 1 | **OPS003** (recommended next infra) | uv + Postgres 16 snapshot; `.gitignore` allow for `.cursor/environment.json` and `.cursor/Dockerfile`; `scripts/verify-environment.sh` names-only checks | Cloud DE 002B/C *eligibility* |
| 2 | Governance follow-up (after operator accept) | Reclassify DE 002B/C to CLOUD in `.ai/TASKS.md` + DE-ADR-020 amendment | Agents may launch 002B in Cloud |
| 3 | DE 002B then DE 002C | Persistence + offline slice | Phone-first kernel |
| 4 | DE 003 | GHA Postgres, gitleaks, Docker **in CI** | Merge-quality integration tests without a Mac |
| 5 | DE 004 (already CLOUD) | Fixtures | Offline warehouse fakes at scale profiles |
| 6 | DE 005 / DE 008 / DE 012 as HYBRID | Fakes and dbt-duckdb in Cloud; live remaining Local | Parallel Cloud lanes without sharing live keys |
| 7 | Optional OPS00x | Dashboard DEV secrets + egress allowlist | Cloud live validation if the operator wants it |
| 8 | DE 017 / DE 018 live | Stay Local for staging and live demo | Recruiter rehearsal |

Integration rule: still one writer per branch; OPS002/OPS003 must not edit DE 002A files.

---

## 7. Estimated setup effort

| Work | Size | Notes |
|------|------|-------|
| OPS003 snapshot (uv + Postgres + ignore exception + verify script) | **S–M** (about one Composer 2.5 Cloud session) | No product code; human saves/activates the environment in the dashboard |
| DE 003 CI Docker expansion | Already estimated 2–3 h in the plan | Separate product-ops task |
| Optional nested Docker in Cloud | **M** and avoid unless testcontainers cannot run against native Postgres | |
| Hosted Postgres / K8s | Out of scope | Rejected as unnecessary |

---

## 8. Estimated monthly cost class

**Class: LOW** for the remote *development* environment itself.

| Item | Class | Comment |
|------|-------|---------|
| Cursor Cloud agents | Already incurred | Phone launches reuse this; no extra VM vendor |
| Native Postgres on the same VM | Negligible | No DBaaS invoice |
| GitHub Actions | Low | Private-repo minutes UNKNOWN until the operator’s plan is known; unit/integration for this repo should fit a modest allowance |
| PyPI / GitHub egress | Negligible | |
| Snowflake X-Small DEV | Low–medium, **usage-based**, Local/live only | Auto-suspend; not part of default Cloud |
| Staging warehouse | Low–medium, DE 017 only | |
| Production | None in V1 | |

Do not budget a second always-on cloud database or a container platform for MVP development.

---

## 9. What can move to Cloud immediately

Meaning: **no new infrastructure** beyond today’s Cursor Cloud + Python 3.12 + GitHub.

- Tasks already assigned CLOUD (DE 002A, later DE 003/004/006/007/009–011/013/015/016, DE 012 fake, DE 014 fake).
- Documentation and ops assessments (this task).
- Future **unit** tests that need only the stdlib and pure Python (DE 002A).

**Nothing in the LOCAL analysis set can fully move today.** This VM has no uv, no PostgreSQL, no Docker, no product tree, and no live secrets — which is correct — but DE 002B/C are blocked on Postgres, not on a Mac.

---

## 10. What should remain Local

- Secret and private-key **entry**
- Live Snowflake connector tests and live dbt-on-Snowflake
- Live GitHub sandbox PR validation until a dedicated token is granted
- Snowflake **account usage** (DE 014 local portion)
- **Staging execution** (DE 017 live)
- Live end-to-end demo rehearsal (DE 018 live)
- Production (disabled; human-only if ever enabled)
- iCloud handoff sync, LaunchAgents, `.ai/private/` bootstrap sources
- DE 019 independent review if it must read private context

Mac Docker remains a **fallback** for DE 002B until OPS003 ships, not a long-term requirement.

---

## 11. Recommended next infrastructure task

**OPS003 — Cursor Cloud snapshot for uv and PostgreSQL 16**

- Branch: `ops/OPS003_cloud_snapshot_uv_postgres` (proposed)
- Environment: CURSOR_CLOUD
- Allowed files (proposed): `.cursor/environment.json`, `.cursor/Dockerfile`, `.gitignore` (exception only), `scripts/verify-environment.sh`, `docs/ops/**`, `docs/agent/runs/OPS003/**`
- Forbidden: `src/**` product behavior, `.ai/TASKS.md` assignment edits unless the operator explicitly includes a reclassification, DE 002A paths
- Do: install uv + Postgres 16 in the snapshot; document env-var **names**; keep secrets empty
- Do not: attach Snowflake keys; install Kubernetes; add DBaaS; implement product code
- Human gate: save/activate the environment in the Cursor dashboard; confirm a follow-up Cloud agent can `uv --version` and connect to localhost Postgres

After OPS003 is proven, a small governance edit (DE-ADR-020 + `.ai/TASKS.md`) may retarget DE 002B and DE 002C to CLOUD. That edit is **out of scope for OPS002**.

---

## 12. Open questions (non-blocking)

| ID | Question | Default assumption |
|----|----------|--------------------|
| Q1 | Operator GitHub Actions minute quota | Treat as sufficient for LOW; confirm if workflows queue |
| Q2 | Whether testcontainers *must* be used in DE 002B vs native Postgres | Native Postgres is enough; testcontainers wait for DE 003 Docker-in-CI |
| Q3 | Whether the operator wants Cloud live Snowflake at all | Default **no**; keep live Local |
| Q4 | Sandbox GitHub repository identity for DE 012 | Unknown until DE 012; do not use AIDataEngineer `main` |
| Q5 | Tighten Cloud egress before any live key | Yes, if live keys are ever granted |

---

## 13. Validation of this assessment

| Check | Result |
|-------|--------|
| Read architecture, workflow, tasks, implementation plan, tech stack, connector architecture, CLOUD_HANDOFF | Done |
| Did not modify `src/**`, `tests/**`, `.ai/TASKS.md`, `.ai/ARCHITECTURE.md`, `.ai/DECISIONS.md`, `.github/**` | Constraint for this PR |
| Did not implement the environment | No packages installed for Postgres/uv/Docker as a product env |
| Did not change task environment assignments | Recommendations only |
| Cloud VM inventory | §1.2 |
| Expected base SHA | `b7d0e014a33d79047880ad4142d8107b4814a45f` after fetch of `origin/main` |
