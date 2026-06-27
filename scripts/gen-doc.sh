#!/usr/bin/env bash
# Generate a Word document via POST /api/generate/doc.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

gen_json doc document.docx \
  '{"complexity":"standard","sections":5,"seed":1}'
