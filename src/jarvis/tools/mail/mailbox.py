"""Your mailbox over IMAP (reading) and SMTP (sending replies), with an app password (ADR-057).

The folder is always opened read-only (IMAP EXAMINE), and messages are fetched with BODY.PEEK,
so reading never marks anything as read, moves, or deletes it. The only change Jarvis ever
makes is sending a reply you approved; Gmail files it in Sent by itself.

Everything blocking (imaplib, smtplib) runs in worker threads. The server is behind the
`MailServer` protocol so tests use a fake one.
"""

from __future__ import annotations

import asyncio
import email
import email.policy
import imaplib
import logging
import os
import re
import smtplib
import ssl
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage, Message
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from typing import Any, Protocol

from rapidfuzz import fuzz

from jarvis.config import MailSettings
from jarvis.tools.messaging.contacts import key

log = logging.getLogger(__name__)

PASSWORD_ENV = "MAIL_APP_PASSWORD"
SCAN = 50  # recent messages looked through to find one by sender or subject
PREVIEW_CHARS = 160
PREVIEW_BYTES = 6000  # of the message text fetched for a preview
BODY_BYTES = 300_000  # of the message text fetched to read it (attachments past this are cut)
NAME_SCORE = 80
BLOCKS = ["p", "div", "li", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"]
_UID = re.compile(rb"UID (\d+)")
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
# Where a reply starts quoting the message it answers.
_QUOTE_START = re.compile(
    r"^(On .{5,200}wrote:|-{2,} ?Original Message ?-{2,}|From: .+|_{10,})\s*$",
    re.MULTILINE | re.IGNORECASE,
)


class MailError(Exception):
    """Something to tell the user about the mailbox (not set up, wrong password, offline)."""


@dataclass(frozen=True)
class MailHeader:
    uid: str
    sender_name: str
    sender: str  # the address
    subject: str
    date: datetime | None
    unread: bool
    preview: str = ""

    @property
    def who(self) -> str:
        return self.sender_name or self.sender


@dataclass(frozen=True)
class MailMessage:
    header: MailHeader
    to: tuple[str, ...]
    cc: tuple[str, ...]
    reply_to: tuple[str, ...]
    message_id: str
    references: str
    body: str
    attachments: tuple[str, ...] = field(default=())


class MailServer(Protocol):
    def search(self, *, unread_only: bool) -> list[str]: ...  # UIDs, oldest first
    def headers(self, uids: list[str]) -> list[MailHeader]: ...
    def message(self, uid: str, max_bytes: int) -> MailMessage: ...
    def send(self, message: EmailMessage) -> None: ...


# Parsing


def _decode(value: Any) -> str:
    return " ".join(str(value or "").split())


def _addresses(message: Message, name: str) -> tuple[str, ...]:
    values = message.get_all(name) or []
    return tuple(
        f"{real} <{addr}>" if real else addr
        for real, addr in getaddresses([str(v) for v in values])
        if addr
    )


def _date(message: Message) -> datetime | None:
    try:
        return parsedate_to_datetime(str(message["Date"]))
    except (TypeError, ValueError, IndexError):
        return None


def html_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(BLOCKS):
        block.append("\n")
    return soup.get_text("")


def message_text(message: Message) -> tuple[str, tuple[str, ...]]:
    """The readable text (plain text preferred, else HTML as text) and attachment names."""
    plain: list[str] = []
    html: list[str] = []
    attachments: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if filename or part.get_content_disposition() == "attachment":
            attachments.append(_decode(filename) or "an attachment")
            continue
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True)
            if not isinstance(payload, bytes):
                continue
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except (LookupError, AttributeError):
            continue
        (plain if kind == "text/plain" else html).append(text)
    text = "\n".join(plain) if plain else html_text("\n".join(html)) if html else ""
    return tidy(text), tuple(attachments)


