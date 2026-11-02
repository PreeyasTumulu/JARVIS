"""market_data: symbol resolution, the provider chain, caching, and spoken answers."""

from __future__ import annotations

import json
from typing import Any

from jarvis.config import MarketSettings
from jarvis.storage.db import Database
from jarvis.tools.data.http import ApiClient
from jarvis.tools.data.market import (
    Listing,
    MarketData,
    Price,
    choose_listing,
    clean_query,
    spoken_name,
)
from tests.conftest import FakeWeb, FakeYahoo, Harness, MakeApp, reply

RELIANCE = Listing("RELIANCE.NS", "Reliance Industries Limited", "NSE", "EQUITY")
INFOSYS = [
    Listing("INFY", "Infosys Limited", "NYSE", "EQUITY"),
    Listing("INFY.NS", "Infosys Limited", "NSE", "EQUITY"),
    Listing("INFY.BO", "Infosys Limited", "Bombay", "EQUITY"),
]
APPLE = Listing("AAPL", "Apple Inc.", "NASDAQ", "EQUITY")


def tool_payload(h: Harness) -> dict[str, Any]:
    """What the model saw for the last tool call."""
    message = [m for m in h.app.agent.messages if m["role"] == "tool"][-1]
    payload: dict[str, Any] = json.loads(message["content"].splitlines()[0])
    return payload


def test_choose_listing_prefers_the_home_exchange_for_the_same_company() -> None:
    prefer = (".NS", ".BO")
    assert choose_listing(INFOSYS, "infosys", prefer).symbol == "INFY.NS"  # type: ignore[union-attr]
    assert choose_listing(INFOSYS, "infosys").symbol == "INFY"  # type: ignore[union-attr]
    exact = choose_listing(INFOSYS, "INFY.BO", prefer)
    assert exact is not None
    assert exact.symbol == "INFY.BO"  # the user named an exact listing
    nifty = [
        Listing("^NSEI", "NIFTY 50", "NSE", "INDEX"),
        Listing("NIFTYBEES.NS", "Nippon India ETF Nifty 50 BeES", "NSE", "EQUITY"),
    ]
    index = choose_listing(nifty, "nifty 50", prefer)
    assert index is not None
    assert index.symbol == "^NSEI"  # the ETF is a different product, not the same company
    assert choose_listing([Listing("BTC-USD", "Bitcoin", "", "CRYPTOCURRENCY")], "btc") is None


def test_names_and_queries_are_cleaned_for_speech() -> None:
    assert spoken_name("Reliance Industries Limited") == "Reliance Industries"
    assert spoken_name("APPLE INC.") == "Apple"
    assert spoken_name("NIFTY 50") == "Nifty 50"
    assert spoken_name("TSLA") == "TSLA"
    assert clean_query("Reliance share price") == "Reliance"
    assert clean_query("stock") == "stock"


def test_provider_chain_order(yahoo: FakeYahoo) -> None:
    api = ApiClient(Database(":memory:"))
    env = {"FINNHUB_API_KEY": "f", "TWELVEDATA_API_KEY": "t"}
    market = MarketData(api, MarketSettings(), yahoo=yahoo, env=env)

    def names(symbol: str) -> list[str]:
        return [provider.name for provider in market.chain(symbol)]

    assert names("AAPL") == ["finnhub", "twelvedata", "yfinance"]  # no Alpha Vantage key
    assert names("RELIANCE.NS") == ["yfinance", "twelvedata"]  # Finnhub's free tier is US only
    assert names("^NSEI") == ["yfinance"]
    keyless = MarketData(api, MarketSettings(), yahoo=yahoo, env={})
    assert [provider.name for provider in keyless.providers] == ["yfinance"]


async def test_market_data_speaks_a_short_answer(make_app: MakeApp, yahoo: FakeYahoo) -> None:
    yahoo.listings["reliance"] = [RELIANCE, Listing("EZRA", "Reliance Global Group, Inc.")]
    yahoo.prices["RELIANCE.NS"] = Price(1174.6, "INR", 7.9, 0.677)
    h = make_app([reply("", ("market_data", {"query": "Reliance"})), reply("ok")])
    await h.app.agent.run_turn("what's reliance trading at")
    payload = tool_payload(h)
    assert payload["summary"] == "Reliance Industries is at 1,174.60 rupees, up 0.7 percent today."
    assert payload["data"]["provider"] == "yfinance"
    assert (
        "untrusted" not in [m for m in h.app.agent.messages if m["role"] == "tool"][-1]["content"]
    )


