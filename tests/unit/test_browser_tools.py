"""Browser step tools: open, read, click, type, and the rules around them."""

from __future__ import annotations

import pytest

from jarvis.tools.base import ToolContext, ToolError
from jarvis.tools.browser.session import PageElement
from jarvis.tools.browser.tools import NEXT_STEP_HINT, browser_click, page_data
from jarvis.tools.policy import EXFILTRATION_REASON
from tests.conftest import FakeBrowser, FakeChannel, FakeWeb, Harness, MakeApp, reply

SEARCH = PageElement(1, "field", "Search Amazon", search=True, in_form=True)
GO = PageElement(2, "button", "Go", submit=True, search=True, in_form=True)
DEALS = PageElement(3, "link", "Today's Deals", href="https://www.amazon.in/deals")
BUY = PageElement(4, "button", "Buy Now")
EMAIL = PageElement(5, "field", "Email", in_form=True)
SIGN_UP = PageElement(6, "button", "Create account", submit=True, in_form=True)
PASSWORD = PageElement(7, "field", "Password", password=True, in_form=True)
CARD = PageElement(8, "field", "Number", autocomplete="cc-number", in_form=True)
ROUTER = PageElement(9, "link", "Router admin", href="http://192.168.1.1/")


def shop(browser: FakeBrowser, *elements: PageElement) -> None:
    browser.tab.show(
        "https://www.amazon.in/",
        "Amazon.in",
        "Deals on headphones",
        *(elements or (SEARCH, GO, DEALS, BUY)),
    )


def context(h: Harness) -> ToolContext:
    app = h.app
    return ToolContext(app.settings, h.channel, app.services, "session", "turn")


def test_page_data_lists_controls_before_text() -> None:
    from jarvis.tools.browser.session import PageSnapshot

    data = page_data(PageSnapshot("T", "https://x.test/", "words", True, [SEARCH, PASSWORD]))
    assert list(data) == ["title", "url", "elements", "text", "truncated"]
    assert data["elements"] == ["1 field: Search Amazon", "7 field: Password (password)"]


