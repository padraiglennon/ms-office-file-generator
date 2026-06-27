# ADR-010: Resource caps for hosted file generation

- **Status:** Done
- **Date:** 2026-06-27
- **Tracking issue:** #11
- **Builds on:** ADR-007
- **Deciders:** Padraig Lennon

## Context

The JSON API (ADR-007) deliberately shipped with **no upper bounds** on count
parameters. Pydantic rejects structural problems (`422`) and the core rejects
counts below its minimums (`slides`/`sections`/`sheets >= 1`, ...) as `400`, but
nothing stops a caller asking for an arbitrarily large file. `slides=1000000`,
`rows=10000000`, or a `sections x blocks_per_section` product in the millions
will pin CPU and memory for the lifetime of the request.

ADR-007 accepted this for the local-first, not-sensitive-by-default posture and
tracked the hosted story as #11. As the API moves toward being hosted (alongside
the auth work in #10), unbounded generation is a **resource-exhaustion vector**:
one unauthenticated request can degrade or take down a shared host.

This ADR adds the bounds. It sits on the seam ADR-007 created: the typed Pydantic
request models and the shared service layer (`web/service.py`) that both the API
and the HTMX UI call. It also follows the env-configuration pattern established by
ADR-002 / ADR-008 (`--flag` overrides `<PREFIX>_VAR` env, with hard defaults).

A second, smaller concern is in scope here because it is the right moment to fix
it: the existing env-var prefix is `MOFG_` (from the old *ms-office-file-generator*
name, ADR-009 renamed the project). The new caps need env vars; introducing them
under `MOFG_` would entrench a stale name. This ADR does a **hard cutover** of the
env-var namespace to match the current project name.

## Decision

Bound generation at three layers - **count caps**, a **composite cost guard**,
and **runtime guards** (timeout + output size) - and migrate the env-var
namespace to `COMMON_FILE_GEN_`.

### 1. Per-field count caps (`422`)

Each count field is bounded by an upper limit; a request over a cap is rejected
as `422` with a field-located message, before any generation work starts -
mirroring ADR-007's "structural problems are 422" split. Lower bounds stay with
the core (`400`) so their messages remain identical across API/UI/CLI.

> **Implementation correction (during build).** The original draft enforced the
> caps with Pydantic `Field(..., le=<cap>)` on the request models. That is
> incompatible with the env-configurability decision below (§4): `Field(le=)` is
> fixed at class-definition time, but the caps resolve from the environment at app
> construction. Rather than make every cap a module-global or thread a Pydantic
> validation `context` through every call site, the caps are validated **in the
> API router** against the injected `Caps` instance and raised as
> `HTTPException(422)` with the same field-located detail. The `422` contract and
> the env-configurability are both preserved; the request models keep only their
> type/`complexity` validation.

Shipped defaults (all env-overridable, see §4):

| Field                 | Applies to            | Default cap |
| --------------------- | --------------------- | ----------- |
| `slides`              | deck                  | 200         |
| `sections`            | doc, pdf, markdown    | 200         |
| `sheets`              | sheet                 | 100         |
| `rows`                | sheet                 | 5000        |
| `cols`                | sheet                 | 100         |
| `blocks_per_section`  | doc, pdf, markdown    | 50          |

These are generous - comfortably above any real transient-test-file need - so the
caps are a sanity ceiling and the runtime guards (§3) are the true backstop.

`blocks_per_section`, `rows`, `cols` are `int | None` (None = per-complexity
default); the cap applies only when a value is supplied.

### 2. Composite cost guard (`422`)

Per-field caps do not stop a request where each field passes individually but the
*product* is huge (e.g. `sheets=100, rows=5000, cols=100` = 50M cells). Each
request type computes an **estimated cost** and is rejected (`422`) if it exceeds
a single budget `COMMON_FILE_GEN_MAX_COST`:

- **deck**: `slides`
- **doc / pdf / markdown**: `sections * (blocks_per_section or default_blocks(complexity))`
- **sheet**: `sheets * (rows or default_rows(complexity)) * (cols or default_cols(complexity))`

When a density field is `None`, the cost uses the per-complexity default the core
would pick, so the guard reflects the file actually produced. The cost helper
lives next to the cap constants (a `caps` module) and is unit-tested directly.

Default `COMMON_FILE_GEN_MAX_COST = 2_000_000`. This admits any single-field
maximum from the table above while rejecting multiplicative blow-ups.

