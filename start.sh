#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run bash setup.sh first."; exit 1; }
docker compose --env-file .env up -d
echo "Started: http://127.0.0.1:5678"
if command -v open >/dev/null; then open http://127.0.0.1:5678; fi
