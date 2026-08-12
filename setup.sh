#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Git Bash rewrites Unix-looking container paths unless path conversion is disabled.
case "${OSTYPE:-}" in
  msys*|cygwin*) export MSYS_NO_PATHCONV=1 ;;
esac

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
secret() { openssl rand -hex "${1:-32}"; }
wait_url() {
  local url="$1"
  for _ in $(seq 1 45); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "Service startup timed out: $url" >&2
  exit 1
}
wait_workflow() {
  local url="$1" internal_key="$2" event_id
  event_id="setup-smoke:$(date +%s)"
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 5 -X POST "$url" \
      -H 'Content-Type: application/json' -H "X-Internal-Key: ${internal_key}" \
      -d "{\"eventId\":\"${event_id}\",\"orderId\":\"SETUP-SMOKE-ORDER\",\"status\":\"SHIPPED\",\"amount\":\"0.00\",\"quantity\":1,\"stock\":10,\"riskScore\":0,\"sourcePlatform\":\"SETUP_SMOKE\"}" >/dev/null 2>&1; then return 0; fi
    sleep 2
  done
  echo "Workflow webhook verification failed: $url" >&2
  exit 1
}

step "Checking Docker"
command -v docker >/dev/null || { echo "Install and start Docker Desktop first: https://www.docker.com/products/docker-desktop/"; exit 1; }
docker info >/dev/null 2>&1 || { echo "Docker Desktop is not running."; exit 1; }
docker compose version >/dev/null
command -v openssl >/dev/null || { echo "openssl is required to generate local secrets."; exit 1; }

if [[ ! -f .env ]]; then
  step "Generating local configuration and secure keys"
  cat > .env <<EOF
GENERIC_TIMEZONE=Asia/Shanghai
TZ=Asia/Shanghai
ORDER_API_PORT=8080
N8N_PORT=5678
FEISHU_WEBHOOK_URL=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_BITABLE_APP_TOKEN=
FEISHU_BITABLE_TABLE_ID=
CONTAINER_HTTP_PROXY=
POSTGRES_PASSWORD=$(secret 24)
INBOUND_WEBHOOK_SECRET=$(secret)
REVIEW_API_KEY=$(secret)
ADMIN_API_KEY=$(secret)
INTERNAL_API_KEY=$(secret)
READ_API_KEY=$(secret)
PROTECT_READ_ENDPOINTS=false
ENABLE_API_DOCS=true
NOTIFY_SEVERITIES=CRITICAL
SEED_SAMPLE_DATA=true
ENABLE_DAILY_REPORTS=false
ENABLE_DEAD_LETTER_ALERTS=false
N8N_SECURE_COOKIE=false
EOF
  chmod 600 .env
else
  echo "Keeping existing .env; no keys were overwritten."
fi

ORDER_API_PORT="$(sed -n 's/^ORDER_API_PORT=//p' .env | tail -n 1)"
N8N_PORT="$(sed -n 's/^N8N_PORT=//p' .env | tail -n 1)"
INTERNAL_API_KEY="$(sed -n 's/^INTERNAL_API_KEY=//p' .env | tail -n 1)"
ORDER_API_PORT="${ORDER_API_PORT:-8080}"
N8N_PORT="${N8N_PORT:-5678}"

step "Starting PostgreSQL, order API and n8n"
docker compose --env-file .env up -d --build
wait_url "http://127.0.0.1:${ORDER_API_PORT}/health/ready"
wait_url "http://127.0.0.1:${N8N_PORT}/healthz"

step "Importing and publishing 5 workflows"
imported=false
for attempt in 1 2 3; do
  sleep 2
  docker compose --env-file .env exec -T n8n n8n import:workflow --separate --input=/workflow-templates/
  if docker compose --env-file .env exec -T n8n n8n list:workflow | grep -q 'DeadLetterWatch01'; then
    imported=true
    break
  fi
  echo "n8n is still completing its first-run initialization; retrying ($attempt/3)..."
done
[[ "$imported" == "true" ]] || { echo "Could not import the 5 workflows after 6 seconds." >&2; exit 1; }
for id in JUilG7xnUiQAOAYX U8GXSUjQqCWLtI2I PfNG53rh2exExojv DailyOpsReport01 DeadLetterWatch01; do
  docker compose --env-file .env exec -T n8n n8n publish:workflow --id="$id"
done
docker compose --env-file .env restart n8n >/dev/null
wait_url "http://127.0.0.1:${N8N_PORT}/healthz"
wait_workflow "http://127.0.0.1:${N8N_PORT}/webhook/order-exception" "$INTERNAL_API_KEY"

step "Installation complete"
echo "Create your n8n administrator account in the browser once."
echo "All 5 workflows are published and the realtime webhook passed a no-exception smoke test."
echo "n8n: http://127.0.0.1:${N8N_PORT}"
echo "API docs: http://127.0.0.1:${ORDER_API_PORT}/docs"
if [[ "${NO_OPEN:-false}" != "true" ]]; then
  if command -v open >/dev/null; then open "http://127.0.0.1:${N8N_PORT}"
  elif command -v xdg-open >/dev/null; then xdg-open "http://127.0.0.1:${N8N_PORT}" >/dev/null 2>&1 || true
  fi
fi
