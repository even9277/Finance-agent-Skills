#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-finance_postgres}"
DB_USER="${DB_USER:-finance}"
DB_NAME="${DB_NAME:-finance_db}"

exec docker exec -it "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME"
