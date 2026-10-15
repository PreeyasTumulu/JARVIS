"""Generic UI automation tools: type, click, press keys, and read a window, in any app.

These are for apps without a dedicated tool. Each call names the app; Jarvis finds its window,
brings it to the front, and checks that it is still in front before every burst of typing, so text
never lands in whatever window you happen to click on meanwhile. Window reading and control lookup
use UI Automation on the COM thread (platform/uia.py); keystrokes use SendInput.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from operator import attrgetter
from typing import Any

from jarvis.platform import sendinput, uia
from jarvis.platform import windows as win
from jarvis.platform.com import run_com
from jarvis.tools.apps.index import AppEntry
from jarvis.tools.apps.tools import app_windows, maybe_resolve, start_and_wait
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.naming import pick
from jarvis.tools.policy import app_risk
from jarvis.tools.registry import tool
from jarvis.tools.ui import guard
from jarvis.tools.ui.keys import describe, parse_keys

CHUNK_CHARS = 24  # focus is re-checked between bursts this long
MAX_TEXT_CHARS = 2000  # typing runs at about 75 characters a second (sendinput.py)
LISTED_CONTROLS = 40
READBACK_DELAY_S = 0.3  # let the app show what was typed before reading it back
FIELD_KINDS = {"field", "document", "combo box"}
PASSWORD_REASON = "that is a password field, and Jarvis never types into those"


@dataclass(frozen=True)
class Target:
    app: str  # display name: the installed app's name, or what the user said
    window: win.WindowInfo | None  # front-most window, None when the app has to be started
    entry: AppEntry | None


async def find_target(ctx: ToolContext, spoken: str, *, may_start: bool) -> Target:
    entry, error = await maybe_resolve(ctx, spoken)
    windows = await app_windows(ctx, entry, spoken)
    display = entry.name if entry else spoken
    if windows:
        return Target(display, windows[0], entry)
    if entry is None:
        raise error or ToolError(f"{spoken} is not open.")
    if not may_start:
        raise ToolError(f"{display} is not open. Open it first with open_app.")
    return Target(display, None, entry)


def ui_rating(ctx: ToolContext, target: Target) -> tuple[Risk, str | None]:
    exe = target.window.exe if target.window else ""
    if not exe and target.entry is not None:
        exe = ctx.services.apps.process_name(target.entry, target.app) or ""
    rating = guard.app_ui_risk(target.app, exe, ctx.settings.safety)
    if target.window is None:
        rating = guard.combine(rating, app_risk(target.app, ctx.settings.safety))
    return rating


async def live_window(ctx: ToolContext, app: str, *, start: bool = False) -> win.WindowInfo:
    """The app's front-most window at run time (it may have changed since the confirmation)."""
    entry = await ctx.services.apps.get(app)
    windows = await app_windows(ctx, entry, app)
    if windows:
        return windows[0]
    if start and entry is not None:
        return await start_and_wait(ctx, entry, app, ctx.settings.ui.window_wait_s)
    raise ToolError(f"{app} is no longer open.")


async def bring_forward(window: win.WindowInfo, app: str) -> None:
    if await asyncio.to_thread(sendinput.is_elevated, window.pid):
        raise ToolError(
            f"{app} is running as administrator, so Windows does not let Jarvis control it."
        )
    if not await asyncio.to_thread(win.focus_window, window.hwnd):
        raise ToolError(f"Windows did not let me bring {app} to the front, so I did nothing.")


async def still_in_front(window: win.WindowInfo, app: str, done: str) -> None:
    if await asyncio.to_thread(win.foreground_window) != window.hwnd:
        raise ToolError(f"{app} stopped being the active window{done}, so I stopped there.")


async def read_controls(ctx: ToolContext, window: win.WindowInfo) -> list[uia.Control]:
    try:
        content, _ = await run_com(uia.read_window, window.hwnd, ctx.settings.ui.read_max_chars)
    except uia.UIAError as exc:
        raise ToolError(str(exc)) from exc
    return content.controls


