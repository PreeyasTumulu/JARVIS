"""Numbers and money the way a person says them: "1,174.60 rupees", "77.05 lakh rupees"."""

from __future__ import annotations

import math

# ISO code to (singular, plural) as spoken.
CURRENCY_WORDS: dict[str, tuple[str, str]] = {
    "USD": ("dollar", "dollars"),
    "INR": ("rupee", "rupees"),
    "EUR": ("euro", "euros"),
    "GBP": ("pound", "pounds"),
    "JPY": ("yen", "yen"),
    "CNY": ("yuan", "yuan"),
    "AED": ("dirham", "dirhams"),
    "SAR": ("riyal", "riyals"),
    "QAR": ("Qatari riyal", "Qatari riyals"),
    "KWD": ("Kuwaiti dinar", "Kuwaiti dinars"),
    "SGD": ("Singapore dollar", "Singapore dollars"),
    "CAD": ("Canadian dollar", "Canadian dollars"),
    "AUD": ("Australian dollar", "Australian dollars"),
    "NZD": ("New Zealand dollar", "New Zealand dollars"),
    "HKD": ("Hong Kong dollar", "Hong Kong dollars"),
    "CHF": ("Swiss franc", "Swiss francs"),
    "KRW": ("won", "won"),
    "THB": ("baht", "baht"),
    "MYR": ("ringgit", "ringgit"),
    "IDR": ("rupiah", "rupiah"),
    "PHP": ("Philippine peso", "Philippine pesos"),
    "BDT": ("taka", "taka"),
    "PKR": ("Pakistani rupee", "Pakistani rupees"),
    "NPR": ("Nepalese rupee", "Nepalese rupees"),
    "LKR": ("Sri Lankan rupee", "Sri Lankan rupees"),
    "RUB": ("ruble", "rubles"),
    "TRY": ("lira", "lira"),
    "ZAR": ("rand", "rand"),
    "MXN": ("Mexican peso", "Mexican pesos"),
    "BRL": ("real", "reais"),
    "SEK": ("Swedish krona", "Swedish kronor"),
    "NOK": ("Norwegian krone", "Norwegian kroner"),
    "DKK": ("Danish krone", "Danish kroner"),
    "PLN": ("zloty", "zloty"),
    "ILS": ("shekel", "shekels"),
}


def number(value: float) -> str:
    """Round for speech: no decimals past 10,000, two below, three significant digits under 1."""
    size = abs(value)
    if size >= 10_000:
        return f"{value:,.0f}"
    if size >= 1 or size == 0:
        text = f"{value:,.2f}"
        return text[:-3] if text.endswith(".00") else text
    decimals = min(10, 2 - math.floor(math.log10(size)))
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def money(value: float, currency: str | None) -> str:
    code = (currency or "").upper()
    singular, plural = CURRENCY_WORDS.get(code, (code, code))
    size = abs(value)
    if code == "INR" and size >= 1e7:
        return f"{number(value / 1e7)} crore rupees"
    if code == "INR" and size >= 1e5:
        return f"{number(value / 1e5)} lakh rupees"
    if size >= 1e9:
        return f"{number(value / 1e9)} billion {plural}".strip()
    if size >= 1e6:
        return f"{number(value / 1e6)} million {plural}".strip()
    unit = singular if size == 1 else plural
    return f"{number(value)} {unit}".strip()


def percent_change(pct: float | None, period: str = "today") -> str | None:
    if pct is None or math.isnan(pct):
        return None
    if abs(pct) < 0.05:
        return f"unchanged {period}"
    direction = "up" if pct > 0 else "down"
    return f"{direction} {abs(pct):.1f} percent {period}"
