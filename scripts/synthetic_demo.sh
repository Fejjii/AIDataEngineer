#!/usr/bin/env bash
# Synthetic Interview MVP demo: Docker Compose when available, else local PostgreSQL.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export AIDE_DATABASE_URL="${AIDE_DATABASE_URL:-${AIDE_TEST_DATABASE_URL:-postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev}}"
export AIDE_HTTP_PORT="${AIDE_HTTP_PORT:-8000}"
export AIDE_SYNTHETIC_DEMO_HTTP="${AIDE_SYNTHETIC_DEMO_HTTP:-0}"

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

env_file_has_nonempty() {
  local key="$1"
  python3 - "$ROOT/.env" "$key" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.is_file():
    raise SystemExit(1)
prefix = f"{key}="
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:].strip()
    if not line.startswith(prefix):
        continue
    value = line.split("=", 1)[1].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    raise SystemExit(0 if value else 1)
raise SystemExit(1)
PY
}

require_compose_postgres_password() {
  if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
    return 0
  fi
  if env_file_has_nonempty POSTGRES_PASSWORD; then
    return 0
  fi
  fail "POSTGRES_PASSWORD must be set in the environment or .env for Compose. Do not use a default password."
}

if [[ -z "${AIDE_CSRF_SECRET:-}" ]]; then
  if ! env_file_has_nonempty AIDE_CSRF_SECRET; then
    AIDE_CSRF_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
    export AIDE_CSRF_SECRET
  fi
fi

have_docker() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

postgres_ready() {
  python3 - "$AIDE_DATABASE_URL" <<'PY'
import sys
from sqlalchemy import create_engine, text

url = sys.argv[1]
engine = create_engine(url)
with engine.connect() as conn:
    conn.execute(text("SELECT 1"))
print("postgres-ready")
PY
}

cmd_health() {
  curl -fsS "http://127.0.0.1:${AIDE_HTTP_PORT}/healthz"
  printf '\n'
  curl -fsS "http://127.0.0.1:${AIDE_HTTP_PORT}/readyz"
  printf '\n'
}

cmd_demo() {
  if have_docker && docker compose ps --status running --services 2>/dev/null | grep -qx app; then
    docker compose exec -T app uv run --frozen --no-dev --offline --no-sync aide interview demo
  else
    uv run aide interview demo
  fi
}

cmd_demo_json() {
  if have_docker && docker compose ps --status running --services 2>/dev/null | grep -qx app; then
    docker compose exec -T app uv run --frozen --no-dev --offline --no-sync aide interview demo --json
  else
    uv run aide interview demo --json
  fi
}

cmd_benchmark() {
  if have_docker && docker compose ps --status running --services 2>/dev/null | grep -qx app; then
    docker compose exec -T app uv run --frozen --no-dev --offline --no-sync aide interview benchmark
  else
    uv run aide interview benchmark
  fi
}

cmd_demo_http() {
  if [[ -z "${AIDE_SYNTHETIC_DEMO_TOKEN:-}" ]]; then
    fail "AIDE_SYNTHETIC_DEMO_TOKEN is required for the HTTP demo. CLI demo does not need this token."
  fi
  local headers=(-H "Content-Type: application/json" -H "X-AIDE-Demo-Token: ${AIDE_SYNTHETIC_DEMO_TOKEN}")
  curl -fsS -X POST "${headers[@]}" -d '{}' "http://127.0.0.1:${AIDE_HTTP_PORT}/v1/interview/demo"
  printf '\n'
}

cmd_up() {
  if have_docker; then
    export POSTGRES_DB="${POSTGRES_DB:-aide_dev}"
    export POSTGRES_USER="${POSTGRES_USER:-aide}"
    require_compose_postgres_password
    docker compose up --build -d
    log "Compose stack started. Health: curl -fsS http://127.0.0.1:${AIDE_HTTP_PORT}/readyz"
    return 0
  fi
  postgres_ready || fail "PostgreSQL is not reachable at AIDE_DATABASE_URL"
  uv run alembic upgrade head
  log "Local PostgreSQL is reachable and migrations are at head."
}

cmd_down() {
  if have_docker; then
    docker compose down -v --remove-orphans
    return 0
  fi
  log "No Docker daemon; nothing to tear down. Local PostgreSQL is left running."
}

cmd_validate() {
  postgres_ready || fail "PostgreSQL is not reachable"
  uv run alembic upgrade head
  uv run alembic check
  uv run aide interview demo
  uv run aide interview demo --json
  uv run aide interview benchmark
}

usage() {
  cat <<'EOF'
Usage: scripts/synthetic_demo.sh <command>

  up            Start Compose (app + PostgreSQL) or verify local PostgreSQL
  health        GET /healthz and /readyz
  demo          uv run aide interview demo
  demo-json     uv run aide interview demo --json
  benchmark     uv run aide interview benchmark
  demo-http     POST /v1/interview/demo (token required; empty JSON only)
  down          docker compose down -v (no-op without Docker)
  validate      migrate + demo + demo --json + benchmark against local PostgreSQL

CLI demo does not require AIDE_SYNTHETIC_DEMO_TOKEN.
Compose requires POSTGRES_PASSWORD in the environment or .env.
PostgreSQL is not published to the host. Do not print or export secret values.
EOF
}

main() {
  local command="${1:-}"
  case "$command" in
    up) cmd_up ;;
    health) cmd_health ;;
    demo) cmd_demo ;;
    demo-json) cmd_demo_json ;;
    benchmark) cmd_benchmark ;;
    demo-http) cmd_demo_http ;;
    down) cmd_down ;;
    validate) cmd_validate ;;
    -h|--help|help|"") usage ;;
    *) fail "unknown command: ${command}" ;;
  esac
}

main "$@"
