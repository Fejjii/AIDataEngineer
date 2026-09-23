# Data Pilot AI

**Governed Data Engineering Control Plane**

Companies keep Snowflake, dbt, and their existing tools. For one locked customer-revenue
scenario, Data Pilot AI pins that estate, coordinates the engineering workflow, detects
one schema-drift failure, performs one bounded repair, and scores the evidence pack.

The Interview MVP on `main` is that governed closed loop: one request, one pinned Digital
Twin, one schema-drift incident, one automatic repair, and a read-only Independent
Verifier. The verifier scores the Supervisor's evidence for this drift-repair scenario.
It cannot dispatch tools or write workflow state. No LLM decides PASS or FAIL.

| Run the demo | Read the architecture | See what is in and out of scope |
|---|---|---|
| [`uv run aide interview demo`](#demo) | [Architecture](#architecture) | [Current limitations](#current-limitations) |

---

## What problem it solves

Modern data platforms are powerful and fragmented. Snowflake stores data. dbt transforms
it. Orchestrators schedule jobs. Humans still do the expensive work in between: finding
the right tables, modelling a product, generating tests, diagnosing a renamed column, and
proving the repair.

Typical failure modes:

| Problem | What happens without a control plane |
|---|---|
| Fragmented data stacks | Context lives in Slack, tickets, and tribal knowledge |
| Manual engineering work | Staging models, tests, and marts are written by hand |
| Incident diagnosis | A renamed source column becomes a multi-hour debug |
| Unsafe autonomous AI | An agent with warehouse credentials can overreach |
| No deterministic verification | “It looks right” replaces tests, reconciliation, and evidence |

Data Pilot AI is not a SQL chatbot and not a warehouse replacement. It is a **governed
executor** of typed capabilities. In this MVP the model design is recorded and validated;
deterministic code decides, executes, and records.

---

## Demo workflow

The Interview MVP converts one business request into a verified development data product.

```mermaid
flowchart TB
  BR["Business Request"] --> DT["Digital Twin"]
  DT --> EC["Estate Context"]
  EC --> SV["Supervisor"]
  SV --> GW["Governed Tool Gateway"]
  GW --> SX["Snowflake and dbt"]
  SX --> TQ["Tests and Quality"]
  TQ --> SD["Schema Drift"]
  SD --> DG["Diagnosis"]
  DG --> RP["Bounded Repair"]
  RP --> RV["Revalidation"]
  RV --> IV["Independent Verifier"]
  IV --> EB["Evidence Bundle"]
```

What that loop actually does:

1. Accept a customer-revenue request against the synthetic Vantara estate.
2. Capture and pin an immutable Digital Twin snapshot.
3. Assemble bounded, grant-filtered estate context.
4. Generate and run the dbt data product in workflow-scoped `AIDE_DEV` objects.
5. Inject `INVOICE_STATUS` → `STATUS` on `BILLING.INVOICES`.
6. Detect `SCHEMA_MISMATCH`, apply one allow-listed column-reference repair, and revalidate.
7. Let a read-only Independent Verifier score the drift-repair evidence pack. Verdict is `PASS` or `FAIL`.

---

## Architecture

Control plane and data plane stay separate. External tools stay replaceable. Verification
cannot mutate the workflow it scores. PostgreSQL is the only control-plane store.

```mermaid
flowchart TB
  subgraph CP["Control Plane"]
    SV["Deterministic Supervisor"]
    TW["Enterprise Data Digital Twin"]
    EC["Bounded Estate Context"]
    PE["Policy Engine"]
    GW["Governed Tool Gateway"]
  end

  subgraph DP["Data Plane"]
    RAW["VANTARA_RAW inspection"]
    DEV["Workflow-scoped AIDE_DEV"]
  end

  subgraph EXT["External Tools"]
    SF["Snowflake"]
    DBT["dbt Core"]
  end

  subgraph VER["Verification"]
    QT["dbt tests and Quality Engine"]
    IV["Read-only Independent Verifier"]
  end

  subgraph PER["Persistence"]
    PG[("PostgreSQL 16")]
    EV["Immutable evidence bundle"]
  end

  SV --> TW
  TW --> EC
  EC --> SV
  SV --> PE
  PE --> GW
  GW --> SF
  GW --> DBT
  SF --> RAW
  SF --> DEV
  DBT --> DEV
  GW --> QT
  QT --> IV
  SV --> PG
  TW --> PG
  GW --> PG
  IV --> EV
  EV --> PG
```

| Plane | Responsibility | Interview MVP fact |
|---|---|---|
| Control plane | Plan, authorize, dispatch, bound repair | Deterministic Supervisor; no multi-agent framework |
| Data plane | RAW inspection and DEV writes | RO reads RAW; RW writes only workflow-scoped `AIDE_DEV` |
| External tools | Warehouse and transformation | Snowflake and dbt Core only |
| Verification | Tests, quality, verdict | Independent Verifier scores the evidence pack; it has no connector or workflow-write access |
| Persistence | Twin, intents, audit, evidence | PostgreSQL 16; append-only evidence manifest |

Every workflow connector action enters the Governed Tool Gateway: validate → policy → persist intent →
execute → reconcile ambiguous side effects → persist evidence. Credentialed validation may inspect
Snowflake grant metadata directly, and live cleanup may drop that workflow's DEV schemas directly.
Neither call is product workflow execution.

```mermaid
sequenceDiagram
  participant SV as Supervisor
  participant GW as Governed Tool Gateway
  participant DBT as dbt Core
  participant SF as Snowflake DEV
  participant RP as Repair validator
  participant IV as Independent Verifier

  SV->>GW: generate, compile, execute, test
  GW->>DBT: DEV-only dispatch
  DBT->>SF: workflow-scoped objects
  Note over SV: Inject INVOICE_STATUS to STATUS
  SV->>GW: detect SCHEMA_MISMATCH
  SV->>RP: allow-listed column reference only
  RP-->>SV: one patch applied
  SV->>GW: recompile, rerun, revalidate
  IV->>IV: read-only PASS or FAIL
  IV-->>SV: evidence bundle
```

---

## Interview MVP capabilities

Implemented on `main` (MVP001–MVP004). This is what the repository actually runs.

| Capability | Implemented |
|---|---|
| Enterprise Data Digital Twin in PostgreSQL | Yes — Snowflake schema metadata and accepted drift evidence, pinned in a snapshot |
| Pinned twin snapshot and bounded estate context | Yes — one snapshot per workflow; grant-filtered; no source rows in reasoning context |
| Deterministic Supervisor | Yes — application workflow, not an autonomous agent loop |
| Governed Tool Gateway | Yes — sole execution path for workflow actions to Snowflake and dbt |
| Deterministic modelling engine | Yes — validates a recorded design against objective signals |
| Bounded dbt generation and DEV execution | Yes — the recorded 21-model customer-revenue project, executed in workflow-scoped DEV |
| dbt tests, quality checks, and reconciliation | Yes — generated dbt tests, model presence, mart checks, and fact-to-mart sums |
| Schema-drift detection | Yes — `INVOICE_STATUS` → `STATUS` |
| Bounded automatic repair | Yes — one allow-listed SQL column-reference correction |
| Read-only Independent Verifier | Yes — deterministic `PASS` / `FAIL` on the drift-repair evidence pack |
| Immutable evidence bundle | Yes — required sections, content digests, 100% completeness gate |
| Offline deterministic benchmark | Yes — two equivalent runs; no LLM judge |
| Credential-gated Snowflake live smoke | Yes — governed path; missing secrets exit `2`, not a weakened test |

**Not implemented.** Do not read vendor names in architecture docs as shipping connectors.

| Connector / surface | Status |
|---|---|
| Databricks | Future connector extension |
| Microsoft Fabric | Future connector extension |
| Airflow | Future connector extension |
| BigQuery | Future connector extension |
| GitHub delivery / pull requests | Designed in V1 docs; **not** in Interview MVP |
| Frontend SPA | Designed in V1 docs; **not** in Interview MVP |
| Production or staging deploy | Disabled |
| Generic unbounded autonomous loop | Explicitly out of scope |

---

## Data Engineering tasks automated

The Interview MVP automates one closed engineering loop, not the entire enterprise backlog.

| Task | How it is automated |
|---|---|
| Discovery | Enumerate and describe allow-listed Snowflake assets |
| Profiling | Deterministic profiles and relationship candidates |
| Asset selection | Fixed relevant-asset selection for this Interview scenario |
| Data modelling | Recorded design, validated against objective signals |
| dbt generation | Staging, intermediate, current-row dimensions, facts, mart, tests, YAML |
| Pipeline execution | dbt compile / run in workflow-scoped DEV |
| Testing | Generated and executed dbt tests |
| Quality | Required model presence, mart checks, and reconciliations |
| Reconciliation | Fact-to-mart invoice-line and payment sums |
| Incident diagnosis | `SCHEMA_MISMATCH` from injected source drift |
| Bounded repair | One validated column-reference patch; tests cannot be weakened |
| Verification | Read-only Independent Verifier over the drift-repair evidence pack |
| Evidence | Canonical bundle with section digests |

GitHub PR preparation, duplicate-payment repair, docs/lineage publication, and staging
deploy remain deferred. They are not counted as automated in the benchmark.

---

## What makes this different

| Property | Why it matters |
|---|---|
| Enterprise Data Digital Twin | Estate understanding is a pinned snapshot, not a chatty catalogue dump |
| Vendor-neutral control plane | Orchestrator reasons about capabilities, not “call Snowflake” |
| Deterministic Supervisor | Explicit phases and persisted state; no hidden agent graph |
| Governed Tool Gateway | Policy, intent, execution, reconcile, and evidence on every governed workflow tool call |
| Least privilege | Distinct RO and DEV identities; no broad RAW grant to DEV |
| Bounded automatic repair | One allow-listed repair class; broader diffs block |
| Independent Verifier | Scores the scenario evidence pack; cannot dispatch tools, re-execute the warehouse, or write workflow state |
| Immutable evidence | Application-audit bundle with required sections and digests |
| Deterministic benchmark | Two offline runs compared after explicit identifier normalization |
| No LLM judge | PASS / FAIL is code over evidence |

---

## Benchmark results

Source: MVP004 offline Interview scenario
(`interview_mvp_customer_revenue_schema_drift`), recorded in
[`docs/agent/runs/MVP004/MVP004-SESSION-20260915T103100Z-bc01a0a49e.md`](docs/agent/runs/MVP004/MVP004-SESSION-20260915T103100Z-bc01a0a49e.md)
and asserted by `tests/integration/interview/test_benchmark.py`. The table is the
measured sample from that recorded run. Tests lock repair count, human interventions,
evidence completeness, and determinism; they do not freeze every absolute count.

**Measured** (not estimates):

| Metric | Value |
|---|---:|
| Relevant assets analyzed | 10 |
| Generated models | 21 |
| Governed tool operations | 36 |
| Policy evaluations | 36 |
| Tests executed | 23 |
| Quality checks | 25 |
| Detected incidents | 1 (`SCHEMA_MISMATCH`) |
| Automatic repairs | 1 |
| Human interventions | 0 |
| Evidence completeness | 100% |
| Deterministic benchmark | PASS |

The 36 governed operations and the 36 policy evaluations are the same dispatch population:
one policy evaluation is recorded for each governed dispatch. The 23 tests are the
generated dbt test count. The 25 quality checks include required model presence plus mart
checks and reconciliations.

The historical manual-engineering estimate stays only in
[`docs/EVALUATION_STRATEGY.md`](docs/EVALUATION_STRATEGY.md) §4. It is not a measured
result of this table.

**Unavailable on the offline path, never invented:** LLM token cost, Snowflake credits,
financial ROI.

Wall-clock duration is measured per host and is not a product SLA.

---

## Demo

PostgreSQL 16 or newer must be reachable at `AIDE_DATABASE_URL` or `AIDE_TEST_DATABASE_URL`.
Offline validation uses PostgreSQL 16. The Railway demo is live-validated on PostgreSQL 18.6.
The CLI fallback (Cursor Cloud / OPS003 local role) is
`postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev`. Export a matching DSN if your
role or password differs. Docker Compose uses `POSTGRES_USER` / `POSTGRES_PASSWORD`
from `.env.example`.

```bash
uv sync --frozen --all-groups
uv run alembic upgrade head
uv run aide interview demo
uv run aide interview benchmark
```

Docker Compose (one app + PostgreSQL 16, no Snowflake credentials): see
[`docs/ops/SYNTHETIC_CLOUD_DEMO.md`](docs/ops/SYNTHETIC_CLOUD_DEMO.md).

| Command | What you see |
|---|---|
| `uv run aide interview demo` | Human report of the 15-step closed loop, Independent Verifier verdict, evidence digest, determinism, final PASS or FAIL. Runs the scenario **twice**. Exit `0` only on PASS. |
| `uv run aide interview benchmark` | The same run plus the scorecard: drift, repair safety, tests, quality, reconciliation, verifier, evidence completeness, repeatability. |
| `uv run aide interview demo --json` | Machine-readable payload of the same result. |

Offline demo uses fake Snowflake and fake dbt. No vendor credentials are required.

Optional credentialed smoke (env **names** only; never paste values into chat):

```bash
uv run aide interview live-smoke
```

Requires `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_RO`, `SNOWFLAKE_PRIVATE_KEY_RO`,
`SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`, and `SNOWFLAKE_WAREHOUSE_DEV`.
Missing credentials exit `2` (`CREDENTIAL_GATED`). The test is not weakened. Live smoke
does not mutate `VANTARA_RAW` to recreate drift; the drift → repair → verifier loop is the
offline proof.

Full interview script: [`docs/INTERVIEW_DEMO.md`](docs/INTERVIEW_DEMO.md).

---

## Safety and governance

| Control | Interview MVP behaviour |
|---|---|
| DEV only | Production and staging actions are disabled |
| RAW read boundary | `AIDE_DEV_RO` inspects `VANTARA_RAW`; `AIDE_DEV_RW` does not |
| No broad RAW DEV grant | Manifest-mediated dual load into workflow-scoped DEV sources |
| Policy before execution | Every gateway call persists a deterministic risk decision |
| Persisted intent | Dispatch intent, attempt, and fence are recorded before execute |
| Reconcile before retry | Ambiguous side effects are never blindly repeated |
| One automatic repair | Second class, broader AST diff, or failed revalidation blocks |
| Read-only Independent Verifier | Scores the drift-repair evidence pack; no gateway, connector, or workflow-write dependency |
| Evidence integrity | Missing or digest-mismatched required sections fail the verdict |
| Legacy demo routes | `POST /v1/sessions`, `POST /v1/workflows`, and `GET /v1/workflows/{workflow_id}/events` are the earlier DE002C slice |

The public synthetic demo also exposes those legacy routes. They use fake connectors and
can write to the demo PostgreSQL control plane. They are not protected by the Interview
demo token, and they are not the Interview product API. Gate them before broader public
promotion. Detail is in
[`docs/ops/SYNTHETIC_CLOUD_DEMO.md`](docs/ops/SYNTHETIC_CLOUD_DEMO.md).

Evidence is transactional application-audit immutability, not cryptographic tamper
evidence. That limitation is intentional and documented.

---

## Technology

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Packaging | uv, committed `uv.lock` |
| Control-plane store | PostgreSQL 16 or newer, SQLAlchemy 2, Alembic |
| API | FastAPI (thin health, session, and workflow submit; no product UI) |
| CLI | Typer (`aide interview …`) |
| Warehouse | Snowflake (real + deterministic fake) |
| Transformation | dbt Core 1.11 with `dbt-duckdb` offline and `dbt-snowflake` live |
| SQL safety | sqlglot parse / render / reparse |
| Quality | Deterministic Quality Engine; no LLM judge |
| Orchestration | Custom state machine; not LangGraph, LangChain, CrewAI, or AutoGen |

---

## Repository map

Start at this README, then the interview demo, then architecture.

```text
AIDataEngineer/
├── README.md                 ← you are here
├── docs/
│   ├── INTERVIEW_DEMO.md     ← how to run and narrate the demo
│   ├── ARCHITECTURE.md       ← accepted architecture (Interview vs V1 design)
│   ├── MVP_SCOPE.md          ← implemented Interview MVP boundary
│   ├── evaluation/           ← FINAL-QA-001 scorecard (not the landing page)
│   ├── pivot/                ← PIVOT001 contract
│   └── agent/runs/           ← execution evidence (not the landing page)
├── src/aide/
│   ├── app/                  ← Supervisor, gateway, interview, benchmark
│   ├── twin/                 ← Digital Twin
│   ├── verification/         ← Independent Verifier and evidence bundle
│   ├── repair/               ← bounded repair
│   ├── connectors/           ← snowflake/ and dbt/ (real + fake)
│   ├── policy/               ← deterministic policy and SQL classifier
│   ├── modelling/            ← modelling engine
│   ├── generation/           ← bounded dbt generation
│   ├── quality/              ← quality and reconciliation
│   └── cli/                  ← aide interview demo | benchmark | live-smoke
├── synthetic/vantara/        ← deterministic Vantara fixtures
├── dbt/                      ← dbt project skeleton
└── tests/                    ← unit, integration, connector, security, contracts
```

Reviewer path:

1. This README (product in ~60 seconds).
2. [`docs/INTERVIEW_DEMO.md`](docs/INTERVIEW_DEMO.md) (run and talk track).
3. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and
   [`docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md`](docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md).
4. `src/aide/app/supervisor.py`, `src/aide/app/gateway.py`, `src/aide/verification/`.

Agent run reports under [`docs/agent/runs/`](docs/agent/runs/) are session evidence. They
are not the product introduction.

---

## Documentation index

| Document | Why open it |
|---|---|
| [Interview demo](docs/INTERVIEW_DEMO.md) | Commands, expected PASS criteria, live-smoke posture |
| [Synthetic cloud demo](docs/ops/SYNTHETIC_CLOUD_DEMO.md) | Compose + PostgreSQL packaging for remote synthetic runs |
| [Operator console](docs/ops/OPERATOR_CONSOLE.md) | Authenticated browser run of the fixed synthetic scenario |
| [Interview MVP scope](docs/MVP_SCOPE.md) | Implemented boundary and hard limits |
| [Architecture](docs/ARCHITECTURE.md) | Accepted DE001 architecture; Interview vs V1 design |
| [PIVOT001 contract](docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md) | Twin, gateway, repair, verifier, acceptance tests |
| [Interview evaluation](docs/evaluation/README.md) | Implemented scorecard, adversarial tests, FINAL-QA-001 |
| [Evaluation strategy](docs/EVALUATION_STRATEGY.md) | V1 evaluation design + labelled time baseline; not an `aide eval` CLI |
| [Execution flow](docs/EXECUTION_FLOW.md) | V1 worked example (broader than the Interview MVP) |
| [Capability model](docs/CAPABILITY_MODEL.md) | Typed capabilities the orchestrator may invoke |
| [Connector architecture](docs/CONNECTOR_ARCHITECTURE.md) | Protocol, Snowflake/dbt, future kinds |
| [Data engineering map](docs/DATA_ENGINEERING_CAPABILITY_MAP.md) | Lifecycle taxonomy versus automation |
| [Permission model](docs/PERMISSION_MODEL.md) | Grants, policy, identities, repair bounds |
| [Quality strategy](docs/QUALITY_STRATEGY.md) | Deterministic checks; no LLM correctness judge |
| [Tech stack](docs/TECH_STACK.md) | Language, store, dbt, tooling decisions |
| [ADRs](docs/adr/README.md) | Architecture decision records |

---

## Current limitations

The Interview MVP is intentionally narrow.

- One business scenario: Vantara customer revenue.
- One automatic repair class: allow-listed `INVOICE_STATUS` → `STATUS` column reference.
- Snowflake and dbt only; other vendors are future extensions.
- Production and staging are disabled.
- Browser surface is the authenticated operator console for the one fixed scenario. There is no generic request UI.
- CLI and the evidence report remain the non-browser interfaces.
- No generic autonomous loop, dynamic tool selection, or unbounded estate traversal.
- GitHub delivery, monitoring, and a required live LLM provider are out of scope.
- Live Snowflake smoke is credential-gated and does not run RAW drift or the Independent Verifier.
- Legacy DE002C session, workflow, and event routes are off unless `AIDE_LEGACY_ANONYMOUS_ROUTES=1`.
- Evidence is application-audit immutability, not cryptographic tamper evidence.

---

## Roadmap

Logical connector expansion after the Interview MVP. **None of these are implemented.**

```text
Implemented today
  PostgreSQL control plane
  Snowflake
  dbt Core

Future connector extensions
  Databricks
  Microsoft Fabric
  Airflow
  BigQuery
  cloud platforms (object storage, additional warehouses)
  BI tooling (semantic / dashboard metadata)
```

Adding a warehouse or transformation platform is a connector plus tests. It is not a
rewrite of Supervisor, policy, or the verifier.

---

## Why this matters

Most “AI data engineer” demos generate SQL. This repository shows a **control plane**:
pinned estate context, least-privilege identities, a policy gateway, one bounded repair,
and an independent verifier that cannot mark its own homework. That is the difference
between an assistant that talks about data engineering and a system that can be trusted
to perform a slice of it.
