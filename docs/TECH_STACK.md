# Technology Stack

**Task:** DE 001 · **Status:** PROPOSED · ADRs: DE-ADR-008, 009, 012, 017, 018, 022, 024, 025

Selection rule: the simplest technology that satisfies the requirement, evaluated
independently of what previous projects used. Anything listed as *rejected* may be
re-proposed by ADR with evidence. Version pins are set in DE 002 after checking current
compatibility (notably dbt adapter ↔ Python version); this document fixes the *choices*.

---

## 1. Decisions

| Area | Decision | Why | Considered and rejected |
|---|---|---|---|
| Language / runtime | **Python 3.12** (highest version supported by `dbt-snowflake` and `snowflake-connector-python` at DE 002 time; re-verify then) | Ecosystem for Snowflake, dbt, SQL parsing; typing maturity | 3.13+/3.14 (adapter support lag); other languages (ecosystem) |
| Dependency management | **uv** with `pyproject.toml` + committed `uv.lock`; `uv run` for all commands | Fast, reproducible, single tool for venv + lock; used in engineering delta | pip + requirements (no lock discipline), Poetry (slower, second lock format), conda (unneeded) |
| Backend framework | **FastAPI** | Typed routers with Pydantic v2, OpenAPI for the SPA and evaluation harness, async, SSE support | Flask (less typing), Django (ORM/admin weight not needed), Litestar (smaller ecosystem) |
| Schema validation | **Pydantic v2** everywhere at boundaries (capability I/O, DTOs, settings, artifacts) | Strong typing, JSON schema generation for LLM structured outputs, fast | dataclasses + marshmallow (two systems), attrs+cattrs (no JSON schema out of the box) |
| Settings | **pydantic-settings** with a single `Settings` tree; `SecretRef` types; no direct `os.environ` outside `config/` | Central, typed, testable | dotenv scattered reads |
| State persistence | **PostgreSQL 16** | Durable workflow/task/audit state; JSONB for typed payloads; row locks (`SKIP LOCKED`) for a safe task queue; also serves as the synthetic source DB; enterprise-credible | SQLite (no concurrent workers, no SKIP LOCKED), MongoDB (no need for document DB; weaker transactional guarantees), Redis (not durable by default, extra service) |
| ORM / data access | **SQLAlchemy 2.0** (typed `Mapped[]` models, async engine via `asyncpg`) with repository classes; **Alembic** migrations | Mature, typed, migration tooling; repositories keep persistence out of domain | raw SQL only (boilerplate), SQLModel (thin layer, less control), Tortoise (smaller ecosystem) |
| Test database | PostgreSQL via Docker (`testcontainers-python` or compose) for integration; in-memory fake repositories for unit tests | Same engine as production; unit tests fast | SQLite for tests (dialect drift) |
| Workflow orchestration | **Custom** orchestrator: explicit state machine (transition table), phase DAG, worker loop — ~1–2k LOC, fully tested | Control flow must be auditable, deterministic, and typed; frameworks hide it | LangGraph (graph is the product; hidden state semantics; version churn), Temporal (excellent but a separate server and SDK learning curve not justified at V1 scale — reconsider for V3 durability), Prefect/Airflow (batch schedulers, not interactive control planes) |
| Agent framework | **None** | See `docs/AGENT_MODEL.md` | LangChain, CrewAI, AutoGen, Semantic Kernel (autonomy and abstraction not wanted) |
| LLM abstraction | **Own thin gateway**: `LLMProvider` protocol + adapters using official provider SDKs; structured output via JSON schema; versioned prompt files rendered with **Jinja2 sandboxed** templates; replay fake | Minimal surface; provider swap = one adapter; prompts inspectable and versioned | LangChain (unneeded abstraction), LiteLLM (useful multi-provider proxy; may be adopted later as an adapter if >2 providers), Instructor (nice, but Pydantic + provider JSON-schema modes already cover it) |
| Structured output enforcement | Provider JSON-schema/tool-call mode where available; fallback: JSON extraction + Pydantic validation + one repair retry | Correctness | Free-text parsing |
| Background execution | **In-process asyncio worker loop** claiming tasks from PostgreSQL (`FOR UPDATE SKIP LOCKED`), leases, idempotency keys; `aide worker` can run as a separate process of the same image | No extra broker; durable; enough for ≤ 5 concurrent workflows | Celery + Redis/RabbitMQ (two more services, at-least-once semantics need the same idempotency work anyway), RQ, Dramatiq, arq (need Redis) |
| Queueing | **PostgreSQL tables** (see above) | Same | Redis, Kafka, SQS |
| Blocking vendor SDK calls | `asyncio.to_thread` / bounded thread pool per connector | Snowflake connector is sync | Rewriting drivers |
| SQL parsing / dialects | **sqlglot** | Parse, classify, transpile (Snowflake → DuckDB for fakes), column lineage | sqlparse (no AST), vendor parsers |
| Warehouse fake | **DuckDB** in-process, loaded from synthetic fixtures; Snowflake SQL transpiled | Offline demo and CI; fast | Dockerized Postgres as "fake Snowflake" (dialect gap larger) |
| Snowflake client | `snowflake-connector-python` | Official | Snowpark (heavier; not needed for SQL execution) |
| dbt | `dbt-core` + `dbt-snowflake` via `dbtRunner` in a subprocess | Programmatic invocation with artifacts; process isolation | dbt Cloud API (external dependency; V2 option), SQLMesh (alternative transformation platform — connector candidate, not V1) |
| dbt offline integration target | **To evaluate in DE 008:** `dbt-duckdb` adapter so real dbt Core runs against the DuckDB fixtures in integration/contract tests; the lightweight deterministic dbt fake stays for unit tests (`docs/CONNECTOR_ARCHITECTURE.md` §5.2) | Exercise real dbt behaviour without Snowflake credentials | Fake only (misses dbt parsing/Jinja edge cases); live Snowflake only (credentials, cost, CI-hostile) |
| Git / GitHub | `git` CLI via subprocess wrapper; GitHub REST via **httpx** | Minimal, reliable | PyGithub (fine, heavier), GitPython (maintenance concerns) |
| PostgreSQL source client | **psycopg 3** (async) | Modern, async | psycopg2, asyncpg for app (asyncpg used via SQLAlchemy already; psycopg3 chosen for source connector to keep SQLAlchemy independent — may unify in DE 002) |
| Frontend | **Vite + React + TypeScript** SPA, minimal; **Tailwind** allowed for speed; state via React Query; SSE for live updates | Demonstrable, typed, small; no SSR needed | Next.js (SSR/routing weight not needed), HTMX + Jinja (faster to build, weaker recruiter impression and harder interactive timeline), Streamlit (prototype only) |
| Logging | **structlog** JSON with redaction processor | Structured, testable | stdlib only (formatting burden), loguru |
| Tracing | **OpenTelemetry** Python SDK; console/no-op by default; OTLP exporter optional | Standard; vendor-neutral | Langfuse/LangSmith (LLM-specific SaaS; may be added as an exporter later), custom only |
| Metrics store | PostgreSQL tables + derived views; optional OTel metrics | Enough for demo and evaluation | Prometheus (adds infra; V2 if needed) |
| Evaluation | **Own harness** (`aide eval`) on pytest + YAML scenarios; recorded LLM fixtures | Same code path as product; deterministic offline | promptfoo/DeepEval/Ragas (prompt-centric, not workflow-centric), LLM judges (circular) |
| Testing | **pytest**, `pytest-asyncio`, `hypothesis` (property tests for SQL classifier and state machine), `testcontainers` for PostgreSQL, `respx` for httpx mocking, `import-linter` for boundaries | Standard, strong | unittest |
| Static analysis | **ruff** (lint + format), **mypy --strict**, `import-linter`, `gitleaks` (secret scan), `bandit` (optional) | Fast, comprehensive | black+isort+flake8 (three tools) |
| Docker | `Dockerfile` (multi-stage, uv) for the app; `docker-compose.yml` for PostgreSQL (+ optional Jaeger); frontend built into the image or served separately in dev | Reproducible local and CI | Kubernetes manifests (not now) |
| CI | **GitHub Actions**: lint, typecheck, unit + integration (PostgreSQL service), offline evaluation scenarios, secret scan, Docker build, frontend lint/typecheck/build; live connector tests opt-in via environment secrets on `workflow_dispatch` | Required checks for `main` | Others |
| Secrets handling | env vars via pydantic-settings `SecretStr` + `SecretRef` indirection; `.env` ignored, `.env.example` tracked; GitHub Actions secrets for CI; cloud secret manager adapter later | Simple, safe | Vault now (overkill) |
| Connector SDK | Internal `aide.connectors.base` (Protocol, `ConnectorSpec`, `@implements`, contract test kit, fake base classes) | Adding a connector = implement protocol + tests | External plugin frameworks (pluggy) — may adopt when out-of-repo connectors appear |
| Synthetic data | Python generator with **Faker** + seeded RNG → CSV/Parquet + PostgreSQL load + Snowflake `COPY` loader | Deterministic fixtures | Hand-written CSVs (too small), dbt seeds only (volume) |
| Task/CLI | **Typer** CLI (`aide api`, `aide worker`, `aide eval`, `aide connectors check`, `aide demo load`) | Typed CLI | argparse |
| Docs | Markdown in `docs/`; Mermaid diagrams | Reviewable in PRs | Sphinx/MkDocs site (later) |

