"""Resource caps and runtime guards for hosted generation (ADR-010).

The JSON API accepts caller-supplied counts; without bounds a single request can
ask for an enormous file and pin CPU/memory. This module is the one place that
owns:

- the per-field **upper bounds** (enforced in the API router against this Caps),
- the **composite cost** estimate and its budget (a cross-field guard for
  combinations that pass each per-field cap but multiply huge),
- the **runtime guards** (generation wall-clock timeout and output-size cap),
- the **concurrency guard** (max simultaneous generations and the wait a request
  will tolerate for a free slot before a 503; the semaphore itself lives in the
  app, ADR-013),

plus the environment resolution for all of the above. Defaults are generous --
comfortably above any real transient-test-file need -- so the caps are a sanity
ceiling and the runtime guards are the true backstop.

Every value reads from a ``COMMON_FILE_GEN_*`` environment variable with a hard
default; an invalid or non-positive value falls back to the default.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from common_file_generator.core import Complexity

# Per-complexity density defaults, mirrored from the generators so the cost
# estimate reflects the file actually produced when a density field is omitted.
# Kept in sync with generators.{docx,pdf,markdown}._BLOCKS_PER_SECTION and
# core.complexity._SHEET_FEATURES.
_DEFAULT_BLOCKS: dict[Complexity, int] = {
    Complexity.MINIMAL: 1,
    Complexity.SIMPLE: 2,
    Complexity.STANDARD: 3,
    Complexity.COMPLEX: 4,
    Complexity.MAXIMUM: 5,
}
_DEFAULT_SHEET_ROWS: dict[Complexity, int] = {
    Complexity.MINIMAL: 6,
    Complexity.SIMPLE: 8,
    Complexity.STANDARD: 10,
    Complexity.COMPLEX: 12,
    Complexity.MAXIMUM: 15,
}
_TABLES_PER_SHEET: dict[Complexity, int] = {
    Complexity.MINIMAL: 1,
    Complexity.SIMPLE: 1,
    Complexity.STANDARD: 1,
    Complexity.COMPLEX: 2,
    Complexity.MAXIMUM: 3,
}
# The core randomises cols in 3..5 when unset; use the worst case for the budget.
_DEFAULT_SHEET_COLS = 5


def _env_int(name: str, default: int) -> int:
    """Read a positive int from ``name``; fall back to ``default`` otherwise."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Caps:
    """Resolved resource caps and runtime guards for one app instance.

    Built once at app construction (:func:`from_env`) and threaded through the
    API router and the service layer, mirroring how ``max_upload_bytes`` is
    already passed around. Tests construct one directly with tight values rather
    than juggling environment variables.
    """

    max_slides: int = 200
    max_sections: int = 200
    max_sheets: int = 100
    max_rows: int = 5000
    max_cols: int = 100
    max_blocks_per_section: int = 50
    max_cost: int = 2_000_000
    gen_timeout_s: int = 30
    max_output_mb: int = 50
    max_concurrent: int = 8
    acquire_timeout_s: int = 5

    @property
    def max_output_bytes(self) -> int:
        return self.max_output_mb * 1024 * 1024

    @classmethod
    def from_env(cls) -> Caps:
        """Build caps from ``COMMON_FILE_GEN_*`` env vars, each with a default."""
        return cls(
            max_slides=_env_int("COMMON_FILE_GEN_MAX_SLIDES", cls.max_slides),
            max_sections=_env_int("COMMON_FILE_GEN_MAX_SECTIONS", cls.max_sections),
            max_sheets=_env_int("COMMON_FILE_GEN_MAX_SHEETS", cls.max_sheets),
            max_rows=_env_int("COMMON_FILE_GEN_MAX_ROWS", cls.max_rows),
            max_cols=_env_int("COMMON_FILE_GEN_MAX_COLS", cls.max_cols),
            max_blocks_per_section=_env_int(
                "COMMON_FILE_GEN_MAX_BLOCKS_PER_SECTION",
                cls.max_blocks_per_section,
            ),
            max_cost=_env_int("COMMON_FILE_GEN_MAX_COST", cls.max_cost),
            gen_timeout_s=_env_int("COMMON_FILE_GEN_GEN_TIMEOUT_S", cls.gen_timeout_s),
            max_output_mb=_env_int("COMMON_FILE_GEN_MAX_OUTPUT_MB", cls.max_output_mb),
            max_concurrent=_env_int(
                "COMMON_FILE_GEN_MAX_CONCURRENT", cls.max_concurrent
            ),
            acquire_timeout_s=_env_int(
                "COMMON_FILE_GEN_ACQUIRE_TIMEOUT_S", cls.acquire_timeout_s
            ),
        )


def _complexity(value: object) -> Complexity:
    """Coerce a complexity name/enum to :class:`Complexity`, defaulting to STANDARD."""
    if isinstance(value, Complexity):
        return value
    try:
        return Complexity(value)
    except ValueError:
        return Complexity.STANDARD


def estimate_cost(kind_key: str, params: dict[str, object]) -> int:
    """Estimate the generation cost of a request.

    The cost is a unit-free proxy for how much work/output a request implies, so
    combinations that pass each per-field cap but multiply huge can be rejected
    against a single budget. When a density field is omitted (``None``), the
    per-complexity default the core would pick is used so the estimate reflects
    the file actually produced.

    - **deck**: ``slides``
    - **doc / pdf / markdown**: ``sections * blocks_per_section``
    - **sheet**: ``sheets * tables_per_sheet * rows * cols``
    """
    level = _complexity(params.get("complexity"))

    if kind_key == "deck":
        return int(params.get("slides") or 0)

    if kind_key in ("doc", "pdf", "markdown"):
        sections = int(params.get("sections") or 0)
        blocks = params.get("blocks_per_section")
        blocks = int(blocks) if blocks is not None else _DEFAULT_BLOCKS[level]
        return sections * blocks

    if kind_key == "sheet":
        sheets = int(params.get("sheets") or 0)
        rows = params.get("rows")
        rows = int(rows) if rows is not None else _DEFAULT_SHEET_ROWS[level]
        cols = params.get("cols")
        cols = int(cols) if cols is not None else _DEFAULT_SHEET_COLS
        return sheets * _TABLES_PER_SHEET[level] * rows * cols

    return 0
