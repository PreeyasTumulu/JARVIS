"""Jarvis's own browser, driven by Playwright, with one persistent profile per purpose.

The "browser" profile is what browser_open, browser_click, and browser_type drive. WhatsApp Web
gets its own "whatsapp" profile, so no page the model opens shares cookies or storage with your
WhatsApp login (ADR-039). Windows are visible, so you can watch what Jarvis does, and WhatsApp
Web refuses headless browsers anyway.

Playwright runs on the main asyncio loop (on Windows a Proactor loop, which it needs for its
driver process). The browser starts on first use and stays open until Jarvis exits; closing its
window by hand is fine, the next call starts it again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, fields
from importlib.resources import files
from typing import TYPE_CHECKING, Any, Literal

from jarvis.config import Settings
from jarvis.platform.browsers import resolve_browser
from jarvis.tools.base import ToolError

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page, Playwright

log = logging.getLogger(__name__)

Profile = Literal["browser", "whatsapp"]
INSTALL_HINT = (
    "Jarvis's browser is not installed. It follows your default browser (Brave, Chrome, or "
    "Edge); set [browser] channel or executable in config/local.toml, or with "
    'channel = "chromium" run `uv run playwright install chromium` once.'
)
SNAPSHOT_JS = files("jarvis.tools.browser").joinpath("snapshot.js").read_text(encoding="utf-8")
ACTION_TIMEOUT_MS = 8000
SETTLE_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class PageElement:
    id: int
    kind: str  # field, button, link, checkbox, radio, dropdown
    label: str
    href: str = ""
    password: bool = False
    autocomplete: str = ""
    submit: bool = False  # pressing it submits a form
    search: bool = False  # looks like a search box or search form
    in_form: bool = False
    disabled: bool = False
    in_view: bool = True

    @property
    def target(self) -> str:
        """How a prepared call names this element: its number and its label at the time."""
        return f"#{self.id} {self.label}".strip()

    def describe(self) -> str:
        flags = " (password)" if self.password else " (disabled)" if self.disabled else ""
        return f"{self.id} {self.kind}: {self.label or '(no label)'}{flags}"


@dataclass(frozen=True)
class PageSnapshot:
    title: str
    url: str
    text: str
    truncated: bool
    elements: list[PageElement]


_ELEMENT_FIELDS = {f.name for f in fields(PageElement)}


class BrowserPage:
    """One tab, with the operations the tools need. A seam for tests (see FakeBrowser)."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def url(self) -> str:
        return self.page.url

    async def goto(self, url: str, timeout_s: float) -> None:
        from playwright.async_api import Error, TimeoutError

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_s * 1000)
        except TimeoutError as exc:
            raise ToolError(f"{url} took longer than {timeout_s:.0f} seconds to load.") from exc
        except Error as exc:
            raise ToolError(f"Could not open {url} ({_short(exc)}).") from exc
        # The HTML is in, but styles and images may not be: controls can still be invisible.
        with contextlib.suppress(Error):
            await self.page.wait_for_load_state("load", timeout=SETTLE_TIMEOUT_MS)

    async def snapshot(self, chars: int, elements: int, everything: bool = False) -> PageSnapshot:
        from playwright.async_api import Error

        limits = {"chars": chars, "elements": elements, "all": everything}
        for attempt in range(3):
            try:
                raw: dict[str, Any] = await self.page.evaluate(SNAPSHOT_JS, limits)
                break
            except Error as exc:  # the page navigated while we read it
                if attempt == 2:
                    raise ToolError(f"Could not read the page ({_short(exc)}).") from exc
                await self.settle()
        return PageSnapshot(
            title=raw["title"],
            url=raw["url"],
            text=raw["text"],
            truncated=raw["truncated"],
            elements=[
                PageElement(**{k: v for k, v in item.items() if k in _ELEMENT_FIELDS})
                for item in raw["elements"]
            ],
        )

    async def click(self, element_id: int) -> None:
        from playwright.async_api import Error

        try:
            await self.page.locator(f'[data-jarvis-id="{element_id}"]').first.click(
                timeout=ACTION_TIMEOUT_MS
            )
        except Error as exc:
            raise ToolError(f"The click did not go through ({_short(exc)}).") from exc
        await self.settle()

    async def fill(self, element_id: int, text: str, submit: bool) -> None:
        from playwright.async_api import Error

        locator = self.page.locator(f'[data-jarvis-id="{element_id}"]').first
        try:
            await locator.fill(text, timeout=ACTION_TIMEOUT_MS)
            if submit:
                await locator.press("Enter", timeout=ACTION_TIMEOUT_MS)
        except Error as exc:
            raise ToolError(f"Typing into the page did not work ({_short(exc)}).") from exc
        if submit:
            await self.settle()

    async def settle(self) -> None:
        """Give a click or Enter a moment to start a navigation, then wait for it to load."""
        from playwright.async_api import Error

        await asyncio.sleep(0.4)
        with contextlib.suppress(Error):  # still loading: the snapshot shows whatever is there
            await self.page.wait_for_load_state("domcontentloaded", timeout=SETTLE_TIMEOUT_MS)

    async def blank(self) -> None:
        await self.page.goto("about:blank")


