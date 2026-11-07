"""Reach your own phone for free (ADR-098): ring it, notify it, send it a file or a link.

KDE Connect carries everything over your own Wi-Fi. When the phone is away, an ntfy push carries
short alerts; files, the clipboard, and screenshots never leave the Wi-Fi. Ringing and notifying
your own phone run without a question; sending a file, the clipboard, or a screenshot asks
first, because it copies something off the laptop. A notification that would go over the
internet while private data is in the conversation asks first too.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from jarvis.adapters.phone import KDE, NTFY, Device, Phone, PhoneError, clip
from jarvis.platform import display
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.files.tools import locate
from jarvis.tools.registry import tool

MAX_FILE_MB = 200
_LINK = re.compile(r"^https?://\S+$", re.I)
_CLIPBOARD = {"clipboard", "my clipboard", "the clipboard", "what i copied", "copied text"}
_SCREENSHOT = {"screenshot", "a screenshot", "the screen", "my screen", "screen"}

PRIVATE_OVER_INTERNET = (
    "your phone is not on this Wi-Fi, so this goes over the internet through ntfy, and this "
    "conversation holds private data"
)


def _phone(ctx: ToolContext) -> Phone:
    if ctx.services.phone is None:
        raise ToolError("The phone is not set up (SETUP.md 5s).")
    return ctx.services.phone


async def _device(phone: Phone) -> Device:
    device = await phone.device()
    if device is None:
        raise ToolError(await phone.why_not())
    return device


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def ring_phone(ctx: ToolContext) -> ToolResult:
    """Ring the user's own phone loudly, even on silent, for "find my phone" or "ring my
    phone". Never calls anyone else."""
    phone = _phone(ctx)
    device = await phone.device()
    try:
        if device is not None:
            await phone.ring(device)
            return ToolResult.success(
                data={"via": KDE, "device": device.name},
                speech=f"Ringing your {device.name}. Stop it on the phone.",
            )
        if phone.ntfy_ready:
            await phone.push("Jarvis", "Jarvis is trying to reach you.", priority=5)
            return ToolResult.success(
                data={"via": NTFY},
                speech="Your phone is not on this Wi-Fi, so I sent it an urgent push instead.",
            )
    except PhoneError as exc:
        raise ToolError(str(exc)) from None
    raise ToolError(await phone.why_not())


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, egress=True, timeout_s=30)
async def notify_phone(
    ctx: ToolContext,
    message: str,
    title: str = "",
    via: Literal["", "kdeconnect", "ntfy"] = "",
) -> ToolResult:
    """Show a notification with a short message on the user's own phone, for "send me a
    reminder on my phone" or "tell my phone the build finished".

    Args:
        message: The text to show, in a sentence or two.
        title: An optional short heading.
        via: Leave empty; Jarvis picks the way.
    """
    phone = _phone(ctx)
    text = clip(message)
    if not text:
        raise ToolError("Ask the user what the notification should say.")
    heading = " ".join(title.split()) or "Jarvis"
    try:
        if via == NTFY:
            await phone.push(heading, text)
            return ToolResult.success(
                data={"via": NTFY}, speech="Sent to your phone as a push notification."
            )
        device = await _device(phone)
        await phone.ping(device, f"{heading}: {text}")
    except PhoneError as exc:
        raise ToolError(str(exc)) from None
    return ToolResult.success(
        data={"via": KDE, "device": device.name}, speech=f"Sent to your {device.name}."
    )


