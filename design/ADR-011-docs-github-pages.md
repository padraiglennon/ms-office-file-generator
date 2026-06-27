# ADR-011: Documentation hosting via GitHub Pages (mkdocs) + UI links to API & docs

- **Status:** Done
- **Date:** 2026-06-27
- **Tracking issue:** #16
- **Builds on:** ADR-002 (FastAPI + HTMX UI), ADR-008 (containerization)
- **Deciders:** Padraig Lennon

## Context

The project ships user guides under `docs/` (`golden-file-guide.md`,
`config-guide.md`) but never published them as a site, and the web UI offered no
path to either the guides or the API reference. We want documentation reachable
from the running app, plus a one-click link to the live API reference.

Two facts shaped the decision:

1. **mkdocs is a static-site generator, not a runtime service.** The original
   request was to "add in-built mkdocs into the container", but the docs do not
   change at runtime, so bundling a docs server (or a built site) into the runtime
   image would add weight and a build step for no benefit. The preference is to
   host the docs *outside* the runtime container.
2. **FastAPI already serves interactive API docs** at `/docs` (Swagger) and
   `/redoc` (ReDoc). Surfacing the API needs no new endpoint - only a UI link.

## Decision

### Documentation site

Build the `docs/` markdown into a site with **mkdocs** + the **mkdocs-material**
theme and publish it to **GitHub Pages**. The build runs in **CI**, not in the
runtime container.

- `mkdocs.yml` at the repo root: `docs_dir: docs`, material theme, and a `nav`
  listing a new `docs/index.md` landing page plus the two existing guides.
- mkdocs/mkdocs-material live in a new `docs` optional-dependency group in
  `pyproject.toml`, deliberately **separate** from the runtime `web` extra. The
  Dockerfile builds with `--extra web` only and copies just
  `pyproject.toml/uv.lock/README.md/LICENSE/src`, so the docs toolchain never
  enters the image.
- `docs/config-guide.md` linked `../configs/sample-deck.json`, which points
  outside `docs_dir` and fails `mkdocs build --strict`; it now links the GitHub
  blob URL instead.

### CI / Pages deployment

`.github/workflows/docs.yml` uses the modern GitHub Pages flow:

- Trigger: push to `main` filtered to `docs/**`, `mkdocs.yml`, and the workflow
  file itself; plus `workflow_dispatch`.
- `build` job: `uv run --frozen --extra docs mkdocs build --strict` →
  `actions/configure-pages` → `actions/upload-pages-artifact` (path `site`).
- `deploy` job: `actions/deploy-pages` in the `github-pages` environment.
- Permissions `pages: write` + `id-token: write`; `concurrency: pages`.

**Manual prerequisite (one-time):** repo Settings → Pages → Source =
"GitHub Actions". The deploy job cannot set this and fails without it.

### UI

Two header nav links, visually separate from the generation tab strip:

- **API** → `/docs` (FastAPI Swagger UI), opened in a new tab.
- **Docs** → the GitHub Pages site, opened in a new tab.

The Pages URL is a constant `_DOCS_URL` in `app.py`, overridable via
`COMMON_FILE_GEN_DOCS_URL` (matching the ADR-010 env-var convention), passed to
the template as `docs_url`. New `.header-nav` styles reuse the existing header
palette.

## Consequences

### Positive

- Polished, hosted documentation reachable from the app, plus a one-click path to
  the live API reference.
- Zero change to the runtime container image; single process preserved.
- Docs rebuild automatically on merge to `main` when docs sources change.

### Negative / trade-offs

- A one-time manual repo setting (Pages source) is required before the first
  deploy succeeds.
- The hosted docs link is dead until that first successful Pages deploy.
- `mkdocs build --strict` makes any out-of-`docs_dir` or broken link a hard CI
  failure (intentional, but a future doc edit can trip it).

### Follow-ups (future ADRs)

- None required.

## Alternatives considered

- **Bundle a built mkdocs site into the container (the literal request).**
  Rejected: adds image weight + a build step to serve content that never changes
  at runtime.
- **Run `mkdocs serve` as a second in-container process.** Rejected: two
  processes, heavier image, more failure modes, for no runtime benefit.
- **Link straight to rendered markdown on github.com (no build).** Rejected:
  raw GitHub file-browser chrome, and links break if the repo goes private.
- **A bespoke in-app API reference page.** Rejected: FastAPI's Swagger UI already
  exists at `/docs`; a hand-written page would only add maintenance.

## Acceptance criteria

1. `mkdocs build --strict` exits 0; the site renders Home + both guides.
2. The web UI header shows "API" and "Docs" links separate from the tab strip;
   "API" opens Swagger at `/docs`, "Docs" opens the Pages URL.
3. The docs toolchain stays out of the runtime container image.
4. `.github/workflows/docs.yml` deploys to GitHub Pages on merge to `main`.
5. Secret, security, and anti-hallucination reviews are clean.