def match_control(
    controls: list[uia.Control], wanted: str, app: str, *, fields: bool = False
) -> uia.Control:
    """The control the user means by name. Exact names win; otherwise a clear fuzzy best."""
    pool = [c for c in controls if not fields or c.kind in FIELD_KINDS]
    best, rival = pick(wanted, pool, attrgetter("name"))
    if best is None:
        what = "field" if fields else "control"
        some = ", ".join([c.name for c in pool if c.name][:8]) or "nothing with a name"
        raise ToolError(f"There is no {what} called '{wanted}' in {app}. Some that are: {some}.")
    if rival is not None:
        raise ToolError(
            f"'{wanted}' could be the {best.label} or the {rival.label} in {app}. "
            "Ask the user which one."
        )
    return best


def _preview(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=60)
async def type_text(ctx: ToolContext, app: str, text: str, field: str | None = None) -> ToolResult:
    """Type text into an app, for example "type hello world in Notepad". Types at the cursor and
    starts the app if it is not open. It does not press Enter or Send.

    Args:
        app: The app to type in, as the user said it, for example "notepad".
        text: The exact text to type.
        field: Only if the user named one: the box to type in, for example "Search" or "To".
    """
    window = await live_window(ctx, app, start=True)
    await bring_forward(window, app)
    wanted = None
    if field:
        wanted = match_control(await read_controls(ctx, window), field, app, fields=True)
    try:
        target = await run_com(uia.focus_field, window.hwnd, wanted)
    except uia.UIAError as exc:
        raise ToolError(str(exc)) from exc
    if target.password:
        raise ToolError(f"Blocked: {PASSWORD_REASON}.")
    flat = text.replace("\r\n", "\n").replace("\r", "\n")
    for start in range(0, len(flat), CHUNK_CHARS):
        done = f" after {start} characters" if start else ""
        await still_in_front(window, app, done)
        await asyncio.to_thread(sendinput.type_unicode, flat[start : start + CHUNK_CHARS])
    # Read the field back: some apps drop characters (sendinput.py), and saying so beats guessing.
    await asyncio.sleep(READBACK_DELAY_S)
    try:
        now = await run_com(uia.focused_text, window.hwnd)
    except uia.UIAError:
        now = None
    data: dict[str, Any] = {"app": app, "typed_chars": len(flat), "into": target.label}
    if not now:
        data["checked"] = False  # the app does not expose its text
        return ToolResult.success(data=data, speech=f"Typed it in {app}.")
    data["checked"] = True
    if _lines(flat) not in _lines(now):
        data["matches"] = False
        return ToolResult.success(
            data=data,
            speech=f"I typed it in {app}, but the text there doesn't match, so the app may have "
            "dropped some characters. Please check it.",
        )
    return ToolResult.success(data=data, speech=f"Typed it in {app}.")


def _lines(text: str) -> str:
    """Text as apps hand it back: any newline style, no outer whitespace."""
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split())


