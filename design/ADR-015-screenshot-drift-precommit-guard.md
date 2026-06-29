# ADR-015: Warn-only pre-commit guard for UI screenshot drift

- **Status:** Proposed
- **Date:** 2026-06-29
- **Tracking issue:** #24
- **Builds on:** ADR-014 (visual docs & automated UI screenshots)
- **Deciders:** Padraig Lennon

## Context

ADR-014 added a screenshot tour of the web UI to the docs site. The PNGs under
`docs/assets/screenshots/` are produced by `scripts/capture_screenshots.py`
(Playwright driving headless Chromium) via `make screenshots`, and the produced
images are **committed**. ADR-014 deliberately kept the browser toolchain out of
CI: the docs build only embeds already-committed images, so CI stays
deterministic and browser-free.

The accepted, explicitly-unenforced trade-off (ADR-014, Negative): committed
screenshots can drift from the live UI when a maintainer changes the UI and
forgets to re-run `make screenshots`. Nothing surfaces the drift; stale images
can ship silently. Issue #24 asks for a guard that catches this.

Constraints that shape the solution:

- **The browser-in-CI cost ADR-014 avoided is real and worth preserving.** Any
  guard that boots a server + Chromium on every CI run reintroduces exactly the
  flakiness and weight ADR-014 rejected.
- **The project already uses pre-commit** (`.pre-commit-config.yaml`) with a
  `local` repo block for project-specific hooks (the `pytest` hook:
  `language: system`, `entry: uv run ...`, `pass_filenames: false`).
- **The capture logic already exists** and is deterministic (fixed seed, fixed
  viewport). A drift check should reuse it, not re-implement capture.
- **Cross-environment pixel noise is expected.** Font hinting, anti-aliasing,
  and GPU differences between machines mean a byte-exact PNG comparison would
  false-positive constantly. The diff needs tolerance.

## Decision

Add a **path-scoped, warn-only pre-commit hook** that re-captures the UI
screenshots and pixel-diffs them against the committed PNGs, surfacing drift to
the maintainer at commit time. It never blocks a commit and never runs in CI.

### Placement: a local pre-commit hook, not a CI job

The guard lives in `.pre-commit-config.yaml` as a sibling `local` hook to the
existing `pytest` hook. CI (`docs.yml`) is **unchanged** - the strict mkdocs
build stays browser-free. This keeps the ADR-014 separation intact: the browser
toolchain runs only on a maintainer's machine, only when they touch the UI.

The hook is **path-scoped**: it fires only when the staged set includes
UI-affecting files. Commits that do not touch the UI pay nothing.

```yaml
  - repo: local
    hooks:
      - id: screenshot-drift
        name: screenshot-drift (warn-only)
        entry: uv run python scripts/check_screenshot_drift.py
        language: system
        pass_filenames: false
        files: >-
          (?x)^(
            src/common_file_generator/web/.*|
            scripts/capture_screenshots\.py|
            docs/assets/screenshots/.*\.png
          )$
```

`files:` scopes *which staged paths trigger the hook*; `pass_filenames: false`
because the check always re-captures the full set, not per-file.

### Mechanism: re-capture headless, then diff

A new `scripts/check_screenshot_drift.py`:

1. Captures the screenshots **into a temporary directory** by reusing the
   existing capture logic from `scripts/capture_screenshots.py` (the capture
   function is parameterised by output directory; no change to its behaviour
   when called by `make screenshots`).
2. For each expected screenshot, pixel-diffs the freshly-captured image against
   the committed one under `docs/assets/screenshots/`.
3. Reports drift and **always exits 0**.

To keep capture reusable, `capture_screenshots.py` is refactored minimally so
its output directory is a parameter (defaulting to the current
`docs/assets/screenshots/`). The `make screenshots` behaviour is unchanged.

### Tolerance: per-pixel threshold + total-diff-ratio

Comparison uses **Pillow** (added to the `shots` optional-dependency group
alongside Playwright). For each image pair:

- Two pixels are "different" only if their per-channel color distance exceeds a
  **per-pixel threshold** (absorbs sub-pixel anti-aliasing / font-hinting
  noise).
- An image has **drifted** only if the ratio of differing pixels to total
  pixels exceeds an **allowed total-diff-ratio**.

Both constants live at the top of `check_screenshot_drift.py` with comments, so
the tolerance is tunable if a runner environment proves noisier than expected.
Mismatched dimensions (a genuinely restructured panel) count as full drift.

### On drift (warn-only)

When one or more images drift, the hook:

- Prints the list of drifted screenshot filenames and their diff ratios to
  stderr.
- Writes per-image **diff PNGs** (highlighting changed regions) to a
  **gitignored** temp directory, and prints that path so the maintainer can
  inspect what changed.
- Exits 0 - the commit proceeds regardless.

A `.gitignore` entry covers the diff-output directory so artifacts never get
committed.

