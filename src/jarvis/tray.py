"""The tray icon: what Jarvis is doing, and quick controls (open the page, mic, stop, quit).

pystray runs its own Windows message loop on its own thread. Menu clicks arrive there, so every
action is handed to the asyncio loop with `run_coroutine_threadsafe` or `call_soon_threadsafe`;
state changes come from the event bus and only swap the icon image and tooltip.
"""

from __future__ import annotations

import asyncio
import logging
import webbrowser
from collections.abc import Callable, Coroutine
from typing import Any

from PIL import Image, ImageDraw

from jarvis.core.events import Event, VoiceStateChanged

log = logging.getLogger(__name__)

SIZE = 64
COLORS = {
    "idle": "#4f5bd5",
    "listening": "#c2383a",
    "awaiting_answer": "#c2383a",
    "transcribing": "#a35d00",
    "thinking": "#a35d00",
    "speaking": "#18864b",
    "muted": "#646b7d",
    "off": "#4f5bd5",
    "voice_retry": "#646b7d",
}
LABELS = {
    "idle": "Ready",
    "listening": "Listening",
    "awaiting_answer": "Waiting for your answer",
    "transcribing": "Transcribing",
    "thinking": "Thinking",
    "speaking": "Speaking",
    "muted": "Microphone off",
    "off": "Ready (voice off)",
    "voice_retry": "Voice is not ready yet, retrying",
}


def icon_image(state: str) -> Image.Image:
    """A filled circle in the state's color with a white J."""
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((2, 2, SIZE - 2, SIZE - 2), fill=COLORS.get(state, COLORS["idle"]))
    # A J drawn from strokes, so no font file is needed.
    white = (255, 255, 255, 255)
    draw.line((40, 16, 40, 40), fill=white, width=7)
    draw.arc((18, 28, 42, 50), start=0, end=180, fill=white, width=7)
    return image


class Tray:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        url: Callable[[], str | None],
        stop: Callable[[], Coroutine[Any, Any, None]],
        quit: Callable[[], None],
        set_muted: Callable[[bool], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self._loop = loop
        self._url = url
        self._stop = stop
        self._quit = quit
        self._set_muted = set_muted
        self._state = "idle" if set_muted else "off"
        self._icon: Any = None

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem(
                lambda _item: f"Jarvis: {LABELS.get(self._state, self._state)}", None, enabled=False
            ),
            pystray.MenuItem("Open Jarvis", self._on_open, default=True),
            pystray.MenuItem(
                "Microphone",
                self._on_mic,
                checked=lambda _item: self._state != "muted",
                visible=lambda _item: self._set_muted is not None,
            ),
            pystray.MenuItem("Stop", self._on_stop),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit Jarvis", self._on_quit),
        )
        self._icon = pystray.Icon("jarvis", icon_image(self._state), self._title(), menu)
        self._icon.run_detached()
        log.info("Tray icon shown")

    def attach_voice(self, set_muted: Callable[[bool], Coroutine[Any, Any, None]]) -> None:
        """Voice came up after the tray (it was retried): show the Microphone item."""
        self._set_muted = set_muted

    def close(self) -> None:
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

    def on_event(self, event: Event) -> None:
        """Event bus subscriber (on the asyncio loop)."""
        if isinstance(event, VoiceStateChanged):
            self.show(event.state)

    def show(self, state: str) -> None:
        self._state = state
        if self._icon is not None:
            self._icon.icon = icon_image(state)
            self._icon.title = self._title()
            self._icon.update_menu()

    def _title(self) -> str:
        return f"Jarvis: {LABELS.get(self._state, self._state)}"

    # Menu actions: these run on pystray's thread.

    def _on_open(self, _icon: Any = None, _item: Any = None) -> None:
        url = self._url()
        if url:
            webbrowser.open(url)

    def _on_mic(self, _icon: Any = None, _item: Any = None) -> None:
        if self._set_muted is not None:
            muted = self._state != "muted"
            asyncio.run_coroutine_threadsafe(self._set_muted(muted), self._loop)

    def _on_stop(self, _icon: Any = None, _item: Any = None) -> None:
        asyncio.run_coroutine_threadsafe(self._stop(), self._loop)

    def _on_quit(self, _icon: Any = None, _item: Any = None) -> None:
        self._loop.call_soon_threadsafe(self._quit)
