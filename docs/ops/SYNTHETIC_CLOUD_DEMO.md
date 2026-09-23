# Synthetic Interview MVP cloud demo

**Task:** DEPLOY001_SYNTHETIC_CLOUD_DEMO / DEPLOY001_SECURITY_REMEDIATION  
**Audience:** recruiters, hiring managers, and operators  
**Scope:** one application container + PostgreSQL 16. Synthetic Vantara data only.

This is not production infrastructure. It does not require Snowflake credentials.

Landing page: [`README.md`](../../README.md). Interview talk track:
[`INTERVIEW_DEMO.md`](../INTERVIEW_DEMO.md).

## Architecture

```text
Docker Compose (or equivalent host)
  postgres:16          control-plane state (Compose network only)
  aide app image       FastAPI + CLI + fake Snowflake + fake dbt
                       host bind 127.0.0.1 by default
```

Matches the accepted modular monolith: one Python package, one image, one
PostgreSQL. No Kubernetes, Redis, Kafka, Temporal, or frontend.

Offline Interview execution uses the existing deterministic fake Snowflake and
fake dbt paths. Alembic migrations are the existing revisions. RAW remains
read-only for the product. Production and staging stay disabled.

## Secure defaults

| Surface | Default | Remote / public use |
|---|---|---|
| CLI demo (`aide interview demo`) | Enabled | No HTTP token |
| `POST /v1/interview/demo` | Disabled (`AIDE_SYNTHETIC_DEMO_HTTP=0`) | Enable HTTP **and** set `AIDE_SYNTHETIC_DEMO_TOKEN` |
| PostgreSQL | Private Compose network | Do not publish a host port |
| Application port | `AIDE_HTTP_BIND=127.0.0.1` | Set `AIDE_HTTP_BIND=0.0.0.0` only when publishing on purpose |
| Secrets | External `.env` / environment | Never commit real values |

A public application bind does not bypass the HTTP demo token. If HTTP demo is
enabled without a nonempty token, application startup fails closed. That token
gates `POST /v1/interview/demo` only.

The operator console is a separate authenticated surface. See
[`OPERATOR_CONSOLE.md`](OPERATOR_CONSOLE.md). Legacy anonymous routes below are
unregistered unless `AIDE_LEGACY_ANONYMOUS_ROUTES=1`.

## Startup

Host with Docker:

```bash
cp .env.example .env   # set POSTGRES_PASSWORD and AIDE_CSRF_SECRET locally; never commit .env
./scripts/synthetic_demo.sh up
./scripts/synthetic_demo.sh health
```

`./scripts/synthetic_demo.sh up` fails closed if `POSTGRES_PASSWORD` is absent from
both the environment and `.env`. Compose interpolates that value into the
internal DSN. PostgreSQL is not published to the host; the app reaches it as
`postgres:5432` on the Compose network.

Equivalent without Docker (Cursor Cloud / local PostgreSQL 16):

```bash
uv sync --frozen --all-groups
export AIDE_DATABASE_URL="${AIDE_DATABASE_URL:-postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev}"
uv run alembic upgrade head
export AIDE_CSRF_SECRET   # 32+ characters; do not print the value
uv run uvicorn asgi:app --host 127.0.0.1 --port 8000
```

Local CLI demo:

```bash
uv run aide interview demo
```

No `AIDE_SYNTHETIC_DEMO_TOKEN` is required for the CLI.

## Database initialization

`scripts/docker-entrypoint.sh` runs `alembic upgrade head` when
`AIDE_DATABASE_URL` is set, then execs the container command. The Interview CLI
also upgrades to head before each demo.

Clean bootstrap: empty PostgreSQL 16 → upgrade head → demo.  
Already initialized: upgrade is idempotent; a second demo allocates new workflow
ids and does not rewrite prior evidence rows.

Inspect PostgreSQL from the host with `docker compose exec`, not a published
port:

