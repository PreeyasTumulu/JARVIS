"""Global hotkeys through the Win32 RegisterHotKey API: no keyboard hooks and no admin rights.

RegisterHotKey only reports key presses, so for hold-to-talk the listener polls the main key with
GetAsyncKeyState until it is released and then reports "up". Registered combinations are taken
over system wide while Jarvis runs, so pick ones no other app needs.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "backspace": 0x08,
    "pause": 0x13,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
}

HotkeyCallback = Callable[[str, str], None]  # (binding name, "down" or "up")


@dataclass(frozen=True)
class Hotkey:
    text: str
    modifiers: int
    vk: int


def parse_hotkey(text: str) -> Hotkey:
    """Parse "ctrl+alt+space" style text. Exactly one non-modifier key is required."""
    parts = [part.strip().casefold() for part in text.split("+") if part.strip()]
    modifiers = 0
    keys: list[int] = []
    for part in parts:
        if part in MODIFIERS:
            modifiers |= MODIFIERS[part]
        elif part in _NAMED_KEYS:
            keys.append(_NAMED_KEYS[part])
        elif len(part) == 1 and part.isalnum():
            keys.append(ord(part.upper()))
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            keys.append(0x70 + int(part[1:]) - 1)
        else:
            raise ValueError(f"Unknown key '{part}' in hotkey '{text}'")
    if len(keys) != 1:
        raise ValueError(f"Hotkey '{text}' needs exactly one non-modifier key")
    return Hotkey(text=text, modifiers=modifiers, vk=keys[0])


class HotkeyListener:
    """Runs a Win32 message loop on its own thread and reports hotkey presses (and releases)."""

    def __init__(
        self,
        bindings: dict[str, Hotkey],
        callback: HotkeyCallback,
        *,
        hold: set[str] | None = None,
    ) -> None:
        self._bindings = bindings
        self._callback = callback
        self._hold = hold or set()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.failed: list[
            str
        ] = []  # bindings Windows refused, usually because another app owns them

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="jarvis-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        ids: dict[int, str] = {}
        for number, (name, hotkey) in enumerate(self._bindings.items(), start=1):
            if user32.RegisterHotKey(None, number, hotkey.modifiers | MOD_NOREPEAT, hotkey.vk):
                ids[number] = name
            else:
                self.failed.append(name)
                log.warning("Could not register hotkey %s (%s)", name, hotkey.text)
        self._ready.set()

        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != WM_HOTKEY or msg.wParam not in ids:
                    continue
                name = ids[msg.wParam]
                self._emit(name, "down")
                if name in self._hold:
                    vk = self._bindings[name].vk
                    while user32.GetAsyncKeyState(vk) & 0x8000:
                        time.sleep(0.02)
                    self._emit(name, "up")
        finally:
            for number in ids:
                user32.UnregisterHotKey(None, number)

    def _emit(self, name: str, phase: str) -> None:
        try:
            self._callback(name, phase)
        except Exception:
            log.exception("Hotkey callback failed for %s", name)
