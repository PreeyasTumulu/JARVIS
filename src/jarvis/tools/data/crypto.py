"""Cryptocurrency prices from CoinGecko. Works without a key; a free demo key raises the limits."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.data.currency import currency_code
from jarvis.tools.data.http import ApiClient, ProviderError, explain_failure
from jarvis.tools.data.spoken import money, percent_change
from jarvis.tools.registry import tool

API = "https://api.coingecko.com/api/v3"
KEY_ENV = "COINGECKO_API_KEY"
PRICE_TTL_S = 60
COIN_TTL_S = 30 * 24 * 3600

# Symbols people say, mapped to CoinGecko ids, so common coins need no search call.
COIN_ALIASES = {
    "btc": ("bitcoin", "Bitcoin"),
    "bitcoin": ("bitcoin", "Bitcoin"),
    "eth": ("ethereum", "Ethereum"),
    "ether": ("ethereum", "Ethereum"),
    "ethereum": ("ethereum", "Ethereum"),
    "sol": ("solana", "Solana"),
    "solana": ("solana", "Solana"),
    "doge": ("dogecoin", "Dogecoin"),
    "dogecoin": ("dogecoin", "Dogecoin"),
    "xrp": ("ripple", "XRP"),
    "ada": ("cardano", "Cardano"),
    "bnb": ("binancecoin", "BNB"),
    "usdt": ("tether", "Tether"),
    "tether": ("tether", "Tether"),
    "ltc": ("litecoin", "Litecoin"),
    "litecoin": ("litecoin", "Litecoin"),
}


@dataclass(frozen=True)
class Coin:
    id: str
    name: str


async def find_coin(api: ApiClient, text: str, headers: dict[str, str]) -> Coin:
    query = " ".join(text.casefold().split()).removesuffix(" coin") or text
    if query in COIN_ALIASES:
        coin_id, name = COIN_ALIASES[query]
        return Coin(coin_id, name)

    async def search() -> dict[str, Any]:
        data = await api.get_json(
            "coingecko", f"{API}/search", params={"query": query}, headers=headers
        )
        coins = [c for c in (data.get("coins") or []) if isinstance(c, dict) and c.get("id")]
        if not coins:
            raise ToolError(f"I couldn't find a cryptocurrency called {text}.")
        return {"id": str(coins[0]["id"]), "name": str(coins[0].get("name") or coins[0]["id"])}

    try:
        found = await api.cached(f"coin:{query}", COIN_TTL_S, search)
    except ProviderError as exc:
        raise ToolError(explain_failure([exc], f"the coin {text}")) from exc
    return Coin(**found)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=20)
async def crypto_price(ctx: ToolContext, coin: str, currency: str | None = None) -> ToolResult:
    """Get the current price of a cryptocurrency such as bitcoin or ethereum.

    Args:
        coin: The coin's name or symbol, for example "bitcoin" or "ETH".
        currency: Currency for the price, like "INR" or "rupees". Leave it out for the default.
    """
    data_hub = ctx.services.data
    api = data_hub.api
    key = data_hub.key(KEY_ENV)
    headers = {"x-cg-demo-api-key": key} if key else {}
    vs = currency_code(currency) if currency else ctx.settings.market.crypto_currency.upper()
    found = await find_coin(api, coin, headers)

    async def fetch() -> dict[str, Any]:
        data = await api.get_json(
            "coingecko",
            f"{API}/simple/price",
            params={"ids": found.id, "vs_currencies": vs.lower(), "include_24hr_change": "true"},
            headers=headers,
        )
        entry = data.get(found.id) if isinstance(data, dict) else None
        if not isinstance(entry, dict) or entry.get(vs.lower()) is None:
            raise ToolError(f"CoinGecko has no {vs} price for {found.name}.")
        return {"price": entry[vs.lower()], "change_24h_pct": entry.get(f"{vs.lower()}_24h_change")}

    try:
        price = await api.cached(f"crypto:{found.id}:{vs}", PRICE_TTL_S, fetch)
    except ProviderError as exc:
        raise ToolError(explain_failure([exc], f"the price of {found.name}")) from exc
    amount = float(price["price"])
    change = price.get("change_24h_pct")
    movement = percent_change(float(change) if change is not None else None, "in the last 24 hours")
    speech = f"{found.name} is at {money(amount, vs)}" + (f", {movement}." if movement else ".")
    result = {**asdict(found), "currency": vs, "price": amount, "change_24h_pct": change}
    return ToolResult.success(data=result, speech=speech)