@notify_phone.preparer
async def _prepare_notify(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    """Pick the way now, so what runs is exactly what was decided (and confirmed, if asked)."""
    phone = _phone(ctx)
    text = clip(str(args.get("message", "")))
    try:
        via, device = await phone.route()
    except PhoneError as exc:
        raise ToolError(str(exc)) from None
    pinned = {**args, "via": via}
    where = f"your {device.name}" if device is not None else "your phone through ntfy"
    summary = f'Send "{text[:80]}" to {where}'
    if via == NTFY and ctx.flags.private:
        return Prepared(pinned, summary, Risk.CONFIRM, PRIVATE_OVER_INTERNET)
    return Prepared(pinned, summary)


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=150)
async def send_to_phone(ctx: ToolContext, item: str = "", text: str = "") -> ToolResult:
    """Send something from the laptop to the user's own phone over the Wi-Fi: a file, a web
    link, what they copied, a screenshot, or a piece of text. For "send this file to my phone",
    "send the clipboard to my phone", "send a screenshot to my phone".

    Args:
        item: A file name or path, a web link, "clipboard", or "screenshot".
        text: Text to send instead of an item, for "send my phone the address".
    """
    phone = _phone(ctx)
    try:
        device = await _device(phone)
        kind, target = _what(item, text)
        if kind == "text":
            await phone.share_text(device, target)
            sent = "the text"
        elif kind == "clipboard":
            await phone.send_clipboard(device)
            sent = "what you copied"
        elif kind == "screenshot":
            shot = await asyncio.to_thread(_screenshot)
            await phone.share(device, str(shot))
            sent = "a screenshot"
        elif kind == "link":
            await phone.share(device, target)
            sent = "the link"
        else:
            await phone.share(device, target)
            sent = Path(target).name
    except PhoneError as exc:
        raise ToolError(str(exc)) from None
    return ToolResult.success(
        data={"sent": sent, "device": device.name}, speech=f"Sent {sent} to your {device.name}."
    )


def _what(item: str, text: str) -> tuple[str, str]:
    words = " ".join(item.split())
    if text.strip() and not words:
        return "text", text.strip()
    if not words:
        raise ToolError("Ask the user what to send: a file, a link, the clipboard, or text.")
    lowered = words.casefold()
    if lowered in _CLIPBOARD:
        return "clipboard", ""
    if lowered in _SCREENSHOT:
        return "screenshot", ""
    if _LINK.match(words):
        return "link", words
    return "file", words


def _screenshot() -> Path:
    folder = Path(tempfile.gettempdir()) / "jarvis-phone"
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.png"):  # only the last one is kept
        old.unlink(missing_ok=True)
    path = folder / f"Screenshot {datetime.now():%Y-%m-%d %H-%M-%S}.png"
    display.capture_screen(path)
    return path


@send_to_phone.preparer
async def _prepare_send(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    phone = _phone(ctx)
    device = await _device(phone)  # fail before asking when the phone cannot be reached
    kind, target = _what(str(args.get("item", "")), str(args.get("text", "")))
    to = f"to your {device.name}"
    if kind == "text":
        return Prepared({"text": target}, f'Send the text "{clip(target)[:80]}" {to}', Risk.CONFIRM)
    if kind == "clipboard":
        return Prepared({"item": "clipboard"}, f"Send what you copied {to}", Risk.CONFIRM)
    if kind == "screenshot":
        return Prepared({"item": "screenshot"}, f"Send a screenshot {to}", Risk.CONFIRM)
    if kind == "link":
        return Prepared({"item": target}, f"Send the link {target[:100]} {to}", Risk.CONFIRM)
    check = ctx.services.files.guard.check(await locate(ctx, target))
    if check.risk is Risk.BLOCKED:
        raise ToolError(check.reason or "That file cannot be sent.")
    path = check.path
    if not await asyncio.to_thread(path.is_file):
        raise ToolError(f"{path.name} is a folder; send one file at a time.")
    size_mb = (await asyncio.to_thread(path.stat)).st_size / 1_000_000
    if size_mb > MAX_FILE_MB:
        raise ToolError(f"{path.name} is {size_mb:.0f} MB; files up to {MAX_FILE_MB} MB are sent.")
    size = f"{size_mb:.1f} MB" if size_mb >= 0.1 else "under 0.1 MB"
    return Prepared(
        {"item": str(path)}, f"Send {path.name} ({size}) {to}", Risk.CONFIRM, check.reason
    )
