"""Clipboard tools. What the user copied can be anything, so reading it is private and untrusted."""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.platform import clipboard
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.secrets import hide_secrets


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
