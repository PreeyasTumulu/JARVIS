"""Weather now and for the next 7 days from Open-Meteo (free, no key), with its geocoder."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.data.http import ApiClient, ProviderError, explain_failure
from jarvis.tools.registry import tool

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
PLACE_TTL_S = 30 * 24 * 3600
FORECAST_TTL_S = 15 * 60
FORECAST_DAYS = 7

# WMO weather interpretation codes, as Open-Meteo documents them.
WMO_CODES = {
    0: "clear skies",
    1: "mainly clear skies",
    2: "partly cloudy skies",
    3: "overcast skies",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "light freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "light snow showers",
    86: "snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with heavy hail",
}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_NOW_WORDS = {"", "now", "today", "currently", "right now", "tonight", "this evening"}
_HERE_WORDS = {"here", "home", "my location", "my city", "outside", "current location", "local"}


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    country: str
    latitude: float
    longitude: float


def describe(code: Any) -> str:
    try:
        return WMO_CODES.get(int(code), "mixed weather")
    except (TypeError, ValueError):
        return "mixed weather"


# Former or everyday names the geocoder does not know. Open-Meteo lists Bengaluru only as
# "Bengaluru", so "Bangalore" matched a neighbourhood of Karachi.
CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "gurgaon": "Gurugram",
    "poona": "Pune",
    "mysore": "Mysuru",
    "mangalore": "Mangaluru",
    "trivandrum": "Thiruvananthapuram",
    "cochin": "Kochi",
    "baroda": "Vadodara",
    "benares": "Varanasi",
    "banaras": "Varanasi",
    "pondicherry": "Puducherry",
    "simla": "Shimla",
    "belgaum": "Belagavi",
    "hubli": "Hubballi",
    "vizag": "Visakhapatnam",
    "peking": "Beijing",
    "saigon": "Ho Chi Minh City",
    "kiev": "Kyiv",
    "nyc": "New York",
    "sf": "San Francisco",
}


def _rank(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Real cities first (not PPLX, a part of a city), then the most populous."""
    cities = [r for r in results if r.get("feature_code") != "PPLX"] or results
    return sorted(cities, key=lambda r: -int(r.get("population") or 0))


async def find_place(api: ApiClient, text: str) -> Place:
    """Geocode "Hyderabad" or "London, UK". The part after a comma narrows by country or state."""
    query = " ".join(text.split())
    key = f"place2:{query.casefold()}"  # place2: lookups before the city aliases were wrong
    hit = api.cache.get(key)
    if hit is not None:
        return Place(**hit)
    name, _, qualifier = query.partition(",")
    name = CITY_ALIASES.get(name.strip().casefold(), name)
    try:
        data = await api.get_json(
            "open-meteo",
            GEOCODE_URL,
            params={"name": name.strip(), "count": 10, "language": "en", "format": "json"},
        )
    except ProviderError as exc:
        raise ToolError(explain_failure([exc], f"the location of {query}")) from exc
    results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
    if qualifier.strip():
        results = [r for r in results if _matches(r, qualifier.strip().casefold())]
    if not results:
        raise ToolError(f"I couldn't find a place called {query}.")
    best = _rank(results)[0]
    place = Place(
        name=str(best.get("name", name)),
        region=str(best.get("admin1", "")),
        country=str(best.get("country", "")),
        latitude=float(best["latitude"]),
        longitude=float(best["longitude"]),
    )
    api.cache.put(key, asdict(place), PLACE_TTL_S)
    return place


def _matches(result: dict[str, Any], qualifier: str) -> bool:
    country = str(result.get("country", ""))
    initials = "".join(word[0] for word in country.split() if word).casefold()
    fields = [country, str(result.get("admin1", "")), str(result.get("country_code", ""))]
    return qualifier == initials or any(f.casefold().startswith(qualifier) for f in fields if f)


