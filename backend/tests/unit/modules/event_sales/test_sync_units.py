"""The Mollie read and the pretix sync with a fake session and a fake client (no database).

They run the store of each Mollie list, the mark of the read, the failure of a read, the
match of a payment to its Event, the record of a failed booking, the switches that stop a
run early, and the account of the links of a pretix booking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.modules.event_sales import mollie_sync, pretix_sync
from app.modules.event_sales.outcome import Outcome
from app.modules.mollie.client import MollieError
from app.modules.pretix.client import PretixError

NOW = datetime(2026, 11, 28, 8, 0, tzinfo=UTC)


@dataclass
class _Session:
    rows: list[Any] = field(default_factory=list[Any])
    answer: Any = None
    executed: int = 0

    async def scalars(self, _statement: Any) -> Any:
        return SimpleNamespace(all=lambda: self.rows)

    async def scalar(self, _statement: Any) -> Any:
        return self.answer

    async def execute(self, _statement: Any) -> Any:
        self.executed += 1
        return SimpleNamespace(all=list)

    async def flush(self) -> None:
        return None


def _session(**kw: Any) -> Any:
    return _Session(**kw)


class _Mollie:
    def __init__(self, error: str | None = None) -> None:
        self.error = error
        self.checks: list[bool] = []

    def _fail(self) -> None:
        if self.error:
            raise MollieError(self.error)  # pyright: ignore[reportArgumentType]

    async def payments(self, known: Any) -> list[Any]:
        self._fail()
        self.checks.append(known([{"id": "tr_old"}]))
        return [
            SimpleNamespace(
                id="tr_1",
                amount=Decimal("12.00"),
                status="paid",
                created_at=NOW,
                paid_at=NOW,
                settlement_id=None,
                organizer="stupa",
                event="fest",
            )
        ]

    async def refunds(self, known: Any) -> list[Any]:
        self.checks.append(known([]))
        move = SimpleNamespace(
            id="re_1",
            kind="refund",
            payment_id="tr_1",
            amount=Decimal(2),
            status="refunded",
            at=NOW,
            settlement_id=None,
        )
        return [move]

    async def chargebacks(self, known: Any) -> list[Any]:
        self.checks.append(known([]))
        return []

    async def settlements(self, known: Any) -> list[Any]:
        self.checks.append(known([]))
        return [
            SimpleNamespace(
                id="stl_1",
                reference="1234.5678",
                status="paidout",
                settled_at=NOW,
                amount=Decimal(10),
                fees=Decimal("0.60"),
            )
        ]

    async def fees(self, known: Any) -> list[Any]:
        rows = ({"type": "payment", "context": {"paymentId": "tr_old"}}, {"type": "other"})
        self.checks.append(known(rows))
        return [SimpleNamespace(payment_id="tr_1", fee=Decimal("0.32"))]


async def test_the_read_stores_every_list_and_marks_the_read() -> None:
    session = _session(rows=["tr_old"])
    client = _Mollie()
    assert await mollie_sync.read_mollie(session, client, NOW) == Outcome()  # pyright: ignore[reportArgumentType]
    assert client.checks == [True, True, True, True, True]
    assert session.executed == 5


async def test_a_failed_read_keeps_its_cause() -> None:
    session = _session()
    outcome = await mollie_sync.read_mollie(session, _Mollie("unauthorized"), NOW)  # pyright: ignore[reportArgumentType]
    assert [f.cause for f in outcome.failures] == ["unauthorized"]
    assert session.executed == 1


async def test_a_payment_finds_its_event_by_its_metadata() -> None:
    link: Any = SimpleNamespace(slug="fest")
    links = await mollie_sync.links_of(_session(rows=[link]), SimpleNamespace(organizer="stupa"))  # pyright: ignore[reportArgumentType]
    assert links.of("stupa", "fest") is link
    assert links.of("other", "fest") is None
    assert links.of("stupa", None) is None
    assert mollie_sync.Links(None, {}).of("stupa", "fest") is None


async def test_a_failed_booking_is_recorded_with_its_cause() -> None:
    session = _session()
    failed = await mollie_sync._record(session, "payment", "tr_1", "fiscal_year_closed")
    assert [f.key for f in failed.failures] == ["tr_1"]
    booked = await mollie_sync._record(session, "payment", "tr_2", uuid.uuid4())
    assert booked.booked == 1


async def test_the_bookings_stop_without_their_switch_or_cost_centre() -> None:
    row: Any = SimpleNamespace(fee_budget_id=None, unassigned_budget_id=None)
    off: Any = SimpleNamespace(book_income=False, organizer="stupa")
    on: Any = SimpleNamespace(book_income=True, organizer="stupa")
    assert await mollie_sync.book_mollie(_session(), row, off) == Outcome()
    assert await mollie_sync.book_mollie(_session(), row, on) == Outcome()
    assert list(await mollie_sync.failed_bookings(_session(rows=["x"]))) == ["x"]


async def test_the_links_of_a_booking_name_the_linker_else_the_creator() -> None:
    creator = uuid.uuid4()
    linker = uuid.uuid4()
    own: Any = SimpleNamespace(created_by=linker, event_id=uuid.uuid4())
    loose: Any = SimpleNamespace(created_by=None, event_id=uuid.uuid4())
    assert await pretix_sync.link_actor(_session(), own) == linker
    assert await pretix_sync.link_actor(_session(answer=creator), loose) == creator


class _Pretix:
    async def orders(self, _slug: str) -> list[Any]:
        raise PretixError("unreachable")


async def test_the_pretix_sync_skips_and_fails() -> None:
    row: Any = SimpleNamespace(
        base_url="https://pretix.test",
        organizer="stupa",
        token="t",
        show_sales=False,
        book_income=False,
    )
    link: Any = SimpleNamespace(slug="fest", income_budget_id=None, id=uuid.uuid4())
    assert await pretix_sync.sync_link(_session(), _Pretix(), row, link, NOW) == Outcome()  # pyright: ignore[reportArgumentType]
    row.show_sales = True
    failed = await pretix_sync.sync_link(_session(), _Pretix(), row, link, NOW)  # pyright: ignore[reportArgumentType]
    assert [f.cause for f in failed.failures] == ["unreachable"]
    assert await pretix_sync._book(_session(), link, []) == Outcome()
    link.income_budget_id = uuid.uuid4()
    assert await pretix_sync._book(_session(), link, []) == Outcome()
