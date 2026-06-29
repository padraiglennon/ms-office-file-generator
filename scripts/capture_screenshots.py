"""Capture web-UI screenshots for the docs site (ADR-014).

Launches the ``gen-ui`` server on an ephemeral localhost port, drives it with
headless Chromium via Playwright, and writes deterministic PNGs into
``docs/assets/screenshots/``. Re-runnable: same inputs (fixed seed, fixed
viewport) yield visually stable images, so diffs stay meaningful.

Run via ``make screenshots`` (needs the ``docs`` + ``web`` extras and a one-time
``playwright install chromium``). Not run in CI - the PNGs are committed and the
CI docs build only embeds them.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO_ROOT / "docs" / "assets" / "screenshots"
_HOST = "127.0.0.1"
_STARTUP_TIMEOUT_S = 30

# Fixed inputs keep the screenshots deterministic: same viewport and same seeded
# generation each run, so diffs only move when the UI genuinely changes. Bump
# these (and re-run `make screenshots`) to refresh the look intentionally.
_VIEWPORT = {"width": 1280, "height": 1000}
_DEMO_SEED = "7"
_DEMO_SLIDES = "10"

# (tab id suffix, output filename). The deck tab is the default panel; the rest
# are reached by clicking their tab. Selectors match index.html (#tab-* / #panel-*).
_TABS = [
    ("deck", "ui-deck.png"),
    ("doc", "ui-doc.png"),
    ("sheet", "ui-sheet.png"),
    ("pdf", "ui-pdf.png"),
    ("md", "ui-md.png"),
    ("fill", "ui-fill.png"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return sock.getsockname()[1]


def _wait_for_health(base_url: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"gen-ui exited early with code {proc.returncode}")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.25)
    raise RuntimeError(f"gen-ui did not become healthy within {_STARTUP_TIMEOUT_S}s")


def _capture(base_url: str, out_dir: Path) -> None:
    # Imported lazily so the module loads without the browser toolchain - the
    # drift-check hook (ADR-015) imports this module to reuse capture_to() and
    # must be able to skip cleanly when Playwright/Chromium aren't installed.
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=_VIEWPORT)
        page.goto(base_url, wait_until="networkidle")

        # Landing page (deck tab is active by default).
        page.screenshot(path=str(out_dir / "ui-home.png"))

        for suffix, filename in _TABS:
            page.click(f"#tab-{suffix}")
            page.wait_for_selector(f"#panel-{suffix}:not([hidden])")
            page.screenshot(path=str(out_dir / filename))

        # Drive one seeded deck generation and capture the result partial.
        page.click("#tab-deck")
        page.wait_for_selector("#panel-deck:not([hidden])")
        page.fill("#panel-deck input[name='seed']", _DEMO_SEED)
        page.fill("#panel-deck input[name='slides']", _DEMO_SLIDES)
        page.click("#panel-deck button[type='submit']")
        # HTMX swaps the download partial into #deck-result; wait for the link.
        page.wait_for_selector("#deck-result a", timeout=15_000)
        page.screenshot(path=str(out_dir / "ui-result.png"))

        browser.close()


def capture_to(out_dir: Path) -> None:
    """Start gen-ui, capture all screenshots into ``out_dir``, tear it down.

    Shared by ``make screenshots`` (writing the committed PNGs) and the
    drift-check hook (capturing into a temp dir to diff). Capture inputs are
    fixed (seed, viewport), so the same UI yields the same images.
    """
    port = _free_port()
    base_url = f"http://{_HOST}:{port}"
    proc = subprocess.Popen(
        ["uv", "run", "gen-ui", "--host", _HOST, "--port", str(port)],
        cwd=_REPO_ROOT,
    )
    try:
        _wait_for_health(base_url, proc)
        _capture(base_url, out_dir)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    capture_to(_OUT_DIR)
    print(f"Wrote screenshots to {_OUT_DIR.relative_to(_REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
