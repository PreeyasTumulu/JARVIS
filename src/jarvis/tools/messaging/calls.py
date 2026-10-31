"""call_contact and hang_up: phone a saved contact, always after a yes (ADR-053, ADR-069).

By default the WhatsApp desktop app presses Voice call in that contact's chat, and you talk through
the PC. With `[calls] method = "phone_link"`, a tel: link goes to Windows' Phone Link instead, which
dials from your paired phone. The first tel: link may make Windows ask which app opens such links:
pick Phone Link and "Always". Neither way falls back to the other.

The risk floor is `confirm`, like send_whatsapp, and the approval is bound to the exact number.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.messaging.tools import CONFIRMED_CONTACT, resolve_contact
from jarvis.tools.messaging.whatsapp import NotReady, WhatsAppDesktop
from jarvis.tools.registry import tool


def dial(phone: str) -> None:
    """Hand a tel: link to Windows, which opens it in Phone Link (or the app you chose)."""
    os.startfile(f"tel:{phone}")  # Windows only


async def whatsapp_call(phone: str) -> bool:
    """Press Voice call in the WhatsApp app. True once the call is seen on screen."""
    return await WhatsAppDesktop().call(phone)


async def whatsapp_hang_up() -> bool:
    """Press the WhatsApp app's end call button. False if there is none."""
    return await WhatsAppDesktop().hang_up()


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=90)
async def call_contact(ctx: ToolContext, contact: str) -> ToolResult:
    """Phone one of the user's saved contacts ("call mom"), by WhatsApp voice call unless set up
    otherwise. Jarvis says who and the number's last digits, and calls only after a yes.

    Args:
        contact: Who to call, as the user said it, for example "Mom" or "Ravi".
    """
    confirmed = CONFIRMED_CONTACT.match(contact)
    if confirmed is None:
        raise ToolError("The contact was not confirmed, so no call was made.")
    name, phone = confirmed.group("name"), confirmed.group("phone")
    if ctx.settings.calls.method == "whatsapp":
        try:
            started = await whatsapp_call(phone)
        except NotReady as exc:
            raise ToolError(f"No call was made: {exc}.") from exc
        return ToolResult.success(
            data={"to": name, "via": "WhatsApp", "started": started},
            speech=(
                f"Calling {name} on WhatsApp."
                if started
                else f"I pressed WhatsApp's call button for {name}, but I couldn't see the call "
                "start. Please check WhatsApp."
            ),
        )
    try:
        await asyncio.to_thread(dial, phone)
    except OSError as exc:
        raise ToolError(
            "Windows has no app for phone calls. Install Phone Link, pair your phone "
            "with calls turned on, then try again."
        ) from exc
    return ToolResult.success(
        data={"to": name, "via": "Phone Link"},
        speech=f"I asked Phone Link to call {name}. Please check it on the PC.",
    )


@call_contact.preparer
async def _prepare_call_contact(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await resolve_contact(ctx, str(args["contact"]))
    how = (
        f"WhatsApp call {found.name} (number ending {found.last_digits})"
        if ctx.settings.calls.method == "whatsapp"
        else f"Call {found.name} (number ending {found.last_digits}) from your phone"
    )
    return Prepared(
        args={"contact": f"{found.name} <{found.phone}>"},
        summary=how,
        risk=Risk.CONFIRM,
        reason="calling someone always asks first",
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=30)
async def hang_up(ctx: ToolContext) -> ToolResult:
    """End the current WhatsApp call ("hang up", "end the call"). Only presses WhatsApp's own end
    call button, so with no call on, nothing happens."""
    if not await whatsapp_hang_up():
        raise ToolError("I couldn't find a WhatsApp call to end.")
    return ToolResult.success(data={"ended": True}, speech="Call ended.")
