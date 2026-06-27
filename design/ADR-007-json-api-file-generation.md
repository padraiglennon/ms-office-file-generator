# ADR-007: JSON API for programmatic file generation

- **Status:** Done
- **Date:** 2026-06-27
- **Tracking issue:** #9
- **Builds on:** ADR-002
- **Deciders:** Padraig Lennon

## Context

File generation is currently reachable two ways: the CLI (`generate ...`, ADR-001)
and the HTMX form UI (ADR-002). Both are human-driven. There is no machine-friendly
endpoint a script or another service can call to obtain a file.

The motivating use case is generating **transient test files** programmatically -
ask for a `.docx`/`.pptx`/`.xlsx`/`.pdf`/`.md` of a given complexity, get the bytes,
use them, discard them - with the longer-term goal of **hosting this as a service**.

ADR-001 kept the engine library-first (the CLI and the UI are thin wrappers over the
`core` functions), and ADR-002 added the web front-end without duplicating any
generation logic. This ADR adds a second, programmatic front-end over the same core
and tightens the seam the two front-ends share. Issue #9 tracks it.

The app is **not sensitive by default** - it produces synthetic, throwaway content
from public lorem-ipsum text. That framing drives the local-first, no-auth posture
below.

## Decision

Add a JSON **API** over the existing core, served by the existing FastAPI app.

### One app, `/api` router

The API is an `APIRouter` mounted under **`/api`** in the existing `create_app()`.
The single `gen-ui` console script serves both the HTMX UI and the JSON API in one
process. FastAPI's automatic OpenAPI docs (`/docs`) document the API for free.

The prefix is **unversioned** (`/api/generate/...`, not `/api/v1/...`). Versioning is
deferred; if a breaking change is ever needed it can be introduced then.

### Typed Pydantic request bodies

Each generate endpoint accepts a **JSON body** validated by a per-file-type Pydantic
model, mirroring the core function signatures:

- `deck`: `complexity`, `slides`, `seed`, `video_url`, `background`, `background_color`
- `doc` / `pdf` / `markdown`: `complexity`, `sections`, `seed`, `blocks_per_section`
- `sheet`: `complexity`, `sheets`, `seed`, `rows`, `cols`