async def test_second_question_is_served_from_the_cache(
    make_app: MakeApp, yahoo: FakeYahoo
) -> None:
    yahoo.listings["apple"] = [APPLE]
    yahoo.prices["AAPL"] = Price(342.96, "USD", 1.69, 0.495)
    call = ("market_data", {"query": "Apple"})
    h = make_app([reply("", call), reply("ok"), reply("", call), reply("ok")])
    await h.app.agent.run_turn("price of apple")
    await h.app.agent.run_turn("price of apple")
    assert yahoo.searches == ["Apple"]  # the symbol is cached for a month
    assert yahoo.quotes == ["AAPL"]  # the quote for a minute
    assert all(row["ok"] for row in h.audit())


async def test_keyed_provider_first_then_fallback(
    make_app: MakeApp, web: FakeWeb, yahoo: FakeYahoo
) -> None:
    yahoo.listings["apple"] = [APPLE]
    yahoo.prices["AAPL"] = Price(342.96, "USD", 1.69, 0.495)
    env = {"FINNHUB_API_KEY": "secret"}
    web.route("finnhub.io/api/v1/quote", {"c": 343.1, "d": 1.8, "dp": 0.53})
    h = make_app([reply("", ("market_data", {"query": "Apple"})), reply("ok")], env=env)
    await h.app.agent.run_turn("price of apple")
    assert tool_payload(h)["data"]["provider"] == "finnhub"
    assert web.requests[0].headers["X-Finnhub-Token"] == "secret"
    assert "secret" not in str(web.requests[0].url)

    web.route("finnhub.io/api/v1/quote", status=503, content=b"down")
    h2 = make_app([reply("", ("market_data", {"query": "Apple"})), reply("ok")], env=env)
    await h2.app.agent.run_turn("price of apple")
    assert tool_payload(h2)["data"]["provider"] == "yfinance"


async def test_offline_says_so_instead_of_crashing(make_app: MakeApp, yahoo: FakeYahoo) -> None:
    yahoo.offline = True
    h = make_app([reply("", ("market_data", {"query": "Reliance"})), reply("No internet.")])
    result = await h.app.agent.run_turn("what's reliance trading at")
    assert result.text == "No internet."
    assert "can't reach the internet" in h.audit()[0]["error"]


async def test_unknown_company(make_app: MakeApp) -> None:
    h = make_app([reply("", ("market_data", {"query": "Zomato"})), reply("Not found.")])
    await h.app.agent.run_turn("price of zomato")
    assert "couldn't find a stock or index called 'Zomato'" in h.audit()[0]["error"]


async def test_config_aliases_skip_to_the_ticker(make_app: MakeApp, yahoo: FakeYahoo) -> None:
    yahoo.listings["^nsei"] = [Listing("^NSEI", "NIFTY 50", "NSE", "INDEX")]
    yahoo.prices["^NSEI"] = Price(22622.7, "INR", -99.2, -0.437)
    h = make_app([reply("", ("market_data", {"query": "nifty"})), reply("ok")])
    await h.app.agent.run_turn("how is the nifty doing")
    assert yahoo.searches == ["^NSEI"]
    assert tool_payload(h)["summary"] == "Nifty 50 is at 22,623, down 0.4 percent today."


async def test_unclear_failures_check_the_connection(
    make_app: MakeApp, web: FakeWeb, yahoo: FakeYahoo
) -> None:
    yahoo.listings["apple"] = [APPLE]
    yahoo.broken = True
    call = ("market_data", {"query": "Apple"})
    h = make_app([reply("", call), reply("ok")])
    await h.app.agent.run_turn("price of apple")
    assert "can't reach the internet" in h.audit()[0]["error"]  # the check failed too

    web.route("www.msftconnecttest.com/connecttest.txt", content=b"Microsoft Connect Test")
    h2 = make_app([reply("", call), reply("ok")])
    await h2.app.agent.run_turn("price of apple")
    assert "not answering right now" in h2.audit()[0]["error"]
