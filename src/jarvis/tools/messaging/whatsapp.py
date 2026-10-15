"""The two ways send_whatsapp sends: WhatsApp Web in Jarvis's WhatsApp profile, and the desktop app.

Both start from WhatsApp's own click-to-chat links (web.whatsapp.com/send and whatsapp://send),
which open the chat with the message already in the box. Jarvis checks the box holds exactly that
message before pressing Send, and afterwards looks for the message in the chat: on Web it also
reads the ticks (sent, delivered, read); the desktop app only shows that the box emptied.

Falling back from Web to the desktop app happens only when Web never got as far as pressing Send
(`NotReady`), so a message can never go out twice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING
from urllib.parse import quote

from jarvis.config import WhatsAppSettings
from jarvis.platform import sendinput, uia
from jarvis.platform import windows as win
from jarvis.platform.com import run_com
from jarvis.storage.repositories import Preferences
from jarvis.tools.base import ToolError
from jarvis.tools.browser.session import BrowserManager
from jarvis.tools.messaging import selectors as sel

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

log = logging.getLogger(__name__)

WEB_URL = "https://web.whatsapp.com/send?phone={phone}&text={text}"
DESKTOP_URL = "whatsapp://send?phone={phone}&text={text}"
LINKED = "whatsapp.web_linked"  # preference: WhatsApp Web in Jarvis's profile is linked
LOAD_TIMEOUT_S = 60  # WhatsApp Web syncs on first load, which can be slow
PREFILL_TIMEOUT_S = 8
DESKTOP_OPEN_TIMEOUT_S = 15
VK_RETURN = 0x0D
_DROP = {"️", "⃣", "‍"}


class SendStatus(StrEnum):
    READ = "read"
    DELIVERED = "delivered"
    SENT = "sent"  # on WhatsApp's server, not on their phone yet
    PENDING = "pending"  # still the clock icon
    UNVERIFIED = "unverified"  # Send was pressed, but the message was not seen in the chat


@dataclass(frozen=True)
class Sent:
    method: str  # "web" or "desktop"
    status: SendStatus


class NotReady(Exception):
    """This way cannot send right now and nothing was sent, so another way may try."""


def same_text(a: str, b: str) -> bool:
    """Compare message text the way WhatsApp shows it: emoji are images there, spacing varies."""

    def flat(text: str) -> str:
        kept = (
            ch
            for ch in unicodedata.normalize("NFC", text)
            if ch not in _DROP and unicodedata.category(ch) not in {"So", "Sk", "Cs", "Co"}
        )
        return " ".join("".join(kept).split()).casefold()

    return flat(a) == flat(b)


class WhatsAppWeb:
    def __init__(
        self, browser: BrowserManager, prefs: Preferences, settings: WhatsAppSettings
    ) -> None:
        self._browser = browser
        self._prefs = prefs
        self._settings = settings

    @property
    def linked(self) -> bool:
        return bool(self._prefs.get(LINKED, False))

    async def send(self, phone: str, message: str) -> Sent:
        from playwright.async_api import Error

        try:
            page = (await self._browser.page("whatsapp")).page
        except ToolError as exc:
            raise NotReady(str(exc)) from exc
        url = WEB_URL.format(phone=phone.lstrip("+"), text=quote(message, safe=""))
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_S * 1000)
            await self._open_chat(page, phone)
            compose = page.locator(sel.COMPOSE).last
            await self._wait_prefilled(compose, message)
            before = await page.locator(sel.OUTGOING).count()
        except Error as exc:
            raise NotReady(f"WhatsApp Web did not get ready ({exc.__class__.__name__})") from exc
        # From here on Send may be pressed: no exception may lead to a second attempt.
        try:
            button = page.locator(sel.SEND_BUTTON).first
            if await button.count():
                await button.click(timeout=5000)
            else:
                await compose.press("Enter", timeout=5000)
        except Error:
            log.exception("Pressing Send in WhatsApp Web failed")
            return Sent("web", SendStatus.UNVERIFIED)
        self._prefs.set(LINKED, True)
        status = await self._verify(page, message, before)
        return Sent("web", status)

    async def _open_chat(self, page: Page, phone: str) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + LOAD_TIMEOUT_S
        while loop.time() < deadline:
            if await page.locator(sel.COMPOSE).count():
                return
            if await page.get_by_text(sel.INVALID_NUMBER).count():
                raise ToolError(f"WhatsApp says the number {phone} is not on WhatsApp.")
            if (
                await page.locator(sel.QR_CODE).count()
                and not await page.locator(sel.CHAT_LIST).count()
            ):
                self._prefs.set(LINKED, False)
                raise NotReady(
                    "WhatsApp Web is not linked to your phone (run `uv run jarvis whatsapp login`)"
                )
            await asyncio.sleep(0.5)
        raise NotReady("WhatsApp Web did not open the chat in time")

    async def _wait_prefilled(self, compose: Locator, message: str) -> None:
        for _ in range(int(PREFILL_TIMEOUT_S / 0.5)):
            if same_text(await compose.inner_text(timeout=2000), message):
                return
            await asyncio.sleep(0.5)
        raise NotReady("the message did not appear in WhatsApp Web's message box")

    async def _verify(self, page: Page, message: str, before: int) -> SendStatus:
        """Wait for the new message in the chat and read its ticks."""
        from playwright.async_api import Error

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.verify_timeout_s
        seen = SendStatus.UNVERIFIED
        while loop.time() < deadline:
            try:
                outgoing = page.locator(sel.OUTGOING)
                count = await outgoing.count()
                if count > before:
                    last = outgoing.nth(count - 1)
                    text = await last.locator(sel.MESSAGE_TEXT).first.inner_text(timeout=2000)
                    if same_text(text, message):
                        seen = await self._ticks(last)
                        if seen in (SendStatus.DELIVERED, SendStatus.READ):
                            return seen
            except Error:
                log.debug("Reading the chat failed; trying again", exc_info=True)
            await asyncio.sleep(0.5)
        return seen

    @staticmethod
    async def _ticks(message: Locator) -> SendStatus:
        icon = message.locator(sel.STATUS_ICON).last
        if not await icon.count():
            return SendStatus.PENDING
        name = (await icon.get_attribute("data-icon")) or ""
        label = ((await icon.get_attribute("aria-label")) or "").casefold()
        if "read" in label or name == "msg-dblcheck-ack":
            return SendStatus.READ
        if name == "msg-dblcheck":
            return SendStatus.DELIVERED
        if name == "msg-check":
            return SendStatus.SENT
        return SendStatus.PENDING

    async def login(self, wait_s: float) -> bool:
        """Open WhatsApp Web so you can scan the QR code. True once the chat list shows."""
        page = (await self._browser.page("whatsapp")).page
        await page.goto("https://web.whatsapp.com/", wait_until="domcontentloaded")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_s
        while loop.time() < deadline:
            if await page.locator(sel.CHAT_LIST).count():
                self._prefs.set(LINKED, True)
                return True
            await asyncio.sleep(1)
        return False


class WhatsAppDesktop:
    """The installed WhatsApp app, through its whatsapp:// link and one Enter key press."""

    async def send(self, phone: str, message: str) -> Sent:
        url = DESKTOP_URL.format(phone=phone.lstrip("+"), text=quote(message, safe=""))
        try:
            await asyncio.to_thread(os.startfile, url)
        except OSError as exc:
            raise NotReady("the WhatsApp desktop app is not installed") from exc
        window = await self._window()
        if not await self._prefilled(window, message):
            raise NotReady(
                "WhatsApp opened, but I could not see the message in its text box, so I did "
                "not press Send"
            )
        if await asyncio.to_thread(win.foreground_window) != window.hwnd and not (
            await asyncio.to_thread(win.focus_window, window.hwnd)
        ):
            raise NotReady("Windows did not let me bring WhatsApp to the front")
        await asyncio.to_thread(sendinput.press_combo, (), VK_RETURN)
        for _ in range(10):
            await asyncio.sleep(0.5)
            after = await run_com(uia.focused_text, window.hwnd)
            if after is not None and not same_text(after, message):
                return Sent("desktop", SendStatus.SENT)
        return Sent("desktop", SendStatus.UNVERIFIED)

    async def _window(self) -> win.WindowInfo:
        for _ in range(int(DESKTOP_OPEN_TIMEOUT_S / 0.5)):
            await asyncio.sleep(0.5)
            front = await asyncio.to_thread(win.foreground_window)
            for window in await asyncio.to_thread(win.list_windows):
                if window.exe.casefold().startswith("whatsapp") and window.hwnd == front:
                    return window
        raise NotReady("the WhatsApp app did not come to the front")

    async def _prefilled(self, window: win.WindowInfo, message: str) -> bool:
        for _ in range(int(PREFILL_TIMEOUT_S / 0.5)):
            text = await run_com(uia.focused_text, window.hwnd)
            if text and same_text(text, message):
                return True
            await asyncio.sleep(0.5)
        return False


class WhatsApp:
    """Picks how to send, per `[whatsapp] method` (see config/jarvis.toml)."""

    def __init__(self, web: WhatsAppWeb, desktop: WhatsAppDesktop, settings: WhatsAppSettings):
        self.web = web
        self.desktop = desktop
        self._settings = settings

    async def send(self, phone: str, message: str) -> Sent:
        method = self._settings.method
        if method == "desktop":
            return await self._only(self.desktop, phone, message)
        if method == "web":
            return await self._only(self.web, phone, message)
        if self.web.linked:
            try:
                return await self.web.send(phone, message)
            except NotReady as exc:
                log.info("WhatsApp Web is not ready (%s); using the desktop app", exc)
        try:
            return await self.desktop.send(phone, message)
        except NotReady as exc:
            hint = (
                ""
                if self.web.linked
                else " You can also link WhatsApp Web once: uv run jarvis whatsapp login."
            )
            raise ToolError(f"Not sent: {exc}.{hint}") from exc

    @staticmethod
    async def _only(way: WhatsAppWeb | WhatsAppDesktop, phone: str, message: str) -> Sent:
        try:
            return await way.send(phone, message)
        except NotReady as exc:
            raise ToolError(f"Not sent: {exc}.") from exc
