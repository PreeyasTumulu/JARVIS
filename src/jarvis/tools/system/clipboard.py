"""Clipboard tools. What the user copied can be anything, so reading it is private and untrusted.

The history (ADR-077) is off until you turn it on, stays in memory, is emptied when the PC locks,
and leaves out what looks like a secret and what the copying app asked not to have recorded.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import Any

from jarvis.config import ClipboardSettings
from jarvis.platform import clipboard
from jarvis.platform.windows import session_locked
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.secrets import hide_secrets, redact_secrets

log = logging.getLogger(__name__)

PREVIEW_CHARS = 200
TURNED_OFF = (
    "Clipboard history is off. Tell the user to set history = true under [clipboard] in "
    "config/local.toml and restart Jarvis."
)


class ClipboardHistory:
    """What was copied while Jarvis ran, newest first, in memory only."""

    def __init__(
        self,
        settings: ClipboardSettings,
        *,
        sequence: Callable[[], int] = clipboard.sequence_number,
        read: Callable[[], str | None] = clipboard.get_text_for_history,
        locked: Callable[[], bool] = session_locked,
    ) -> None:
        self._settings = settings
        self._sequence = sequence
        self._read = read
        self._locked = locked
        self._seen = sequence()  # what was on the clipboard before Jarvis started is not kept
        self.items: deque[str] = deque(maxlen=settings.max_items)

    def check(self) -> None:
        """One look. Blocking: the clipboard is only opened when it has changed."""
        try:
            locked = self._locked()
        except OSError:
            locked = True  # unknown: keep nothing new, and never guess that it is safe
        if locked:
            self.items.clear()
            self._seen = self._sequence()
            return
        sequence = self._sequence()
        if sequence == self._seen:
            return
        self._seen = sequence
        text = self._read()
        if not text or not text.strip() or len(text) > self._settings.max_chars:
            return
        if redact_secrets(text)[1]:
            return
        if text in self.items:
            self.items.remove(text)
        self.items.appendleft(text)

    async def run(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.check)
            except OSError as exc:
                log.info("Could not look at the clipboard: %s", exc)  # busy in another app
            await asyncio.sleep(self._settings.poll_s)


def _history(ctx: ToolContext) -> ClipboardHistory:
    history = ctx.services.clipboard
    if history is None:
        raise ToolError(TURNED_OFF)
    return history


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=5)
async def clipboard_read(ctx: ToolContext) -> ToolResult:
    """Read the text the user copied, for example to explain, summarize, or translate it."""
    try:
        text = await asyncio.to_thread(clipboard.get_text)
    except OSError as exc:
        raise ToolError(str(exc)) from exc
    if not text or not text.strip():
        raise ToolError("The clipboard has no text on it.")
    limit = ctx.settings.files.read_max_chars
    data: dict[str, Any] = {"text": text[:limit], "chars": len(text)}
    if len(text) > limit:
        data["truncated"] = True
    return ToolResult.success(data=hide_secrets(data, "text"))


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=5)
async def clipboard_write(ctx: ToolContext, text: str) -> ToolResult:
    """Copy text to the clipboard so the user can paste it somewhere.

    Args:
        text: The exact text to copy.
    """
    try:
        await asyncio.to_thread(clipboard.set_text, text)
    except OSError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult.success(data={"copied_chars": len(text)}, speech="Copied.")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=5)
async def clipboard_history(ctx: ToolContext, count: int = 5) -> ToolResult:
    """List what the user copied recently, newest first, for "what did I copy earlier".

    Args:
        count: How many to list, for example 5.
    """
    items = list(_history(ctx).items)[: max(1, min(count, 20))]
    if not items:
        return ToolResult.success(data=[], speech="I have nothing in the clipboard history yet.")
    return ToolResult.success(
        data=[
            {"position": number, "text": text[:PREVIEW_CHARS], "chars": len(text)}
            for number, text in enumerate(items, 1)
        ]
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def clipboard_restore(ctx: ToolContext, position: int = 2) -> ToolResult:
    """Put something copied earlier back on the clipboard, ready to paste, for "the second last
    thing I copied". The user pastes it themselves.

    Args:
        position: Which one, counting back: 1 is the latest, 2 the one before it.
    """
    items = _history(ctx).items
    if not 1 <= position <= len(items):
        raise ToolError(f"I only have {len(items)} things in the clipboard history.")
    try:
        await asyncio.to_thread(clipboard.set_text, items[position - 1], private=True)
    except OSError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult.success(
        data={"position": position},
        speech="It's on the clipboard. Press Control V to paste it.",
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=5)
async def clipboard_forget(ctx: ToolContext) -> ToolResult:
    """Empty the clipboard history, for "forget what I copied"."""
    _history(ctx).items.clear()
    return ToolResult.success(data={"cleared": True}, speech="Clipboard history cleared.")
