"""Pure rules, numbers and schemas of the Bestellungen.

§ F/finance/orders/002851 the fields, § 002853 the statuses and their dates, § 002855 the
number, § 002856 the link, § 002852 the buyer of an Auslage, § 002860 the position ids and
§ 002868 the sum.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.orders.numbers import NUMBER_ALPHABET, draw_number, format_number
from app.modules.orders.rules import (
    buyer_missing,
    orders_sum,
    over_by,
    position_ids,
    price,
    status_dates,
    url_valid,
)
from app.modules.orders.schemas import OrderCreate, OrderStatusIn

_TODAY = date(2026, 11, 24)
_TYPED = date(2026, 11, 2)


def test_number_form_and_difference() -> None:
    first, second = draw_number(), draw_number()
    assert len(first) == 8
    assert set(first) <= set(NUMBER_ALPHABET)
    assert first != second
    assert format_number("7K3QX9MD") == "B-7K3QX9MD"


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://shop.example/artikel/1", True),
        ("HTTP://shop.example", True),
        ("javascript:alert(1)", False),
        ("ftp://x", False),
        ("https://" + "a" * 2000, False),
    ],
)
def test_link_is_http_or_https(url: str, ok: bool) -> None:
    assert url_valid(url) is ok


def test_an_auslage_needs_its_buyer() -> None:
    assert buyer_missing("outlay", None, None)
    assert buyer_missing("outlay", None, "  ")
    assert not buyer_missing("outlay", None, "Anna")
    assert not buyer_missing("outlay", "id", None)
    assert not buyer_missing("order", None, None)


def test_status_sets_only_an_empty_date() -> None:
    assert status_dates("ordered", None, None, _TODAY) == (_TODAY, None)
    assert status_dates("ordered", _TYPED, None, _TODAY) == (_TYPED, None)
    assert status_dates("delivered", None, None, _TODAY) == (None, _TODAY)
    assert status_dates("delivered", _TYPED, _TYPED, _TODAY) == (_TYPED, _TYPED)
    assert status_dates("planned", None, None, _TODAY) == (None, None)
    assert status_dates("cancelled", _TYPED, None, _TODAY) == (_TYPED, None)


def test_position_ids_come_from_every_list_with_offers() -> None:
    data = {
        "title": "Regal",
        "kosten": [
            {"id": "p1", "label": "Regal", "offers": [{"value": 10}]},
            {"label": "ohne id", "offers": []},
            "kein Objekt",
        ],
        "mehr": [{"id": "p2", "offers": []}],
        "tabelle": [{"id": "zeile"}],
        "zahl": 3,
    }
    assert position_ids(data) == frozenset({"p1", "p2"})
    assert position_ids({}) == frozenset()


def test_sum_leaves_out_a_cancelled_bestellung() -> None:
    rows = [
        ("ordered", Decimal("112.50"), Decimal("100.00")),
        ("planned", None, Decimal("20.00")),
        ("delivered", None, None),
        ("cancelled", Decimal("999.00"), None),
    ]
    assert orders_sum(rows) == Decimal("132.50")
    assert orders_sum([]) == Decimal(0)
    assert price(None, Decimal(5)) == Decimal(5)
    assert price(Decimal(7), Decimal(5)) == Decimal(7)
    assert price(None, None) is None


def test_warning_only_above_the_approved_amount() -> None:
    assert over_by(Decimal("132.50"), Decimal("100.00")) == Decimal("32.50")
    assert over_by(Decimal("100.00"), Decimal("100.00")) is None
    assert over_by(Decimal("100.00"), None) is None


def test_schema_accepts_the_required_fields_only() -> None:
    order = OrderCreate.model_validate({"title": " Regal "})
    assert (order.title, order.kind, order.status, order.position_ids) == (
        "Regal",
        "order",
        "planned",
        (),
    )


@pytest.mark.parametrize(
    "body",
    [
        {"title": "x" * 201},
        {"title": ""},
        {"title": "Regal", "plannedAmount": "1.234"},
        {"title": "Regal", "actualAmount": "-1"},
        {"title": "Regal", "status": "paid"},
        {"title": "Regal", "kind": "gift"},
        {"title": "Regal", "unknown": 1},
    ],
)
def test_schema_refuses(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OrderCreate.model_validate(body)


def test_status_body_refuses_a_fifth_value() -> None:
    assert OrderStatusIn.model_validate({"status": "delivered", "version": 1}).status == "delivered"
    with pytest.raises(ValidationError):
        OrderStatusIn.model_validate({"status": "returned", "version": 1})
