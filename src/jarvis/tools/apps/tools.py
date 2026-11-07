"""App control tools: open, focus (switch to), and close apps by spoken name, now or later.

Opening waits for the app's window and says how long it took (`[apps] open_wait_s`).
`schedule_app` opens or closes an app later ("close Spotify in 20 minutes"); the scheduler
runs it through the policy gate when it falls due (ADR-087).
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Any, Literal

from rapidfuzz import fuzz

from jarvis.platform import windows as win
from jarvis.tools.apps.index import AppEntry, launch, looks_unsaved, normalize, title_parts
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.policy import app_risk
from jarvis.tools.registry import tool
from jarvis.tools.system.reminders import parse_at, spoken_when

ALREADY_OPEN_S = 2.0  # an app that shows no new window this soon was already running

TITLE_MATCH = 90


async def resolve_app(ctx: ToolContext, spoken: str) -> AppEntry:
    """The installed app the user most likely means. Raises ToolError with options if unclear."""
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
    return match.entry


async def app_windows(
    ctx: ToolContext, entry: AppEntry | None, spoken: str
) -> list[win.WindowInfo]:
    """Open windows that belong to the app, front to back."""
    apps = ctx.services.apps
    exe = (apps.process_name(entry, spoken) or "").casefold()
    names = {normalize(n) for n in (spoken, apps.canonical(spoken), entry.name if entry else "")}
    names.discard("")

    def belongs(window: win.WindowInfo) -> bool:
        if exe and window.exe.casefold() == exe:
            return True
        return any(
            fuzz.ratio(part, name) >= TITLE_MATCH
            for part in title_parts(window.title)
            for name in names
        )

    return [w for w in await asyncio.to_thread(win.list_windows) if belongs(w)]


async def maybe_resolve(ctx: ToolContext, spoken: str) -> tuple[AppEntry | None, ToolError | None]:
    """Like resolve_app, but hands back the error instead of raising (the app may still be open
    under a name the index does not know)."""
    try:
        return await resolve_app(ctx, spoken), None
    except ToolError as exc:
        return None, exc


async def start_and_wait(
    ctx: ToolContext, entry: AppEntry, spoken: str, wait_s: float
) -> win.WindowInfo:
    """Start an app and wait for its first window."""
    await asyncio.to_thread(launch, entry)
    for _ in range(max(1, int(wait_s / 0.25))):
        await asyncio.sleep(0.25)
        windows = await app_windows(ctx, entry, spoken)
        if windows:
            return windows[0]
    raise ToolError(f"{entry.name} did not open a window within {wait_s:.0f} seconds.")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def open_app(ctx: ToolContext, name: str) -> ToolResult:
    """Start an installed application program, for example Notepad, VS Code, Docker Desktop,
    or WhatsApp. Not for files, folders, documents, or websites.

    Args:
        name: The app name as the user said it, for example "notepad", "vs code" or "docker".
    """
    entry = await ctx.services.apps.get(name)
    if entry is None:
        raise ToolError(f"{name} is no longer in the app index.")
    before = {w.hwnd for w in await app_windows(ctx, entry, name)}
    started = time.perf_counter()
    await asyncio.to_thread(launch, entry)
    wait_s = ctx.settings.apps.open_wait_s
    while (elapsed := time.perf_counter() - started) < wait_s:
        await asyncio.sleep(0.25)
        windows = await app_windows(ctx, entry, name)
        if any(w.hwnd not in before for w in windows):
            seconds = round(time.perf_counter() - started, 1)
            return ToolResult.success(
                data={"opened": entry.name, "seconds": seconds},
                speech=f"{entry.name} is open, in {seconds:g} seconds.",
            )
        if before and windows and elapsed >= ALREADY_OPEN_S:
            return ToolResult.success(
                data={"opened": entry.name, "already_running": True},
                speech=f"{entry.name} was already open.",
            )
    if wait_s == 0:
        return ToolResult.success(data={"opened": entry.name}, speech=f"Opening {entry.name}.")
    return ToolResult.success(
        data={"opened": entry.name, "seconds": None},
        speech=f"Opening {entry.name}. It has not shown a window after {wait_s:g} seconds.",
    )


@open_app.preparer
async def _prepare_open_app(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    entry = await resolve_app(ctx, args["name"])
    risk, reason = app_risk(entry.name, ctx.settings.safety)
    return Prepared(
        args={"name": entry.name}, summary=f"Open {entry.name}", risk=risk, reason=reason
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def focus_app(ctx: ToolContext, name: str) -> ToolResult:
    """Switch to an app ("switch to", "go to", "bring up"): brings its open window to the front,
    or starts the app if it is not running.

    Args:
        name: The app name as the user said it, for example "vs code" or "whatsapp".
    """
    entry = await ctx.services.apps.get(name)
    windows = await app_windows(ctx, entry, name)
    if windows:
        if await asyncio.to_thread(win.focus_window, windows[0].hwnd):
            return ToolResult.success(
                data={"focused": windows[0].title}, speech=f"Switched to {name}."
            )
        raise ToolError(f"Windows did not let me bring {name} to the front.")
    if entry is None:
        raise ToolError(f"{name} is not open and is not an installed app I can start.")
    await asyncio.to_thread(launch, entry)
    return ToolResult.success(
        data={"opened": entry.name}, speech=f"{entry.name} wasn't open, so I'm opening it."
    )


@focus_app.preparer
async def _prepare_focus_app(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    spoken = args["name"]
    entry, error = await maybe_resolve(ctx, spoken)
    windows = await app_windows(ctx, entry, spoken)
    display = entry.name if entry else spoken
    if windows:
        return Prepared(args={"name": display}, summary=f"Switch to {display}")
    if entry is None:
        raise error or ToolError(f"{spoken} is not open.")
    risk, reason = app_risk(entry.name, ctx.settings.safety)
    return Prepared(
        args={"name": entry.name},
        summary=f"Open {entry.name} (not running)",
        risk=risk,
        reason=reason,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def close_app(ctx: ToolContext, name: str) -> ToolResult:
    """Close an open app (like clicking its X button). Apps still ask about unsaved work.

    Args:
        name: The app name as the user said it, for example "notepad" or "calculator".
    """
    entry = await ctx.services.apps.get(name)
    windows = await app_windows(ctx, entry, name)
    if not windows:
        return ToolResult.success(data={"closed": 0}, speech=f"{name} is already closed.")
    for window in windows:
        await asyncio.to_thread(win.close_window, window.hwnd)
    remaining = windows
    for _ in range(8):  # up to 2 seconds for the windows to go away
        await asyncio.sleep(0.25)
        remaining = await app_windows(ctx, entry, name)
        if not remaining:
            break
    if remaining:
        return ToolResult.success(
            data={
                "closed": len(windows) - len(remaining),
                "still_open": [w.title for w in remaining],
            },
            speech=f"{name} is still open. It may be asking whether to save.",
        )
    return ToolResult.success(data={"closed": len(windows)}, speech=f"Closed {name}.")


@close_app.preparer
async def _prepare_close_app(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    spoken = args["name"]
    entry, error = await maybe_resolve(ctx, spoken)
    windows = await app_windows(ctx, entry, spoken)
    if not windows:
        raise error or ToolError(f"{spoken} does not seem to be open.")
    display = entry.name if entry else spoken
    count = f" ({len(windows)} windows)" if len(windows) > 1 else ""
    unsaved = [w.title for w in windows if looks_unsaved(w.title)]
    safe_list = {n.casefold() for n in ctx.settings.safety.safe_to_close}
    if unsaved:
        risk, reason = Risk.CONFIRM, f"Unsaved changes: {unsaved[0]}"
    elif display.casefold() in safe_list:
        risk, reason = Risk.SAFE, None
    else:
        risk, reason = (
            Risk.CONFIRM,
            "Closing apps asks first unless they are in safety.safe_to_close",
        )
    return Prepared(
        args={"name": display}, summary=f"Close {display}{count}", risk=risk, reason=reason
    )


async def _action_prepared(ctx: ToolContext, action: str, name: str) -> Prepared:
    """What the open or close will be when it runs, rated as if it ran now."""
    if action == "open":
        return await _prepare_open_app(ctx, {"name": name})
    try:
        return await _prepare_close_app(ctx, {"name": name})
    except ToolError:
        entry = await resolve_app(ctx, name)  # not open yet: it may be by then
    safe = entry.name.casefold() in {n.casefold() for n in ctx.settings.safety.safe_to_close}
    return Prepared(
        args={"name": entry.name},
        summary=f"Close {entry.name}",
        risk=Risk.SAFE if safe else Risk.CONFIRM,
        reason=None if safe else "Closing apps asks first unless they are in safety.safe_to_close",
    )


def _due(ctx: ToolContext, in_minutes: float | None, at: str | None) -> float:
    now = ctx.services.reminders.clock()
    if in_minutes is not None:
        if in_minutes <= 0:
            raise ToolError("The time must be in the future.")
        return now + in_minutes * 60
    if at:
        later = _RELATIVE.match(" ".join(at.casefold().split()))
        if later is not None:  # the live test saw at="in 20 minutes"
            minutes = float(later["count"]) * (60 if later["unit"].startswith("h") else 1)
            return now + minutes * 60
        return parse_at(at, datetime.fromtimestamp(now)).timestamp()
    raise ToolError("Ask the user when: in how many minutes, or at what time.")


_RELATIVE = re.compile(
    r"^(?:in\s+)?(?P<count>\d+(?:\.\d+)?)\s*(?P<unit>minutes?|mins?|hours?|hrs?)(?:\s+from now)?$"
)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def schedule_app(
    ctx: ToolContext,
    action: Literal["open", "close"],
    name: str,
    in_minutes: float | None = None,
    at: str | None = None,
) -> ToolResult:
    """Open or close an app later, for "close Spotify in 20 minutes" or "open VS Code at 9".
    For right now, use open_app or close_app.

    Args:
        action: "open" or "close".
        name: The app name as the user said it, for example "spotify".
        in_minutes: Minutes from now, for "in 20 minutes" (an hour is 60).
        at: A clock time, for example "9 am", "17:30", or "tomorrow 9 am".
    """
    reminders = ctx.services.reminders
    due_at = _due(ctx, in_minutes, at)
    inner = await _action_prepared(ctx, action, name)
    # This call ran past the gate, so a confirm-level action has your yes for these exact
    # arguments; the scheduler hands that to the gate when the action runs (ADR-087).
    approved = inner.digest if inner.risk is Risk.CONFIRM else None
    plan = {"tool": f"{action}_app", "args": inner.args, "approved": approved}
    item = reminders.add("app", inner.summary, due_at, plan)
    when = spoken_when(item.due, datetime.fromtimestamp(reminders.clock()))
    note = "" if reminders.running else " Keep Jarvis running for it to happen."
    return ToolResult.success(
        data={"id": item.id, "action": inner.summary, "due": when},
        speech=f"I'll {inner.summary[:1].lower()}{inner.summary[1:]} at {when}.{note}",
    )


@schedule_app.preparer
async def _prepare_schedule_app(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    due_at = _due(ctx, args.get("in_minutes"), args.get("at"))
    inner = await _action_prepared(ctx, args["action"], args["name"])
    when = spoken_when(
        datetime.fromtimestamp(due_at), datetime.fromtimestamp(ctx.services.reminders.clock())
    )
    return Prepared(
        args={**args, "name": inner.args["name"]},
        summary=f"{inner.summary} at {when}",
        risk=inner.risk,
        reason=inner.reason,
    )
