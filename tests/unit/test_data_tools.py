"""Currency, crypto, and weather tools against canned API answers, plus spoken formatting."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from jarvis.tools.base import ToolError
from jarvis.tools.data.currency import currency_code
from jarvis.tools.data.spoken import money, number, percent_change
from jarvis.tools.data.weather import day_index
from tests.conftest import FakeWeb, Harness, MakeApp, reply

FRANKFURTER = "api.frankfurter.dev/v1/latest"
ER_API = "open.er-api.com/v6/latest"
GEOCODE = "geocoding-api.open-meteo.com/v1/search"
FORECAST = "api.open-meteo.com/v1/forecast"
COINGECKO = "api.coingecko.com/api/v3"

HYDERABAD = {
    "name": "Hyderabad",
    "latitude": 17.384,
    "longitude": 78.456,
    "country": "India",
    "country_code": "IN",
    "admin1": "Telangana",
}
FORECAST_DATA = {
    "current": {
        "temperature_2m": 27.4,
        "apparent_temperature": 30.1,
        "relative_humidity_2m": 70,
        "weather_code": 2,
        "wind_speed_10m": 9.0,
    },
    "daily": {
        "time": [f"2026-10-{day}" for day in range(15, 22)],
        "weather_code": [2, 61, 3, 0, 0, 80, 95],
        "temperature_2m_max": [31.2, 29.6, 30, 31, 32, 30, 28],
        "temperature_2m_min": [21.8, 21.1, 21, 22, 22, 21, 20],
        "precipitation_probability_max": [10, 70, 20, 0, 0, 40, 90],
    },
}


def summary(h: Harness) -> str:
    message = [m for m in h.app.agent.messages if m["role"] == "tool"][-1]
    payload: dict[str, Any] = json.loads(message["content"])
    assert payload["ok"], payload
    return str(payload["summary"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1174.6, "1,174.60"),
        (22622.7, "22,623"),
        (342.0, "342"),
        (0.5, "0.5"),
        (0.0001234, "0.000123"),
    ],
)
def test_number(value: float, expected: str) -> None:
    assert number(value) == expected


def test_money_and_change() -> None:
    assert money(7704912, "INR") == "77.05 lakh rupees"
    assert money(25_000_000, "INR") == "2.50 crore rupees"
    assert money(2_500_000, "USD") == "2.50 million dollars"
    assert money(1, "USD") == "1 dollar"
    assert money(12.5, "XYZ") == "12.50 XYZ"
    assert percent_change(1.234) == "up 1.2 percent today"
    assert percent_change(-0.04) == "unchanged today"
    assert percent_change(None) is None


def test_currency_names() -> None:
    assert currency_code("rupees") == "INR"
    assert currency_code("Dollars") == "USD"
    assert currency_code("yen") == "JPY"
    assert currency_code("aed") == "AED"
    assert currency_code("british pounds") == "GBP"
    with pytest.raises(ToolError, match="don't know the currency"):
        currency_code("space credits")


async def test_convert_currency(make_app: MakeApp, web: FakeWeb) -> None:
    web.route(
        FRANKFURTER, {"amount": 1.0, "base": "USD", "date": "2026-10-14", "rates": {"INR": 95.16}}
    )
    call = ("convert_currency", {"amount": 100, "from_currency": "dollars", "to_currency": "INR"})
    h = make_app([reply("", call), reply("ok")])
    await h.app.agent.run_turn("convert 100 dollars to rupees")
    assert summary(h) == "100 dollars is 9,516 rupees."
    assert web.requests[0].url.params["base"] == "USD"


async def test_currency_falls_back_for_rates_the_ecb_lacks(make_app: MakeApp, web: FakeWeb) -> None:
    web.route(FRANKFURTER, {"base": "INR", "date": "2026-10-14", "rates": {"USD": 0.0105}})
    web.route(
        ER_API,
        {
            "result": "success",
            "time_last_update_utc": "Thu, 15 Oct 2026 00:02:31",
            "rates": {"AED": 0.0386},
        },
    )
    call = (
        "convert_currency",
        {"amount": 1000, "from_currency": "rupees", "to_currency": "dirhams"},
    )
    h = make_app([reply("", call), reply("ok")])
    await h.app.agent.run_turn("1000 rupees in dirhams")
    assert summary(h) == "1,000 rupees is 38.60 dirhams."
    assert json.loads(h.audit()[0]["result_json"])["source"] == "open.er-api.com"


async def test_currency_offline(make_app: MakeApp) -> None:
    call = ("convert_currency", {"amount": 5, "from_currency": "EUR", "to_currency": "INR"})
    h = make_app([reply("", call), reply("ok")])
    await h.app.agent.run_turn("5 euros in rupees")
    assert "can't reach the internet" in h.audit()[0]["error"]


async def test_crypto_price_in_rupees(make_app: MakeApp, web: FakeWeb) -> None:
    web.route(
        f"{COINGECKO}/simple/price",
        {"bitcoin": {"inr": 7704912, "inr_24h_change": -3.06}},
    )
    h = make_app(
        [reply("", ("crypto_price", {"coin": "BTC", "currency": "rupees"})), reply("ok")],
        env={"COINGECKO_API_KEY": "demo"},
    )
    await h.app.agent.run_turn("bitcoin in rupees")
    assert summary(h) == ("Bitcoin is at 77.05 lakh rupees, down 3.1 percent in the last 24 hours.")
    request = web.requests[0]
    assert request.url.params["vs_currencies"] == "inr"
    assert request.headers["x-cg-demo-api-key"] == "demo"
    assert web.hits(f"{COINGECKO}/search") == 0  # common coins need no search


async def test_crypto_search_for_other_coins(make_app: MakeApp, web: FakeWeb) -> None:
    web.route(f"{COINGECKO}/search", {"coins": [{"id": "pepe", "name": "Pepe", "symbol": "PEPE"}]})
    web.route(f"{COINGECKO}/simple/price", {"pepe": {"usd": 0.00001234, "usd_24h_change": 5.0}})
    h = make_app([reply("", ("crypto_price", {"coin": "pepe"})), reply("ok")])
    await h.app.agent.run_turn("price of pepe coin")
    assert summary(h) == "Pepe is at 0.0000123 dollars, up 5.0 percent in the last 24 hours."
    assert "x-cg-demo-api-key" not in web.requests[0].headers


def test_day_index() -> None:
    thursday = date(2026, 10, 15)
    assert day_index("today", thursday) == 0
    assert day_index("now", thursday) == 0
    assert day_index("tomorrow", thursday) == 1
    assert day_index("day after tomorrow", thursday) == 2
    assert day_index("saturday", thursday) == 2
    assert day_index("this friday", thursday) == 1
    assert day_index("thursday", thursday) == 0
    assert day_index("next thursday", thursday) == 7
    assert day_index("2026-10-19", thursday) == 4
    with pytest.raises(ToolError):
        day_index("whenever", thursday)


async def test_weather_now_uses_the_home_city(make_app: MakeApp, web: FakeWeb) -> None:
    web.route(GEOCODE, {"results": [HYDERABAD]})
    web.route(FORECAST, FORECAST_DATA)
    h = make_app(
        [reply("", ("weather", {})), reply("ok")], overrides={"weather": {"home": "Hyderabad"}}
    )
    await h.app.agent.run_turn("what's the weather")
    assert summary(h) == (
        "In Hyderabad it's 27 degrees with partly cloudy skies, feels like 30. "
        "Today: 22 to 31 degrees."
    )


async def test_weather_tomorrow_and_cache(make_app: MakeApp, web: FakeWeb) -> None:
    web.route(GEOCODE, {"results": [HYDERABAD]})
    web.route(FORECAST, FORECAST_DATA)
    call = ("weather", {"place": "Hyderabad", "day": "tomorrow"})
    h = make_app([reply("", call), reply("ok"), reply("", call), reply("ok")])
    await h.app.agent.run_turn("weather tomorrow in hyderabad")
    assert summary(h) == (
        "Tomorrow in Hyderabad: light rain, 21 to 30 degrees, 70 percent chance of rain."
    )
    await h.app.agent.run_turn("weather tomorrow in hyderabad")
    assert web.hits(GEOCODE) == 1
    assert web.hits(FORECAST) == 1


async def test_weather_country_qualifier(make_app: MakeApp, web: FakeWeb) -> None:
    london_ca = {"name": "London", "latitude": 42.98, "longitude": -81.23, "country": "Canada"}
    london_uk = {
        "name": "London",
        "latitude": 51.5,
        "longitude": -0.12,
        "country": "United Kingdom",
        "country_code": "GB",
    }
    web.route(GEOCODE, {"results": [london_ca, london_uk]})
    web.route(FORECAST, FORECAST_DATA)
    h = make_app([reply("", ("weather", {"place": "London, UK"})), reply("ok")])
    await h.app.agent.run_turn("weather in london uk")
    assert web.requests[-1].url.params["latitude"] == "51.5"


async def test_weather_without_a_city_asks(make_app: MakeApp) -> None:
    h = make_app([reply("", ("weather", {"place": "here"})), reply("Which city?")])
    await h.app.agent.run_turn("is it going to rain")
    assert "no home city is set" in h.audit()[0]["error"]
