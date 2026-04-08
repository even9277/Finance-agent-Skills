#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-finance_postgres}"
DB_USER="${DB_USER:-finance}"
DB_NAME="${DB_NAME:-finance_db}"

echo "== 1) Server version =="
docker exec -it "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "SELECT version();"

echo
echo "== 2) Extensions (vector, uuid-ossp) =="
docker exec -it "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c \
  "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector','uuid-ossp') ORDER BY extname;"

echo
echo "== 3) Tables in public schema =="
docker exec -it "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"

echo
echo "If tables are empty, start backend once to trigger create_all."
