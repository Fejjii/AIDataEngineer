# AIDataEngineer — Environments

Select an environment before work starts. Record it in `HANDOFF.md`.

## Selection rule

Use **LOCAL** when work requires private AI context, Mac tooling, local credentials,
iCloud synchronization, local Docker, or controlled live access.

Use **CURSOR_CLOUD** when the task is reproducible entirely from tracked GitHub state,
no local private files are required, no production secrets are required, and the task
can operate on an isolated branch.

---

## LOCAL

**Purpose:** Primary development on the Mac checkout at `~/Developer/AIDataEngineer`.

**Allowed:** Edit the working tree; run local tests; read ignored `.ai/private/` and
`.ai/local/` when needed; regenerate handoffs; run iCloud sync; use local Docker when
introduced; authorized Git writes on a task branch.

**Forbidden:** Bypass branch protection; force-push protected history; print secrets;
unauthorized production mutation; storing the Git repository inside a consumer sync folder.

**Credentials:** May use local `.env` and Mac keychain. Values never enter Git, handoffs,
or chat.

**Data:** Local/dev fixtures and sandboxes only. Treat any accidentally reachable live
system as read-only unless the task explicitly authorizes controlled access.

**Human gates:** Merge, deploy, secret entry, production writes.

**Typical models:** Composer 2.5 for specified work; Grok 4.6 / Muse Spark 1.3 for hard
implementation; Fable 5.1 for architecture inside Cursor.

---

## CURSOR_CLOUD

**Purpose:** Unattended or phone-launched implementation against GitHub on an isolated
branch.

**Allowed:** Read tracked files; implement on a task-owned branch; run tests available in
the Cloud image; open a PR when authorized.

**Forbidden:** Assume private local files exist; read production secrets; write iCloud;
merge `main`; modify live infrastructure.

**Credentials:** None implied. Use only secrets the Cloud task is explicitly granted.

**Data:** Tracked fixtures and synthetic data only.

**Human gates:** PR merge; any live or credentialed action.

**Typical models:** Muse Spark 1.3 for multi-step Cloud work; Composer 2.5 for specified
implementation; Grok 4.6 for difficult Cloud implementation.

Product-task mapping for Wave 0 (authoritative: DE-ADR-020 and
`docs/IMPLEMENTATION_PLAN.md` §3): **DE 002A is CURSOR_CLOUD**; **DE 002B and DE 002C
are LOCAL**. Later Cloud-eligible tasks are listed per-task in the implementation plan.

Cloud execution is ineligible when the task requires bootstrap sources, local `.env`,
Mac LaunchAgents, or other ignored files.

---

## GITHUB_ACTIONS

**Purpose:** Deterministic CI validation of tracked code.

**Allowed:** Lint, typecheck, unit/integration tests, secret scanning, build checks using
CI secrets.

**Forbidden:** Deploy to production; mutate live warehouses; use developer laptop state;
print secrets in logs.

**Credentials:** Repository or environment secrets via the platform secret store.

**Data:** CI fixtures only.

**Human gates:** Required checks on PRs once CI exists. Workflow file changes are
reviewed.

**Typical models:** Not a model environment. Agents may update workflow YAML with Composer
2.5 when authorized.

---

## APPLICATION_DEVELOPMENT

**Purpose:** Application sandbox for generated SQL, dbt, and pipelines (future).

**Allowed:** Schema discovery of permitted development objects; generate and execute
development SQL/dbt; create development artifacts within sandbox permissions; run tests.

**Forbidden:** Production writes; identity/network changes; unrestricted cost-heavy
warehouses without limits.

**Credentials:** Least-privilege development service accounts. Never production keys.

**Data:** Development or synthetic datasets. No production copies unless explicitly
approved and masked.

**Human gates:** Connecting a new live source; raising warehouse size/cost limits.

**Typical models:** Composer 2.5 / Grok 4.6 for connector and pipeline work.

---

## APPLICATION_STAGING

**Purpose:** Pre-production rehearsal of the product (future).

**Allowed:** Deploy from reviewed artifacts; run smoke tests; verify approvals and audit.

**Forbidden:** Treat staging as a playground for unreviewed agent experiments; use
production credentials; silent production promotion.

**Credentials:** Staging-specific secrets in a secret manager.

**Data:** Staging datasets. Production-like data only if approved and controlled.

**Human gates:** Staging deploy; any data refresh from production.

**Typical models:** Implementation models for fixes found in staging; Fable 5.1 for
release-blocking issues.

---

## APPLICATION_PRODUCTION

**Purpose:** Live customer/recruiter-demo production (future).

**Allowed:** Read-only observation when authorized; deploy only after approval.

**Forbidden:** Agent-initiated production data mutation, deletion, or pipeline deploy
without an explicit human gate; use of production secrets in prompts.

**Credentials:** Production secrets never in Git, Cloud prompts, or handoffs.

**Data:** Production data. Agents do not dump it into chat or docs.

**Human gates:** Every production deploy, credential rotation, destructive action, and
cost-impacting warehouse change.

**Typical models:** Independent Fable 5.1 / Astra review before first production
readiness. Not a coding playground.

---

## iCloud transport (not an execution environment)

`~/Library/Mobile Documents/com~apple~CloudDocs/AI-Projects/AIDataEngineer/`
receives only `HANDOFF.md` and `CHANGELOG_SESSION.md`. It is not a Git remote and not a
place to run agents.
