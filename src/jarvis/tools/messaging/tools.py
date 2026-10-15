"""send_whatsapp: message a saved contact, always after reading the message back and hearing yes.

The risk floor is `confirm` and config cannot lower it. The confirmation names the contact, the
last digits of the number, and the exact message, and the approval is bound to exactly that
(Prepared.digest), so nothing can change between your yes and the send.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.messaging.contacts import Contact, key
from jarvis.tools.messaging.whatsapp import SendStatus
from jarvis.tools.registry import tool

ASK_TIMEOUT_S = 60
MAX_OPTIONS = 4
# How a prepared call names its contact: "Amma <+919876543210>". The model's own text is never
# trusted for the number; the preparer always looks the name up again.
CONFIRMED_CONTACT = re.compile(r"^(?P<name>.+?) <(?P<phone>\+\d{8,15})>$")


def _spoken_name(text: str) -> str:
    match = CONFIRMED_CONTACT.match(text.strip())
    return match.group("name") if match else text


async def resolve_contact(ctx: ToolContext, spoken: str) -> Contact:
    """The one contact meant. Asks the user when the name fits several (ARCHITECTURE.md 3)."""
    name = _spoken_name(spoken).strip()
    found = ctx.services.contacts.find(name)
    if not found:
        raise ToolError(
            f"There is no contact called '{name}'. Tell the user to add one with "
            "`jarvis contacts add` or in the Contacts tab of the web page."
        )
    if len(found) == 1:
        return found[0]
    choices = found[:MAX_OPTIONS]
    options = [f"{c.name}, number ending {c.last_digits}" for c in choices]
    try:
        async with asyncio.timeout(ASK_TIMEOUT_S):
            answer = await ctx.channel.ask(f"Which {name} do you mean?", options)
    except TimeoutError:
        raise ToolError("There was no answer about which contact, so nothing was sent.") from None
    for contact, option in zip(choices, options, strict=True):
        if answer == option:
            return contact
    said = key(answer)
    narrowed = [
        c
        for c in choices
        if said and (said in key(c.name) or key(c.name) in said or c.last_digits in answer)
    ]
    if len(narrowed) == 1:
        return narrowed[0]
    raise ToolError(f"I couldn't tell which {name} was meant, so nothing was sent.")


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=150)
async def send_whatsapp(ctx: ToolContext, contact: str, message: str) -> ToolResult:
    """Send a WhatsApp message to one of the user's saved contacts. Jarvis reads it back and
    sends only after the user says yes.

    Args:
        contact: Who to send it to, as the user said it, for example "Mom" or "Ravi".
        message: The message itself, worded as the user wants it sent, for example
            "I'll be late" for "tell Mom that I'll be late".
    """
    confirmed = CONFIRMED_CONTACT.match(contact)
    if confirmed is None:
        raise ToolError("The contact was not confirmed, so nothing was sent.")
    name, phone = confirmed.group("name"), confirmed.group("phone")
    sent = await ctx.services.whatsapp.send(phone, message)
    speech = {
        SendStatus.READ: f"Sent to {name}, and it's been read.",
        SendStatus.DELIVERED: f"Sent to {name} and delivered.",
        SendStatus.SENT: f"Sent to {name}."
        + (" It isn't delivered to their phone yet." if sent.method == "web" else ""),
        SendStatus.PENDING: f"WhatsApp is still sending it to {name}; check it in a moment.",
        SendStatus.UNVERIFIED: (
            f"I pressed Send for {name}, but I couldn't see the message in the chat. "
            "Please check WhatsApp."
        ),
    }[sent.status]
    return ToolResult.success(
        data={"to": name, "via": f"WhatsApp {sent.method}", "status": sent.status.value},
        speech=speech,
    )


@send_whatsapp.preparer
async def _prepare_send_whatsapp(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    message = str(args["message"]).strip()
    if not message:
        raise ToolError("The message is empty. Ask the user what to say.")
    limit = ctx.settings.whatsapp.max_chars
    if len(message) > limit:
        raise ToolError(f"That message is longer than {limit} characters; shorten it.")
    contact = await resolve_contact(ctx, str(args["contact"]))
    return Prepared(
        args={"contact": f"{contact.name} <{contact.phone}>", "message": message},
        summary=(
            f"Send this WhatsApp message to {contact.name} (number ending "
            f'{contact.last_digits}): "{message}"'
        ),
        risk=Risk.CONFIRM,
        reason="sending a message always asks first",
    )