### 3. Runtime guards (timeout + output size) - shared service layer

Counts alone cannot bound pathological CPU/memory, and they do not protect the
`fill` path (an adversarial template/config). Two guards live in the **shared
service layer** (`web/service.py`) so they protect **both front-ends** (API + UI)
and **both paths** (generate + fill) uniformly:

- **Generation timeout.** Generation runs in a worker thread; the request thread
  joins with a wall-clock timeout `COMMON_FILE_GEN_GEN_TIMEOUT_S` (default 30s).
  On expiry the service raises a `GenerationTimeout`, surfaced as **`503`** with a
  JSON `detail`. The orphaned worker thread is left to finish and is not joined
  (a daemon thread); this is a single-process app and the GIL means we cannot
  hard-kill CPU-bound work without process machinery (rejected, see Alternatives);
  the timeout bounds the *client's* wait and frees the request slot, which is the
  goal. Each request already generates into its own temp dir (ADR-007), so a
  draining thread cannot corrupt another request.
- **Output size guard.** After generation, if the produced file exceeds
  `COMMON_FILE_GEN_MAX_OUTPUT_MB` (default 50) the service raises an
  `OutputTooLarge`, surfaced as **`400`** (the bytes are discarded, never
  streamed). A backstop against memory blowup independent of counts.

Both guard errors map to HTTP status in the API router and to the existing error
partial in the UI, reusing the established error-rendering paths.

**Status-code rationale.** Over-large *requests* (per-field and composite caps,
§1/§2) are `422` - the request shape is invalid and a retry of the same body will
always fail, consistent with ADR-007's existing validation `422`. A **timeout** is
`503 Service Unavailable` - the request was well-formed and the same input might
succeed under less load or a higher budget, so it is a transient server condition,
not a client error. An **output over the size cap** is `400` rather than `422`
because the violation is only knowable *after* generation (it depends on generated
content, not a declared field), so it is reported as a generation-time error
alongside the core's other `400`s, keeping one error class for "your input was
accepted but produced something we won't return".

Count and composite caps (§1, §2) stay **API-only**; the UI form already bounds
its own inputs, and the runtime guards cover the UI's exposure. The `fill` path
gets the runtime guards (timeout + size) but **no count/composite cap** - its cost
lives in the uploaded template, not in scalar fields, so there is nothing to cap
pre-generation; the timeout and size guards (plus the existing upload-size cap)
are its bound.

### 4. Env-var namespace hard cutover to `COMMON_FILE_GEN_`

Every environment variable migrates from `MOFG_` to `COMMON_FILE_GEN_`, a
**breaking change** with no fallback (the old names stop working):

| Old                   | New                                  |
| --------------------- | ------------------------------------ |
| `MOFG_HOST`           | `COMMON_FILE_GEN_HOST`               |
| `MOFG_PORT`           | `COMMON_FILE_GEN_PORT`               |
| `MOFG_MAX_UPLOAD_MB`  | `COMMON_FILE_GEN_MAX_UPLOAD_MB`      |

New cap/guard vars (all in the same namespace):

- `COMMON_FILE_GEN_MAX_SLIDES`, `COMMON_FILE_GEN_MAX_SECTIONS`,
  `COMMON_FILE_GEN_MAX_SHEETS`, `COMMON_FILE_GEN_MAX_ROWS`,
  `COMMON_FILE_GEN_MAX_COLS`, `COMMON_FILE_GEN_MAX_BLOCKS_PER_SECTION`
- `COMMON_FILE_GEN_MAX_COST`
- `COMMON_FILE_GEN_GEN_TIMEOUT_S`
- `COMMON_FILE_GEN_MAX_OUTPUT_MB`

All retain the existing precedence: an explicit `--flag` (where one exists) wins
over the env var, which wins over the hard default. The Dockerfile, the
docker-compose service + healthcheck, the README, and the env-driven tests
(`tests/test_web.py`) are updated in the **same change** so nothing references the
dead prefix. The `mofg-*` `tempfile` prefixes are renamed to `cfg-*` for
consistency (cosmetic; not a contract).

### Where the constants live

A new `web/caps.py` (or `core`-adjacent) module owns the default constants, the
env-resolution helpers, and the cost function - one place to read and tune, kept
out of the route handlers. `create_app()` / `create_api_router()` accept the
resolved caps the same way they already accept `max_upload_bytes`, so tests can
inject tight caps without environment juggling.

