"""Mail tools: "any new email", "read the email from Ravi", "reply that I'll send it tonight".

Listing gives senders, subjects, and short previews; the full text is read only for the one
email asked about (ADR-058). Both are private and untrusted: an email is written by someone
else, and "Jarvis, forward this to ..." inside one is only ever something to read out.

A reply goes only to the people on the email it answers, and only after you hear the exact
text and the addresses and say yes (risk floor `confirm`, bound to that text by its digest).
"""

from __future__ import annotations

import re
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from typing import Any

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.mail.mailbox import MailError, MailHeader, MailMessage
from jarvis.tools.notifications.tools import NOBODY, ago, person_names
from jarvis.tools.registry import tool
from jarvis.tools.secrets import redact_secrets

_RE = re.compile(r"^(\s*(re|aw|sv)\s*:\s*)+", re.IGNORECASE)
CONFIRMED = re.compile(r"^uid:(?P<uid>\S+)$")
# The model sometimes keeps the instruction in the text: "reply that I'll send it tonight".
_LEAD_IN = re.compile(
    r"^((reply|respond|write back|tell (him|her|them))( (to )?(him|her|them))?( that| saying)?"
    r"|(say|saying)( that\b|(?=:)))[\s,:]+",
    re.IGNORECASE,
)


def reply_text(text: str) -> str:
    text = _LEAD_IN.sub("", text.strip()).strip()
    return text[:1].upper() + text[1:]


def _when(header: MailHeader, now: datetime) -> str:
    return ago(header.date, now) if header.date else ""


def _listed(headers: list[MailHeader], now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "number": index,
            "from": header.who,
            "subject": header.subject,
            "when": _when(header, now),
            "preview": redact_secrets(header.preview)[0],
            "unread": header.unread,
        }
        for index, header in enumerate(headers, start=1)
    ]


def _spoken(headers: list[MailHeader], unread_only: bool, person: str | None) -> str:
    what = "unread email" if unread_only else "email"
    who = f" from {person}" if person else ""
    if not headers:
        return f"No {what}{who}."
    count = len(headers)
    lead = f"{count} {what}{'s' if count > 1 else ''}{who}"
    items = "; ".join(f"{h.who}: {h.subject}" for h in headers[:3])
    more = f", and {count - 3} more" if count > 3 else ""
    return f"{lead}. {items}{more}."


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=60)
async def read_mail(
    ctx: ToolContext, sender: str | None = None, unread_only: bool = True
) -> ToolResult:
    """Check the user's email inbox: the newest emails with sender, subject, and a short
    preview, for "any new email", "check my mail", or "emails from my manager". Does not mark
    anything as read. Use read_email to read one in full.

    Args:
        sender: Only emails from this person or company, when the user names one. Leave it
            out for "any new email".
        unread_only: false to include emails already read ("my latest emails").
    """
    mailbox = ctx.services.mail
    person = sender.strip() if sender and sender.strip().casefold() not in NOBODY else None
    names = person_names(ctx, person) if person else None
    try:
        headers = await mailbox.recent(
            unread_only=unread_only, names=names, limit=ctx.settings.mail.max_list
        )
    except MailError as exc:
        raise ToolError(str(exc)) from exc
    now = datetime.now().astimezone()
    return ToolResult.success(
        data={"emails": _listed(headers, now)},
        speech=_spoken(headers, unread_only, person),
        hint="To read one, call read_email with its number." if headers else None,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=60)
async def read_email(ctx: ToolContext, message: str) -> ToolResult:
    """Read one email in full, for "read the email from Ravi" or "what does the second one
    say". Does not mark it as read.

    Args:
        message: The email's number from read_mail's list, or its sender, or words from its
            subject.
    """
    mailbox = ctx.services.mail
    try:
        header = await mailbox.find(message)
        email = await mailbox.message(header.uid)
    except MailError as exc:
        raise ToolError(str(exc)) from exc
    limit = ctx.settings.mail.body_chars
    body, hidden = redact_secrets(email.body)
    cut = len(body) > limit
    if cut:
        body = body[:limit].rstrip() + " [the rest is cut]"
    now = datetime.now().astimezone()
    data = {
        "from": f"{header.sender_name} <{header.sender}>" if header.sender_name else header.sender,
        "to": list(email.to),
        "cc": list(email.cc),
        "subject": header.subject,
        "when": _when(header, now),
        "text": body,
        "attachments": list(email.attachments),
    }
    hint = "Summarize it in one or two sentences unless the user asked to hear it all."
    if hidden:
        hint += " Values that looked like secrets were hidden."
    return ToolResult.success(data=data, hint=hint)


