"""search_site: a named site's own search page, opened in the default browser."""

from __future__ import annotations

import pytest

from jarvis.tools.web.sites import SITES, resolve_site, search_address
from tests.conftest import FakeDesktop, MakeApp, reply


@pytest.mark.parametrize(
    ("site", "query", "url"),
    [
        ("youtube", "lofi music", "https://www.youtube.com/results?search_query=lofi+music"),
        ("Wikipedia", "Alan Turing", "https://en.wikipedia.org/w/index.php?search=Alan+Turing"),
        ("maps", "cafes near me", "https://www.google.com/maps/search/cafes%20near%20me"),
        ("amazon.com", "usb c cable", "https://www.amazon.in/s?k=usb+c+cable"),
        ("Stackoverflow", "asyncio timeout", "https://stackoverflow.com/search?q=asyncio+timeout"),
    ],
)
async def test_named_sites_open_their_search_page(
    make_app: MakeApp, desktop: FakeDesktop, site: str, query: str, url: str
) -> None:
    h = make_app([reply("", ("search_site", {"site": site, "query": query})), reply("Done.")])
    await h.app.agent.run_turn(f"search {site} for {query}")
    assert desktop.urls == [url]
    assert h.audit()[0]["decision"] == "auto"


async def test_an_unknown_site_is_not_guessed(make_app: MakeApp, desktop: FakeDesktop) -> None:
    h = make_app([reply("", ("search_site", {"site": "myintranet", "query": "x"})), reply("No.")])
    result = await h.app.agent.run_turn("search myintranet for x")
    assert desktop.urls == []
    assert "browser_open" in (result.outcomes[0].result.error or "")


async def test_config_can_add_a_site(make_app: MakeApp, desktop: FakeDesktop) -> None:
    h = make_app(
        [reply("", ("search_site", {"site": "jira", "query": "login bug"})), reply("ok")],
        overrides={
            "search": {"sites": {"Jira": "https://acme.atlassian.net/issues/?jql=text~{p}"}}
        },
    )
    await h.app.agent.run_turn("search jira for login bug")
    assert desktop.urls == ["https://acme.atlassian.net/issues/?jql=text~login%20bug"]


def test_aliases_and_fuzzy_names() -> None:
    assert resolve_site("yt", SITES) == "youtube"
    assert resolve_site("twitter", SITES) == "x"
    assert resolve_site("youtub", SITES) == "youtube"
    assert resolve_site("banana republic", SITES) is None
    assert search_address(SITES["spotify"], "AC/DC") == "https://open.spotify.com/search/AC%2FDC"


def test_routing_offers_search_site_when_a_site_is_named() -> None:
    from jarvis.core.tool_routing import select_tools
    from jarvis.tools.catalog import build_registry

    names = {t.name for t in select_tools("search youtube for lofi music", build_registry())}
    assert "search_site" in names
