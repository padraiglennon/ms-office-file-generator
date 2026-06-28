"""Format-native visual themes for the Word document generator (ADR-012).

Unlike the PPTX :class:`~.theme.Theme`, whose colour fields are
``pptx.dml.color.RGBColor``, these themes use ``docx.shared.RGBColor`` so they
apply directly to python-docx styles and runs. The two theme types stay
independent; nothing here imports the PPTX theme.

The ``ocean`` palette mirrors the PPTX ``OCEAN`` hex values so the two
generators read as the same brand. Because the colour *types* differ, the hexes
are copied, not imported -- a drift test asserts they stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

from docx.shared import RGBColor


def _rgb(hex_value: int) -> RGBColor:
    return RGBColor((hex_value >> 16) & 0xFF, (hex_value >> 8) & 0xFF, hex_value & 0xFF)


@dataclass(frozen=True)
class DocxTheme:
    """A palette + typography used to restyle a Word document's built-in styles."""

    name: str
    heading_color: RGBColor
    body_color: RGBColor
    accent_color: RGBColor
    table_header_fill: RGBColor
    table_header_text: RGBColor
    title_font: str = "Calibri Light"
    body_font: str = "Calibri"


OCEAN = DocxTheme(
    name="ocean",
    # Mirrors the PPTX OCEAN palette (primary / accent / body). Kept in sync by a
    # drift test, since the PPTX values are a different RGBColor type.
    heading_color=_rgb(0x2E86C1),
    body_color=_rgb(0x333333),
    accent_color=_rgb(0x2EB88A),
    table_header_fill=_rgb(0x2E86C1),
    table_header_text=_rgb(0xFFFFFF),
)

SLATE = DocxTheme(
    name="slate",
    # A clear steel-blue, not a near-black charcoal, so the theme reads as
    # distinctly slate-coloured on a plain (table-free) document.
    heading_color=_rgb(0x41698F),
    body_color=_rgb(0x2E2E2E),
    accent_color=_rgb(0x5D7079),
    table_header_fill=_rgb(0x41698F),
    table_header_text=_rgb(0xFFFFFF),
)

SAND = DocxTheme(
    name="sand",
    # A warm terracotta rather than a muddy brown, so sand is obviously distinct
    # from slate and ocean even without a table or quote. The accent matches the
    # heading so the quote text also clears WCAG AA (the older B07B3C did not).
    heading_color=_rgb(0xA85820),
    body_color=_rgb(0x3A2E22),
    accent_color=_rgb(0xA85820),
    table_header_fill=_rgb(0xA85820),
    table_header_text=_rgb(0xFFF6E9),
)

THEMES: dict[str, DocxTheme] = {theme.name: theme for theme in (OCEAN, SLATE, SAND)}

DEFAULT_DOCX_THEME = OCEAN


def resolve_theme(name: str) -> DocxTheme:
    """Return the :class:`DocxTheme` named ``name`` or raise ``ValueError``.

    An unknown name is a user error, not a silent fallback to the default.
    """
    try:
        return THEMES[name]
    except KeyError:
        valid = ", ".join(sorted(THEMES))
        raise ValueError(f"unknown theme '{name}'; choose one of: {valid}") from None