### Missing tooling: skip, never block

If Chromium or the required extras are not available (a fresh clone without
`playwright install chromium`, or `shots`/`web` not synced), the hook prints

```
screenshot-drift check skipped (run `playwright install chromium`)
```

and exits 0. A missing browser binary must never turn into "I can't commit."
This is detected before attempting capture (catch the Playwright
browser-not-found / import error path) so the skip is clean, not a stack trace.

### A baseline with no committed image

If an expected screenshot has no committed counterpart (e.g. a new tab was added
but `make screenshots` not yet run), that counts as drift and is reported - it
is exactly the "you forgot to re-capture" case the guard exists to surface.

## Consequences

### Positive

- UI drift surfaces at commit time, on the machine of the person who changed the
  UI, while the change is fresh - the gap ADR-014 left open.
- The browser-in-CI cost ADR-014 avoided stays avoided: `docs.yml` is untouched
  and the CI docs build remains browser-free and deterministic.
- Zero cost on non-UI commits (path-scoped); cost is paid only when the UI,
  the capture script, or the committed PNGs are staged.
- Never blocks a commit: warn-only plus skip-on-missing-tooling means it cannot
  wedge a contributor who lacks Chromium.
- Reuses the existing deterministic capture logic - one capture implementation,
  not two.

### Negative / trade-offs

- Warn-only is advisory, not enforcing: a maintainer can see the drift warning
  and commit anyway (or commit on a machine without Chromium, where it skips).
  The guard reduces silent drift; it does not guarantee fresh screenshots.
- UI-touching commits pay a ~10-30s capture cost (server boot + headless
  Chromium + capture). Acceptable because UI commits are infrequent and the
  hook is path-scoped.
- Pixel-diff tolerance is a tuned heuristic; a too-tight ratio nags on
  cross-machine noise, a too-loose one misses small real changes. The constants
  are exposed for tuning, but they are still a judgement call.
- Adds Pillow to the `shots` extra (not the runtime container - `shots` stays
  out of the `web` extra and the Dockerfile, per ADR-014).

### Follow-ups (future ADRs)

- If warn-only proves too weak in practice (drift keeps shipping despite the
  warning), a hard-fail CI job re-capturing headless and gating the docs deploy
  is the stronger remedy - but it reintroduces browser-in-CI and needs its own
  ADR to weigh that cost. Not opened now; this ADR is the lighter first step
  #24 asks for.

## Alternatives considered

- **Hard-fail CI job in `docs.yml`.** Rejected for now: it reintroduces the
  browser + running server in CI that ADR-014 deliberately removed, and because
  `docs.yml` runs only on push to `main`, the failure would block the docs
  *deploy* after merge rather than catch drift at PR time. A warn-only local
  hook gives feedback earlier (at commit) and at lower cost. Kept as a documented
  follow-up if the advisory approach proves insufficient.
- **A new `pull_request` CI workflow.** Rejected: the repo has no PR-triggered
  CI today, so this adds a whole CI surface plus the browser cost, for a check
  that a local hook covers more cheaply.
- **A `make check-screenshots` target only (no hook).** Rejected as too easy to
  forget - the drift the guard targets is itself caused by forgetting to
  re-capture, so a purely opt-in target inherits the same failure mode. The
  pre-commit hook fires automatically on the relevant paths.
- **Hard-fail pre-commit hook.** Rejected: it would block commits on
  cross-machine pixel noise and on machines without Chromium, and is bypassable
  with `--no-verify` anyway - so it pays the friction of enforcement without the
  guarantee. Warn-only delivers the signal without the wedge.
- **Byte-exact PNG comparison (no tolerance).** Rejected: font hinting, GPU, and
  anti-aliasing differences across environments would make it flake on every
  machine that isn't the one that last captured.

## Acceptance criteria

1. `.pre-commit-config.yaml` gains a path-scoped `local` hook that runs
   `scripts/check_screenshot_drift.py` only when staged files match the UI
   surface (web package, capture script, committed PNGs).
2. The hook re-captures into a temp dir (reusing the existing capture logic, with
   `make screenshots` behaviour unchanged), pixel-diffs against the committed
   PNGs with a per-pixel threshold + total-diff-ratio tolerance, and **exits 0
   on drift** after reporting drifted filenames + ratios and writing diff PNGs to
   a gitignored temp dir.
3. With Chromium/extras missing, the hook prints the documented skip notice and
   exits 0 - it never blocks a commit.
4. Pillow is added to the `shots` optional extra only; the runtime container
   (Dockerfile, `web` extra) is unchanged.
5. A `.gitignore` entry covers the diff-output directory; no diff artifacts are
   committable.
6. Secret, security, and anti-hallucination reviews are clean.

<!--
Status lifecycle: Proposed -> Accepted -> Done (or Superseded by ADR-XXX).
-->
