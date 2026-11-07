"""Record docs/demo.gif from ui-demos/chat.html: typing, a confirmation, a reply, a spoken turn.

Playwright (with Edge, Brave, or its own Chromium) plays the page and takes a frame about ten
times a second; Pillow turns the frames into a looping GIF. No other software is needed.

    uv run python scripts/make_demo_gif.py
"""

from __future__ import annotations

import argparse
import io
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import Error, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui-demos" / "chat.html"
FRAME_S = 0.1


class Recorder:
    def __init__(self, page: Page, scale: float) -> None:
        self.page = page
        self.scale = scale
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []
        self._last = time.perf_counter()

    def frame(self) -> None:
        shot = Image.open(io.BytesIO(self.page.screenshot(type="png")))
        if self.scale != 1:
            shot = shot.resize(
                (round(shot.width * self.scale), round(shot.height * self.scale)), Image.LANCZOS
            )
        now = time.perf_counter()
        if self.frames:
            self.durations.append(max(40, round((now - self._last) * 1000)))
        self._last = now
        self.frames.append(shot.convert("RGB"))

    def hold(self, seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            started = time.perf_counter()
            self.frame()
            time.sleep(max(0.0, FRAME_S - (time.perf_counter() - started)))

    def type(self, text: str) -> None:
        for i, char in enumerate(text):
            self.page.keyboard.type(char)
            if i % 2:
                self.frame()

    def save(self, path: Path, colors: int) -> None:
        self.durations.append(1600)  # rest on the last frame before the loop starts again
        # One palette from frames across the whole run, so every state keeps its colours.
        picks = self.frames[:: max(1, len(self.frames) // 12)]
        w, h = picks[0].size
        montage = Image.new("RGB", (w, h * len(picks)))
        for i, frame in enumerate(picks):
            montage.paste(frame, (0, i * h))
        palette = montage.quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in self.frames]
        frames[0].save(
            path,
            save_all=True,
            append_images=frames[1:],
            duration=self.durations,
            loop=0,
            optimize=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "demo.gif")
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=560)
    parser.add_argument("--scale", type=float, default=0.72)
    parser.add_argument("--colors", type=int, default=128)
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    args = parser.parse_args()
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
        page = browser.new_page(
            viewport={"width": args.width, "height": args.height}, color_scheme=args.theme
        )
        page.goto(PAGE.as_uri())
        page.add_style_tag(content="#dock { display: none !important; }")  # the demo's own controls
        rec = Recorder(page, args.scale)
        rec.hold(1.4)
        page.click("#text")
        rec.type("send the clipboard to my phone")
        rec.hold(0.4)
        page.keyboard.press("Enter")
        rec.hold(2.2)  # thinking, then the confirmation card
        page.click(".card .yes")
        rec.hold(4.4)  # running the tool, then the reply word by word
        page.click("#mic")
        rec.hold(6.0)  # your words as you speak, then the reply
        page.click("#new-chat")
        rec.hold(1.4)  # the orb glides back to the middle
        browser.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rec.save(args.out, args.colors)
    size = args.out.stat().st_size / 1_000_000
    print(f"wrote {args.out.relative_to(ROOT)}: {len(rec.frames)} frames, {size:.1f} MB")


if __name__ == "__main__":
    main()
