#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
case "${OSTYPE:-}" in
  msys*|cygwin*) export MSYS_NO_PATHCONV=1 ;;
esac
[[ $# -eq 1 ]] || { echo "Usage: bash import-orders.sh /path/to/orders.csv"; exit 1; }
CSV="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
[[ -f "$CSV" ]] || { echo "CSV not found: $CSV"; exit 1; }
[[ -f "$ROOT/.env" ]] || { echo "Run bash setup.sh first."; exit 1; }
secret="$(grep '^INBOUND_WEBHOOK_SECRET=' "$ROOT/.env" | cut -d= -f2-)"
docker run --rm \
  --add-host host.docker.internal:host-gateway \
  -e INBOUND_WEBHOOK_SECRET="$secret" \
  -v "$ROOT/scripts/import_orders_csv.py:/app/import_orders_csv.py:ro" \
  -v "$CSV:/input/orders.csv:ro" \
  python:3.12-alpine \
  python /app/import_orders_csv.py /input/orders.csv --url http://host.docker.internal:8080/v1/orders/ingest
