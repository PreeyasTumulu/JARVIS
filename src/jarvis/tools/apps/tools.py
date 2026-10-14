"""App control tools. Phase 1 has open_app; focus and close arrive in Phase 3."""

from __future__ import annotations

import asyncio
from typing import Any

from jarvis.tools.apps.index import launch
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.policy import app_risk
from jarvis.tools.registry import tool


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def open_app(ctx: ToolContext, name: str) -> ToolResult:
    """Open an installed application on this laptop by name.

    Args:
        name: The app name as the user said it, for example "notepad", "vs code" or "docker".
    """
    entry = await ctx.services.apps.get(name)
    if entry is None:
        raise ToolError(f"{name} is no longer in the app index.")
    await asyncio.to_thread(launch, entry)
    return ToolResult.success(data={"opened": entry.name}, speech=f"Opening {entry.name}.")


@open_app.preparer
async def _prepare_open_app(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    spoken = args["name"]
    match = await ctx.services.apps.match(spoken)
    if match.entry is None:
        if match.candidates:
            closest = ", ".join(name for name, _ in match.candidates[:3])
            raise ToolError(
                f"No installed app clearly matches '{spoken}'. Closest: {closest}. "
                "Ask the user which one they mean."
            )
        raise ToolError(f"No installed app matches '{spoken}'.")
    if match.ambiguous:
        options = " or ".join(name for name, _ in match.candidates[:3])
        raise ToolError(f"'{spoken}' could mean {options}. Ask the user which one.")

    risk, reason = app_risk(match.entry.name, ctx.settings.safety)
    return Prepared(
        args={"name": match.entry.name},
        summary=f"Open {match.entry.name}",
        risk=risk,
        reason=reason,
    )
