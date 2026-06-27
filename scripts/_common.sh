#!/usr/bin/env bash
# Shared config + helpers for the API test scripts (ADR-007).
#
# Sourced by the per-endpoint scripts. Override the target with env vars:
#   API_HOST=0.0.0.0 API_PORT=9000 ./scripts/gen-deck.sh
set -euo pipefail

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-18990}"
API_BASE="http://${API_HOST}:${API_PORT}/api"

# Where generated files land. Created on demand; gitignored under output/.
OUT_DIR="${OUT_DIR:-output}"
mkdir -p "$OUT_DIR"

# POST a JSON body to a generate endpoint and save the streamed bytes.
#   gen_json <endpoint> <out-file> <json-body>
gen_json() {
  local endpoint="$1" out="$2" body="$3"
  echo "POST ${API_BASE}/generate/${endpoint}"
  echo "  body: ${body}"
  local code
  code=$(curl -s -o "${OUT_DIR}/${out}" -w '%{http_code}' \
    -H 'Content-Type: application/json' \
    -d "${body}" \
    "${API_BASE}/generate/${endpoint}")
  if [ "$code" = "200" ]; then
    echo "  -> 200 OK, saved ${OUT_DIR}/${out} ($(wc -c <"${OUT_DIR}/${out}") bytes)"
  else
    echo "  -> ${code} ERROR:"
    cat "${OUT_DIR}/${out}"
    echo
    return 1
  fi
}
