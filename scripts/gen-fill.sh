#!/usr/bin/env bash
# Fill a Golden template via POST /api/generate/fill (multipart upload).
#
# Usage: ./scripts/gen-fill.sh <template.(pptx|docx|xlsx)> [config.json]
#
# There is no committed sample template, so pass your own Golden file. The
# config defaults to configs/sample-deck.json (matches a .pptx deck template).
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

TEMPLATE="${1:-}"
CONFIG="${2:-configs/sample-deck.json}"

if [ -z "$TEMPLATE" ] || [ ! -f "$TEMPLATE" ]; then
  echo "Usage: $0 <template.(pptx|docx|xlsx)> [config.json]" >&2
  echo "Provide a Golden template file (none is committed to the repo)." >&2
  exit 2
fi

ext="${TEMPLATE##*.}"
out="${OUT_DIR}/filled.${ext}"

# 1) Default: stream the filled file back, one-line report in the header.
echo "POST ${API_BASE}/generate/fill  (streaming)"
report=$(curl -s -o "$out" -D - \
  -F "template=@${TEMPLATE}" \
  -F "config=@${CONFIG}" \
  "${API_BASE}/generate/fill" \
  | grep -i '^x-injection-report:' || true)
echo "  -> saved ${out} ($(wc -c <"$out") bytes)"
echo "  ${report:-(no report header)}"

# 2) Full multi-line report as JSON (file base64-encoded inside).
echo "POST ${API_BASE}/generate/fill?include_report=true  (JSON)"
curl -s \
  -F "template=@${TEMPLATE}" \
  -F "config=@${CONFIG}" \
  "${API_BASE}/generate/fill?include_report=true" \
  | { python -m json.tool 2>/dev/null || cat; }
