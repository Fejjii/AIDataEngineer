# Synthetic Interview MVP cloud demo

**Task:** DEPLOY001_SYNTHETIC_CLOUD_DEMO  
**Audience:** recruiters, hiring managers, and operators  
**Scope:** one application container + PostgreSQL 16. Synthetic Vantara data only.

This is not production infrastructure. It does not require Snowflake credentials.

Landing page: [`README.md`](../../README.md). Interview talk track:
[`INTERVIEW_DEMO.md`](../INTERVIEW_DEMO.md).

## Architecture

```text
Docker Compose (or equivalent host)
  postgres:16          control-plane state
  aide app image       FastAPI + CLI + fake Snowflake + fake dbt
```

Matches the accepted modular monolith: one Python package, one image, one
PostgreSQL. No Kubernetes, Redis, Kafka, Temporal, or frontend.

Offline Interview execution uses the existing deterministic fake Snowflake and
fake dbt paths. Alembic migrations are the existing revisions. RAW remains
read-only for the product. Production and staging stay disabled.

## Startup

Host with Docker:

```bash
cp .env.example .env   # set POSTGRES_PASSWORD and AIDE_CSRF_SECRET locally; never commit .env
./scripts/synthetic_demo.sh up
./scripts/synthetic_demo.sh health
```

Equivalent without Docker (Cursor Cloud / local PostgreSQL 16):

```bash
uv sync --frozen --all-groups
export AIDE_DATABASE_URL="${AIDE_DATABASE_URL:-postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev}"
uv run alembic upgrade head
export AIDE_CSRF_SECRET   # 32+ characters; do not print the value
export AIDE_SYNTHETIC_DEMO_HTTP=1
uv run uvicorn asgi:app --host 127.0.0.1 --port 8000
```

## Database initialization

`scripts/docker-entrypoint.sh` runs `alembic upgrade head` when
`AIDE_DATABASE_URL` is set, then execs the container command. The Interview CLI
also upgrades to head before each demo.

Clean bootstrap: empty PostgreSQL 16 → upgrade head → demo.  
Already initialized: upgrade is idempotent; a second demo allocates new workflow
ids and does not rewrite prior evidence rows.

## Deployment command

```bash
docker compose up --build -d
```

or `./scripts/synthetic_demo.sh up`.

Authenticated cloud VM / Fly / Railway / Render is a **manual authentication
gate**. This repository does not commit cloud account credentials. After the
operator authenticates a host that can run Compose, the same two-service stack
is the deploy unit.

## Health verification

| Endpoint | Meaning |
|---|---|
| `GET /healthz` | Process liveness (`{"status":"ok"}`) |
| `GET /readyz` | PostgreSQL `SELECT 1` (no DSN in the body) |

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

## Demo command

On a uv checkout:

```bash
uv run aide interview demo
uv run aide interview demo --json
```

Inside the app container:

```bash
docker compose exec app uv run --frozen --no-dev --offline --no-sync aide interview demo
docker compose exec app uv run --frozen --no-dev --offline --no-sync aide interview demo --json
```

Optional HTTP surface (enabled when `AIDE_SYNTHETIC_DEMO_HTTP=1`). Runs **only**
the accepted synthetic scenario. No SQL body, no connector credentials, no
production/staging target.

```bash
curl -fsS -X POST -H 'Content-Type: application/json' -d '{}' \
  http://127.0.0.1:8000/v1/interview/demo
```

If `AIDE_SYNTHETIC_DEMO_TOKEN` is set, also send `X-AIDE-Demo-Token`. Do not
paste the value into chat. Internet-exposed hosts should set the token.

The JSON body is a bounded summary: workflow status, Digital Twin snapshot
digest, schema-drift mapping, repair apply count, Independent Verifier
verdict, evidence completeness, and benchmark metrics.

## Benchmark command

```bash
uv run aide interview benchmark
```

or `docker compose exec app uv run --frozen --no-dev --offline --no-sync aide interview benchmark`.

Expected: Independent Verifier `PASS`, determinism `PASS`, evidence completeness
100%, repair count exactly 1, human interventions 0.

## Logs

```bash
docker compose logs -f app postgres
```

Application logs must not contain secret values. Do not raise log level to dump
environment maps.

## Restart procedure

```bash
docker compose restart app
curl -fsS http://127.0.0.1:8000/readyz
```

PostgreSQL volume `postgres_data` retains control-plane rows. Evidence bundles
and workflow state remain queryable after the application process restarts.
Do not `docker compose down -v` if you need that state.

## Teardown

```bash
./scripts/synthetic_demo.sh down
# or: docker compose down -v
```

This removes the Compose project and the demo volume. It does not touch
production or staging. Local native PostgreSQL is left running.

## Cost-relevant resources

| Resource | Recurring cost |
|---|---|
| `postgres:16` container | Host/VM disk + memory only |
| Application image | Host/VM CPU + memory only |
| Snowflake | None on this path |
| Cursor Cloud agent | Ephemeral VM; not a standing demo URL |

No cloud account was authenticated in the packaging environment, so there is no
provider invoice to quote. A small VM running this Compose stack is typically the
cost of that VM only.

## Credential-gated Snowflake extension

Do **not** add Snowflake variables to Compose for the synthetic demo.

Live smoke remains:

```bash
uv run aide interview live-smoke
```

Required **names** only: `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_RO`,
`SNOWFLAKE_PRIVATE_KEY_RO`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`,
`SNOWFLAKE_WAREHOUSE_DEV`. Missing credentials exit `2`. Do not grant
`AIDE_DEV_RW` any new `VANTARA_RAW` privilege.

## Known limitations

- Not a production or multi-tenant deployment.
- Nested Docker is often absent in Cursor Cloud; validate Compose in CI or on a
  Docker host, and use native PostgreSQL 16 as the Cloud equivalent.
- `POST /v1/interview/demo` runs the scenario twice (determinism). It is
  expensive; do not expose it unauthenticated on the public internet.
- `/v1/workflows` remains the earlier DE002C slice, not the Interview closed
  loop. Use the Interview CLI or `/v1/interview/demo`.
- No standing public URL is created until an operator authenticates a host.

## Remaining authentication gate

This package is ready when Compose (or the local PostgreSQL equivalent) is
healthy. A standing remote URL requires the operator to authenticate **one**
container host (Docker Desktop, a VM, Fly, Railway, or Render) and run the
same Compose file. Do not paste those credentials into chat.
