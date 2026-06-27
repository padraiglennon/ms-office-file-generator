#!/usr/bin/env bash
# Generate a Markdown document via POST /api/generate/markdown.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

gen_json markdown document.md \
  '{"complexity":"standard","sections":5,"seed":1}'
