# MVP Scope — Recruiter-Ready V1

**Task:** DE 001 · **Status:** PROPOSED

The MVP is one strong, repeatable, end-to-end workflow on a synthetic enterprise, executed
against real Snowflake development objects and a real dbt project, with a real GitHub pull
request, and with the whole thing also runnable **offline** against deterministic fakes.

---

## 1. The MVP promise (what a recruiter sees in five minutes)

1. A natural-language requirement is typed in:
   *"Build a customer revenue data product from CRM and billing. Deduplicate customers,
   reconcile billing to payments, track plan changes historically, add quality tests,
   document lineage and prepare it for deployment."*
2. The system restates the requirement, lists assumptions, and asks one clarification
   (how to define *active customer*). The human answers.
3. The system discovers the relevant Snowflake schemas and tables (13 found, 10 selected)
   — no table names were hard-coded — and profiles them: duplicates, nulls, identifier
   mismatch, key candidates.
4. The system decides a modelling strategy (layered staging → intermediate → star schema,
   SCD2 on customer and plan) and explains why the rule table chose it.
5. The system generates dbt models, tests and docs and runs them in Snowflake DEV.
6. A run **fails** (renamed source column). The system classifies the failure, diagnoses
   it with evidence, patches the staging model, re-runs, and the build goes green.
7. A **test fails** (duplicate payments break fact grain). The system diagnoses, adds a
   deterministic deduplication rule in the intermediate layer, re-runs, tests pass.
8. Documentation and a lineage graph appear. A GitHub branch and pull request are created
   with a generated summary.
9. The system materializes `deploy_staging` in the same DELIVERY phase run, then asks for
   a typed `OperationApproval` bound to that operation. Nothing deploys until the complete
   subject is approved.
10. The audit timeline shows every plan, policy decision, tool call, model call with cost,
    repair, and approval. A metrics panel shows first-attempt success, repairs, tokens,
    cost, and estimated engineering time saved.

---

## 2. In scope (V1)

| Area | V1 deliverable |
|---|---|
| Interface | Minimal web SPA: request form, clarification dialog, plan view, task timeline, artifact viewer (SQL/YAML/docs/lineage), validation results, approval buttons, connector status, metrics. Plus CLI for the same flows. |
| Requirement understanding | `interpret_requirement` → typed `RequirementSpec`; ambiguity detection → clarification questions; max 2 clarification rounds. |
| Discovery | Snowflake `INFORMATION_SCHEMA` / `SHOW` based catalogue for allow-listed databases/schemas; PostgreSQL synthetic source discovery. |
| Profiling | Deterministic profile SQL with budgets; candidate keys; candidate relationships; duplicate and null detection. |
| Ad-hoc development SQL | `generate_sql_query` (read-only SELECT or single DEV `CREATE TABLE AS`) for investigation-type requests and the DE 002 slice; always classified, EXPLAIN-validated and policy-checked. |
| Modelling | Rule-table selection among: layered staging/intermediate/marts; star schema; SCD1/SCD2; incremental vs full refresh. Data Vault detection only (recommend, not generate). |
| Generation | dbt models (staging, intermediate, dims, facts, one mart), `schema.yml` with tests, `sources.yml`, model docs; Snowflake dialect. |
| Execution | `dbt build` in DEV schema via dbt connector; `execute_query` for validation; timeouts and cost caps. |
| Quality | dbt tests + Quality Engine checks (uniqueness, not-null, referential integrity, accepted values, reconciliation of totals, row counts, freshness). |
| Failure & repair | Deterministic classifier; bounded repair for `SQL_SYNTAX`, `MISSING_OBJECT`, `SCHEMA_MISMATCH`, `TYPE_MISMATCH`, `DBT_COMPILE`, `DBT_RUNTIME`, `DBT_TEST`, `DATA_QUALITY`; max 2 repairs per task, 4 per workflow. |
| Documentation & lineage | Model + column docs; lineage graph from dbt manifest + SQL parsing; rendered in UI and stored as artifact. |
| Delivery | Git branch + commit + push + PR; `deploy_staging` is operation-approval-gated; separate `deploy_production` is disabled and unadvertised in V1. |
| Identity, policy & approvals | Local opaque server session → trusted principal; server-authorized workflow grants. Typed operation/design/budget subjects; operation approval binds operation key, resolved-input digest, artifact/provenance hashes, connector/version, target, expiry and relevant external state. |
| Audit & observability | Audit timeline; model call accounting; tool call accounting; cost per workflow. |
| Evaluation | Benchmark harness with ≥ 3 repeatable scenarios (happy path, schema drift failure, quality failure). |
| Synthetic enterprise | `docs/DEMO_COMPANY.md` company generated into PostgreSQL and loaded to Snowflake RAW. |
| Offline mode | Whole flow against fake Snowflake/dbt/GitHub/LLM replays for CI and demos without credentials. |

