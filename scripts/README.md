# API test scripts

Sample `curl` scripts that exercise the JSON API (ADR-007), one per generation
endpoint. Handy for smoke-testing a running server and as copy-paste examples.

## Run

Start the server, then run a script:

```bash
uv sync --extra web
uv run gen-ui            # serves the API on 127.0.0.1:18990

./scripts/gen-deck.sh    # one endpoint
./scripts/run-all.sh     # every generate endpoint
```

Each generate script POSTs a JSON body and saves the streamed file under
`output/`.

| Script | Endpoint | Output |
| --- | --- | --- |
| `gen-deck.sh` | `POST /api/generate/deck` | `output/deck.pptx` |
| `gen-doc.sh` | `POST /api/generate/doc` | `output/document.docx` |
| `gen-sheet.sh` | `POST /api/generate/sheet` | `output/workbook.xlsx` |
| `gen-pdf.sh` | `POST /api/generate/pdf` | `output/document.pdf` |
| `gen-markdown.sh` | `POST /api/generate/markdown` | `output/document.md` |
| `gen-fill.sh` | `POST /api/generate/fill` | `output/filled.<ext>` |

`gen-fill.sh` takes a Golden template you supply (none is committed):

```bash
./scripts/gen-fill.sh path/to/template.pptx [configs/sample-deck.json]
```

It shows both responses: the streamed file with the one-line
`X-Injection-Report` header, and the `?include_report=true` JSON form with the
full multi-line report.

## Targeting a different server

All scripts honour env overrides:

```bash
API_HOST=0.0.0.0 API_PORT=9000 ./scripts/gen-deck.sh
OUT_DIR=/tmp/files ./scripts/run-all.sh
```
