"""Unit tests of the Mollie client against a fake organization.

§F/integrations/mollie/003099 the client has only GET calls. §F/integrations/mollie/003098
it reads only the money values. §NF/security/network/003100 it calls only api.mollie.com
and follows no redirect. §NF/security/network/003101 an error carries a cause code.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import httpx
import pytest

from app.modules.mollie.client import (
    MollieClient,
    MollieError,
    fee_of,
    move_of,
    payment_of,
    settlement_of,
)
from tests._support.sales_fakes import MOLLIE_TOKEN, FakeMollie, money


def _fake() -> FakeMollie:
    return FakeMollie(
        payments=[
            {
                "id": "tr_1",
                "amount": money("10.00"),
                "status": "paid",
                "createdAt": "2026-11-20T10:00:00+00:00",
                "paidAt": "2026-11-20T10:01:00+00:00",
                "settlementId": "stl_1",
                "metadata": {"organizer": "stupa", "event": "party"},
                "details": {"consumerName": "Jemand", "consumerAccount": "DE00"},
            },
            {
                "id": "tr_2",
                "amount": money("x"),
                "status": "open",
                "createdAt": "bad",
                "metadata": None,
            },
            {"amount": money("1.00")},
        ],
        refunds=[
            {"id": "re_1", "paymentId": "tr_1", "amount": money("4.00"), "status": "refunded"}
        ],
        chargebacks=[{"id": "chb_1", "paymentId": "tr_1", "amount": money("-10.00")}],
        settlements=[
            {
                "id": "stl_1",
                "reference": "1234.2611.01",
                "status": "paidout",
                "settledAt": "2026-11-26T08:00:00+00:00",
                "amount": money("9.40"),
                "periods": {
                    "2026": {"11": {"costs": [{"amountGross": money("0.60")}, {}]}, "x": 1}
                },
            }
        ],
        transactions=[
            {"type": "payment", "context": {"paymentId": "tr_1"}, "deductions": money("-0.32")},
            {
                "type": "payment",
                "context": {"payment": {"paymentId": "tr_2"}},
                "deductions": money("-0.10"),
            },
            {"type": "payment", "context": {}},
            {"type": "refund"},
        ],
    )


def _answering(response: httpx.Response) -> MollieClient:
    return MollieClient(
        token=MOLLIE_TOKEN,
        client_factory=lambda _t: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _r: response)
        ),
    )


async def test_the_reads_use_get_with_the_token() -> None:
    fake = _fake()
    client = fake.client(MOLLIE_TOKEN)
    assert await client.organization() == "Studierendenschaft"
    payments = await client.payments()
    refunds = await client.refunds()
    chargebacks = await client.chargebacks()
    settlements = await client.settlements()
    fees = await client.fees()

    assert [p.id for p in payments] == ["tr_1", "tr_2"]
    assert payments[0].event == "party"
    assert payments[0].organizer == "stupa"
    assert payments[1].amount == Decimal(0)
    assert payments[1].created_at is None
    assert "Jemand" not in repr(payments)
    assert refunds[0].amount == Decimal("4.00")
    assert chargebacks[0].amount == Decimal("10.00")
    assert chargebacks[0].status == "charged_back"
    assert settlements[0].fees == Decimal("0.60")
    assert [(f.payment_id, f.fee) for f in fees] == [
        ("tr_1", Decimal("0.32")),
        ("tr_2", Decimal("0.10")),
    ]
    assert {r.method for r in fake.requests} == {"GET"}
    assert all(r.headers["Authorization"] == f"Bearer {MOLLIE_TOKEN}" for r in fake.requests)
    assert {r.url.host for r in fake.requests} == {"api.mollie.com"}


async def test_a_read_stops_at_a_known_page() -> None:
    fake = _fake()

    def known(rows: tuple[Mapping[str, object], ...]) -> bool:
        return all(row.get("id") == "tr_1" for row in rows)

    assert [p.id for p in await fake.client(MOLLIE_TOKEN).payments(known)] == ["tr_1"]


async def test_a_next_address_on_another_host_is_blocked() -> None:
    body = {
        "_embedded": {"payments": [{"id": "tr_1"}]},
        "_links": {"next": {"href": "https://evil.test/v2/payments"}},
    }
    with pytest.raises(MollieError) as err:
        await _answering(httpx.Response(200, json=body)).payments()
    assert err.value.code == "blocked"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(301, headers={"Location": "https://evil.test"}), "redirect"),
        (httpx.Response(401), "unauthorized"),
        (httpx.Response(500), "status"),
        (httpx.Response(200, text="<html>"), "format"),
        (httpx.Response(200, json={"_embedded": {}}), "format"),
    ],
)
async def test_each_failure_has_a_cause_code(response: httpx.Response, code: str) -> None:
    with pytest.raises(MollieError) as err:
        await _answering(response).payments()
    assert err.value.code == code


async def test_organization_needs_a_name() -> None:
    with pytest.raises(MollieError) as err:
        await _answering(httpx.Response(200, json={})).organization()
    assert err.value.code == "format"


@pytest.mark.parametrize(
    ("error", "code"),
    [(httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("down"), "unreachable")],
)
async def test_a_transport_error_has_a_cause_code(error: Exception, code: str) -> None:
    def _raise(_request: httpx.Request) -> httpx.Response:
        raise error

    client = MollieClient(
        token=MOLLIE_TOKEN,
        client_factory=lambda _t: httpx.AsyncClient(transport=httpx.MockTransport(_raise)),
    )
    with pytest.raises(MollieError) as err:
        await client.organization()
    assert err.value.code == code


def test_the_parsers_skip_rows_without_an_id() -> None:
    assert payment_of({}) is None
    assert move_of({"id": "re_1"}, "refund") is None
    assert settlement_of({}) is None
    assert fee_of({"type": "payment", "context": "x"}) is None
    found = settlement_of({"id": "stl_2", "periods": []})
    assert found is not None
    assert found.reference == "stl_2"
    assert found.fees == Decimal(0)
