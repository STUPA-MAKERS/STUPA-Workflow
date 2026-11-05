"""Tests for `app.shared.money`."""

from __future__ import annotations

from decimal import Decimal

from app.shared.money import format_money


def test_german_format_groups_and_rounds() -> None:
    """German puts dots between thousands and a comma before the cents."""
    assert format_money(Decimal("1234567.005"), "EUR", "de") == "1.234.567,01 €"


def test_english_format_puts_the_euro_sign_first() -> None:
    """English groups with commas and writes the euro sign without a space."""
    assert format_money(Decimal("1234.5"), "EUR", "en") == "€1,234.50"


def test_other_currency_and_negative_amount() -> None:
    """A currency other than EUR keeps its code, and a negative amount keeps its sign."""
    assert format_money(Decimal("-12"), "CHF", "en") == "-CHF 12.00"
    assert format_money(Decimal("-12"), "CHF", "de") == "-12,00 CHF"
