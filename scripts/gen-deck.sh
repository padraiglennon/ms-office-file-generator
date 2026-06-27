#!/usr/bin/env bash
# Generate a PowerPoint deck via POST /api/generate/deck.
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/_common.sh

gen_json deck deck.pptx \
  '{"complexity":"standard","slides":8,"seed":1,"background":"theme"}'
