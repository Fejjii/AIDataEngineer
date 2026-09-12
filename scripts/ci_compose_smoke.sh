#!/usr/bin/env bash
# DE003 — CI-only Docker Compose smoke test. Ephemeral values; never commit real secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export POSTGRES_DB="${POSTGRES_DB:-aide_dev}"
export POSTGRES_USER="${POSTGRES_USER:-aide_ci}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-ci-smoke-password-not-a-production-secret}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export AIDE_HTTP_PORT="${AIDE_HTTP_PORT:-8000}"
export AIDE_CSRF_SECRET="${AIDE_CSRF_SECRET:-ci-smoke-csrf-secret-at-least-32-characters-long}"

COMPOSE=(docker compose)
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-aide-ci-smoke}"
COMPOSE=(docker compose -p "$PROJECT_NAME")

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

dump_logs() {
  log "--- docker compose ps ---"
  "${COMPOSE[@]}" ps -a || true
  log "--- postgres logs ---"
  "${COMPOSE[@]}" logs postgres || true
  log "--- app logs ---"
  "${COMPOSE[@]}" logs app || true
}

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT

on_error() {
  log "Compose smoke test failed; collecting container logs"
  dump_logs
}

trap on_error ERR

wait_postgres_healthy() {
  local attempt
  for attempt in $(seq 1 60); do
    if "${COMPOSE[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
      log "PostgreSQL is healthy"
      return 0
    fi
    sleep 2
  done
  fail "PostgreSQL did not become healthy within 120 seconds"
}

wait_app_healthy() {
  local attempt response
  for attempt in $(seq 1 60); do
    if response="$(curl -fsS "http://127.0.0.1:${AIDE_HTTP_PORT}/healthz" 2>/dev/null)"; then
      log "Application health response: ${response}"
      [[ "$response" == *"ok"* ]] || fail "unexpected /healthz payload: ${response}"
      return 0
    fi
    sleep 2
  done
  fail "Application /healthz did not succeed within 120 seconds"
}

verify_app_database_connectivity() {
  "${COMPOSE[@]}" exec -T app python -c "
import os
from sqlalchemy import create_engine, text

url = os.environ['AIDE_DATABASE_URL']
engine = create_engine(url)
with engine.connect() as conn:
    value = conn.execute(text('SELECT 1')).scalar_one()
    assert value == 1, value
print('app-to-postgres-bridge-ok')
"
}

verify_migrations_applied() {
  local revision table_count
  revision="$("${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT version_num FROM alembic_version LIMIT 1;" | tr -d '[:space:]')"
  [[ -n "$revision" ]] || fail "alembic_version row is missing"
  log "Alembic revision in database: ${revision}"

  table_count="$("${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';" \
    | tr -d '[:space:]')"
  [[ "${table_count:-0}" -ge 10 ]] || fail "expected migrated public tables, found ${table_count:-0}"
  log "Public base tables after migration: ${table_count}"
}

log "Starting Docker Compose smoke test (project: ${PROJECT_NAME})"
"${COMPOSE[@]}" up --build -d

if "${COMPOSE[@]}" ps --status running --services | grep -qx postgres; then
  wait_postgres_healthy
else
  fail "postgres service is not running"
fi

wait_app_healthy
verify_app_database_connectivity
verify_migrations_applied

log "Docker Compose smoke test succeeded"