async def test_browser_open_returns_the_page_as_private_untrusted_data(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    h = make_app([reply("", ("browser_open", {"url": "amazon.in"})), reply("Opened.")])
    shop(fake_browser)
    result = await h.app.agent.run_turn("open amazon in your browser")
    assert fake_browser.tab.visits == ["https://amazon.in"]
    assert fake_browser.profiles[0] == "browser"
    outcome = result.outcomes[0]
    assert outcome.flags.private
    assert outcome.flags.untrusted
    tool_message = next(m for m in h.llm.requests[1] if m["role"] == "tool")
    assert 'untrusted="true"' in tool_message["content"]
    assert "Search Amazon" in tool_message["content"]


@pytest.mark.parametrize(
    "url", ["http://localhost:8765/", "http://192.168.1.1/", "web.whatsapp.com", "file:///C:/x"]
)
async def test_browser_open_blocks_local_addresses_and_whatsapp(
    make_app: MakeApp, fake_browser: FakeBrowser, url: str
) -> None:
    h = make_app([reply("", ("browser_open", {"url": url})), reply("No.")])
    await h.app.agent.run_turn(f"open {url}")
    assert fake_browser.tab.visits == []
    assert h.audit()[0]["decision"] == "blocked"


async def test_a_redirect_to_a_local_address_is_left_at_once(
    make_app: MakeApp, fake_browser: FakeBrowser, web: FakeWeb
) -> None:
    web.dns["evil.example"] = ["93.184.216.34"]
    fake_browser.tab.redirect = "http://127.0.0.1:11434/api/tags"
    h = make_app([reply("", ("browser_open", {"url": "https://evil.example/"})), reply("No.")])
    await h.app.agent.run_turn("open evil.example")
    assert fake_browser.tab.url == "about:blank"
    assert "local network" in (h.audit()[0]["error"] or "")


async def test_browser_read_needs_an_open_page(make_app: MakeApp) -> None:
    h = make_app([reply("", ("browser_read", {})), reply("Nothing open.")])
    await h.app.agent.run_turn("read the page")
    assert "browser_open first" in (h.audit()[0]["error"] or "")


async def test_clicking_a_link_by_number_runs_directly(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser)
    h = make_app([reply("", ("browser_click", {"target": "3"})), reply("Opened deals.")])
    await h.app.agent.run_turn("click today's deals")
    assert fake_browser.tab.clicks == [3]
    assert h.channel.requests == []
    assert h.audit()[0]["args_json"] == '{"target": "#3 Today\'s Deals"}'


async def test_clicking_buy_asks_and_no_means_no(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser)
    h = make_app(
        [reply("", ("browser_click", {"target": "buy now"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("buy it")
    assert fake_browser.tab.clicks == []
    assert h.channel.requests[0].summary == "Click the Buy Now button on www.amazon.in"


async def test_a_form_submit_button_asks_but_a_search_button_does_not(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser, SEARCH, GO, EMAIL, SIGN_UP)
    h = make_app(
        [
            reply("", ("browser_click", {"target": "go"})),
            reply("", ("browser_click", {"target": "create account"})),
            reply("Done."),
        ],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("search, then sign up")
    assert fake_browser.tab.clicks == [2]
    assert len(h.channel.requests) == 1
    assert h.channel.requests[0].reason == "it submits a form on the page"


async def test_links_to_local_addresses_are_blocked(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser, ROUTER)
    h = make_app([reply("", ("browser_click", {"target": "9"})), reply("No.")])
    await h.app.agent.run_turn("open the router page")
    assert fake_browser.tab.clicks == []
    assert h.audit()[0]["decision"] == "blocked"


async def test_click_refuses_when_the_page_changed_after_the_confirmation(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser, PageElement(3, "link", "Something else"))
    h = make_app()
    with pytest.raises(ToolError, match="page changed"):
        await browser_click(context(h), target="#3 Today's Deals")


async def test_typing_a_search_and_pressing_enter_runs_directly(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser)
    args = {"text": "noise cancelling headphones", "submit": True}
    h = make_app([reply("", ("browser_type", args)), reply("Searched.")])
    await h.app.agent.run_turn("search for headphones")
    assert fake_browser.tab.fills == [(1, "noise cancelling headphones", True)]
    assert h.channel.requests == []


async def test_pressing_enter_in_another_form_asks(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser, EMAIL, SIGN_UP)
    args = {"text": "me@example.com", "target": "email", "submit": True}
    h = make_app([reply("", ("browser_type", args)), reply("Okay.")], channel=FakeChannel(False))
    await h.app.agent.run_turn("sign me up")
    assert fake_browser.tab.fills == []
    assert h.channel.requests[0].reason == "pressing Enter here submits a form"


@pytest.mark.parametrize("field", ["7", "8"])
async def test_passwords_and_card_numbers_are_never_typed(
    make_app: MakeApp, fake_browser: FakeBrowser, field: str
) -> None:
    shop(fake_browser, PASSWORD, CARD)
    h = make_app([reply("", ("browser_type", {"text": "secret", "target": field})), reply("No.")])
    await h.app.agent.run_turn("type it")
    assert fake_browser.tab.fills == []
    assert h.audit()[0]["decision"] == "blocked"


async def test_type_without_a_target_needs_one_clear_field(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser, EMAIL, PageElement(10, "field", "Name"))
    h = make_app([reply("", ("browser_type", {"text": "Preeyas"})), reply("Which one?")])
    await h.app.agent.run_turn("type my name")
    assert "Which field?" in (h.audit()[0]["error"] or "")


async def test_typing_after_reading_pages_with_private_data_asks(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    """A page could tell the model to type your data into its search box: egress asks."""
    shop(fake_browser)
    h = make_app(
        [
            reply("", ("browser_read", {})),
            reply("", ("browser_type", {"text": "my notes", "submit": True})),
            reply("Okay."),
        ],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("search my notes on amazon")
    assert fake_browser.tab.fills == []
    assert h.channel.requests[0].reason == EXFILTRATION_REASON


async def test_open_and_search_in_one_call(make_app: MakeApp, fake_browser: FakeBrowser) -> None:
    shop(fake_browser)
    args = {"url": "amazon.in", "search": "wireless earbuds"}
    h = make_app([reply("", ("browser_open", args)), reply("Here are the results.")])
    result = await h.app.agent.run_turn("search amazon for earbuds in your browser")
    assert fake_browser.tab.fills == [(1, "wireless earbuds", True)]
    assert h.channel.requests == []
    assert result.outcomes[0].result.speech == "Searched amazon.in for wireless earbuds."


async def test_open_and_search_needs_a_real_search_box(
    make_app: MakeApp, fake_browser: FakeBrowser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.tools.browser.tools.SEARCH_BOX_TRIES", 1)
    shop(fake_browser, EMAIL, SIGN_UP)
    args = {"url": "example.com", "search": "anything"}
    h = make_app([reply("", ("browser_open", args)), reply("No search box.")])
    await h.app.agent.run_turn("search example.com")
    assert fake_browser.tab.fills == []
    assert "no search box" in (h.audit()[0]["error"] or "")


async def test_the_next_step_hint_sits_outside_the_page_content(
    make_app: MakeApp, fake_browser: FakeBrowser
) -> None:
    shop(fake_browser)
    h = make_app([reply("", ("browser_open", {"url": "amazon.in"})), reply("Opened.")])
    await h.app.agent.run_turn("open amazon in your browser")
    content = next(m for m in h.llm.requests[1] if m["role"] == "tool")["content"]
    wrapped, after = content.split("</tool_result>")
    assert NEXT_STEP_HINT not in wrapped
    assert after.strip() == NEXT_STEP_HINT
