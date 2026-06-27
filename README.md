# ms-office-file-generator

Python tool for producing test sample files (PowerPoint, Word, Excel, PDF, and
Markdown) for testing purposes.

It works in two modes:

- **Generate** a complex deck from scratch at a chosen complexity level and slide
  count - the common "give me an N-slide deck" case. Content is lorem-ipsum.
- **Fill** a polished "Golden" template (template-driven): you design the file
  once, mark where data should go, and the tool injects values from a simple JSON
  data file without ever redrawing the layout.

## Who it's for

- **Anyone (non-technical)** supplies the *data* by editing a JSON file and
  preparing a Golden template - no programming needed.
- **Developers** install and run the tool.

## Install

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Use

### Generate a complex deck

```bash
uv run generate deck \
  --out output/deck.pptx \
  --complexity maximum \
  --slides 70
```

Each slide is one designed type, picked at random (seeded) from a pool that grows
with complexity:

| Level | Slide types in the pool |
| --- | --- |
| `minimal` | bullets |
| `simple` | bullets, chevron list |
| `standard` | + image-and-text, image-and-bullets, chart |
| `complex` | + table, section divider |
| `maximum` | + video |

Slide types include bullet lists, chevron lists, image-and-text, image-and-bullets
(image on a random side + a bullet list, like a typical content slide), charts,
tables, video links, and section dividers.

Because each slide has a single focal element, nothing overlaps or overflows.
Types are weighted, so content slides dominate and sparse section dividers stay
rare.

Options:

- `--seed N` - reproducible output (same seed => identical deck).
- `--video-url URL` - YouTube link used on video slides (default provided). Video
  slides show a poster with a play button that links to the video (python-pptx
  cannot author true inline-YouTube playback).
- `--theme path/to/design.pptx` - use a designed PowerPoint as the base so its
  slide-master backgrounds, colours, and layouts carry through. Without it, an
  in-code theme is applied.
- `--background {none,theme,random}` - slide background: `none` (white, default),
  `theme` (one consistent themed tint on every slide), or `random` (a different
  soft tint per slide). Tints are light so text stays readable.
- `--background-color HEX` - an explicit consistent colour (e.g. `EAF2F8`) that
  overrides `--background`.

### Generate a Word document

```bash
uv run generate doc \
  --out output/document.docx \
  --complexity maximum \
  --sections 20
```

Builds a `.docx` from scratch. Each **section** is a heading plus a run of
content blocks drawn from a pool that grows with complexity:

| Level | Content blocks |
| --- | --- |
| `minimal` | headings + paragraphs |
| `simple` | + bullet lists |
| `standard` | + numbered lists, tables |
| `complex` | + images, block quotes |
| `maximum` | + page breaks |

`--sections N` sets the length and `--seed N` makes the output reproducible.

### Generate an Excel workbook

```bash
uv run generate sheet \
  --out output/workbook.xlsx \
  --complexity maximum \
  --sheets 5
```

Builds an `.xlsx` from scratch. Each **sheet** holds one or more data tables;
complexity decides what each sheet gets:

| Level | Sheet content |
| --- | --- |
| `minimal` | one plain data table |
| `simple` | + formula total rows |
| `standard` | + charts, styling |
| `complex` | + a second table per sheet |
| `maximum` | denser tables |

`--sheets N` sets the workbook size, `--rows N` overrides the table size, and
`--seed N` makes the output reproducible. Totals are live formulas
(`=SUM`/`=AVERAGE`) the spreadsheet app evaluates on open.

### Generate a PDF

```bash
uv run generate pdf \
  --out output/document.pdf \
  --complexity maximum \
  --sections 20
```

Builds a `.pdf` from scratch (with `reportlab`). Like the Word generator, each
**section** is a heading plus a run of content blocks (paragraphs, bullet and
numbered lists, tables, images, block quotes, page breaks) that grows with
complexity. `--sections N` sets the length. `--seed N` makes the *content*
reproducible (the PDF embeds a creation timestamp, so the bytes vary but the
content does not).

### Generate a Markdown document

```bash
uv run generate markdown \
  --out output/document.md \
  --complexity maximum \
  --sections 20
```

