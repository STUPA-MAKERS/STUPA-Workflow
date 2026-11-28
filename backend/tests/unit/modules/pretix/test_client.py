"""Unit tests of the pretix client against a fake organizer.

§F/integrations/pretix/003089 the client has only GET calls. §F/integrations/pretix/003088
an order holds no personal value. §NF/security/network/003100 the client calls only a host
of the allowlist and follows no redirect. §NF/security/network/003101 an error carries a
cause code and no text.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.modules.pretix.client import (
    Money,
    PretixClient,
    PretixError,
    address_allowed,
    event_of,
    normalize_url,
    order_of,
)
from tests._support.sales_fakes import ORGANIZER, PRETIX_HOST, PRETIX_TOKEN, PRETIX_URL, FakePretix


def _fake() -> FakePretix:
    return FakePretix(
        events=[
            {
                "slug": "party",
                "name": {"de": "Party", "en": "Party EN"},
                "date_from": "2026-12-11T20:00:00Z",
                "public_url": f"{PRETIX_URL}/stupa/party/",
            },
            {"slug": "fahrt", "name": "Fahrt", "date_from": None},
            {"name": "ohne Slug"},
        ],
        items={"party": [{"id": 1, "name": {"en": "Ticket"}}, {"id": "x"}]},
        quotas={
            "party": [
                {"name": "Einlass", "available_number": 12},
                {"name": "Frei", "available_number": None},
            ]
        },
        orders={
            "party": [
                {
                    "code": "ABC12",
                    "status": "p",
                    "total": "10.00",
                    "payment_date": "2026-11-20",
                    "email": "person@example.org",
                    "invoice_address": {"name": "Jemand"},
                    "positions": [{"item": 1, "attendee_name": "Jemand"}, {"item": True}],
                    "payments": [
                        {
                            "local_id": 1,
                            "state": "confirmed",
                            "amount": "10.00",
                            "payment_date": "2026-11-20T10:00:00Z",
                        },
                        {"local_id": 2, "state": "failed", "amount": "10.00"},
                    ],
                    "refunds": [
                        {
                            "local_id": 1,
                            "state": "done",
                            "amount": "4.00",
                            "execution_date": None,
                            "created": "2026-11-21T09:00:00Z",
                        }
                    ],
                },
                {"code": "", "status": "p"},
                {"code": "ZZZ", "status": "x"},
            ]
        },
    )


def _client(fake: FakePretix, allowlist: tuple[str, ...] = (PRETIX_HOST,)) -> PretixClient:
    return fake.client(PRETIX_URL, ORGANIZER, PRETIX_TOKEN, allowlist)


def _answering(response: httpx.Response) -> PretixClient:
    return PretixClient(
        base_url=PRETIX_URL,
        organizer=ORGANIZER,
        token=PRETIX_TOKEN,
        allowlist=(PRETIX_HOST,),
        client_factory=lambda _t: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: response)
        ),
    )


def _raising(error: Exception) -> PretixClient:
    def _raise(_request: httpx.Request) -> httpx.Response:
        raise error

    return PretixClient(
        base_url=PRETIX_URL,
        organizer=ORGANIZER,
        token=PRETIX_TOKEN,
        allowlist=(PRETIX_HOST,),
        client_factory=lambda _t: httpx.AsyncClient(transport=httpx.MockTransport(_raise)),
    )


@pytest.mark.parametrize(
    ("url", "allowlist", "allowed"),
    [
        ("https://pretix.test", ["pretix.test"], True),
        ("https://other.test", ["pretix.test"], False),
        ("https://pretix.test", [], False),
        ("ftp://pretix.test", ["pretix.test"], False),
        ("https://user@pretix.test", ["pretix.test"], False),
    ],
)
def test_address_allowed(url: str, allowlist: list[str], allowed: bool) -> None:
    assert address_allowed(url, allowlist) is allowed


def test_normalize_url_drops_the_slash() -> None:
    assert normalize_url(" https://pretix.test/ ") == "https://pretix.test"


async def test_the_reads_use_get_with_the_token_and_every_page() -> None:
    fake = _fake()
    client = _client(fake)
    await client.check()
    events = await client.events()
    event = await client.event("party")
    products = await client.products("party")
    quotas = await client.quotas("party")
    orders = await client.orders("party")

    assert [e.slug for e in events] == ["party", "fahrt"]
    assert events[0].name == "Party"
    assert events[0].date_from == date(2026, 12, 11)
    assert event.public_url == f"{PRETIX_URL}/stupa/party/"
    assert [(p.id, p.name) for p in products] == [(1, "Ticket")]
    assert [(q.name, q.available) for q in quotas] == [("Einlass", 12), ("Frei", None)]
    assert len(orders) == 1
    assert {r.method for r in fake.requests} == {"GET"}
    assert all(r.headers["Authorization"] == f"Token {PRETIX_TOKEN}" for r in fake.requests)


async def test_an_order_holds_no_personal_value() -> None:
    (order,) = await _client(_fake()).orders("party")
    assert order.code == "ABC12"
    assert order.products == (1,)
    assert order.payments == (Money(local_id=1, amount=Decimal("10.00"), on=date(2026, 11, 20)),)
    assert order.refunds == (Money(local_id=1, amount=Decimal("4.00"), on=date(2026, 11, 21)),)
    assert "person@example.org" not in repr(order)
    assert "Jemand" not in repr(order)


async def test_a_host_outside_the_allowlist_is_blocked() -> None:
    fake = _fake()
    with pytest.raises(PretixError) as err:
        await _client(fake, allowlist=("other.test",)).events()
    assert err.value.code == "blocked"
    assert fake.requests == []


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(302, headers={"Location": "https://evil.test"}), "redirect"),
        (httpx.Response(401), "unauthorized"),
        (httpx.Response(403), "unauthorized"),
        (httpx.Response(404), "not_found"),
        (httpx.Response(500), "status"),
        (httpx.Response(200, text="<html>"), "format"),
        (httpx.Response(200, json=[]), "format"),
    ],
)
async def test_each_failure_has_a_cause_code(response: httpx.Response, code: str) -> None:
    with pytest.raises(PretixError) as err:
        await _answering(response).events()
    assert err.value.code == code


async def test_check_and_event_need_the_shape_of_the_api() -> None:
    with pytest.raises(PretixError) as check:
        await _answering(httpx.Response(200, json={"count": 0})).check()
    with pytest.raises(PretixError) as event:
        await _answering(httpx.Response(200, json={"name": "no slug"})).event("x")
    assert check.value.code == event.value.code == "format"


@pytest.mark.parametrize(
    ("error", "code"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("down"), "unreachable")],
)
async def test_a_transport_error_has_a_cause_code(error: Exception, code: str) -> None:
    with pytest.raises(PretixError) as err:
        await _raising(error).events()
    assert err.value.code == code
    assert str(err.value) == code


def test_the_parsers_skip_rows_without_a_key() -> None:
    assert event_of({"name": "x"}) is None
    assert order_of({"code": "A", "status": "?"}) is None
    order = order_of({"code": "A", "status": "n", "total": "x1", "payment_date": "bad-date-x"})
    assert order is not None
    assert order.total == Decimal(0)
    assert order.payment_date is None
    assert event_of({"slug": "s", "name": {"fr": "Fête"}}) is not None
    assert event_of({"slug": "s", "name": 5}).name == "s"  # type: ignore[union-attr]
