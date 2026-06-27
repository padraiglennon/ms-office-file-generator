#!/usr/bin/env bash
# Run every generate-endpoint script against a running server.
#
# Start the server first:  uv run gen-ui
# Then:                     ./scripts/run-all.sh
#
# Skips gen-fill.sh, which needs a Golden template argument.
set -euo pipefail
cd "$(dirname "$0")"

for script in gen-deck.sh gen-doc.sh gen-sheet.sh gen-pdf.sh gen-markdown.sh; do
  echo "=== ${script} ==="
  "./${script}"
  echo
done

echo "All generate endpoints exercised. Files are in ${OUT_DIR:-output}/."
