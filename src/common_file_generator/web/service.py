"""Shared generation service for both front-ends (ADR-007).

The API streams bytes; the UI writes a temp file it serves under a token. Both
need the same mapping of "kind" -> (core generator, MIME type, download name)
and the same "run the core into a file" step. That common seam lives here so the
orchestration is not duplicated across the JSON API routes and the HTMX form
routes.

The core generators write to a path (they build on disk), so generation always
goes through a temp file. ``generate_to_path`` is what the UI uses (it keeps the
file to serve later); ``generate_bytes`` wraps it for the API (read the bytes,
drop the file).

Both front-ends run generation through :func:`run_guarded`, which applies the
ADR-010 runtime guards: a wall-clock **timeout** (generation runs in a worker
thread the caller joins with a deadline) and an **output-size** cap. These guard
the work the per-request count caps cannot bound -- pathological CPU and the
``fill`` path -- and apply uniformly to API and UI, generate and fill.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from common_file_generator.core import (
    generate_deck,
    generate_doc,
    generate_markdown,
    generate_pdf,
    generate_sheet,
)
from common_file_generator.web.caps import Caps

_OFFICE = "application/vnd.openxmlformats-officedocument"


class GenerationTimeout(Exception):
    """Generation exceeded the configured wall-clock budget (ADR-010)."""


class OutputTooLarge(Exception):
    """A generated file exceeded the configured output-size cap (ADR-010)."""


@dataclass(frozen=True)
class FileKind:
    """How one generated file type is produced and presented.

    ``builder`` is the core generate function; ``params`` are the keyword
    parameters it accepts beyond ``out`` (used to filter request fields). The
    MIME type and download filename are fixed per kind.
    """

    key: str
    builder: Callable[..., str]
    params: tuple[str, ...]
    suffix: str
    media_type: str
    download_name: str


# The five generate-mode file types. ``fill`` is handled separately because it
# takes uploaded files rather than scalar parameters.
_KINDS: dict[str, FileKind] = {
    "deck": FileKind(
        key="deck",
        builder=generate_deck,
        params=(
            "complexity",
            "slides",
            "seed",
            "video_url",
            "background",
            "background_color",
        ),
        suffix=".pptx",
        media_type=f"{_OFFICE}.presentationml.presentation",
        download_name="deck.pptx",
    ),
    "doc": FileKind(
        key="doc",
        builder=generate_doc,
        params=("complexity", "sections", "seed", "blocks_per_section"),
        suffix=".docx",
        media_type=f"{_OFFICE}.wordprocessingml.document",
        download_name="document.docx",
    ),
    "sheet": FileKind(
        key="sheet",
        builder=generate_sheet,
        params=("complexity", "sheets", "seed", "rows", "cols"),
        suffix=".xlsx",
        media_type=f"{_OFFICE}.spreadsheetml.sheet",
        download_name="workbook.xlsx",
    ),
    "pdf": FileKind(
        key="pdf",
        builder=generate_pdf,
        params=("complexity", "sections", "seed", "blocks_per_section"),
        suffix=".pdf",
        media_type="application/pdf",
        download_name="document.pdf",
    ),
    "markdown": FileKind(
        key="markdown",
        builder=generate_markdown,
        params=("complexity", "sections", "seed", "blocks_per_section"),
        suffix=".md",
        media_type="text/markdown",
        download_name="document.md",
    ),
}


def file_kind(key: str) -> FileKind:
    """Return the :class:`FileKind` for ``key`` or raise ``KeyError``."""
    return _KINDS[key]


def run_guarded(work: Callable[[], Path], caps: Caps) -> Path:
    """Run ``work`` under the ADR-010 timeout and output-size guards.

    ``work`` builds a file and returns its path. Generation runs in a daemon
    worker thread the caller joins with ``caps.gen_timeout_s``; on expiry a
    :class:`GenerationTimeout` is raised and the orphaned thread is left to
    drain (the GIL prevents a hard kill in-process; each request builds in its
    own temp dir, ADR-007, so a draining thread cannot corrupt another). After a
    successful build the output is checked against ``caps.max_output_bytes`` and
    :class:`OutputTooLarge` is raised if it overflows.
    """
    result: dict[str, Path] = {}
    error: dict[str, BaseException] = {}

    def _target() -> None:
        try:
            result["path"] = work()
        except BaseException as exc:  # surfaced to the caller after join
            error["exc"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(caps.gen_timeout_s)
    if worker.is_alive():
        raise GenerationTimeout(
            f"Generation exceeded the {caps.gen_timeout_s}s time limit."
        )
    if "exc" in error:
        raise error["exc"]

    path = result["path"]
    size = path.stat().st_size
    if size > caps.max_output_bytes:
        path.unlink(missing_ok=True)
        raise OutputTooLarge(
            f"Generated file ({size // (1024 * 1024)} MB) exceeds the "
            f"{caps.max_output_mb} MB limit."
        )
    return path


def generate_to_path(
    kind: FileKind, out_dir: Path, caps: Caps, **params: object
) -> Path:
    """Generate a ``kind`` file into ``out_dir`` and return its path.

    Only the parameters the builder accepts are passed through; ``None`` values
    are dropped so the core's own defaults apply. Generation runs under the
    ADR-010 runtime guards (:func:`run_guarded`). The UI uses this to keep the
    file for token-based download.
    """
    out = out_dir / f"{kind.key}{kind.suffix}"
    accepted = {
        name: value
        for name, value in params.items()
        if name in kind.params and value is not None
    }

    def _build() -> Path:
        kind.builder(str(out), **accepted)
        return out

    return run_guarded(_build, caps)


def generate_bytes(kind: FileKind, caps: Caps, **params: object) -> bytes:
    """Generate a ``kind`` file and return its bytes, leaving nothing behind.

    The API path: build into a throwaway temp dir, read the bytes, discard the
    directory. No token, no persistence.
    """
    with tempfile.TemporaryDirectory(prefix="cfg-api-") as tmp:
        path = generate_to_path(kind, Path(tmp), caps, **params)
        return path.read_bytes()
