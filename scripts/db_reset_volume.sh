#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "WARNING: This will DELETE postgres_data volume (all DB data)."
read -r -p "Type 'yes' to continue: " confirm
if [[ "${confirm}" != "yes" ]]; then
  echo "Cancelled."
  exit 0
fi

docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up -d postgres

echo
echo "Postgres volume reset completed."
echo "Tip: ./scripts/db_check.sh"