@type_text.preparer
async def _prepare_type_text(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    text: str = args["text"]
    if not text:
        raise ToolError("There is no text to type.")
    if len(text) > MAX_TEXT_CHARS:
        raise ToolError(f"That is more than {MAX_TEXT_CHARS} characters to type.")
    target = await find_target(ctx, args["app"], may_start=True)
    risk, reason = ui_rating(ctx, target)
    field = args.get("field") or None
    if target.window is not None:
        try:
            if field:
                controls = await read_controls(ctx, target.window)
                spot: uia.Control | None = match_control(controls, field, target.app, fields=True)
            else:
                spot = await run_com(uia.focused_control, target.window.hwnd)
        except uia.UIAError as exc:
            raise ToolError(str(exc)) from exc
        if spot is not None and spot.password:
            risk, reason = Risk.BLOCKED, PASSWORD_REASON
        field = spot.name if field and spot is not None else field
    where = f"the {field} field of {target.app}" if field else target.app
    opening = "" if target.window else f" (opening {target.app} first)"
    return Prepared(
        args={"app": target.app, "text": text, "field": field},
        summary=f'Type "{_preview(text)}" in {where}{opening}',
        risk=risk,
        reason=reason,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def click(ctx: ToolContext, app: str, target: str) -> ToolResult:
    """Click a button, menu, tab, link, or checkbox in an open app by its visible name, for
    example "click File in Notepad". Call read_window_text first if you do not know the names.

    Args:
        app: The app, as the user said it, for example "notepad".
        target: The visible name of what to click, for example "Save" or "File".
    """
    window = await live_window(ctx, app)
    control = match_control(await read_controls(ctx, window), target, app)
    await bring_forward(window, app)
    try:
        how = await run_com(uia.press, window.hwnd, control)
    except uia.UIAError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult.success(
        data={"app": app, "control": control.label, "action": how},
        speech=f"Clicked {control.name}.",
    )


@click.preparer
async def _prepare_click(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await find_target(ctx, args["app"], may_start=False)
    assert found.window is not None
    control = match_control(await read_controls(ctx, found.window), args["target"], found.app)
    risk, reason = guard.combine(ui_rating(ctx, found), guard.target_risk(control.name))
    return Prepared(
        args={"app": found.app, "target": control.name},
        summary=f"Click the {control.label} in {found.app}",
        risk=risk,
        reason=reason,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def press_keys(ctx: ToolContext, app: str, keys: str) -> ToolResult:
    """Press keyboard keys or shortcuts in an open app, for example "ctrl+s", "enter", or
    "ctrl+a, delete".

    Args:
        app: The app, as the user said it, for example "notepad".
        keys: Keys joined with "+" for combinations and commas between presses, e.g. "ctrl+s".
    """
    combos = parse_keys(keys)
    window = await live_window(ctx, app)
    await bring_forward(window, app)
    for index, combo in enumerate(combos):
        await still_in_front(window, app, f" after {index} key presses" if index else "")
        await asyncio.to_thread(sendinput.press_combo, combo.modifier_vks, combo.vk)
    return ToolResult.success(
        data={"app": app, "pressed": describe(combos)}, speech=f"Pressed {describe(combos)}."
    )


@press_keys.preparer
async def _prepare_press_keys(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    combos = parse_keys(args["keys"])
    found = await find_target(ctx, args["app"], may_start=False)
    risk, reason = guard.combine(ui_rating(ctx, found), guard.keys_risk(combos))
    return Prepared(
        args={"app": found.app, "keys": describe(combos)},
        summary=f"Press {describe(combos)} in {found.app}",
        risk=risk,
        reason=reason,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=20)
async def read_window_text(ctx: ToolContext, app: str) -> ToolResult:
    """Read the text and the buttons shown in an open app's window, for example to answer "what
    does Notepad say" or to find what to click.

    Args:
        app: The app, as the user said it, for example "notepad" or "calculator".
    """
    found = await find_target(ctx, app, may_start=False)
    window = found.window
    assert window is not None
    minimized = await asyncio.to_thread(win.is_minimized, window.hwnd)
    try:
        content, truncated = await run_com(
            uia.read_window, window.hwnd, ctx.settings.ui.read_max_chars, not minimized
        )
    except uia.UIAError as exc:
        raise ToolError(str(exc)) from exc
    data: dict[str, Any] = {
        "app": found.app,
        "window": window.title,
        "text": "\n".join(content.lines),
        "controls": [c.label for c in content.controls[:LISTED_CONTROLS]],
    }
    if truncated:
        data["truncated"] = True
    if not content.lines and not content.controls:
        data["note"] = "The window shows no readable text (some apps do not expose any)."
    return ToolResult.success(data=data)


@read_window_text.preparer
async def _prepare_read_window_text(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await find_target(ctx, args["app"], may_start=False)
    exe = found.window.exe if found.window else ""
    if exe.casefold() in guard.BLOCKED:
        return Prepared(
            args={"app": found.app},
            summary=f"Read the {found.app} window",
            risk=Risk.BLOCKED,
            reason=f"reading {guard.BLOCKED[exe.casefold()]} is not allowed",
        )
    return Prepared(args={"app": found.app}, summary=f"Read the {found.app} window")
