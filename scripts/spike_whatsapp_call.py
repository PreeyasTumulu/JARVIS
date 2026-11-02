"""Phase 17 feasibility spike: can Jarvis see WhatsApp desktop's call buttons?

Read-only: it presses nothing and places no call. Open any chat in WhatsApp first.

Privacy: chat lists and messages also appear in the UI Automation tree, so only words on a fixed
list are printed. Every other word becomes "*".

Run:

    uv run python scripts/spike_whatsapp_call.py
"""

from __future__ import annotations

import re
from collections import Counter

from jarvis.platform import uia
from jarvis.platform import windows as win

VOCABULARY = set(
    [
        "voice",
        "video",
        "audio",
        "call",
        "calls",
        "start",
        "new",
        "end",
        "hang",
        "up",
        "mute",
        "unmute",
        "leave",
        "missed",
        "incoming",
        "outgoing",
        "group",
        "link",
        "schedule",
        "with",
        "to",
        "the",
        "a",
        "from",
    ]
)


def main() -> None:
    windows = [w for w in win.list_windows() if w.exe.casefold().startswith("whatsapp")]
    print(f"WhatsApp windows: {len(windows)}")
    for window in windows:
        walked = uia._walk(window.hwnd)
        kinds = Counter(c.kind for _e, c, _t in walked if c is not None)
        print(f"elements: {len(walked)}, usable controls: {dict(kinds)}")
        shapes: Counter[str] = Counter()
        for _element, control, _text in walked:
            if control is None or "call" not in control.name.casefold():
                continue
            shapes[f"{control.kind}: {masked(control.name)} enabled={control.enabled}"] += 1
        for shape, count in sorted(shapes.items()):
            print(f"  {count} x {shape}")


def masked(name: str) -> str:
    """The name with every word off the list hidden, so a contact or a message never prints."""
    words = (w if w.casefold().strip(".,:") in VOCABULARY else "*" for w in name.split())
    return re.sub(r"(\* ?)+", "* ", " ".join(words)).strip()[:60]


if __name__ == "__main__":
    main()
