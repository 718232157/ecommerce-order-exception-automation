#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
docker compose --env-file .env down
echo "Stopped. Orders, workflows and database volumes were preserved."
