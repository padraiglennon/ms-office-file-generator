# ADR-013: Global concurrency cap for hosted file generation

- **Status:** Done
- **Date:** 2026-06-28
- **Tracking issue:** #15
- **Builds on:** ADR-010
- **Deciders:** Padraig Lennon

## Context

ADR-010 (#11) bounds a **single** request: per-field count caps and a composite
cost budget reject over-large requests (`422`) before generation, and two runtime
guards - a wall-clock timeout (`503`) and an output-size cap (`400`) - backstop
pathological work and the `fill` path. Those guards live in the shared service
layer (`web/service.py`, `run_guarded`) so they protect both front-ends (API + UI)
and both paths (generate + fill).

What ADR-010 deliberately does **not** bound is concurrent load. N simultaneous
requests can each pass every per-request cap yet still saturate CPU/memory
together. ADR-010 noted this explicitly: the thread-based timeout frees the
*client* and the request slot, but the GIL means an orphaned worker thread keeps
consuming CPU until it finishes, so a burst of expensive requests can still load
the box. ADR-010's own follow-up list names #15 as the next step.

The app runs as a **single uvicorn process** (`uvicorn.run(app, ...)` in
`web/server.py`, no `workers=`), so all in-flight generations share one
interpreter. Auth (#10) has not landed, so there is no authenticated principal to
key a per-caller limit on. The real, present threat is therefore host saturation
from concurrent generation - a *global* concern, not a per-caller one.

This ADR adds a global concurrency ceiling. It sits on the same seam ADR-010 used
(`run_guarded`) and follows the same env-configuration pattern
(`COMMON_FILE_GEN_*` with hard defaults, resolved into the `Caps` dataclass at app
construction).

## Decision

Add a **process-wide concurrency cap** on generation work, enforced by a
semaphore acquired inside `run_guarded()`, with a bounded wait-then-`503` policy
when the cap is full. Two new env-overridable values live alongside the existing
ADR-010 caps.

### 1. A global semaphore in the shared service layer

A single `threading.BoundedSemaphore(max_concurrent)` is created once per app
instance and threaded through to `run_guarded` the same way `Caps` already is.
Every generation - API or UI, generate or fill - already funnels through
`run_guarded`, so one acquire/release there caps all of them with no duplication.
This is the same placement argument ADR-010 used for the timeout and output-size
guards.

The semaphore is acquired **before** the worker thread is started and released in
a `finally` so it is returned on success, on `GenerationTimeout`, and on any
generation error. Crucially, the slot is **held across the existing wall-clock
join**: a request occupies a concurrency slot for as long as its worker thread is
counted as in-flight, which is the behaviour we want (the slot models "work the
host is currently doing"). On timeout the orphaned daemon thread keeps draining
(ADR-010's accepted trade-off), but the slot is released when `run_guarded`
returns control to the caller, so the timeout still frees the slot for the next
request - the cap bounds the number of requests *waited on at once*, and the
timeout bounds how long any one of them holds its slot.

### 2. Wait-briefly-then-503 when full

When all slots are taken, a new request blocks on the semaphore for up to
`acquire_timeout_s`. If a slot frees within that window it proceeds normally; if
not, `run_guarded` raises a new `ConcurrencyLimited` exception, surfaced as
**`503 Service Unavailable`** with a JSON `detail` - the same status ADR-010 uses
for its generation timeout, because both are transient "well-formed request, host
busy, retry later" conditions rather than client errors.

The bounded wait (not an unbounded queue) is deliberate: an unbounded queue
re-introduces the client-wait / thread-pileup problem ADR-010's timeout exists to
prevent. The short wait absorbs ordinary bursts (most generations finish well
inside the 30s generation timeout) without letting a backlog grow without limit.

Both new error mappings reuse the established error-rendering paths: the API
router raises `HTTPException(503, detail=...)`; the UI renders the existing error
partial with `status_code=503`, exactly as the `GenerationTimeout` path already
does.

### 3. Defaults and env configuration

Two new values, both env-overridable under the existing namespace, both resolved
in `Caps.from_env`:

| Value                                 | Default | Meaning                                              |
| ------------------------------------- | ------- | ---------------------------------------------------- |
| `COMMON_FILE_GEN_MAX_CONCURRENT`      | 8       | Max simultaneous in-flight generations (semaphore).  |
| `COMMON_FILE_GEN_ACQUIRE_TIMEOUT_S`   | 5       | Seconds a request waits for a free slot before 503.  |

They join the `Caps` dataclass as `max_concurrent` and `acquire_timeout_s`,
resolved through the existing `_env_int` helper (positive-int-or-default), keeping
one place to read and tune. Tests construct a `Caps` with tight values directly,
as they already do for the ADR-010 caps.

The semaphore itself is **not** a field on the frozen `Caps` dataclass (it is
mutable shared state, not a config scalar); it is constructed in `create_app`
from `caps.max_concurrent` and passed to the service alongside `caps`, mirroring
how `max_upload_bytes` is derived from config and passed separately.

### Note on the default of 8 (not 8-way parallelism)

On a single GIL-bound process, 8 concurrent CPU-bound generations do not run
8-wide - they contend on one interpreter, so wall-clock per request inflates
under load and the 30s generation timeout is the real CPU backstop. The
concurrency cap is therefore primarily a **memory and pile-up backstop**: it
bounds how many requests are simultaneously holding temp files, worker threads,
and connections, not how much true parallelism the host delivers. 8 is generous
for transient-test-file use and tunable down on a small host; operators wanting
real parallelism would run multiple workers/processes, which is out of scope here
(see Consequences).

### 4. Telemetry

A single **warning log line on each concurrency reject** (the `503` path): enough
for an operator to see the cap biting without new infrastructure. No new metric,
gauge, or endpoint - consistent with ADR-010 adding no telemetry for its guards.
The log records that a request was rejected after waiting the full
`acquire_timeout_s`; it does not log every acquire.

## Consequences

### Positive

- The concurrent-load vector ADR-010 left open is closed: the host can no longer
  be saturated by N requests that each individually pass every per-request cap.
- One implementation in `run_guarded` covers API + UI and generate + fill, with
  no duplication - the same seam and the same argument ADR-010 used.
- No new runtime dependency: a stdlib `threading.BoundedSemaphore`, not a
  rate-limit library or external store.
- Env-tunable with safe defaults, consistent with the ADR-002 / ADR-008 / ADR-010
  configuration story; the default of 8 lets the existing suite and documented
  usage run without setting anything.
- A bounded wait smooths ordinary bursts while the wait-cap prevents the
  unbounded-queue failure mode.

### Negative / trade-offs

- **Not true parallelism.** The cap is a pile-up/memory backstop, not a throughput
  knob; on one GIL-bound process 8 concurrent jobs share one interpreter. A reader
  must not mistake `MAX_CONCURRENT=8` for "8 files built in parallel". Documented
  above and in the README.
- **Single-process only.** The semaphore is per-process. If the app is ever run
  with multiple uvicorn workers, each worker gets its own cap and the effective
  global limit multiplies. The app ships single-worker today; a multi-worker
  deployment would need a shared limiter (out of scope, see Follow-ups).
- **A held slot spans a draining timed-out thread's client wait, not its CPU
  drain.** The slot frees when `run_guarded` returns (on timeout), but the orphan
  thread keeps using CPU until it finishes (ADR-010's accepted GIL trade-off), so
  under a burst of timeouts the box can still be loaded by draining threads even
  though slots are free. The generation timeout, not the concurrency cap, bounds
  that; true reclamation still needs process isolation (deferred).
- **Still no per-caller fairness.** A global cap does not stop one noisy client
  from consuming all slots; per-principal fairness waits on auth (#10).

### Follow-ups (future ADRs)

- **#10** - API-key auth + hosted multi-user deployment; the natural home for
  *per-principal* rate limiting, which this ADR deliberately defers.
- **Multi-worker / shared limiter.** If the app moves to multiple workers or
  processes, the per-process semaphore must become a shared limiter (e.g. a small
  external store or a single front limiter). An ADR is required before that.
- **Process-pool isolation.** Revisit ADR-010's thread-based timeout in favour of
  process isolation if hosted load requires truly reclaiming CPU on abort; would
  also let the concurrency slot model real CPU occupancy.

## Alternatives considered

- **Per-caller (per-IP) limit now.** Rejected: without auth the only key is
  client IP, which is spoofable, fragile behind shared NAT, and needs
  X-Forwarded-For trust config behind a proxy - bookkeeping that does not match
  the real threat (host saturation is global). Per-principal limiting belongs with
  auth (#10).
- **A rate limit (requests-per-window) instead of a concurrency cap.** Rejected as
  the primary mechanism: a rate window bounds sustained volume but not a single
  burst of expensive concurrent jobs, which is exactly the vector ADR-010 left
  open. A concurrency ceiling addresses that burst directly.
- **Both concurrency and rate in this ADR.** Rejected for scope: two mechanisms,
  two config pairs, and more tests for a threat (concurrent saturation) that one
  global cap already addresses. Rate limiting can layer on with #10.
- **ASGI middleware counting in-flight requests.** Rejected: it would have to
  match generate/fill route paths and sit apart from the service seam where
  ADR-010's guards already live; `run_guarded` is the one place that already wraps
  every generation for both front-ends and both paths.
- **slowapi / an external rate-limit library.** Rejected: heavier than a single
  global counter needs, and pulls a new runtime dependency into the web image for
  no benefit over a stdlib semaphore.
- **Reject immediately when full (no wait).** Rejected: fails requests that would
  have succeeded a few hundred ms later; the bounded wait absorbs ordinary bursts
  at no real cost.
- **Queue with no timeout.** Rejected: re-introduces the unbounded client-wait /
  thread-pileup problem ADR-010's timeout exists to prevent.

## Acceptance criteria

1. With `COMMON_FILE_GEN_MAX_CONCURRENT` slots all occupied, a new generation
   request waits up to `COMMON_FILE_GEN_ACQUIRE_TIMEOUT_S` and, if no slot frees,
   returns `503` with a JSON `detail`.
2. A request that obtains a slot within the wait window proceeds and succeeds
   normally.
3. The semaphore slot is released on success, on `GenerationTimeout`, and on a
   generation error - verified by showing capacity is restored after each (no
   leak).
4. The concurrency cap applies on both the API and the UI, for both generate and
   fill paths (covered by `TestClient` tests).
5. A concurrency reject (`503` after the full wait) emits a warning log line.
6. Both new values resolve from `COMMON_FILE_GEN_MAX_CONCURRENT` /
   `COMMON_FILE_GEN_ACQUIRE_TIMEOUT_S`, each with the documented default and the
   positive-int-or-default fallback; an invalid value falls back to the default.
7. Defaults (8 / 5s) are generous enough that the existing test suite and
   documented usage run without setting any concurrency env var.
8. Secret, security, and anti-hallucination reviews are clean.
