#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
docker compose -f docker/docker-compose.yml up -d postgres

echo
echo "Postgres started."
echo "Next:"
echo "  - Check logs: docker logs finance_postgres --tail 50"
echo "  - Connect:    ./scripts/psql.sh"
