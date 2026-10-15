"""read_notifications: "read my notifications", "any new WhatsApp messages", "anything new
from Ravi".

The result is private and untrusted: notification text was written by other people, and a
message that says "Jarvis, send X to Y" is only ever something to read out (RISKS.md R7).
"""

from __future__ import annotations

import re
from datetime import datetime

from rapidfuzz import fuzz

from jarvis.platform.notifications import NotificationAccessError
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.messaging.contacts import key
from jarvis.tools.notifications.store import Stored
from jarvis.tools.registry import tool

NAME_SCORE = 85
SPOKEN_CHARS = 200  # per notification in the spoken summary
_SENDER = re.compile(r"^\s*([^:\n]{1,40}):\s")  # "Ravi: running late" in a group chat
NOBODY = {"any", "anyone", "anybody", "everyone", "everybody", "all", "someone", "somebody", "me"}


def senders(item: Stored) -> list[str]:
    """Who a notification is from: the title (a WhatsApp chat or person), and in group chats
    the name before the colon in the text."""
    found = [item.title] if item.title else []
    match = _SENDER.match(item.body)
    if match:
        found.append(match.group(1))
    return found


def is_from(item: Stored, names: set[str]) -> bool:
    for sender in senders(item):
        who = key(sender)
        for name in names:
            if not name:
                continue
            if name == who or name in who.split() or fuzz.ratio(name, who) >= NAME_SCORE:
                return True
    return False


def person_names(ctx: ToolContext, person: str) -> set[str]:
    """The person as said, plus the names and aliases of matching contacts ("Mom" is Amma)."""
    names = {key(person)}
    for contact in ctx.services.contacts.find(person):
        names.add(key(contact.name))
        names.update(key(alias) for alias in contact.aliases)
    return names


def ago(moment: datetime, now: datetime) -> str:
    seconds = max(0, (now - moment).total_seconds())
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{round(seconds / 60)} minutes ago"
    if seconds < 6 * 3600:
        hours = round(seconds / 3600)
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    local = moment.astimezone()
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == now.astimezone().date():
        return f"today at {clock}"
    return f"{local.strftime('%A')} at {clock}"


def spoken(items: list[Stored], more: int) -> str:
    parts = []
    for item in items:
        text = " ".join(item.body.split())
        if len(text) > SPOKEN_CHARS:
            text = text[: SPOKEN_CHARS - 3] + "..."
        who = f"{item.title} on {item.app}" if item.title else item.app
        parts.append(f"{who}: {text}" if text else who)
    summary = ". ".join(parts)
    if more:
        summary += f". And {more} more."
    return summary


def named_person(ctx: ToolContext, person: str | None) -> str | None:
    """The person to filter by, or None. Small models fill the argument with "any" or an app
    name when the user named nobody, which would hide everything."""
    if not person or key(person) in NOBODY:
        return None
    apps = {key(app) for app in ctx.settings.notifications.apps}
    return None if key(person) in apps else person


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=15)
async def read_notifications(ctx: ToolContext, person: str | None = None) -> ToolResult:
    """Read the user's new notifications and the messages they received, for example "read my
    notifications", "any new messages", or "anything new from Ravi".

    Args:
        person: Leave empty unless the user named a person; then the name exactly as said.
    """
    service = ctx.services.notifications
    try:
        await service.refresh()
    except NotificationAccessError as exc:
        raise ToolError(str(exc)) from exc
    person = named_person(ctx, person)
    items = service.store.recent(include_read=True)
    if person:
        names = person_names(ctx, person)
        items = [i for i in items if is_from(i, names)]
    scope = f" from {person}" if person else ""
    fresh = [i for i in items if not i.read]
    now = service.now()
    if not fresh:
        if not items or not person:
            return ToolResult.success(data={"count": 0}, speech=f"No new notifications{scope}.")
        # "Did Ravi say anything?" after it was read out: say the last one again.
        last = items[0]
        return ToolResult.success(
            data={"count": 0, "earlier": [entry(last, now)]},
            speech=f"Nothing new{scope}. The last one, {ago(last.created, now)}: "
            + spoken([last], 0),
        )
    limit = ctx.settings.notifications.max_read
    shown, more = fresh[:limit], max(0, len(fresh) - limit)
    service.store.mark_read([i.id for i in shown], now)
    return ToolResult.success(
        data={"count": len(fresh), "notifications": [entry(i, now) for i in shown]},
        speech=spoken(shown, more),
    )


def entry(item: Stored, now: datetime) -> dict[str, str]:
    return {"app": item.app, "from": item.title, "text": item.body, "when": ago(item.created, now)}