async def forecast(api: ApiClient, place: Place, units: str) -> dict[str, Any]:
    async def fetch() -> dict[str, Any]:
        params: dict[str, Any] = {
            "latitude": place.latitude,
            "longitude": place.longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,"
            "wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": FORECAST_DAYS,
        }
        if units == "fahrenheit":
            params["temperature_unit"] = "fahrenheit"
        data = await api.get_json("open-meteo", FORECAST_URL, params=params)
        return {"current": data.get("current") or {}, "daily": data.get("daily") or {}}

    key = f"weather:{place.latitude:.2f},{place.longitude:.2f}:{units}"
    try:
        result: dict[str, Any] = await api.cached(key, FORECAST_TTL_S, fetch)
    except ProviderError as exc:
        raise ToolError(explain_failure([exc], f"the weather for {place.name}")) from exc
    return result


def day_index(day: str, first: date) -> int:
    """Days after the forecast's first day (today, in the place's own time zone)."""
    text = " ".join(day.casefold().replace("the ", "").split())
    if text in _NOW_WORDS:
        return 0
    if "day after tomorrow" in text:
        return 2
    if text.startswith("tomorrow"):
        return 1
    for number, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", text):
            ahead = (number - first.weekday()) % 7
            return 7 if ahead == 0 and "next" in text else ahead
    if text.startswith("this "):  # this morning, this afternoon
        return 0
    try:
        return (date.fromisoformat(text) - first).days
    except ValueError:
        raise ToolError(
            "I can give the weather for today, tomorrow, a weekday, or a date in the next week."
        ) from None


def _round(value: Any) -> int | None:
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def spoken_weather(place: Place, data: dict[str, Any], index: int, first: date) -> str:
    daily = data["daily"]

    def at(field: str) -> Any:
        values = daily.get(field) or []
        return values[index] if index < len(values) else None

    low, high = _round(at("temperature_2m_min")), _round(at("temperature_2m_max"))
    rain = _round(at("precipitation_probability_max"))
    span = f"{low} to {high} degrees" if low is not None and high is not None else ""
    rain_text = f", {rain} percent chance of rain" if rain is not None and rain >= 20 else ""

    current = data["current"]
    if index == 0 and current:
        temp = _round(current.get("temperature_2m"))
        feels = _round(current.get("apparent_temperature"))
        text = f"In {place.name} it's {temp} degrees with {describe(current.get('weather_code'))}"
        if feels is not None and temp is not None and abs(feels - temp) >= 2:
            text += f", feels like {feels}"
        today = f" Today: {span}{rain_text}." if span else ""
        return f"{text}.{today}"

    target = first + timedelta(days=index)
    when = "Tomorrow" if index == 1 else f"On {target:%A}"
    return f"{when} in {place.name}: {describe(at('weather_code'))}, {span}{rain_text}."


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=20)
async def weather(ctx: ToolContext, place: str | None = None, day: str = "today") -> ToolResult:
    """Get the current weather or the forecast for up to a week ahead.

    Args:
        place: A city, for example "Hyderabad" or "London, UK". Leave it out for the user's home.
        day: "today", "tomorrow", a weekday such as "friday", or a date like "2026-10-20".
    """
    wanted = (place or "").strip()
    if wanted.casefold() in _HERE_WORDS:
        wanted = ""
    where = wanted or ctx.settings.weather.home.strip()
    if not where:
        raise ToolError(
            "No city was named and no home city is set. Ask the user which city; they can set "
            "weather.home in config/local.toml so they don't have to say it."
        )
    api = ctx.services.data.api
    found = await find_place(api, where)
    data = await forecast(api, found, ctx.settings.weather.units)
    dates = data["daily"].get("time") or []
    if not dates:
        raise ToolError("The weather service sent no forecast.")
    first = date.fromisoformat(dates[0])
    index = day_index(day, first)
    if not 0 <= index < len(dates):
        raise ToolError("The forecast only covers the next 7 days.")
    result = {
        "place": asdict(found),
        "date": dates[index],
        "units": ctx.settings.weather.units,
        "daily": {key: values[index] for key, values in data["daily"].items() if key != "time"},
    }
    if index == 0:
        result["current"] = data["current"]
    return ToolResult.success(data=result, speech=spoken_weather(found, data, index, first))
