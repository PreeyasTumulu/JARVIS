"""Parse shortcut text like "ctrl+shift+s" or "alt+f4, enter" into virtual key presses."""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.tools.base import ToolError

MAX_COMBOS = 20

MODIFIERS: dict[str, tuple[str, int]] = {
    "ctrl": ("Ctrl", 0x11),
    "control": ("Ctrl", 0x11),
    "shift": ("Shift", 0x10),
    "alt": ("Alt", 0x12),
}
MODIFIER_ORDER = ("Ctrl", "Shift", "Alt")
# The Windows key reaches the shell, not the app (Win+R opens Run), so it is never sent.
WINDOWS_KEY = {"win", "windows", "super", "meta", "cmd", "start"}

NAMED: dict[str, tuple[str, int]] = {
    "enter": ("Enter", 0x0D),
    "return": ("Enter", 0x0D),
    "tab": ("Tab", 0x09),
    "esc": ("Esc", 0x1B),
    "escape": ("Esc", 0x1B),
    "space": ("Space", 0x20),
    "spacebar": ("Space", 0x20),
    "backspace": ("Backspace", 0x08),
    "delete": ("Delete", 0x2E),
    "del": ("Delete", 0x2E),
    "insert": ("Insert", 0x2D),
    "home": ("Home", 0x24),
    "end": ("End", 0x23),
    "pageup": ("PageUp", 0x21),
    "pgup": ("PageUp", 0x21),
    "pagedown": ("PageDown", 0x22),
    "pgdn": ("PageDown", 0x22),
    "up": ("Up", 0x26),
    "down": ("Down", 0x28),
    "left": ("Left", 0x25),
    "right": ("Right", 0x27),
    "menu": ("Menu", 0x5D),
    "plus": ("Plus", 0xBB),
    "minus": ("Minus", 0xBD),
    "-": ("Minus", 0xBD),
    "=": ("Equals", 0xBB),
    ",": ("Comma", 0xBC),
    "comma": ("Comma", 0xBC),
    ".": ("Period", 0xBE),
    "period": ("Period", 0xBE),
    "/": ("Slash", 0xBF),
    ";": ("Semicolon", 0xBA),
    "'": ("Quote", 0xDE),
    "[": ("[", 0xDB),
    "]": ("]", 0xDD),
    "\\": ("Backslash", 0xDC),
    "`": ("Backtick", 0xC0),
}
NAMED.update({f"f{n}": (f"F{n}", 0x6F + n) for n in range(1, 25)})
NAMED.update({c: (c.upper(), ord(c.upper())) for c in "abcdefghijklmnopqrstuvwxyz0123456789"})

_ALIASES = {"page up": "pageup", "page down": "pagedown", "arrow up": "up", "arrow down": "down"}
_ALIASES |= {"arrow left": "left", "arrow right": "right", "up arrow": "up", "down arrow": "down"}
_ALIASES |= {"left arrow": "left", "right arrow": "right", "control key": "ctrl"}


@dataclass(frozen=True)
class KeyCombo:
    modifiers: tuple[str, ...]  # display names in a fixed order: Ctrl, Shift, Alt
    key: str  # display name, for example "S" or "F4"
    modifier_vks: tuple[int, ...]
    vk: int

    @property
    def label(self) -> str:
        return "+".join((*self.modifiers, self.key))


def parse_keys(text: str) -> list[KeyCombo]:
    """Turn "ctrl+s", "Alt+F4", or "tab tab enter" into key combos. Raises ToolError."""
    lowered = " ".join(text.casefold().split())
    for phrase, word in _ALIASES.items():
        lowered = lowered.replace(phrase, word)
    lowered = re.sub(r"\s*\+\s*", "+", lowered)
    tokens = [token for token in re.split(r"[\s,]+", lowered) if token]
    if not tokens:
        raise ToolError("No keys were given.")
    if len(tokens) > MAX_COMBOS:
        raise ToolError(f"That is more than {MAX_COMBOS} key presses; split it up.")
    return [_combo(token) for token in tokens]


def _combo(token: str) -> KeyCombo:
    if token.endswith("++") or token == "+":  # "ctrl++" is Ctrl and the plus key
        parts = [*filter(None, token[:-2].split("+")), "plus"]
    else:
        parts = token.split("+")
    if "" in parts:
        raise ToolError(f"'{token}' has no key to press with the modifiers.")
    *mods, key = parts
    if any(part in WINDOWS_KEY for part in parts):
        raise ToolError(
            "Shortcuts with the Windows key are not allowed. Use open_app to start apps."
        )
    names: dict[str, int] = {}
    for mod in mods:
        if mod not in MODIFIERS:
            raise ToolError(f"'{mod}' is not a modifier key. Use ctrl, shift, or alt.")
        name, vk = MODIFIERS[mod]
        names[name] = vk
    if key in MODIFIERS:
        raise ToolError(f"'{token}' has no key to press with the modifiers.")
    if key not in NAMED:
        raise ToolError(f"I don't know the key '{key}'.")
    display, vk = NAMED[key]
    ordered = tuple(name for name in MODIFIER_ORDER if name in names)
    return KeyCombo(ordered, display, tuple(names[name] for name in ordered), vk)


def describe(combos: list[KeyCombo]) -> str:
    return ", ".join(combo.label for combo in combos)
