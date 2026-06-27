"""Pydantic request models for the JSON API (ADR-007).

One model per generate-mode file type, mirroring the matching ``core`` function
signature.

Validation split: **structural** problems (wrong type, unknown ``complexity``)
are rejected by Pydantic as ``422``; **lower value bounds** (counts too small)
are left to the core, which raises ``ValueError`` and surfaces as ``400``. This
keeps the lower-bound errors and their messages identical across the API, the UI,
and the CLI rather than duplicating them here.

**Upper bounds** (ADR-010) are not expressed as Pydantic ``Field(le=)`` here:
the caps are env-configurable per app instance, so they are validated in the API
router against the resolved :class:`~common_file_generator.web.caps.Caps` and also
surface as ``422``.
"""

from __future__ import annotations

from pydantic import BaseModel

from common_file_generator.core import Complexity


class DeckRequest(BaseModel):
    """Parameters for ``POST /api/generate/deck``."""

    complexity: Complexity = Complexity.STANDARD
    slides: int = 10
    seed: int = 0
    video_url: str = ""
    background: str = "none"
    background_color: str | None = None


class DocRequest(BaseModel):
    """Parameters for ``POST /api/generate/doc``."""

    complexity: Complexity = Complexity.STANDARD
    sections: int = 5
    seed: int = 0
    blocks_per_section: int | None = None


class SheetRequest(BaseModel):
    """Parameters for ``POST /api/generate/sheet``."""

    complexity: Complexity = Complexity.STANDARD
    sheets: int = 3
    seed: int = 0
    rows: int | None = None
    cols: int | None = None


class SectionRequest(BaseModel):
    """Parameters for ``POST /api/generate/{pdf,markdown}`` (shared shape)."""

    complexity: Complexity = Complexity.STANDARD
    sections: int = 5
    seed: int = 0
    blocks_per_section: int | None = None
