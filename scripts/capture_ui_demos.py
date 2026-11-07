"""Screenshots of every UI demo in its main states, for ui-demos/README.md and the README.

Each page is opened from disk with `?state=<name>&still`, which freezes one frame, so the
pictures come out the same every run. Uses Playwright with Edge (or Brave, or Playwright's
own Chromium), the same browsers Jarvis's browser tools use.

    uv run python scripts/capture_ui_demos.py            # the README set
    uv run python scripts/capture_ui_demos.py --all      # every state, for checking by eye
    uv run python scripts/capture_ui_demos.py --width 390 --height 844 --out <folder>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Error, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEMOS = ROOT / "ui-demos"
README_STATES = ("listening", "thinking", "confirm", "speaking")
ALL_STATES = ("idle", "listening", "thinking", "speaking", "confirm", "tool", "error")


def pages() -> list[Path]:
    return sorted(p for p in DEMOS.glob("*.html") if p.name != "index.html")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="every state, not only the README set")
    parser.add_argument("--width", type=int, default=1000)
    parser.add_argument("--height", type=int, default=625)
    parser.add_argument("--out", type=Path, default=DEMOS / "screenshots")
    args = parser.parse_args()
    states = ALL_STATES if args.all else README_STATES
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = None
        for channel in ("msedge", "brave", None):
            try:
                browser = pw.chromium.launch(channel=channel) if channel else pw.chromium.launch()
                break
            except Error:
                continue
        if browser is None:
            raise SystemExit(
                "No browser: install Edge, or run `uv run playwright install chromium`."
            )
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        for demo in pages():
            for state in states:
                page.goto(f"{demo.as_uri()}?state={state}&still")
                page.wait_for_timeout(250)  # a few frames, so blurs and fonts settle
                target = args.out / f"{demo.stem}-{state}.jpg"
                page.screenshot(path=str(target), type="jpeg", quality=84)
                shown = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target
                print(f"wrote {shown}")
        browser.close()


if __name__ == "__main__":
    main()
