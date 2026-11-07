"""Open Jarvis's own chat window, for "open Jarvis" (ADR-103)."""

from __future__ import annotations

import asyncio

from jarvis.server.ui import open_window, running_port
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=15)
async def open_chat(ctx: ToolContext) -> ToolResult:
    """Open Jarvis's own chat window, for "open Jarvis", "show Jarvis", or "open the chat"."""
    port = await asyncio.to_thread(running_port, ctx.settings.data_dir)
    if port is None:
        raise ToolError(
            "The chat window comes from jarvis serve, which is not running. Start it with "
            "`uv run jarvis serve`, then say it again."
        )
    browser = await asyncio.to_thread(open_window, port)
    return ToolResult.success(data={"browser": browser}, speech="Opening the chat window.")
