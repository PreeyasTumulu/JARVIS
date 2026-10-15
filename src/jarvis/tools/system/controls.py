"""Volume, brightness, lock screen, and screenshot tools."""

from __future__ import annotations

import asyncio
from datetime import datetime

from jarvis.platform import display, volume
from jarvis.platform.com import run_com
from jarvis.platform.known_folders import expand_folder
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool


def _clamp(level: float) -> int:
    return max(0, min(100, round(level)))


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=10)
async def set_volume(
    ctx: ToolContext,
    level: int | None = None,
    change: int | None = None,
    mute: bool | None = None,
) -> ToolResult:
    """Set, raise, lower, mute, or unmute the speaker volume. With no arguments, report it.

    Args:
        level: New volume from 0 to 100, for "volume to 30".
        change: Step in percent, 10 for "louder" and -10 for "quieter".
        mute: true to mute, false to unmute.
    """
    try:
        current, muted = await run_com(volume.get_volume)
        target = None
        if level is not None:
            target = _clamp(level)
        elif change is not None:
            target = _clamp(current + change)
        if mute is None and muted and target:
            mute = False  # asking for a volume means wanting to hear it
        if target is not None or mute is not None:
            current, muted = await run_com(volume.set_volume, target, mute)
    except Exception as exc:
        raise ToolError(f"I couldn't reach the speaker volume control ({exc}).") from exc
    speech = "Muted." if muted else f"The volume is at {current} percent."
    return ToolResult.success(data={"level": current, "muted": muted}, speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=20)
async def set_brightness(
    ctx: ToolContext, level: int | None = None, change: int | None = None
) -> ToolResult:
    """Set, raise, or lower the screen brightness of the laptop's own display.

    Args:
        level: New brightness from 0 to 100, for "brightness to 70".
        change: Step in percent, 10 for "brighter" and -10 for "dimmer".
    """
    try:
        if level is not None:
            now = await asyncio.to_thread(display.set_brightness, _clamp(level))
        else:
            now = await asyncio.to_thread(display.get_brightness)
            if change is not None:
                now = await asyncio.to_thread(display.set_brightness, _clamp(now + change))
    except (OSError, ValueError) as exc:
        raise ToolError(
            "I couldn't change the brightness. It works only for a built-in laptop screen."
        ) from exc
    return ToolResult.success(data={"level": now}, speech=f"Brightness is at {now} percent.")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=5)
async def lock_screen(ctx: ToolContext) -> ToolResult:
    """Lock the laptop, the same as pressing Windows+L."""
    try:
        await asyncio.to_thread(display.lock_workstation)
    except OSError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult.success(data={"locked": True}, speech="Locking.")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def screenshot(ctx: ToolContext) -> ToolResult:
    """Take a screenshot of the whole screen and save it as a picture."""
    folder = expand_folder(ctx.settings.system.screenshot_folder)
    path = folder / f"Jarvis {datetime.now():%Y-%m-%d %H-%M-%S}.png"
    try:
        width, height = await asyncio.to_thread(display.capture_screen, path)
    except Exception as exc:
        raise ToolError(f"The screenshot failed ({type(exc).__name__}).") from exc
    return ToolResult.success(
        data={"path": str(path), "width": width, "height": height},
        speech=f"Screenshot saved in your {folder.name} folder.",
    )
