"""Stock, ETF, and index prices from a chain of providers, with symbol search and caching.

Providers are tried in the configured order, skipping the ones without an API key (Finnhub,
Twelve Data, Alpha Vantage); yfinance needs no key and comes last. Symbols with an exchange
suffix (`RELIANCE.NS`) and index symbols (`^NSEI`) go to yfinance first, because the free tiers of
the others cover mostly US stocks. Spoken names become tickers through config aliases, then
Yahoo's symbol search, cached for a month.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from jarvis.config import MarketSettings
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.data.http import ApiClient, ProviderError
from jarvis.tools.data.spoken import money, number, percent_change
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

QUOTE_TTL_S = 60
SYMBOL_TTL_S = 30 * 24 * 3600
KEY_ENV = {
    "finnhub": "FINNHUB_API_KEY",
    "twelvedata": "TWELVEDATA_API_KEY",
    "alphavantage": "ALPHAVANTAGE_API_KEY",
}

_LISTED = {"EQUITY", "ETF", "INDEX", "MUTUALFUND", "FUTURE"}
_TWELVE_EXCHANGES = {".NS": "NSE", ".BO": "BSE"}
_SUFFIX = re.compile(r"\.[A-Z]{1,3}$")
_TICKER = re.compile(r"^\^?[A-Za-z0-9]{1,10}(?:[.\-=][A-Za-z]{1,3})?$")
_FILLER = re.compile(
    r"\b(stock|stocks|share|shares|price|prices|ticker|quote|the|of|today|now|current)\b", re.I
)
_NAME_TAIL = re.compile(
    r"[,.]?\s+(inc|incorporated|ltd|limited|corp|corporation|plc|co|company|n\.?v|s\.?a|ag)\.?$",
    re.I,
)


@dataclass(frozen=True)
class Listing:
    symbol: str
    name: str
    exchange: str = ""
    kind: str = ""


@dataclass(frozen=True)
class Price:
    price: float
    currency: str | None
    change: float | None = None
    change_pct: float | None = None


@dataclass(frozen=True)
class Quote:
    symbol: str
    name: str
    price: float
    currency: str | None
    change: float | None
    change_pct: float | None
    provider: str

    def speech(self) -> str:
        # An index is in points, not money: "Nifty 50 is at 22,623".
        value = number(self.price) if is_index(self.symbol) else money(self.price, self.currency)
        text = f"{self.name} is at {value}"
        movement = percent_change(self.change_pct)
        return f"{text}, {movement}." if movement else f"{text}."


class QuoteProvider(Protocol):
    name: str

    def supports(self, symbol: str) -> bool: ...
    async def price(self, api: ApiClient, symbol: str) -> Price: ...


class SymbolSearch(Protocol):
    async def search(self, api: ApiClient, query: str) -> list[Listing]: ...


class SearchingProvider(QuoteProvider, SymbolSearch, Protocol):
    """A provider that can also search symbols (yfinance, or a fake in tests)."""


def split_suffix(symbol: str) -> tuple[str, str | None]:
    """ "RELIANCE.NS" to ("RELIANCE", ".NS"). Share classes use a hyphen on Yahoo (BRK-B)."""
    match = _SUFFIX.search(symbol)
    if match is None:
        return symbol, None
    return symbol[: match.start()], match.group(0)


def is_index(symbol: str) -> bool:
    return symbol.startswith("^")


def spoken_name(name: str) -> str:
    """ "Reliance Industries Limited" to "Reliance Industries", "APPLE INC." to "Apple"."""
    text = " ".join(name.split())[:80]
    if text.isupper() and " " in text:  # a lone ticker such as TCS stays as it is
        text = text.title()
    while True:
        shorter = _NAME_TAIL.sub("", text).strip()
        if shorter == text or not shorter:
            return text
        text = shorter


def normalize(text: str) -> str:
    return " ".join(text.casefold().replace("'s", "").split())


def clean_query(text: str) -> str:
    """Drop words like "stock" and "price" that the model sometimes leaves in the name."""
    cleaned = " ".join(_FILLER.sub(" ", text).split())
    return cleaned or text.strip()


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def choose_listing(
    listings: list[Listing], query: str, prefer: tuple[str, ...] = ()
) -> Listing | None:
    """The listing a person most likely means: an exact ticker, else search's first result.

    When the same company is also listed on a preferred exchange (for example NSE for Infosys,
    whose US share INFY ranks first), that listing wins.
    """
    usable = [item for item in listings if not item.kind or item.kind.upper() in _LISTED]
    if not usable:
        return None
    wanted = query.strip().upper()
    choice = next((item for item in usable if item.symbol.upper() == wanted), usable[0])
    if choice.symbol.upper() == wanted and "." in wanted:
        return choice  # the user named an exact listing
    company = normalize(choice.name)
    for suffix in prefer:
        twin = next(
            (
                item
                for item in usable
                if item.symbol.upper().endswith(suffix.upper()) and normalize(item.name) == company
            ),
            None,
        )
        if twin is not None:
            return twin
    return choice


class Finnhub:
    """US stocks on the free tier. Key in FINNHUB_API_KEY."""

    name = "finnhub"

    def __init__(self, key: str) -> None:
        self._key = key

    def supports(self, symbol: str) -> bool:
        return not is_index(symbol) and split_suffix(symbol)[1] is None and "=" not in symbol

    async def price(self, api: ApiClient, symbol: str) -> Price:
        data = await api.get_json(
            self.name,
            "https://finnhub.io/api/v1/quote",
            params={"symbol": symbol.replace("-", ".")},
            headers={"X-Finnhub-Token": self._key},
        )
        price = _num(data.get("c")) if isinstance(data, dict) else None
        if not price:
            raise ProviderError(self.name, f"no price for {symbol}", miss=True)
        return Price(price, "USD", _num(data.get("d")), _num(data.get("dp")))


class TwelveData:
    """US stocks, plus NSE and BSE where the plan allows. Key in TWELVEDATA_API_KEY."""

    name = "twelvedata"

    def __init__(self, key: str) -> None:
        self._key = key

    def supports(self, symbol: str) -> bool:
        suffix = split_suffix(symbol)[1]
        return (
            not is_index(symbol)
            and "=" not in symbol
            and (suffix is None or suffix in _TWELVE_EXCHANGES)
        )

    async def price(self, api: ApiClient, symbol: str) -> Price:
        base, suffix = split_suffix(symbol)
        params = {"symbol": base.replace("-", "."), "apikey": self._key}
        if suffix:
            params["exchange"] = _TWELVE_EXCHANGES[suffix]
        data = await api.get_json(self.name, "https://api.twelvedata.com/quote", params=params)
        if not isinstance(data, dict):
            raise ProviderError(self.name, "unexpected reply")
        if data.get("status") == "error":
            code = data.get("code")
            if code == 429:
                raise ProviderError(self.name, "rate limited by the provider")
            if code in (400, 403, 404):  # unknown symbol, or not in the free plan
                raise ProviderError(self.name, f"no data for {symbol}", miss=True)
            raise ProviderError(self.name, f"error {code}")
        price = _num(data.get("close"))
        if price is None:
            raise ProviderError(self.name, f"no price for {symbol}", miss=True)
        currency = data.get("currency")
        return Price(
            price,
            str(currency) if currency else None,
            _num(data.get("change")),
            _num(data.get("percent_change")),
        )


class AlphaVantage:
    """US stocks and BSE. 25 requests a day on the free tier. Key in ALPHAVANTAGE_API_KEY."""

    name = "alphavantage"

    def __init__(self, key: str) -> None:
        self._key = key

    def supports(self, symbol: str) -> bool:
        suffix = split_suffix(symbol)[1]
        return not is_index(symbol) and "=" not in symbol and suffix in (None, ".BO")

    async def price(self, api: ApiClient, symbol: str) -> Price:
        base, suffix = split_suffix(symbol)
        av_symbol = f"{base}.BSE" if suffix == ".BO" else symbol
        data = await api.get_json(
            self.name,
            "https://www.alphavantage.co/query",
            params={"function": "GLOBAL_QUOTE", "symbol": av_symbol, "apikey": self._key},
        )
        if not isinstance(data, dict):
            raise ProviderError(self.name, "unexpected reply")
        if "Note" in data or "Information" in data:
            raise ProviderError(self.name, "free request limit reached")
        quote = data.get("Global Quote") or {}
        price = _num(quote.get("05. price"))
        if price is None:
            raise ProviderError(self.name, f"no price for {symbol}", miss=True)
        pct = _num(str(quote.get("10. change percent", "")).rstrip("%"))
        return Price(price, "INR" if suffix else "USD", _num(quote.get("09. change")), pct)


class Yahoo:
    """yfinance: no key, covers NSE, BSE, indices, and most world markets. Unofficial."""

    name = "yfinance"

    def supports(self, symbol: str) -> bool:
        return True

    async def price(self, api: ApiClient, symbol: str) -> Price:
        return await api.call(self.name, lambda: asyncio.to_thread(self._price, symbol))

    async def search(self, api: ApiClient, query: str) -> list[Listing]:
        return await api.call(self.name, lambda: asyncio.to_thread(self._search, query))

    def _price(self, symbol: str) -> Price:
        import yfinance as yf

        log.info("GET yfinance quote %s", symbol)
        try:
            info = yf.Ticker(symbol).fast_info
            last, previous, currency = info.last_price, info.previous_close, info.currency
        except Exception as exc:
            raise _yahoo_error(exc) from exc
        price = _num(last)
        if price is None:
            raise ProviderError(self.name, f"no price for {symbol}", miss=True)
        prev = _num(previous)
        change = price - prev if prev else None
        pct = change / prev * 100 if change is not None and prev else None
        return Price(price, str(currency) if currency else None, change, pct)

    def _search(self, query: str) -> list[Listing]:
        import yfinance as yf

        log.info("GET yfinance search %r", query)
        try:
            search = yf.Search(
                query, max_results=8, news_count=0, lists_count=0, recommended=0, timeout=8
            )
            quotes = search.quotes
        except Exception as exc:
            raise _yahoo_error(exc) from exc
        return [
            Listing(
                symbol=str(item["symbol"]),
                name=str(item.get("longname") or item.get("shortname") or item["symbol"]),
                exchange=str(item.get("exchDisp") or item.get("exchange") or ""),
                kind=str(item.get("quoteType") or ""),
            )
            for item in quotes
            if item.get("symbol")
        ]


def _yahoo_error(exc: Exception) -> ProviderError:
    """yfinance raises many exception types; a failed connection or DNS lookup means offline."""
    text = f"{type(exc).__name__} {exc}".casefold()
    offline = isinstance(exc, ConnectionError) or any(
        word in text for word in ("connect", "resolve", "dns", "getaddrinfo", "proxy")
    )
    return ProviderError("yfinance", f"failed ({type(exc).__name__})", offline=offline)


_KEYED: dict[str, type[Finnhub] | type[TwelveData] | type[AlphaVantage]] = {
    "finnhub": Finnhub,
    "twelvedata": TwelveData,
    "alphavantage": AlphaVantage,
}


class MarketData:
    def __init__(
        self,
        api: ApiClient,
        settings: MarketSettings,
        *,
        yahoo: SearchingProvider | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self._api = api
        self._aliases = {normalize(name): symbol for name, symbol in settings.aliases.items()}
        self._prefer = tuple(settings.prefer_listings)
        self._yahoo = yahoo or Yahoo()
        self.providers: list[QuoteProvider] = []
        for name in settings.providers:
            if name == "yfinance":
                self.providers.append(self._yahoo)
            elif key := env.get(KEY_ENV[name], "").strip():
                self.providers.append(_KEYED[name](key))

    def chain(self, symbol: str) -> list[QuoteProvider]:
        usable = [p for p in self.providers if p.supports(symbol)]
        if split_suffix(symbol)[1] or is_index(symbol) or "=" in symbol:
            usable.sort(key=lambda p: p.name != "yfinance")  # stable, so the rest keep order
        return usable

    async def resolve(self, query: str) -> Listing:
        wanted = clean_query(query)
        target = self._aliases.get(normalize(wanted), wanted)
        key = f"symbol:{normalize(target)}"
        hit = self._api.cache.get(key)
        if hit is not None:
            return Listing(**hit)
        try:
            listings = await self._yahoo.search(self._api, target)
        except ProviderError as exc:
            if _TICKER.match(target) and not exc.offline:
                return Listing(target.upper(), target.upper())  # search is down; try it as is
            raise ToolError(await self._api.explain([exc], f"the ticker for {query}")) from exc
        listing = choose_listing(listings, target, self._prefer)
        if listing is None:
            raise ToolError(f"I couldn't find a stock or index called '{query}'.")
        self._api.cache.put(key, asdict(listing), SYMBOL_TTL_S)
        return listing

    async def quote(self, query: str) -> Quote:
        listing = await self.resolve(query)

        async def fetch() -> dict[str, Any]:
            return asdict(await self._fetch(listing))

        data = await self._api.cached(f"quote:{listing.symbol}", QUOTE_TTL_S, fetch)
        return Quote(**data)

    async def _fetch(self, listing: Listing) -> Quote:
        errors: list[ProviderError] = []
        for provider in self.chain(listing.symbol):
            try:
                price = await provider.price(self._api, listing.symbol)
            except ProviderError as exc:
                log.info("Quote provider failed: %s", exc)
                errors.append(exc)
                continue
            return Quote(
                symbol=listing.symbol,
                name=spoken_name(listing.name),
                price=price.price,
                currency=price.currency,
                change=price.change,
                change_pct=price.change_pct,
                provider=provider.name,
            )
        raise ToolError(
            await self._api.explain(errors, f"the price of {spoken_name(listing.name)}")
        )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def market_data(ctx: ToolContext, query: str) -> ToolResult:
    """Get the latest price of a stock, ETF, or market index, with today's change.

    Covers Indian and world markets, for example "Reliance", "Infosys", "Apple", "TSLA",
    "Nifty 50", or "Sensex". For cryptocurrencies use crypto_price instead.

    Args:
        query: The company, ticker symbol, or index the user named.
    """
    quote = await ctx.services.data.market.quote(query)
    return ToolResult.success(data=asdict(quote), speech=quote.speech())
