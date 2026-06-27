"""Command-line entry point: a thin wrapper over the core library.

Modes:

* ``fill`` - inject JSON data into a Golden template (template-driven).
* ``deck`` / ``doc`` / ``sheet`` / ``pdf`` / ``markdown`` - generate a file from
  scratch at a chosen complexity level (generate mode; the common "give me an
  N-slide deck / N-section document" case).

All real work lives in the core library so the UI (see ADR-001) can reuse it
unchanged.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from common_file_generator.core import (
    DEFAULT_VIDEO_URL,
    Complexity,
    ConfigError,
    generate,
    generate_deck,
    generate_doc,
    generate_markdown,
    generate_pdf,
    generate_sheet,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate",
        description="Produce test files by injection or generation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fill = sub.add_parser(
        "fill", help="Inject JSON data into a Golden template (.pptx/.docx/.xlsx)."
    )
    fill.add_argument("--template", required=True, type=Path)
    fill.add_argument("--config", required=True, type=Path)
    fill.add_argument("--out", required=True, type=Path)
    fill.add_argument("--report", type=Path, default=None)
    fill.add_argument("-v", "--verbose", action="store_true")
    fill.set_defaults(func=_run_fill)

    deck = sub.add_parser(
        "deck", help="Generate a complex PowerPoint deck from scratch."
    )
    deck.add_argument("--out", required=True, type=Path)
    deck.add_argument(
        "--complexity",
        choices=[level.value for level in Complexity],
        default=Complexity.STANDARD.value,
    )
    deck.add_argument("--slides", type=int, default=10)
    deck.add_argument("--seed", type=int, default=0)
    deck.add_argument(
        "--video-url",
        default=DEFAULT_VIDEO_URL,
        help="YouTube URL used on video slides.",
    )
    deck.add_argument(
        "--theme",
        type=Path,
        default=None,
        help="Designed .pptx whose master/layouts are used as the base.",
    )
    deck.add_argument(
        "--background",
        choices=["none", "theme", "random"],
        default="none",
        help="Slide background: none (white), theme (one tint), random (per slide).",
    )
    deck.add_argument(
        "--background-color",
        default=None,
        help="Explicit background hex (e.g. EAF2F8); overrides --background.",
    )
    deck.add_argument("-v", "--verbose", action="store_true")
    deck.set_defaults(func=_run_deck)

    doc = _add_section_parser(
        sub, "doc", "Generate a complex Word document from scratch."
    )
    doc.set_defaults(func=_run_doc)

    pdf = _add_section_parser(
        sub, "pdf", "Generate a complex PDF document from scratch."
    )
    pdf.set_defaults(func=_run_pdf)

    markdown = _add_section_parser(
        sub,
        "markdown",
        "Generate a complex Markdown document from scratch.",
        aliases=["md"],
    )
    markdown.set_defaults(func=_run_markdown)

    sheet = sub.add_parser(
        "sheet", help="Generate a complex Excel workbook from scratch."
    )
    sheet.add_argument("--out", required=True, type=Path)
    sheet.add_argument(
        "--complexity",
        choices=[level.value for level in Complexity],
        default=Complexity.STANDARD.value,
    )
    sheet.add_argument("--sheets", type=int, default=3)
    sheet.add_argument("--seed", type=int, default=0)
    sheet.add_argument(
        "--rows",
        type=int,
        default=None,
        help="Rows per table (default scales with complexity).",
    )
    sheet.add_argument(
        "--cols",
        type=int,
        default=None,
        help="Columns per table including label and date (default 3-5 random).",
    )
    sheet.add_argument("-v", "--verbose", action="store_true")
    sheet.set_defaults(func=_run_sheet)

    return parser


def _add_section_parser(
    sub: argparse._SubParsersAction,
    name: str,
    help_text: str,
    *,
    aliases: list[str] | None = None,
) -> argparse.ArgumentParser:
    """Add a section-based generate subparser (out/complexity/sections/seed).

    Word, PDF, and Markdown generate the same way - a series of sections at a
    chosen complexity - so they share one argument shape.
    """
    parser = sub.add_parser(name, help=help_text, aliases=aliases or [])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--complexity",
        choices=[level.value for level in Complexity],
        default=Complexity.STANDARD.value,
    )
    parser.add_argument("--sections", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--blocks-per-section",
        type=int,
        default=None,
        help="Content blocks per section (default scales with complexity).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _run_fill(args: argparse.Namespace) -> int:
    try:
        report = generate(
            template=args.template,
            config=args.config,
            out=args.out,
            report_path=args.report,
        )
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"Could not generate the file: {exc}", file=sys.stderr)
        return 2

    print(f"Created {args.out}")
    if report.has_problems:
        print(report.render())
        return 1
    print("No issues found.")
    return 0


def _run_deck(args: argparse.Namespace) -> int:
    try:
        out = generate_deck(
            str(args.out),
            complexity=args.complexity,
            slides=args.slides,
            seed=args.seed,
            video_url=args.video_url,
            theme_path=str(args.theme) if args.theme else None,
            background=args.background,
            background_color=args.background_color,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"Could not generate the deck: {exc}", file=sys.stderr)
        return 2
    print(f"Created {out} ({args.slides} slides, {args.complexity} complexity).")
    return 0


def _run_doc(args: argparse.Namespace) -> int:
    try:
        out = generate_doc(
            str(args.out),
            complexity=args.complexity,
            sections=args.sections,
            seed=args.seed,
            blocks_per_section=args.blocks_per_section,
        )
    except ValueError as exc:
        print(f"Could not generate the document: {exc}", file=sys.stderr)
        return 2
    print(f"Created {out} ({args.sections} sections, {args.complexity} complexity).")
    return 0


def _run_pdf(args: argparse.Namespace) -> int:
    try:
        out = generate_pdf(
            str(args.out),
            complexity=args.complexity,
            sections=args.sections,
            seed=args.seed,
            blocks_per_section=args.blocks_per_section,
        )
    except ValueError as exc:
        print(f"Could not generate the PDF: {exc}", file=sys.stderr)
        return 2
    print(f"Created {out} ({args.sections} sections, {args.complexity} complexity).")
    return 0


def _run_markdown(args: argparse.Namespace) -> int:
    try:
        out = generate_markdown(
            str(args.out),
            complexity=args.complexity,
            sections=args.sections,
            seed=args.seed,
            blocks_per_section=args.blocks_per_section,
        )
    except ValueError as exc:
        print(f"Could not generate the Markdown document: {exc}", file=sys.stderr)
        return 2
    print(f"Created {out} ({args.sections} sections, {args.complexity} complexity).")
    return 0


def _run_sheet(args: argparse.Namespace) -> int:
    try:
        out = generate_sheet(
            str(args.out),
            complexity=args.complexity,
            sheets=args.sheets,
            seed=args.seed,
            rows=args.rows,
            cols=args.cols,
        )
    except ValueError as exc:
        print(f"Could not generate the workbook: {exc}", file=sys.stderr)
        return 2
    print(f"Created {out} ({args.sheets} sheets, {args.complexity} complexity).")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
