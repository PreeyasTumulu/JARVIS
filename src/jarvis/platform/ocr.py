"""Reading the screen with Windows' own OCR (Windows.Media.Ocr through pywinrt, ADR-067).

For apps that expose no text to UI Automation (games, some Electron apps, images, remote
desktop), Jarvis captures the window's pixels (mss) and has Windows recognize the text, on
this laptop, with the language packs Windows already has. Each word comes back with its
position on screen, in physical pixels like SendInput's clicks (the process is DPI aware).

A window has to be visible to be read this way: whatever covers it is what gets read, so
callers bring the window to the front first.
"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

DWMWA_EXTENDED_FRAME_BOUNDS = 9
MATCH_SCORE = 80
RIVAL_MARGIN = 3


class OcrError(Exception):
    """Something to tell the user: OCR is not available or the window cannot be captured."""


@dataclass(frozen=True)
class Word:
    text: str
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class Line:
    text: str
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Spot:
    """Where some text was found: its words' combined box, and the text as read."""

    text: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2


Rect = tuple[int, int, int, int]  # left, top, right, bottom


def window_rect(hwnd: int) -> Rect:
    """The window's visible bounds (DWM's, without the invisible resize border)."""
    rect = wintypes.RECT()
    dwm = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if dwm != 0 and not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise OcrError("Windows did not say where that window is.")
    return rect.left, rect.top, rect.right, rect.bottom


def grab(rect: Rect | None) -> tuple[bytes, int, int, int, int]:
    """BGRA pixels of a screen region, or of every screen when rect is None:
    (pixels, width, height, left, top)."""
    import mss

    with mss.mss() as screen:
        if rect is None:
            area = screen.monitors[0]  # all monitors together
        else:
            left, top, right, bottom = rect
            if right - left < 8 or bottom - top < 8:
                raise OcrError("That window is too small to read.")
            area = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        shot = screen.grab(area)
        return bytes(shot.bgra), shot.width, shot.height, int(area["left"]), int(area["top"])


async def recognize(pixels: bytes, width: int, height: int, left: int, top: int) -> list[Line]:
    """Run Windows OCR on BGRA pixels; word boxes are moved to screen coordinates."""
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError(
            "Windows has no OCR language installed. Add English in Settings, Time and "
            "language, Language, with its optical character recognition feature."
        )
    if max(width, height) > OcrEngine.max_image_dimension:
        raise OcrError("The screen is too large to read in one piece.")
    writer = DataWriter()
    writer.write_bytes(pixels)
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, width, height
    )
    result = await engine.recognize_async(bitmap)
    lines = []
    for line in result.lines:
        words = []
        for word in line.words:
            box: Any = word.bounding_rect
            words.append(
                Word(
                    word.text,
                    left + int(box.x),
                    top + int(box.y),
                    int(box.width),
                    int(box.height),
                )
            )
        lines.append(Line(line.text, tuple(words)))
    return lines


async def read(rect: Rect | None) -> list[Line]:
    """The text in a screen region (or every screen), top to bottom."""
    import asyncio

    try:
        pixels, width, height, left, top = await asyncio.to_thread(grab, rect)
    except OcrError:
        raise
    except Exception as exc:  # mss failing (a locked screen, a remote session)
        raise OcrError(f"The screen could not be captured ({exc}).") from exc
    return await recognize(pixels, width, height, left, top)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.casefold()).split())


def find(lines: list[Line], wanted: str) -> tuple[Spot | None, Spot | None]:
    """The best place where the words of `wanted` appear (fuzzy, consecutive words in one
    line), and a close rival if there is one, so callers can ask which was meant."""
    target = _norm(wanted)
    size = max(1, len(target.split()))
    found: list[tuple[float, Spot]] = []
    for line in lines:
        words = list(line.words)
        for span in range(size, min(size + 1, len(words)) + 1):
            for start in range(0, len(words) - span + 1):
                chunk = words[start : start + span]
                text = " ".join(w.text for w in chunk)
                score = fuzz.ratio(_norm(text), target)
                if score >= MATCH_SCORE:
                    found.append(
                        (
                            score,
                            Spot(
                                text,
                                min(w.left for w in chunk),
                                min(w.top for w in chunk),
                                max(w.left + w.width for w in chunk),
                                max(w.top + w.height for w in chunk),
                            ),
                        )
                    )
    if not found:
        return None, None
    found.sort(key=lambda item: -item[0])
    best_score, best = found[0]
    elsewhere = [
        spot
        for score, spot in found[1:]
        if best_score - score <= RIVAL_MARGIN
        and (abs(spot.top - best.top) > 4 or abs(spot.left - best.left) > 4)
    ]
    rival = elsewhere[0] if elsewhere else None
    return best, rival
