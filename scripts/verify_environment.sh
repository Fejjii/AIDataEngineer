#!/usr/bin/env bash
# OPS003 — Cloud development environment bootstrap, start, and verification.
# Never prints secret values. Environment-variable *names* only.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/verify_environment.sh [--bootstrap|--start|--verify]

  --bootstrap  Install system packages, uv, and the locked Python environment.
  --start      Ensure PostgreSQL 16 is listening on localhost and a local role exists.
  --verify     Run readiness checks (default).
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PG_MAJOR="16"
DEV_DB="aide_dev"
DEV_ROLE="ubuntu"
HBA_MARKER="# OPS003 localhost trust (ephemeral Cloud development only)"
CONF_D="/etc/postgresql/${PG_MAJOR}/main/conf.d/aide-cloud.conf"
HBA_FILE="/etc/postgresql/${PG_MAJOR}/main/pg_hba.conf"

FORBIDDEN_SECRET_NAMES=(
  SNOWFLAKE_ACCOUNT
  SNOWFLAKE_USER
  SNOWFLAKE_USER_DEV
  SNOWFLAKE_PASSWORD
  SNOWFLAKE_PRIVATE_KEY
  SNOWFLAKE_PRIVATE_KEY_DEV
  SNOWFLAKE_PRIVATE_KEY_PASSPHRASE
  SNOWFLAKE_WAREHOUSE
  SNOWFLAKE_WAREHOUSE_DEV
  SNOWFLAKE_ROLE
  GITHUB_TOKEN_AIDE
  OPENAI_API_KEY
  ANTHROPIC_API_KEY
  AWS_SECRET_ACCESS_KEY
  AZURE_OPENAI_API_KEY
)

log() { printf '%s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

ensure_sudo() {
  sudo -n true >/dev/null 2>&1 || fail "passwordless sudo is required for PostgreSQL administration"
}

apt_install_packages() {
  ensure_sudo
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -qq
  sudo apt-get install -y --no-install-recommends \
    git \
    build-essential \
    ca-certificates \
    curl \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    libpq-dev \
    "postgresql-${PG_MAJOR}" \
    "postgresql-client-${PG_MAJOR}" \
    postgresql-contrib
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  need_cmd curl
  ensure_sudo
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
  command -v uv >/dev/null 2>&1 || fail "uv installation did not produce a uv binary on PATH"
}

ensure_pg_localhost() {
  ensure_sudo
  if [[ ! -d "/etc/postgresql/${PG_MAJOR}/main" ]]; then
    fail "PostgreSQL ${PG_MAJOR} cluster configuration is missing"
  fi
  sudo mkdir -p "/etc/postgresql/${PG_MAJOR}/main/conf.d"
  sudo tee "$CONF_D" >/dev/null <<'EOF'
# OPS003: bind PostgreSQL to loopback only. Do not listen on public interfaces.
listen_addresses = 'localhost'
port = 5432
password_encryption = scram-sha-256
EOF
  if [[ ! -f "$HBA_FILE" ]]; then
    fail "pg_hba.conf is missing"
  fi
  # First matching pg_hba row wins. Ubuntu defaults to scram on 127.0.0.1
  # before any appended trust lines, so rewrite loopback host methods in place.
  sudo python3 - "$HBA_FILE" "$HBA_MARKER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
marker = sys.argv[2]
text = path.read_text()
out = []
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith("#") or not stripped:
        out.append(line)
        continue
    parts = line.split()
    if (
        len(parts) >= 5
        and parts[0] == "host"
        and parts[1] == "all"
        and parts[3] in {"127.0.0.1/32", "::1/128"}
        and parts[4] != "reject"
    ):
        parts[4] = "trust"
        # Preserve original spacing style loosely by joining fields.
        line = "\t".join(parts)
    out.append(line)
if marker not in "\n".join(out):
    out.append("")
    out.append(marker)
path.write_text("\n".join(out) + "\n")
PY
}

pg_start() {
  ensure_sudo
  if sudo pg_lsclusters --no-header | awk -v m="$PG_MAJOR" '$1==m && $2=="main" && $4=="online" {found=1} END {exit found?0:1}'; then
    return 0
  fi
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    sudo pg_ctlcluster "$PG_MAJOR" main start
  else
    sudo service postgresql start
  fi
}

pg_reload_or_start() {
  ensure_sudo
  if sudo pg_lsclusters --no-header | awk -v m="$PG_MAJOR" '$1==m && $2=="main" && $4=="online" {found=1} END {exit found?0:1}'; then
    sudo pg_ctlcluster "$PG_MAJOR" main reload
  else
    pg_start
  fi
}

wait_pg_ready() {
  local i
  for i in $(seq 1 30); do
    if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "PostgreSQL did not become ready on 127.0.0.1:5432"
}

ensure_dev_role_and_db() {
  ensure_sudo
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DEV_ROLE}'" | grep -qx 1; then
    sudo -u postgres createuser --createdb --login "$DEV_ROLE"
  fi
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DEV_DB}'" | grep -qx 1; then
    sudo -u postgres createdb -O "$DEV_ROLE" "$DEV_DB"
  fi
}