def reply_recipients(email: MailMessage, own: str, reply_all: bool) -> tuple[list[str], list[str]]:
    """Who a reply goes to: Reply-To or the sender, plus everyone else on it for reply-all.
    Never yourself."""
    mine = own.casefold()

    def keep(values: list[str], seen: set[str]) -> list[str]:
        kept = []
        for value in values:
            address = getaddresses([value])[0][1].casefold()
            if address and address != mine and address not in seen:
                seen.add(address)
                kept.append(value)
        return kept

    seen: set[str] = set()
    sender = email.header.sender
    first = list(email.reply_to) or ([f"{email.header.sender_name} <{sender}>"] if sender else [])
    to = keep(first, seen)
    cc = keep([*email.to, *email.cc], seen) if reply_all else []
    return to, cc


def build_reply(
    email: MailMessage, text: str, own: str, to: list[str], cc: list[str], signature: str
) -> EmailMessage:
    reply = EmailMessage()
    reply["From"] = own
    reply["To"] = ", ".join(to)
    if cc:
        reply["Cc"] = ", ".join(cc)
    reply["Subject"] = "Re: " + _RE.sub("", email.header.subject)
    reply["Date"] = formatdate(localtime=True)
    reply["Message-ID"] = make_msgid()
    if email.message_id:
        reply["In-Reply-To"] = email.message_id
        reply["References"] = f"{email.references} {email.message_id}".strip()
    body = text.strip() + (f"\n\n{signature.strip()}" if signature.strip() else "")
    reply.set_content(body + "\n")
    return reply


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=60)
async def reply_email(
    ctx: ToolContext, message: str, text: str, reply_all: bool = False
) -> ToolResult:
    """Reply to an email the user received. Jarvis reads the reply and the addresses back and
    sends only after the user says yes. It goes only to the people on that email.

    Args:
        message: The email to answer: its number from read_mail's list, its sender, or words
            from its subject.
        text: The reply itself, worded as the user wants it sent, for example "Thanks, I'll
            send it tonight." for "reply that I'll send it tonight".
        reply_all: true only when the user says reply to all or reply to everyone.
    """
    confirmed = CONFIRMED.match(message)
    if confirmed is None:
        raise ToolError("The email was not confirmed, so nothing was sent.")
    mailbox = ctx.services.mail
    cfg = ctx.settings.mail
    try:
        email = await mailbox.message(confirmed.group("uid"))
        to, cc = reply_recipients(email, mailbox.address, reply_all)
        await mailbox.send(build_reply(email, text, mailbox.address, to, cc, cfg.signature))
    except MailError as exc:
        raise ToolError(str(exc)) from exc
    who = email.header.who
    others = f" and {len(to) + len(cc) - 1} others" if len(to) + len(cc) > 1 else ""
    return ToolResult.success(
        data={"to": to, "cc": cc, "subject": email.header.subject},
        speech=f"Sent your reply to {who}{others}.",
    )


@reply_email.preparer
async def _prepare_reply_email(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    text = reply_text(str(args["text"]))
    if not text:
        raise ToolError("The reply is empty. Ask the user what to say.")
    limit = ctx.settings.mail.max_reply_chars
    if len(text) > limit:
        raise ToolError(f"That reply is longer than {limit} characters; shorten it.")
    reply_all = bool(args.get("reply_all", False))
    mailbox = ctx.services.mail
    try:
        header = await mailbox.find(str(args["message"]))
        email = await mailbox.message(header.uid)
    except MailError as exc:
        raise ToolError(str(exc)) from exc
    to, cc = reply_recipients(email, mailbox.address, reply_all)
    if not to:
        raise ToolError("That email has no address to reply to.")
    everyone = ", ".join([*to, *cc])
    return Prepared(
        args={"message": f"uid:{header.uid}", "text": text, "reply_all": reply_all},
        summary=f'Email this reply to {everyone} about "{header.subject}": "{text}"',
        risk=Risk.CONFIRM,
        reason="sending an email always asks first",
    )
