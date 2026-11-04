#!/usr/bin/env bash
set -euo pipefail
ENV_FILE=/data/infra/control-plane/api.env
TOKEN=$(sed -n 's/^CONTROL_API_TOKEN=//p' "$ENV_FILE")
if [[ -z "$TOKEN" ]]; then
  echo 'CONTROL_API_TOKEN is missing' >&2
  exit 1
fi
curl -fsS --max-time 55 -X POST http://127.0.0.1:8787/v1/claude/start \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"session":"claude"}' >/var/lib/claude-control-plane/keepalive.last.json