assert_listen_localhost() {
  local addr
  addr="$(sudo -u postgres psql -tAc "SHOW listen_addresses;" | tr -d '[:space:]')"
  case "$addr" in
    localhost|127.0.0.1|::1|"localhost,127.0.0.1")
      return 0
      ;;
    *)
      fail "PostgreSQL listen_addresses must be localhost-only (got a non-loopback setting; value not printed)"
      ;;
  esac
}

bootstrap() {
  apt_install_packages
  ensure_uv
  need_cmd python3
  uv sync --frozen --all-groups
  start_postgres
}

start_postgres() {
  ensure_pg_localhost
  pg_reload_or_start
  wait_pg_ready
  ensure_dev_role_and_db
  assert_listen_localhost
}

python_is_312() {
  local ver
  ver="$(python3 --version 2>&1)"
  [[ "$ver" == Python\ 3.12.* ]]
}

postgres_is_16() {
  local ver
  if command -v pg_config >/dev/null 2>&1; then
    ver="$(pg_config --version)"
  else
    ver="$(psql --version)"
  fi
  [[ "$ver" == PostgreSQL\ 16* ]]
}

assert_no_vendor_secrets() {
  local name present=0
  for name in "${FORBIDDEN_SECRET_NAMES[@]}"; do
    if [[ -n "${!name:-}" ]]; then
      printf 'ERROR: forbidden vendor secret name is set: %s (value not printed)\n' "$name" >&2
      present=1
    fi
  done
  if [[ "$present" -ne 0 ]]; then
    exit 1
  fi
}

temp_db_probe() {
  need_cmd psql
  psql -h 127.0.0.1 -p 5432 -U "$DEV_ROLE" -d "$DEV_DB" -v ON_ERROR_STOP=1 \
    -c "SELECT 1 AS ok;" >/dev/null
}

verify() {
  local errors=0
  check() {
    local label="$1"
    shift
    if "$@" >/dev/null; then
      log "PASS  ${label}"
    else
      log "FAIL  ${label}"
      errors=1
    fi
  }

  check "Python 3.12 available" python_is_312
  check "uv available" command -v uv
  check "uv sync --frozen --all-groups" uv sync --frozen --all-groups
  check "PostgreSQL 16 available" postgres_is_16
  check "Git available" command -v git
  check "repository working tree visible" git rev-parse --is-inside-work-tree
  check "pyproject.toml present" test -f "$ROOT/pyproject.toml"
  check "uv.lock present" test -f "$ROOT/uv.lock"

  if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    log "PASS  PostgreSQL reachable on 127.0.0.1:5432"
  else
    log "FAIL  PostgreSQL reachable on 127.0.0.1:5432"
    errors=1
  fi

  if assert_listen_localhost; then
    log "PASS  PostgreSQL listen_addresses is localhost-only"
  else
    errors=1
  fi

  if temp_db_probe; then
    log "PASS  temporary database connection succeeded"
  else
    log "FAIL  temporary database connection succeeded"
    errors=1
  fi

  if assert_no_vendor_secrets; then
    log "PASS  no required vendor secret is present"
  else
    errors=1
  fi

  if [[ "$errors" -ne 0 ]]; then
    fail "environment verification failed"
  fi
  log "OPS003 environment verification succeeded"
}

mode="${1:---verify}"
case "$mode" in
  -h|--help)
    usage
    ;;
  --bootstrap)
    bootstrap
    ;;
  --start)
    start_postgres
    ;;
  --verify)
    verify
    ;;
  *)
    usage >&2
    fail "unknown argument: $mode"
    ;;
esac