## Consequences

### Positive

- A single request can no longer pin the host: counts, the multiplicative
  product, wall-clock time, and output size are all bounded.
- Caps reject pre-generation (`422`) - the cheap, fail-fast path - while the
  runtime guards catch what counts cannot (pathological CPU, the fill path).
- Guards in the shared service mean API and UI, generate and fill, are protected
  by one implementation - no duplication, consistent with ADR-007's seam.
- The env namespace finally matches the project name (ADR-009); no stale `MOFG_`.
- Everything is env-tunable for a host, with safe defaults for local use -
  consistent with the ADR-002 / ADR-008 configuration story.

### Negative / trade-offs

- **Breaking env change.** Anyone setting `MOFG_HOST/PORT/MAX_UPLOAD_MB` must
  switch to `COMMON_FILE_GEN_*`. Mitigated by updating every in-repo reference
  (Dockerfile, compose, README, tests) in the same change and calling it out in
  the README. Accepted over a fallback to avoid carrying the dead name.
- **Timeout cannot reclaim CPU.** A daemon worker thread keeps running post
  -timeout until it finishes (GIL). The client wait and the request slot are
  freed, but a burst of expensive requests can still load the box. True isolation
  needs a process pool (rejected as over-engineering for now); revisit with the
  hosting/auth work (#10) if load demands it.
- **Cost function is an estimate.** It uses per-complexity defaults for `None`
  density fields, so it approximates rather than measures the final byte size;
  the output-size guard is the exact backstop.
- More configuration surface (nine new env vars). Mitigated by central defaults
  in one module and generous values that most callers never hit.

### Follow-ups (future ADRs)

- **#10** - API-key auth + hosted multi-user deployment.
- **#15** - Concurrency / rate limiting. This ADR bounds a single request, not a
  request *rate* or concurrent load; N simultaneous requests can each pass every
  per-request cap yet still saturate the host. Likely tied to #10 (rate limits are
  usually per-principal) and may revisit the thread-based timeout for process
  isolation.

## Alternatives considered

- **Caps only, no composite guard.** Rejected: leaves the multiplicative
  blow-up (`sheets x rows x cols`) open, which is the most dangerous combination.
- **Composite guard only, no per-field caps.** Rejected: per-field caps give
  precise field-located `422`s and self-document in `/docs`; the composite guard
  alone gives a vaguer error.
- **Hardcoded caps, no env override.** Rejected: a host cannot tune without
  editing code; inconsistent with the existing `MOFG_MAX_UPLOAD_MB` precedent.
- **Process-pool timeout (hard-kill the worker).** Rejected for now: truly
  reclaims CPU/memory but adds subprocess plumbing, serialization, and failure
  modes disproportionate to a single-process local-first app. Reconsider under
  #10 if hosted load requires it.
- **Keep `MOFG_` env vars (add new caps under `MOFG_` too).** Rejected: entrenches
  the old project name the rename (ADR-009) removed everywhere else.
- **`MOFG_` -> `COMMON_FILE_GEN_` with a deprecated fallback.** Rejected: the
  consumer surface is small (a Dockerfile, a compose file, a README), all updated
  here; a fallback carries the dead name indefinitely for little benefit.

## Acceptance criteria

1. A generate request exceeding any per-field cap (e.g. `slides=10000`) returns
   `422` with a field location, before generation runs.
2. A generate request under every per-field cap but over `COMMON_FILE_GEN_MAX_COST`
   (e.g. `sheets`x`rows`x`cols` past the budget) returns `422`.
3. With a low `COMMON_FILE_GEN_GEN_TIMEOUT_S`, a request that exceeds it returns
   `503 {"detail": ...}` and the request thread is released.
4. With a low `COMMON_FILE_GEN_MAX_OUTPUT_MB`, a request whose output exceeds it
   returns `400 {"detail": ...}` and no bytes are streamed.
5. The timeout and output-size guards apply on both the API and the UI, for both
   generate and fill paths (covered by `TestClient` tests).
6. All env vars use the `COMMON_FILE_GEN_` prefix; no `MOFG_` reference remains in
   source, Dockerfile, docker-compose, README, or tests; existing host/port/upload
   behaviour works under the new names.
7. Defaults are generous enough that the existing test suite and documented usage
   generate successfully without setting any cap env var.
8. Secret, security, and anti-hallucination reviews are clean.