Validation splits by kind: **structural** problems (wrong type, an unknown
`complexity`) are rejected by Pydantic as `422`; **value bounds** (counts below the
core's minimums - `slides`/`sections`/`sheets >= 1`, `cols >= 3`, ...) are left to the
core, which raises `ValueError` surfaced as `400`. This keeps the bound messages
identical across the API, UI, and CLI rather than duplicating them in the models.
There are deliberately **no upper bounds** for now (see Consequences).

### Stream bytes directly

Each `POST /api/generate/{type}` returns the **raw file bytes** as the response body
with `Content-Type` (the correct Office/PDF/markdown MIME) and
`Content-Disposition: attachment; filename=...`. There is **no token, no temp file,
and no TTL** on the API path: one call returns the file. This is the natural primitive
for transient test files and leaves nothing to clean up or leak.

Endpoints:

- `POST /api/generate/deck` -> `application/vnd.openxmlformats-officedocument.presentationml.presentation`
- `POST /api/generate/doc` -> `...wordprocessingml.document`
- `POST /api/generate/sheet` -> `...spreadsheetml.sheet`
- `POST /api/generate/pdf` -> `application/pdf`
- `POST /api/generate/markdown` -> `text/markdown`

### Fill mode: multipart + report header

Template injection (the `fill` mode of ADR-001) needs file inputs and produces a
plain-English report alongside the file. It is exposed as:

- `POST /api/generate/fill` - **multipart/form-data** carrying the template
  (`.pptx`/`.docx`/`.xlsx`) and the config (`.json`), reusing the same type and size
  checks as the UI (`MOFG_MAX_UPLOAD_MB`, streamed and aborted past the cap).

The filled file is streamed back as bytes; a one-line (newline-folded) summary
travels in an **`X-Injection-Report`** response header so the common (streaming)
path stays uniform. Because an HTTP header cannot hold the multi-line report,
`?include_report=true` switches the response to JSON carrying the **full**
structured report plus the file base64-encoded, for callers that need it.

### Errors: structured JSON

The API returns RFC-ish structured errors:

- **`422`** - Pydantic validation failures (FastAPI default shape, with field locations).
- **`400 {"detail": "..."}`** - generation-time errors (`ValueError` from the core,
  bad complexity, malformed config, missing theme) surfaced as a JSON `detail` string.

### Shared service layer (UI refactor)

Today the UI form routes contain the "generate to a temp file, store under a token,
render a partial" glue, and the API would need its own "generate to bytes" glue. To
avoid duplicating generation orchestration across two front-ends, extract a **shared
internal service layer** that both call:

- a small service module owns "run the core generator and produce the result"
  (and, for the UI, the temp-file + token storage),
- **API routes** use it to obtain bytes and stream them,
- **UI routes** use it to obtain a stored artifact and render the existing
  token + partial response.

The UI does **not** make in-process HTTP calls to the API; both front-ends sit on the
same Python service. The UI's externally observable behaviour is unchanged.

### Local-first, no auth

The API ships **unauthenticated**, bound to localhost by default like the UI. Given
the app is not sensitive by default, this is acceptable for local and CI use.
Authentication and a hosted multi-user deployment are a follow-up (#10).

## Consequences

### Positive

- A script or service can generate a file in one HTTP call; ideal for transient
  test fixtures.
- One process and one launch command serve both the UI and the API; `/docs` is free.
- The shared service layer removes the duplication between the two front-ends, so a
  new option added to the core surfaces in both with less glue.
- Streaming means the API path has no temp storage, no token registry, and no TTL to
  manage or leak.
- Each request generates into its own throwaway temp directory, so concurrent
  requests do not contend for a shared path - the API is concurrency-safe without
  extra locking.
- Rollout needs no new dependency (Pydantic ships with FastAPI's `web` extra) and no
  new console script - `uv sync --extra web` then `gen-ui` serves UI and API together.

### Negative / trade-offs

- **No upper bounds on counts** means a single request can ask for an enormous file
  and pin CPU/memory - a resource-exhaustion vector once hosted. Accepted for local
  use; tracked as #11 for the hosted story.
- **No auth**: safe only on localhost. Exposing the API via `--host 0.0.0.0` is the
  user's explicit, unauthenticated choice - same posture as ADR-002. Tracked as #10.
- Refactoring the UI onto a shared service touches working UI routes; mitigated by
  keeping the UI's observable behaviour identical and covering it with the existing
  and new `TestClient` tests.
- The fill report header holds only a folded one-line summary; the full structured
  report requires the `?include_report=true` JSON mode. Acceptable: the streaming
  path stays uniform and the complete report is still retrievable on request.

### Follow-ups (future ADRs)

- **#10** - API-key authentication + hosted multi-user deployment (supersedes the
  ADR-002 "auth/hosting" follow-up).
- **#11** - Resource caps / upper bounds for hosted generation.

## Alternatives considered

- **Token + separate download (mirror the UI).** Rejected as the API default: adds
  temp storage, a token registry, and a TTL for no benefit when the caller just wants
  the bytes. The UI keeps token delivery because it needs an in-page link and report.
- **Versioned `/api/v1` prefix.** Rejected for now: premature ceremony for a
  single-version surface; can be introduced when a breaking change actually arrives.
- **UI calls the API over in-process HTTP.** Rejected: a self-request round-trip and
  it still leaves the temp/token glue in the UI. A shared Python service is cleaner.
- **Upper-bound caps now.** Rejected for this ADR: the app is local-first and not
  sensitive; caps belong with the hosting/auth work (#11) where they have a clear
  policy.
- **A separate API-only app / `gen-api` script.** Rejected: duplicates app wiring;
  one app with an `/api` router is simpler and keeps UI + API in lockstep.

## Acceptance criteria

1. `POST /api/generate/doc` with a JSON body streams a valid `.docx` with the correct
   content-type and a `Content-Disposition` filename; the bytes open as a real
   document.
2. All five generate endpoints (`deck`, `doc`, `sheet`, `pdf`, `markdown`) stream the
   correct file type from a typed JSON body.
3. `POST /api/generate/fill` accepts a template + config via multipart, streams the
   filled file, and returns the plain-English report in `X-Injection-Report`.
4. Invalid input returns `422` (validation) or `400 {"detail": ...}` (generation
   error) with a machine-readable body.
5. `/docs` renders the typed API.
6. The HTMX UI still works unchanged, now sharing the service layer with the API;
   existing and new `TestClient` tests pass.
7. Secret, security, and anti-hallucination reviews are clean.
