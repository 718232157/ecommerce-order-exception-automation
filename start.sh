#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run bash setup.sh first."; exit 1; }
N8N_PORT="$(sed -n 's/^N8N_PORT=//p' .env | tail -n 1)"
N8N_PORT="${N8N_PORT:-5678}"
docker compose --env-file .env up -d
echo "Started: http://127.0.0.1:${N8N_PORT}"
if command -v open >/dev/null; then open "http://127.0.0.1:${N8N_PORT}"; fi
