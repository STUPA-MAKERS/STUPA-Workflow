"""Format an amount of money for a reader, without a locale library."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def format_money(value: Decimal, currency: str, lang: str) -> str:
    """Format an amount for a reader.

    Written out rather than taken from a locale library: the backend has no locale data
    dependency. German gets the German format, every other language the English one,
    because an extra language falls back to English.
    """
    amount = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    symbol = "€" if currency == "EUR" else currency
    if lang != "de":
        grouped = _group(whole, ",")
        joiner = "" if symbol == "€" else " "
        return f"{sign}{symbol}{joiner}{grouped}.{cents}"
    return f"{sign}{_group(whole, '.')},{cents} {symbol}"


def _group(digits: str, sep: str) -> str:
    """Thousands separators, right to left."""
    out = ""
    for i, ch in enumerate(reversed(digits)):
        if i and i % 3 == 0:
            out = sep + out
        out = ch + out
    return out
