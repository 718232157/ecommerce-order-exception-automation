#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo "Run bash setup.sh first."; exit 1; }

echo "Feishu setup wizard (press Enter to keep an existing value)"
read -r -p "Group robot Webhook URL: " webhook
read -r -p "App ID: " app_id
read -r -s -p "App Secret: " app_secret; echo
read -r -p "Bitable App Token: " app_token
read -r -p "Bitable Table ID: " table_id

update_env() {
  local key="$1" value="$2" temp
  [[ -n "$value" ]] || return 0
  temp="$(mktemp)"
  awk -v key="$key" -v value="$value" 'BEGIN{found=0} index($0,key"=")==1 {print key"="value; found=1; next} {print} END{if(!found) print key"="value}' .env > "$temp"
  mv "$temp" .env
  chmod 600 .env
}
update_env FEISHU_WEBHOOK_URL "$webhook"
update_env FEISHU_APP_ID "$app_id"
update_env FEISHU_APP_SECRET "$app_secret"
update_env FEISHU_BITABLE_APP_TOKEN "$app_token"
update_env FEISHU_BITABLE_TABLE_ID "$table_id"

docker compose --env-file .env up -d --force-recreate order-api
sleep 6
admin_key="$(grep '^ADMIN_API_KEY=' .env | cut -d= -f2-)"
result="$(curl -fsS -X POST -H "X-API-Key: $admin_key" http://127.0.0.1:8080/feishu/bootstrap)"
echo "$result" | grep -q '"configured":true' || { echo "Feishu setup failed: $result"; exit 1; }
echo "Feishu connected and Bitable fields initialized."
