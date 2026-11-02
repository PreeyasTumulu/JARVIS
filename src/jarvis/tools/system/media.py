"""Media tools: play, pause, and skip in whatever app is playing, and say what is playing."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from jarvis.platform import media
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

_DONE = {
    "play": "Playing",
    "pause": "Paused",
    "next": "Skipped to the next track",
    "previous": "Back to the previous track",
}


def _in(app: str) -> str:
    return f" in {app}" if app else ""


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=10)
async def media_control(
    ctx: ToolContext, action: Literal["play", "pause", "toggle", "next", "previous"]
) -> ToolResult:
    """Play, pause, or skip the music or video that is playing in any app (Spotify, YouTube in
    the browser, the Media Player), for "pause the music", "next song", or "resume".

    Args:
        action: play (also for resume, unpause, continue), pause (also for stop the music),
            next (skip), previous (go back), or toggle only when the user says play/pause.
    """
    try:
        before = await media.control(action)
    except OSError as exc:
        raise ToolError(f"{exc}.") from exc
    except Exception as exc:  # the media session API missing or broken: the keys still work
        log.warning("Media sessions unavailable (%s); using the media keys", exc)
        before, sessions = None, False
    else:
        sessions = True

    if before is None:
        if sessions and action == "pause":
            return ToolResult.success(
                data={"action": action, "playing": False}, speech="Nothing is playing."
            )
        try:
            await asyncio.to_thread(media.press_media_key, action)
        except OSError as exc:
            raise ToolError(f"I couldn't press the media key ({exc}).") from exc
        done = "Pressed play or pause" if action in ("play", "pause", "toggle") else _DONE[action]
        return ToolResult.success(data={"action": action, "via": "media key"}, speech=f"{done}.")

    done_action = action
    if action == "toggle":
        done_action = "pause" if before.status == "playing" else "play"
    return ToolResult.success(
        data={"action": done_action, "app": before.app, "via": "media session"},
        speech=f"{_DONE[done_action]}{_in(before.app)}.",
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=10)
async def now_playing(ctx: ToolContext) -> ToolResult:
    """Say which song or video is playing and in which app, for "what's playing" or "what song
    is this"."""
    try:
        state = await media.current(details=True)
    except Exception as exc:
        raise ToolError(f"I couldn't ask Windows what is playing ({exc}).") from exc
    if state is None or state.status not in ("playing", "paused"):
        return ToolResult.success(data={"playing": False}, speech="Nothing is playing.")
    what = state.title or "something"
    if state.title and state.artist:
        what = f"{state.title} by {state.artist}"
    verb = "is playing" if state.status == "playing" else "has paused"
    who = state.app or "An app"
    speech = f"{who} {verb} {what}."
    if not state.title:
        speech = f"{who} {verb} something, but it doesn't say what."
    return ToolResult.success(
        data={
            "app": state.app,
            "status": state.status,
            "title": state.title,
            "artist": state.artist,
        },
        speech=speech,
    )
