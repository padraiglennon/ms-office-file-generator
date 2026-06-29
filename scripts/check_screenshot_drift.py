"""Warn-only pre-commit guard for UI screenshot drift (ADR-015).

Re-captures the docs UI screenshots headless into a temp dir and pixel-diffs
them against the committed PNGs under ``docs/assets/screenshots/``. Reports any
drift and **always exits 0** - it never blocks a commit. If the browser
toolchain is unavailable (no ``playwright install chromium``, or the ``shots``/
``web`` extras not synced) it prints a skip notice and exits 0.

Wired as a path-scoped ``local`` pre-commit hook: it fires only when a commit
stages UI-affecting files (the web package, the capture script, or the committed
PNGs). On drift it writes per-image diff PNGs to a gitignored temp dir so the
maintainer can see what changed, and nudges them to re-run ``make screenshots``.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from capture_screenshots import _OUT_DIR, _TABS, capture_to
from PIL import Image, ImageChops

# Tolerance for cross-environment rendering noise (font hinting, anti-aliasing,
# GPU). A pixel counts as "changed" only if any channel differs by more than
# _PIXEL_THRESHOLD (0-255); an image has "drifted" only if the share of changed
# pixels exceeds _DIFF_RATIO. Loosen these if a runner proves noisier; tighten
# to catch smaller real changes.
_PIXEL_THRESHOLD = 16
_DIFF_RATIO = 0.01

# Every screenshot capture_screenshots.py writes: the landing page, one per tab,
# and the seeded result view. Kept in sync with that script's capture set.
_EXPECTED = ["ui-home.png", *[fn for _, fn in _TABS], "ui-result.png"]


def _drift_ratio(committed: Path, fresh: Path) -> float:
    """Share of pixels that differ beyond the per-pixel threshold (0.0-1.0).

    A dimension mismatch (a genuinely restructured panel) counts as full drift.
    """
    with Image.open(committed) as a_img, Image.open(fresh) as b_img:
        a = a_img.convert("RGB")
        b = b_img.convert("RGB")
        if a.size != b.size:
            return 1.0
        diff = ImageChops.difference(a, b)
        # Per-pixel max channel difference, thresholded to a 0/255 changed mask.
        mask = diff.convert("L").point(lambda v: 255 if v > _PIXEL_THRESHOLD else 0)
        # histogram()[255] is the count of changed pixels (mask is binary).
        changed = mask.histogram()[255]
        return changed / (mask.width * mask.height)


def _save_diff(committed: Path, fresh: Path, dest: Path) -> None:
    """Write a visual diff highlighting changed regions, for inspection."""
    with Image.open(committed) as a_img, Image.open(fresh) as b_img:
        a = a_img.convert("RGB")
        b = b_img.convert("RGB")
        if a.size != b.size:
            b = b.resize(a.size)
        ImageChops.difference(a, b).save(dest)


def main() -> int:
    fresh_dir = Path(tempfile.mkdtemp(prefix="screenshot-drift-"))
    try:
        capture_to(fresh_dir)
    except Exception as exc:  # noqa: BLE001 - missing browser/extras must not block
        name = type(exc).__name__
        print(
            "screenshot-drift check skipped "
            f"({name}: run `playwright install chromium` and sync the "
            "`shots`+`web` extras to enable it).",
            file=sys.stderr,
        )
        return 0

    drifted: list[tuple[str, float]] = []
    diff_dir = Path(tempfile.mkdtemp(prefix="screenshot-drift-diffs-"))
    for filename in _EXPECTED:
        committed = _OUT_DIR / filename
        fresh = fresh_dir / filename
        if not fresh.exists():
            # Capture didn't produce an expected shot: report rather than hide.
            drifted.append((filename, 1.0))
            continue
        if not committed.exists():
            # New screenshot with no committed baseline - exactly the "forgot to
            # re-capture" case this guard exists to surface.
            drifted.append((filename, 1.0))
            continue
        ratio = _drift_ratio(committed, fresh)
        if ratio > _DIFF_RATIO:
            _save_diff(committed, fresh, diff_dir / filename)
            drifted.append((filename, ratio))

    if drifted:
        print(
            "\nUI screenshot drift detected (warn-only - commit not blocked):",
            file=sys.stderr,
        )
        for filename, ratio in drifted:
            print(f"  - {filename}: {ratio:.1%} of pixels changed", file=sys.stderr)
        print(
            f"\nDiff images written to {diff_dir}\n"
            "Run `make screenshots` to refresh the committed PNGs if the UI "
            "changed intentionally.\n",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
