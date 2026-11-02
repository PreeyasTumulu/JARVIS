"""Currency conversion: Frankfurter (European Central Bank rates), then open.er-api.com.

Frankfurter covers about 30 major currencies with daily ECB reference rates. Currencies it does
not have (the UAE dirham, for example) come from open.er-api.com, which covers about 160.
"""

from __future__ import annotations

import re
from typing import Any

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.data.http import ApiClient, ProviderError, explain_failure
from jarvis.tools.data.spoken import CURRENCY_WORDS, money
from jarvis.tools.registry import tool

FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
ER_API_URL = "https://open.er-api.com/v6/latest/{base}"
RATES_TTL_S = 3600

_EXTRA_NAMES = {
    "us dollar": "USD",
    "us dollars": "USD",
    "american dollars": "USD",
    "buck": "USD",
    "bucks": "USD",
    "$": "USD",
    "rs": "INR",
    "indian rupee": "INR",
    "indian rupees": "INR",
    "₹": "INR",
    "€": "EUR",
    "£": "GBP",
    "sterling": "GBP",
    "british pound": "GBP",
    "british pounds": "GBP",
    "pound sterling": "GBP",
    "japanese yen": "JPY",
    "renminbi": "CNY",
    "rmb": "CNY",
    "chinese yuan": "CNY",
    "uae dirham": "AED",
    "uae dirhams": "AED",
    "saudi riyal": "SAR",
    "saudi riyals": "SAR",
    "franc": "CHF",
    "francs": "CHF",
    "korean won": "KRW",
    "rouble": "RUB",
    "roubles": "RUB",
}
_NAMES: dict[str, str] = {
    **{word.casefold(): code for code, pair in CURRENCY_WORDS.items() for word in pair},
    **_EXTRA_NAMES,
}


def currency_code(text: str) -> str:
    """ "rupees" to INR, "usd" to USD. Raises ToolError for anything unknown."""
    raw = " ".join(text.strip().casefold().rstrip(".").split())
    if raw in _NAMES:
        return _NAMES[raw]
    if re.fullmatch(r"[a-z]{3}", raw):
        return raw.upper()
    raise ToolError(
        f"I don't know the currency '{text}'. Use a name like rupees or a code like INR."
    )


async def exchange_rates(api: ApiClient, base: str, target: str) -> dict[str, Any]:
    """Rates from `base`, from the first source that has `target`. Cached for an hour."""
    errors: list[ProviderError] = []

    async def frankfurter() -> dict[str, Any]:
        data = await api.get_json("frankfurter", FRANKFURTER_URL, params={"base": base})
        return {"rates": data.get("rates") or {}, "date": data.get("date"), "source": "ECB"}

    async def er_api() -> dict[str, Any]:
        data = await api.get_json("er-api", ER_API_URL.format(base=base))
        if data.get("result") != "success":
            raise ProviderError("er-api", f"no rates for {base}", miss=True)
        updated = str(data.get("time_last_update_utc", ""))[5:16]  # "15 Oct 2026"
        return {"rates": data.get("rates") or {}, "date": updated, "source": "open.er-api.com"}

    for name, fetch in (("frankfurter", frankfurter), ("er-api", er_api)):
        try:
            table: dict[str, Any] = await api.cached(f"fx:{name}:{base}", RATES_TTL_S, fetch)
        except ProviderError as exc:
            errors.append(exc)
            continue
        if target in table["rates"]:
            return table
        errors.append(ProviderError(name, f"no {target} rate", miss=True))
    raise ToolError(explain_failure(errors, f"the {base} to {target} exchange rate"))


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=20)
async def convert_currency(
    ctx: ToolContext, amount: float, from_currency: str, to_currency: str
) -> ToolResult:
    """Convert an amount of money between currencies at the latest exchange rate.

    Args:
        amount: How much money, for example 100.
        from_currency: Currency to convert from, as a code like USD or a name like dollars.
        to_currency: Currency to convert to, as a code like INR or a name like rupees.
    """
    base, target = currency_code(from_currency), currency_code(to_currency)
    if base == target:
        raise ToolError(f"Both currencies are {base}, so there is nothing to convert.")
    table = await exchange_rates(ctx.services.data.api, base, target)
    rate = float(table["rates"][target])
    result = amount * rate
    data = {
        "amount": amount,
        "from": base,
        "to": target,
        "rate": rate,
        "result": round(result, 4),
        "rate_date": table["date"],
        "source": table["source"],
    }
    return ToolResult.success(
        data=data, speech=f"{money(amount, base)} is {money(result, target)}."
    )
