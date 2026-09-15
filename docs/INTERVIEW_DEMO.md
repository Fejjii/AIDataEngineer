# Interview Demo Guide — Data Pilot AI

**Task:** MVP004  
**Audience:** recruiters, hiring managers, and interviewers  
**Command:** `uv run aide interview demo`

## What this product demonstrates

Data Pilot AI is an **Autonomous Data Engineering Control Plane**. It does not replace
Snowflake, dbt, or an orchestrator. It sits above them and converts one business request
into a governed, tested, repaired, and independently verified development data product.

The interview story is fixed:

1. Receive a customer-revenue request.
2. Understand the relevant CRM and billing estate through a pinned Digital Twin.
3. Generate the bounded dbt data product.
4. Execute and validate it in workflow-scoped DEV objects.
5. Inject the accepted `INVOICE_STATUS` → `STATUS` schema drift.
6. Detect `SCHEMA_MISMATCH`.
7. Diagnose the renamed invoice status column.
8. Propose the one allow-listed SQL reference repair.
9. Validate the repair deterministically.
10. Apply it exactly once.
11. Recompile and rerun.
12. Execute dbt tests and revenue/payment reconciliation.
13. Run the read-only Independent Verifier.
14. Emit an immutable evidence bundle.
15. Report benchmark metrics and a deterministic PASS or FAIL.

## Why this is a control plane, not another warehouse

| This product | Not this product |
|---|---|
| Pins estate context and decides what may run | A place to store tables |
| Routes every connector call through a Governed Tool Gateway | A scheduler that fires dbt jobs |
| Enforces policy, least privilege, and one bounded repair | An unbounded AI agent |
| Proves PASS/FAIL from immutable evidence | An LLM judge of quality |
| Works offline deterministically, then optionally on Snowflake DEV | A production automation platform |

Snowflake remains the warehouse. dbt remains the transformation tool. PostgreSQL remains
the control-plane state store. The Supervisor is an application workflow, not a
multi-agent framework.

## Architecture summary

```text
business request
  → Supervisor (deterministic phase machine)
      → Digital Twin snapshot + bounded EstateContext
      → modelling engine (existing DE007 rules)
      → Governed Tool Gateway (policy → intent → execute → reconcile → evidence)
      → dbt in AIDE_DEV only
      → one allow-listed schema-drift repair
      → Independent Verifier (read-only)
      → EvidenceBundle (manifest of digests)
```

Identities:

- `AIDE_DEV_RO` inspects `VANTARA_RAW`.
- `AIDE_DEV_RW` writes only workflow-scoped `AIDE_DEV` objects.
- DEV has no broad RAW grant. Production and staging are disabled.

## Prerequisites

```bash
uv sync --frozen --all-groups
uv run alembic upgrade head
```

PostgreSQL 16 must be reachable at `AIDE_DATABASE_URL` or
`AIDE_TEST_DATABASE_URL` (default `postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev`).

Offline demo uses fake Snowflake and fake dbt. No vendor credentials are required.

## Offline demo command

```bash
uv run aide interview demo
```

This runs the accepted scenario **twice**, prints a concise human report, and exits
`0` only on deterministic PASS.

JSON:

```bash
uv run aide interview demo --json
```

Scorecard-focused:

```bash
uv run aide interview benchmark
```

## Live smoke command (credentials optional)

Required environment **names** (never paste values into chat):

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER_RO`
- `SNOWFLAKE_PRIVATE_KEY_RO`
- `SNOWFLAKE_USER_DEV`
- `SNOWFLAKE_PRIVATE_KEY_DEV`
- `SNOWFLAKE_WAREHOUSE_DEV`

```bash
uv run aide interview live-smoke
```

If those variables are absent, the command is **credential gated** (exit `2`). The test
is not weakened. Human action: set the named variables on a credentialed host. Do not
grant `AIDE_DEV_RW` any new `VANTARA_RAW` privilege.

Live checks:

- RO inspects RAW with read-only `SELECT`
- RO/DEV write prohibition is proven from `SHOW GRANTS TO ROLE` / future grants, never
  by issuing DML against `VANTARA_RAW`
- DEV cannot read RAW
- DEV stays in workflow-scoped `AIDE_DEV`
- the pinned fixture manifest reconciles selected RAW vs DEV copies
- the credentialed path then runs InterviewSupervisor → Governed Tool Gateway → real
  Snowflake RO/DEV → real dbt, with policy, dispatch intents, evidence persistence, and
  DEV-only execution
- Independent Verifier and RAW drift injection remain the offline closed-loop proof;
  live does not mutate RAW to recreate that drift
- no production or staging action; no GRANT/REVOKE SQL

The drift → repair → verifier closed loop is proven offline. Live `VANTARA_RAW` is the
already-loaded tiny v2 estate and must not be mutated.

## Expected sequence

The printed report follows the 15-step story above and ends with Independent Verifier
verdict, timing, cost classification, evidence bundle digest, determinism, and final
PASS or FAIL.

## Expected PASS criteria

Deterministic only. No LLM judge.

- Workflow completes inspect → build → drift → one repair → revalidation → verifier PASS
- Phase sequence is the accepted Interview MVP sequence
- Repair class is `SCHEMA_MISMATCH`; mapping is `INVOICE_STATUS` → `STATUS`; apply count is 1
- dbt parse/compile/execute, tests, quality, and reconciliation succeed
- Evidence bundle has every required section and matching artifact digests
- Two offline runs have equivalent stable fingerprints after explicit UUID/timestamp
  normalization
- Cost and warehouse timing fields are labelled MEASURED, ESTIMATED, or UNAVAILABLE

## Benchmark metrics

Measured where possible: assets analyzed, models generated, gateway operations, policy
evaluations, incidents, automatic repairs, human interventions (0), tests, quality
checks, evidence completeness %, wall-clock and repair duration.

Estimated and labelled: nine automated engineering steps / 690 minutes from the versioned
evaluation baseline. Deferred manual steps (duplicate-payment repair, docs/lineage, GitHub
PR) are not counted as automated.

Never invented: financial ROI, LLM token cost, or Snowflake credits on the offline path.

## Known limitations

- One business request and one automatic repair class
- No GitHub delivery, UI, real LLM provider, production, or staging
- Live RAW is not drifted; repair is the offline closed loop
- Cost metadata is classified, not fabricated
- Evidence is application-audit immutability, not cryptographic tamper evidence

## How to explain this in an interview

1. Start from the business request, not from a warehouse UI.
2. Show that estate understanding is a pinned Twin snapshot, not a chatty catalogue dump.
3. Show generated dbt models and the first green build.
4. Inject the rename and show `SCHEMA_MISMATCH` rather than a retry loop.
5. Show the repair validator refusing anything broader than one column reference.
6. Show the Independent Verifier reading evidence it cannot mutate.
7. Show two offline runs matching after normalized identifiers.
8. Say clearly: this is a control plane for governed data-engineering work, not a
   replacement for Snowflake, dbt, Airflow, or a BI tool.
