#!/usr/bin/env bash
# Generate a PDF via POST /api/generate/pdf.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

gen_json pdf document.pdf \
  '{"complexity":"standard","sections":5,"seed":1}'
