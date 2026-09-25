# MVP Scope — Data Pilot AI Interview

**Task:** PIVOT001
**Status:** IMPLEMENTED — MVP001–MVP004 merged to `main`
**Authoritative contract:** `docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md`
**Landing page:** repository `README.md` · **Demo:** `docs/INTERVIEW_DEMO.md`

## 1. Interview promise

Data Pilot AI demonstrates one complete governed closed loop:

1. Inspect the Vantara `tiny` estate in Snowflake.
2. Persist Snowflake schema metadata and accepted drift evidence in the PostgreSQL Digital Twin.
3. Accept one customer and revenue request.
4. Pin one `TwinSnapshot` and assemble bounded, authorized context.
5. Validate the recorded customer-revenue design with the deterministic modelling engine.
6. Execute that recorded dbt project in workflow-scoped Snowflake DEV objects.
7. Validate dbt tests and deterministic revenue/payment reconciliation.
8. Inject the Vantara `INVOICE_STATUS` → `STATUS` schema drift.
9. Detect, diagnose, and apply one allow-listed column-reference correction.
10. Revalidate, run the read-only Independent Verifier, and emit a final evidence report.

The required modes are a deterministic offline run and one credentialed Snowflake/dbt DEV
smoke. No production or staging action is part of the interview.

## 2. Fixed product boundary

| Area | Interview MVP |
|---|---|
| Systems | PostgreSQL 16 control state, Snowflake, dbt Core |
| Company | Vantara `tiny`, v1 and v2 |
| Request | One customer-revenue data product from CRM, billing, payments, and plans |
| Digital Twin | Snowflake schema metadata and accepted drift evidence; PostgreSQL only |
| Context | One pinned snapshot; server-authorized scope; deterministic bounds; no source rows in model context |
| Control | Deterministic Supervisor application responsibility over the existing state machine |
| Reasoning | Typed, tool-less capabilities grouped as Estate Intelligence, Data Engineering, and Reliability |
| Modelling | Deterministic modelling engine validates a recorded design against objective signals |
| Execution | Existing Snowflake/dbt foundations through the sole Governed Tool Gateway; workflow-scoped `AIDE_DEV` objects |
| Quality | dbt compile/build/tests, fact-to-mart reconciliation, and fixture-independent currency, refund, grain, duplicate-payment, and deleted-CRM checks |
| Fault | One injected rename: `BILLING.INVOICES.INVOICE_STATUS` → `STATUS` |
| Repair | One allow-listed reference-only dbt SQL correction; at most one automatic application |
| Verification | Read-only deterministic verifier over immutable evidence; optional LLM explanation cannot set verdict |
| Output | One immutable evidence bundle and one human-readable report with cost/timing metadata |
| Interface | CLI/demo command and report only; no frontend requirement |

## 3. Explicitly out of scope

- Databricks, Fabric, Airflow, Power BI, Tableau, or any second data-platform vendor.
- Graph database, Temporal, LangGraph, LangChain, CrewAI, AutoGen, or any multi-agent
  framework.
- Enterprise IAM, multi-tenancy, policy administration UI, or generalized governance
  catalogue.
- Production writes, staging deployment, destructive actions, infrastructure changes, or
  security administration.
- GitHub delivery, a real LLM provider requirement, generalized monitoring, streaming,
  migration, optimization, or a large frontend.
- A second business request, duplicate-payment repair, or any second automatic repair
  class.
- Unbounded tool selection, retry, repair, context retrieval, or estate traversal.

These may appear only as deferred extension points. They carry no MVP implementation or
acceptance burden.

## 4. Acceptance criteria

1. The twin captures Snowflake schema metadata for the selected physical assets and
   fields, plus accepted drift evidence. It does not require dbt model, profile, or test
   observations for Interview acceptance.
2. Every workflow pins one `TwinSnapshot`; later captures cannot change its context, plan,
   or evidence digest.
3. Context contains only authorized snapshot members, respects all hard bounds, and blocks
   instead of silently truncating required facts.
4. The deterministic modelling engine validates a recorded design against objective
   signals and cited twin evidence. It does not freely select or generate that design.
5. Every Snowflake/dbt execute, cancel, and reconcile call enters the Governed Tool
   Gateway and has a persisted intent, risk decision, result, evidence, and audit record.
6. `AIDE_DEV_RW` cannot read or write `VANTARA_RAW`; the manifest-mediated dual load
   reconciles selected RAW and workflow DEV sources to the same immutable Vantara input.
7. dbt compile/build/tests and deterministic revenue/payment reconciliation pass before
   drift.
8. The injected rename is detected and classified as `SCHEMA_MISMATCH`.
9. Exactly one allow-listed, reference-only patch is applied; broader changes, a second
   repair, test weakening, or failed revalidation block.
10. Full post-repair validation passes and every ambiguous side effect is reconciled before
    retry or verdict.
11. The Independent Verifier has no connector or workflow-write authority and returns
    `PASS` only from complete, immutable, digest-valid deterministic evidence.
12. The final bundle contains request, twin snapshot/context, plan, risk decisions, tool
    actions, code before/after, tests, reconciliation, failure, repair, final validation,
    verifier result, and cost/timing metadata.
13. Repeatability compares normalized structural fingerprints. Two offline runs produce
    identical normalized fingerprints for plan, context, repair, validation, verifier,
    and evidence.
14. One credentialed Snowflake/dbt DEV smoke completes without a production/staging action
    or new RAW grant.

The executable test mapping is `docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md` §14.

## 4.1 Data modelling limitation

The demo revenue mart grain is `customer_sk`, `date_day`, and canonical invoice
currency. `invoiced_amount`, `paid_amount`, and `refunded_amount` are not summed
across currencies, and `net_paid_amount` is paid minus refunded on that grain.
There is no FX conversion. Dimension tables expose current-row validity columns.
That shape is not full Type 2 history. Open amount, active subscriptions, and MRR
are not in the mart.

## 5. Hard bounds

| Bound | Value |
|---|---:|
| Business requests | 1 |
| Synthetic companies / profiles | 1 / Vantara `tiny` |
| Real warehouse / transformation vendors | 1 / 1 |
| Pinned twin snapshots per workflow | 1 |
| Top-level context assets | 12 |
| Context fields / relationships / observations | 120 / 64 / 32 |
| Relationship traversal depth | 2 |
| Serialized estate context | 64 KiB |
| Source rows in reasoning context | 0 |
| Repair proposals | 2 |
| Automatic repair applications per task/workflow | 1 / 1 |
| Post-repair full revalidation | 1 |
| Recursive repairs | 0 |
| Automatic repair classes | 1 |

Existing operation `max_attempts` remains authoritative but is capped at two for this
workflow. Every ambiguous side effect reconciles before another attempt.

## 6. Deferred extension points

Only provider-neutral versioned ports may be named for a future graph store, external
principal provider, monitor scheduler, evidence exporter/signer, additional connector
kinds, and specialist sub-workflows. MVP001–MVP004 do not implement those ports unless an
executable acceptance test above requires the core interface directly.