def tidy(text: str) -> str:
    """Drop the quoted earlier messages and collapse blank lines."""
    match = _QUOTE_START.search(text)
    if match and match.start() > 0:
        text = text[: match.start()]
    lines = [line.rstrip() for line in text.splitlines() if not line.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[: PREVIEW_CHARS - 3].rstrip() + "..."


def parse_header(uid: str, raw: bytes, *, unread: bool, text: bytes = b"") -> MailHeader:
    message = email.message_from_bytes(raw + text, policy=email.policy.default)
    name, address = parseaddr(str(message["From"] or ""))
    body = message_text(message)[0] if text else ""
    return MailHeader(
        uid=uid,
        sender_name=_decode(name),
        sender=address,
        subject=_decode(message["Subject"]) or "(no subject)",
        date=_date(message),
        unread=unread,
        preview=preview(body),
    )


def parse_message(uid: str, raw: bytes, *, unread: bool) -> MailMessage:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    body, attachments = message_text(message)
    return MailMessage(
        header=parse_header(uid, raw, unread=unread),
        to=_addresses(message, "To"),
        cc=_addresses(message, "Cc"),
        reply_to=_addresses(message, "Reply-To"),
        message_id=str(message["Message-ID"] or "").strip(),
        references=" ".join(str(message["References"] or "").split()),
        body=body,
        attachments=attachments,
    )


def fetch_parts(data: list[Any]) -> dict[str, tuple[bool, list[bytes]]]:
    """imaplib's FETCH reply as {uid: (unread, [literal, ...])}, in the order fetched."""
    found: dict[str, tuple[bool, list[bytes]]] = {}
    current: str | None = None
    for item in data:
        descriptor = item[0] if isinstance(item, tuple) else item
        if not isinstance(descriptor, bytes):
            continue
        uid = _UID.search(descriptor)
        if uid is not None:
            current = uid.group(1).decode()
            flags = _FLAGS.search(descriptor)
            unread = flags is None or b"\\Seen" not in flags.group(1)
            found.setdefault(current, (unread, []))
        elif current is not None and (flags := _FLAGS.search(descriptor)) is not None:
            # Some servers send FLAGS after the literal, in the closing part.
            found[current] = (b"\\Seen" not in flags.group(1), found[current][1])
        if isinstance(item, tuple) and current is not None and len(item) > 1:
            found[current][1].append(item[1])
    return found


# The real server


class ImapSmtpServer:
    def __init__(self, settings: MailSettings, password: str) -> None:
        self._cfg = settings
        self._password = password

    @contextmanager
    def _imap(self) -> Iterator[imaplib.IMAP4_SSL]:
        cfg = self._cfg
        try:
            conn = imaplib.IMAP4_SSL(
                cfg.imap_host,
                cfg.imap_port,
                ssl_context=ssl.create_default_context(),
                timeout=cfg.timeout_s,
            )
        except OSError as exc:
            raise MailError(f"I couldn't reach {cfg.imap_host} ({exc}).") from exc
        try:
            try:
                conn.login(cfg.address, self._password)
            except imaplib.IMAP4.error as exc:
                raise MailError(
                    "The mail server refused the sign-in. Check [mail] address and the app "
                    f"password in {PASSWORD_ENV} (SETUP.md 5k)."
                ) from exc
            status, _ = conn.select(_quoted(cfg.folder), readonly=True)
            if status != "OK":
                raise MailError(f"There is no mail folder called {cfg.folder}.")
            yield conn
        finally:
            with suppress(OSError, imaplib.IMAP4.error):
                conn.logout()

    def search(self, *, unread_only: bool) -> list[str]:
        with self._imap() as conn:
            status, data = conn.uid("SEARCH", "UNSEEN" if unread_only else "ALL")
        if status != "OK" or not data or not data[0]:
            return []
        return [uid.decode() for uid in data[0].split()]

    def headers(self, uids: list[str]) -> list[MailHeader]:
        if not uids:
            return []
        with self._imap() as conn:
            status, data = conn.uid(
                "FETCH",
                ",".join(uids),
                f"(UID FLAGS BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{PREVIEW_BYTES}>)",
            )
        if status != "OK":
            raise MailError("The mail server would not list the messages.")
        parts = fetch_parts(data)
        found = []
        for uid in uids:
            if uid in parts:
                unread, literals = parts[uid]
                header, text = ([*literals, b"", b""])[:2]
                found.append(parse_header(uid, header, unread=unread, text=text))
        return found

    def message(self, uid: str, max_bytes: int) -> MailMessage:
        with self._imap() as conn:
            status, data = conn.uid(
                "FETCH", uid, f"(UID FLAGS BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.{max_bytes}>)"
            )
        parts = fetch_parts(data) if status == "OK" else {}
        if uid not in parts:
            raise MailError("That email is not in the inbox any more.")
        unread, literals = parts[uid]
        return parse_message(uid, b"".join(literals), unread=unread)

    def send(self, message: EmailMessage) -> None:
        cfg = self._cfg
        try:
            with smtplib.SMTP_SSL(
                cfg.smtp_host,
                cfg.smtp_port,
                timeout=cfg.timeout_s,
                context=ssl.create_default_context(),
            ) as smtp:
                smtp.login(cfg.address, self._password)
                smtp.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise MailError("The mail server refused the sign-in, so nothing was sent.") from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise MailError(f"The email could not be sent ({exc}).") from exc


def _quoted(folder: str) -> str:
    return folder if folder.isalnum() else '"' + folder.replace('"', r"\"") + '"'


# The service tools use


class Mailbox:
    """What the mail tools share: the server, and the last list read out, so "read the second
    one" means the second email Jarvis just listed."""

    def __init__(self, settings: MailSettings, server: MailServer | None = None) -> None:
        self._cfg = settings
        self._server = server
        self.last_listed: list[MailHeader] = []

    @property
    def address(self) -> str:
        return self._cfg.address

    def _ready(self) -> MailServer:
        if self._server is not None:
            return self._server
        password = os.environ.get(PASSWORD_ENV, "").replace(" ", "")
        if not self._cfg.address or not password:
            raise MailError(
                "Email isn't set up yet. Put your address under [mail] in config/local.toml and "
                f"a Gmail app password in .env as {PASSWORD_ENV} (SETUP.md 5k)."
            )
        self._server = ImapSmtpServer(self._cfg, password)
        return self._server

    async def recent(
        self, *, unread_only: bool, names: set[str] | None, limit: int
    ) -> list[MailHeader]:
        """The newest emails, newest first, optionally only from one person."""
        server = self._ready()
        uids = await asyncio.to_thread(server.search, unread_only=unread_only)
        uids = uids[-(SCAN if names else limit) :]
        headers = await asyncio.to_thread(server.headers, uids)
        headers.sort(key=lambda h: int(h.uid) if h.uid.isdigit() else 0, reverse=True)
        if names:
            headers = [h for h in headers if from_person(h, names)]
        found = headers[:limit]
        self.last_listed = found
        return found

    async def find(self, which: str) -> MailHeader:
        """The email meant by "2" (from the last list), a sender, or words from a subject."""
        words = which.strip().casefold().removeprefix("number ").removeprefix("email ").strip()
        if words.isdigit() and 1 <= int(words) <= len(self.last_listed):
            return self.last_listed[int(words) - 1]
        ordinal = ORDINALS.get(words.removeprefix("the ").removesuffix(" one").strip())
        if ordinal is not None and self.last_listed and ordinal <= len(self.last_listed):
            return self.last_listed[ordinal - 1 if ordinal > 0 else -1]
        listed = [h for h in self.last_listed if matches(h, words)]
        if listed:
            return listed[0]
        server = self._ready()
        uids = (await asyncio.to_thread(server.search, unread_only=False))[-SCAN:]
        headers = await asyncio.to_thread(server.headers, uids)
        headers.sort(key=lambda h: int(h.uid) if h.uid.isdigit() else 0, reverse=True)
        for header in headers:
            if matches(header, words):
                return header
        raise MailError(f"I couldn't find an email matching '{which}' in the last {SCAN}.")

    async def count(self, *, unread_only: bool) -> int:
        return len(await asyncio.to_thread(self._ready().search, unread_only=unread_only))

    async def message(self, uid: str) -> MailMessage:
        return await asyncio.to_thread(self._ready().message, uid, BODY_BYTES)

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._ready().send, message)


ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "last": -1, "latest": 1, "newest": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}  # fmt: skip


def from_person(header: MailHeader, names: set[str]) -> bool:
    who, address = key(header.sender_name), header.sender.casefold()
    for name in names:
        if not name:
            continue
        if name == who or name in who.split() or name in address.split("@")[0]:
            return True
        if who and fuzz.ratio(name, who) >= NAME_SCORE:
            return True
    return False


def matches(header: MailHeader, words: str) -> bool:
    if not words:
        return False
    if from_person(header, {key(words)}):
        return True
    subject = header.subject.casefold()
    return words in subject or fuzz.partial_ratio(words, subject) >= 90