---

## 2. Runtime topology (V1)

```text
docker compose
 ├─ postgres:16          app DB (schema aide) + synthetic source (schema vantara_*)
 ├─ aide-api             FastAPI + in-process worker (AIDE_WORKER_INPROCESS=true)
 │    └─ dbt subprocesses per task
 └─ aide-web (dev only)  Vite dev server; in prod built assets served by aide-api
external: Snowflake DEV account, GitHub repo, LLM provider
```

Configuration switches: `AIDE_MODE=offline|live` (fakes vs real connectors),
`AIDE_LLM_PROVIDER=fake|<provider>`, `AIDE_WORKER_INPROCESS`, `AIDE_OTLP_ENDPOINT`.

---

## 3. Version and compatibility policy

- Pin Python minor version in `pyproject.toml` and `.python-version`; CI uses the same.
- `uv.lock` committed; dependabot/renovate for updates; adapter compatibility checked in CI
  by running `dbt --version` and the fake dbt connector contract tests.
- Frontend: Node LTS pinned in `.nvmrc`; `pnpm` with lockfile.

---

## 4. Re-evaluation triggers

| Trigger | Reconsider |
|---|---|
| > 5 concurrent workflows or multi-node workers | Temporal or a dedicated queue |
| > 2 LLM providers or per-request routing | LiteLLM as adapter |
| Thousands of catalogue assets | embedding index (pgvector first, not a separate vector DB) |
| Multi-tenant deployment | auth provider, RBAC, tenant isolation, separate worker processes |
| Enterprise observability requirement | Prometheus/Grafana, Langfuse exporter |
