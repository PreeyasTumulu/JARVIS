"""App control tools: open, focus (switch to), and close apps by spoken name."""

from __future__ import annotations

import asyncio
from typing import Any

from rapidfuzz import fuzz

from jarvis.platform import windows as win
from jarvis.tools.apps.index import AppEntry, launch, looks_unsaved, normalize, title_parts
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.policy import app_risk
from jarvis.tools.registry import tool

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
    await asyncio.to_thread(launch, entry)
    return ToolResult.success(data={"opened": entry.name}, speech=f"Opening {entry.name}.")


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
