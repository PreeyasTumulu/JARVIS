"""call_contact: phone a saved contact through Phone Link, always after a yes (ADR-053).

Windows 11's Phone Link (paired with your Android phone over Bluetooth) places calls from the
PC through your own phone and number. Jarvis opens a tel: link for the confirmed contact and
Phone Link dials; the talking happens through the PC's microphone and speakers. Nothing goes
through a paid service. The first tel: link may make Windows ask which app opens such links:
pick Phone Link and "Always".

The risk floor is `confirm`, like send_whatsapp, and the approval is bound to the exact number.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.messaging.tools import CONFIRMED_CONTACT, resolve_contact
from jarvis.tools.registry import tool


def dial(phone: str) -> None:
    """Hand a tel: link to Windows, which opens it in Phone Link (or the app you chose)."""
    os.startfile(f"tel:{phone}")  # Windows only


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=30)
async def call_contact(ctx: ToolContext, contact: str) -> ToolResult:
    """Phone one of the user's saved contacts ("call mom") through Phone Link and the user's
    own phone. Jarvis says who and the number's last digits, and calls only after a yes.

    Args:
        contact: Who to call, as the user said it, for example "Mom" or "Ravi".
    """
    confirmed = CONFIRMED_CONTACT.match(contact)
    if confirmed is None:
        raise ToolError("The contact was not confirmed, so no call was made.")
    name, phone = confirmed.group("name"), confirmed.group("phone")
    try:
        await asyncio.to_thread(dial, phone)
    except OSError as exc:
        raise ToolError(
            "Windows has no app for phone calls. Install Phone Link, pair your Android phone "
            "with calls turned on, then try again."
        ) from exc
    return ToolResult.success(
        data={"to": name, "via": "Phone Link"},
        speech=f"Calling {name} on your phone. Talk through the PC once they pick up.",
    )


@call_contact.preparer
async def _prepare_call_contact(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await resolve_contact(ctx, str(args["contact"]))
    return Prepared(
        args={"contact": f"{found.name} <{found.phone}>"},
        summary=f"Call {found.name} (number ending {found.last_digits}) from your phone",
        risk=Risk.CONFIRM,
        reason="calling someone always asks first",
    )