class BrowserManager:
    """Starts Playwright on first use and keeps one persistent context per profile."""

    def __init__(self, settings: Settings, *, headless: bool = False) -> None:
        self._settings = settings
        self._headless = headless  # tests only: WhatsApp Web refuses headless browsers
        self._playwright: Playwright | None = None
        self._contexts: dict[Profile, BrowserContext] = {}
        self._lock = asyncio.Lock()

    def profile_dir(self, profile: Profile) -> Any:
        if profile == "whatsapp":
            return self._settings.whatsapp_profile_dir
        return self._settings.browser_profile_dir

    async def context(self, profile: Profile) -> BrowserContext:
        async with self._lock:
            existing = self._contexts.get(profile)
            if existing is not None:
                return existing
            context = await self._launch(profile)

            def forget(_closed: BrowserContext) -> None:
                self._contexts.pop(profile, None)  # closed by hand: the next call relaunches

            context.on("close", forget)
            self._contexts[profile] = context
            return context

    async def page(self, profile: Profile = "browser") -> BrowserPage:
        """The most recent open tab of a profile (a link that opened a new tab is the new one)."""
        context = await self.context(profile)
        pages = [page for page in context.pages if not page.is_closed()]
        return BrowserPage(pages[-1] if pages else await context.new_page())

    def is_open(self, profile: Profile) -> bool:
        return profile in self._contexts

    async def _launch(self, profile: Profile) -> BrowserContext:
        from playwright.async_api import Error, async_playwright

        if self._playwright is None:
            self._playwright = await async_playwright().start()
        folder = self.profile_dir(profile)
        folder.mkdir(parents=True, exist_ok=True)
        cfg = self._settings.browser
        try:
            choice = resolve_browser(cfg.channel, cfg.executable)
        except FileNotFoundError as exc:
            raise ToolError(str(exc)) from exc
        try:
            context = await self._playwright.chromium.launch_persistent_context(
                str(folder),
                headless=self._headless,
                channel=choice.channel,  # "chromium" is the full build, also when headless
                executable_path=str(choice.executable) if choice.executable else None,
                no_viewport=True,  # the page follows the window size
                args=["--start-maximized"] if profile == "browser" else [],
            )
        except Error as exc:
            message = str(exc)
            if "Executable doesn't exist" in message or "is not found at" in message:
                raise ToolError(INSTALL_HINT) from exc
            if "ProcessSingleton" in message or "already in use" in message:
                raise ToolError(
                    f"Jarvis's {profile} profile is open in another Jarvis or browser window. "
                    "Close that one first."
                ) from exc
            raise ToolError(f"Jarvis's browser did not start ({_short(exc)}).") from exc
        context.set_default_navigation_timeout(self._settings.browser.navigation_timeout_s * 1000)
        log.info("Started the %s browser profile in %s", profile, choice.name)
        return context

    async def close(self, profile: Profile) -> None:
        context = self._contexts.pop(profile, None)
        if context is not None:
            await context.close()

    async def aclose(self) -> None:
        for profile in list(self._contexts):
            try:
                await self.close(profile)
            except Exception:
                log.debug("Closing the %s profile failed", profile, exc_info=True)
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None


def _short(exc: Exception) -> str:
    first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return first.removeprefix("Page.goto: ").removeprefix("Locator.click: ")[:160]
