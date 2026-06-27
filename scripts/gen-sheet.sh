#!/usr/bin/env bash
# Generate an Excel workbook via POST /api/generate/sheet.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

gen_json sheet workbook.xlsx \
  '{"complexity":"standard","sheets":3,"seed":1}'