(`md` is a shorthand alias for `markdown`.) Builds a `.md` from scratch - plain
text, no dependencies. Each **section** is a heading plus blocks: paragraphs,
bullet and numbered lists, GitHub-flavoured tables, and block quotes. Markdown
has no images or page breaks, so the image block renders as a fenced code block
and a page break renders as a horizontal rule. `--sections N` sets the length and
`--seed N` makes the output byte-for-byte reproducible.

### Fill a Golden template

```bash
uv run generate fill \
  --template templates/deck.pptx \
  --config  configs/sample-deck.json \
  --out     output/deck.pptx
```

Supported template types: `.pptx`, `.docx`, `.xlsx` (picked automatically by the
template's extension).

After every `fill` run a plain-English **report** is written next to the output
(e.g. `deck.report.txt`) listing anything that didn't fit so you can fix it.

## Guides

- [How to prepare a Golden template](docs/golden-file-guide.md) - marking text,
  tables, and picture spots in PowerPoint / Word / Excel.
- [The data file (JSON), field by field](docs/config-guide.md).

## Web UI

A simple browser UI (FastAPI + HTMX) drives both modes - no command line.

```bash
uv sync --extra web
uv run gen-ui
```

Then open <http://127.0.0.1:18990>. The deck form's options are derived from the
core, so they stay in step with the CLI. The fill form takes a Golden template
and a JSON config and shows the plain-English report.

The server binds `127.0.0.1` by default. Pass `--host 0.0.0.0` to expose it on
the network (it is unauthenticated - your choice). The fill-mode upload size cap
is set with `--max-upload-mb` or the `MOFG_MAX_UPLOAD_MB` env var (default 25).
Generated files are temporary and swept after one hour.

HTMX is vendored at `src/ms_office_file_generator/web/static/htmx.min.js` (see
`VENDOR.md` there for the pinned version and how to update it).

## JSON API

The same `gen-ui` server also exposes a JSON API under `/api` for programmatic,
machine-friendly generation - ideal for scripting transient test files. Each
generate endpoint takes a JSON body and **streams the file bytes back** (no
download token, nothing persisted):

```bash
curl -s -o document.docx \
  -H 'Content-Type: application/json' \
  -d '{"complexity":"standard","sections":4,"seed":7}' \
  http://127.0.0.1:18990/api/generate/doc
```

| Endpoint | Body fields | Returns |
| --- | --- | --- |
| `POST /api/generate/deck` | `complexity`, `slides`, `seed`, `video_url`, `background`, `background_color` | `.pptx` |
| `POST /api/generate/doc` | `complexity`, `sections`, `seed`, `blocks_per_section` | `.docx` |
| `POST /api/generate/sheet` | `complexity`, `sheets`, `seed`, `rows`, `cols` | `.xlsx` |
| `POST /api/generate/pdf` | `complexity`, `sections`, `seed`, `blocks_per_section` | `.pdf` |
| `POST /api/generate/markdown` | `complexity`, `sections`, `seed`, `blocks_per_section` | `.md` |
| `POST /api/generate/fill` | multipart: `template` + `config` files | filled file + `X-Injection-Report` header |

All body fields are optional and default to the same values as the CLI. A wrong
*type* or unknown `complexity` returns `422`; an out-of-range value (e.g. an
unknown background, `sections` below 1) returns `400` with a JSON `detail`. The
interactive schema is at <http://127.0.0.1:18990/docs>.

The fill endpoint folds a one-line report summary into the `X-Injection-Report`
header. For the full multi-line report, call
`POST /api/generate/fill?include_report=true`, which returns JSON
`{filename, report, file_base64}` instead of streaming the bytes.

The API is unauthenticated and local-first, like the UI; counts are not yet
upper-bounded. Authentication, hosted deployment, and resource caps are tracked
for a future ADR.

## Develop

```bash
uv sync --extra web
uv run pytest          # tests
uv run ruff check .    # lint
uv run pre-commit install   # enable pre-commit hooks
```

## Design

Architecture decision records:

- [ADR-001](design/ADR-001-template-driven-office-file-generator.md) - the
  generator core (inject + generate modes).
- [ADR-002](design/ADR-002-fastapi-htmx-ui.md) - the FastAPI + HTMX web UI.
- [ADR-007](design/ADR-007-json-api-file-generation.md) - the JSON API for
  programmatic file generation.
