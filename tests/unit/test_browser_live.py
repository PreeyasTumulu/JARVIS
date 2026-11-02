"""Real Chromium against local pages: the page snapshot script, clicks and typing, and the
WhatsApp Web send flow against tests/fixtures/whatsapp_web.html (a stand-in, not the real page).

Run with: uv run pytest -m browser (needs `uv run playwright install chromium`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from jarvis.config import Settings
from jarvis.storage.db import Database
from jarvis.storage.repositories import Preferences
from jarvis.tools.base import ToolError
from jarvis.tools.browser.session import BrowserManager
from jarvis.tools.messaging.whatsapp import LINKED, NotReady, SendStatus, WhatsAppWeb

pytestmark = pytest.mark.browser

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "whatsapp_web.html"
SHOP = """<!doctype html><title>Shop</title>
<form role="search" action="/search"><input name="q" aria-label="Search the shop">
<button>Go</button></form>
<a href="/deals">Today's deals</a>
<button id="buy">Buy now</button>
<form action="/login"><label for="pw">Password</label><input id="pw" type="password">
<input type="submit" value="Sign in"></form>
<div style="display:none"><button>Hidden</button></div>
<p id="out">Nothing clicked</p>
<script>document.getElementById("buy").onclick = () => out.textContent = "Bought";</script>
"""


@pytest.fixture
async def manager(settings: Settings) -> AsyncIterator[BrowserManager]:
    browser = BrowserManager(settings, headless=True)
    yield browser
    await browser.aclose()


async def test_snapshot_numbers_visible_controls_and_flags_them(manager: BrowserManager) -> None:
    page = await manager.page("browser")
    await page.page.set_content(SHOP)
    snap = await page.snapshot(2000, 40)
    by_label = {e.label: e for e in snap.elements}
    assert set(by_label) == {
        "Search the shop",
        "Go",
        "Today's deals",
        "Buy now",
        "Password",
        "Sign in",
    }
    assert by_label["Search the shop"].kind == "field"
    assert by_label["Search the shop"].search
    assert by_label["Go"].submit
    assert by_label["Go"].search
    assert by_label["Password"].password
    assert by_label["Sign in"].submit
    assert not by_label["Sign in"].search
    assert snap.elements[0].kind == "field"  # fields first
    assert "Nothing clicked" in snap.text
    again = await page.snapshot(2000, 40)
    assert {e.label: e.id for e in again.elements} == {e.label: e.id for e in snap.elements}


async def test_click_and_fill_use_the_numbers(manager: BrowserManager) -> None:
    page = await manager.page("browser")
    await page.page.set_content(SHOP)
    snap = await page.snapshot(2000, 40)
    ids = {e.label: e.id for e in snap.elements}
    await page.click(ids["Buy now"])
    await page.fill(ids["Search the shop"], "headphones", submit=False)
    after = await page.snapshot(2000, 40)
    assert "Bought" in after.text
    assert await page.page.input_value("[name=q]") == "headphones"


@pytest.fixture
def prefs() -> Preferences:
    return Preferences(Database(":memory:"))


async def fake_whatsapp(manager: BrowserManager, mode: str) -> None:
    body = FIXTURE.read_text(encoding="utf-8").replace("__MODE__", mode)
    context = await manager.context("whatsapp")
    await context.route(
        "https://web.whatsapp.com/**",
        lambda route: route.fulfill(body=body, content_type="text/html"),
    )


async def test_whatsapp_web_sends_and_reads_the_delivered_tick(
    manager: BrowserManager, prefs: Preferences, settings: Settings
) -> None:
    await fake_whatsapp(manager, "chat")
    web = WhatsAppWeb(manager, prefs, settings.whatsapp)
    sent = await web.send("+919876543210", "I'll be late 🙂")
    assert (sent.method, sent.status) == ("web", SendStatus.DELIVERED)
    page = (await manager.page("whatsapp")).page
    assert "phone=919876543210" in page.url
    assert await page.locator("#main div.message-out").count() == 1
    assert prefs.get(LINKED) is True


async def test_whatsapp_web_not_linked_is_not_ready(
    manager: BrowserManager, prefs: Preferences, settings: Settings
) -> None:
    await fake_whatsapp(manager, "qr")
    prefs.set(LINKED, True)
    with pytest.raises(NotReady, match="not linked"):
        await WhatsAppWeb(manager, prefs, settings.whatsapp).send("+919876543210", "hi")
    assert prefs.get(LINKED) is False


async def test_whatsapp_web_reports_a_number_without_whatsapp(
    manager: BrowserManager, prefs: Preferences, settings: Settings
) -> None:
    await fake_whatsapp(manager, "invalid")
    with pytest.raises(ToolError, match="not on WhatsApp"):
        await WhatsAppWeb(manager, prefs, settings.whatsapp).send("+919876543210", "hi")