```bash
docker compose exec postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

## PostgreSQL compatibility

Offline Compose and GitHub Actions are validated on PostgreSQL 16 (`postgres:16`).
The Railway Data Pilot AI Demo database is live-validated on PostgreSQL 18.6.
The supported control-plane requirement is PostgreSQL 16 or newer.

The application does not assert `server_version`. Persistence uses JSONB, UUID,
transactional advisory locks, and `SKIP LOCKED`. Do not replace or downgrade a
live database to force major version 16.

## Railway application port

The image listens on TCP 8000, and the public domain targets that port. Railway
healthchecks the `PORT` variable. The Data Pilot AI Demo application service sets
`PORT=8000`. Removing it makes a new deployment fail `/readyz` with
`service unavailable` while an older deployment can keep serving.

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

On a uv checkout (no HTTP token):

```bash
uv run aide interview demo
uv run aide interview demo --json
```

Inside the app container (no HTTP token):

```bash
docker compose exec app uv run --frozen --no-dev --offline --no-sync aide interview demo
docker compose exec app uv run --frozen --no-dev --offline --no-sync aide interview demo --json
```

## Remote HTTP demo (token mandatory)

Keep `AIDE_SYNTHETIC_DEMO_HTTP=0` unless you intend to expose
`POST /v1/interview/demo`. That route runs **only** the accepted synthetic
scenario. No SQL body, no connector credentials, no production/staging target.

For a remotely usable HTTP demo:

1. Set a nonempty `AIDE_SYNTHETIC_DEMO_TOKEN` in `.env` or the environment.
2. Set `AIDE_SYNTHETIC_DEMO_HTTP=1`.
3. Keep PostgreSQL unpublished.
4. Bind the application port to loopback unless you intentionally publish it:
   `AIDE_HTTP_BIND=127.0.0.1` (default) or `AIDE_HTTP_BIND=0.0.0.0`.
5. Recreate the app container so startup can validate the token.

```bash
curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H "X-AIDE-Demo-Token: ${AIDE_SYNTHETIC_DEMO_TOKEN}" \
  -d '{}' \
  http://127.0.0.1:8000/v1/interview/demo
```

or `./scripts/synthetic_demo.sh demo-http`.

Do not paste the token into chat. Missing token: startup fails (Compose / uvicorn)
or the helper script exits before calling the route. Wrong token: HTTP 401.
Disabled HTTP demo: HTTP 404.

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
environment maps. Do not print `POSTGRES_PASSWORD` or `AIDE_SYNTHETIC_DEMO_TOKEN`.

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

## Legacy DE002C routes

These routes belong to the earlier DE002C slice. They are **not** registered on
the deployed demo. Set `AIDE_LEGACY_ANONYMOUS_ROUTES=1` only for a local process
that still needs the old contract. They are not the Interview product API. Do
not present them as `uv run aide interview demo` or `POST /v1/interview/demo`.

| Method | Path |
|---|---|
| `POST` | `/v1/sessions` |
| `POST` | `/v1/workflows` |
| `GET` | `/v1/workflows/{workflow_id}/events` |

- They use fake connectors only. The demo ASGI entrypoint builds the offline stack for this slice.
- They can write to the demo PostgreSQL control plane. Session issuance and workflow submit persist control-plane rows there.
- They are not protected by the Interview demo token (`AIDE_SYNTHETIC_DEMO_TOKEN`). `POST /v1/sessions` issues a local session without that token. Workflow submit then uses that session, not the Interview token. The events route does not require the Interview token.
- Use the Interview CLI, or the token-gated HTTP demo, when showing the product.

The image default is `AIDE_LEGACY_ANONYMOUS_ROUTES=0`. Unset or `0` returns 404
for the three routes. Documentation alone is not the control.

## Known limitations

- Not a production or multi-tenant deployment.
- Nested Docker is often absent in Cursor Cloud; validate Compose in CI or on a
  Docker host, and use native PostgreSQL 16 as the Cloud equivalent.
- `POST /v1/interview/demo` runs the scenario twice (determinism). It is
  expensive; it is disabled by default and requires a token when enabled.
- Legacy anonymous session, workflow, and event routes stay off unless
  `AIDE_LEGACY_ANONYMOUS_ROUTES=1`. They are not the Interview closed loop.
- The operator console (`/console`) is the browser surface for the fixed
  synthetic scenario. Business correctness stays `NOT_VALIDATED`.
- No standing public URL is created until an operator authenticates a host.

## Remaining authentication gate

This package is ready when Compose (or the local PostgreSQL equivalent) is
healthy and the secure defaults above are in place. A standing remote URL
requires the operator to authenticate **one** container host (Docker Desktop,
a VM, Fly, Railway, or Render), set `POSTGRES_PASSWORD` and
`AIDE_SYNTHETIC_DEMO_TOKEN` locally, enable HTTP only if needed, and bind
publicly only on purpose. Do not paste those credentials into chat.
