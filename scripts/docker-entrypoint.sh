#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${AIDE_DATABASE_URL:-}" ]]; then
  alembic upgrade head
fi

exec "$@"