---

## 3. Explicitly not attempted in V1

| Not in V1 | Reason | Earliest phase |
|---|---|---|
| Production deployment execution | No production target exists; keep approval boundary demonstrable without risk | After staging identity and rollback path exist |
| Streaming / CDC ingestion | Different runtime model; not needed for demo value | V2+ |
| Ingestion connectors for APIs, S3, Azure Storage | Sources land in RAW via synthetic loader | V2 |
| Spark / Databricks / Fabric / Airflow / BI connectors | Connector interface designed for them; none implemented | V2+ as separate connector tasks |
| Semantic layer generation | Requires BI target | V2 |
| Query and warehouse optimization *actions* | V1 collects execution metrics and cost, emits recommendations only | V2 |
| Live monitoring loop | V1 registers monitor definitions (freshness/tests) as artifacts; no scheduler runs them | V2 |
| Multi-tenant/federated IAM and RBAC administration UI | V1 uses one local account with distinct operator/approver role checks and server-side grants | Enterprise showcase |
| Data Vault generation | Detection and recommendation only | V2 |
| Python/Spark transformation generation | dbt SQL only in V1; Python hook reserved | V2 |
| Vector search over enterprise docs | Not needed at catalogue scale | Only if asset counts demand |
| Autonomous destructive operations | Never automatic | Never |
| Security/identity/network changes | Disabled | Never for the agent |

---

## 4. MVP acceptance criteria (objective)

1. Discovery finds all demo tables without hard-coded names; catalogue artifact persisted.
2. Profiling identifies the planted duplicates, nulls, and identifier mismatch (see `docs/DEMO_COMPANY.md` §6).
3. Modelling engine selects the expected architecture for the demo requirement and the rationale cites objective signals.
4. Generated dbt project compiles and `dbt build` succeeds in Snowflake DEV after ≤ 2 repair cycles on the planted failures.
5. Both planted failures are detected, classified into the expected classes, and repaired automatically; the repair history shows distinct hypotheses.
6. All Quality Engine checks pass on the final data product; reconciliation of billed vs paid totals is reported.
7. Lineage artifact contains the expected edges (`docs/DEMO_COMPANY.md` §9).
8. GitHub PR is created; `deploy_staging` is materialized in the same DELIVERY run and remains `AWAITING_APPROVAL` / workflow `APPROVAL_REQUIRED` until its typed operation subject is approved.
9. Audit timeline is complete: every tool call and model call linked to a task; no secret appears in any artifact, log or prompt record (verified by automated scan in tests).
10. Same scenario completes in offline mode with fakes in CI in under 5 minutes.
11. Evaluation report shows the metrics in `docs/EVALUATION_STRATEGY.md` §3 for all three scenarios.

---

## 5. Non-functional bounds for V1

| Bound | Value |
|---|---|
| Max concurrent workflows | 5 (single node) |
| Max tasks per phase | 50 |
| Max clarification rounds | 2 |
| Max replans per phase | 2 |
| Max repair attempts per task / per workflow | 2 / 4 |
| Default task timeout | 300 s; `dbt build` 900 s |
| Query row cap for samples sent to LLM | 20 rows, masked columns |
| Warehouse | Snowflake X-Small with auto-suspend; estimated preflight budget plus hard statement/query bounds and attribution tags. No hard credit cap without isolated warehouse/resource monitor |
| LLM cost cap per workflow | Configurable; default USD 5; atomic reservation prevents dispatch above cap; continuation needs explicit new-cap/delta approval |
