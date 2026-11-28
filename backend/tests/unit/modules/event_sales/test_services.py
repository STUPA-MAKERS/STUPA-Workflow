"""The connection services, the link and the booking with a fake session (no database).

They run every line after a database call: the save with its audit entry, the 422 of a
host outside the allowlist and of a new address without the token, the client and the test
of each connection, the link with its shop and its cost centre, the 409 of a taken event,
and the booking with its sub-bookings, its links and the cause of a failure.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.event_sales import booking, links
from app.modules.mollie import connection as mollie_connection
from app.modules.mollie.client import MollieError
from app.modules.mollie.schemas import ConnectionIn as MollieIn
from app.modules.pretix import connection as pretix_connection
from app.modules.pretix.client import PretixError
from app.modules.pretix.schemas import ConnectionIn as PretixIn
from app.settings import load_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

SETTINGS = load_settings().model_copy(update={"pretix_host_allowlist": ["pretix.test"]})
EVENT_ID = uuid.uuid4()
ACTOR_ID = uuid.uuid4()


@dataclass
class _Session:
    row: Any = None
    answers: list[Any] = field(default_factory=list[Any])
    found: Any = None
    executed: int = 0
    added: list[Any] = field(default_factory=list[Any])

    async def execute(self, _statement: Any) -> None:
        self.executed += 1

    async def scalar(self, _statement: Any) -> Any:
        return self.answers.pop(0) if self.answers else self.row

    async def get(self, _model: Any, _id: Any) -> Any:
        return self.found

    def add_all(self, rows: list[Any]) -> None:
        self.added.extend(rows)

    async def flush(self) -> None:
        return None

    def begin_nested(self) -> _Savepoint:
        return _Savepoint()


class _Savepoint:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


def _session(**kw: Any) -> Any:
    return _Session(**kw)


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    async def record(_session: Any, **kw: Any) -> None:
        seen.append(kw)

    for module in (pretix_connection, mollie_connection, links):
        monkeypatch.setattr(module, "audit_record", record)
    return seen


def _pretix_row(**kw: Any) -> Any:
    values: dict[str, Any] = {
        "base_url": "https://pretix.test",
        "organizer": "stupa",
        "token": "secret",
        "show_sales": True,
        "book_income": False,
    }
    return SimpleNamespace(**{**values, **kw})


def _pretix_in(**kw: Any) -> PretixIn:
    return PretixIn.model_validate(
        {"baseUrl": "https://pretix.test/", "organizer": " stupa ", "showSales": True, **kw}
    )


class _PretixClient:
    organizer = "stupa"

    def __init__(self, error: str | None = None) -> None:
        self.error = error

    async def check(self) -> None:
        if self.error:
            raise PretixError(self.error)  # pyright: ignore[reportArgumentType]


async def test_the_pretix_connection_saves_and_audits(audits: list[dict[str, Any]]) -> None:
    session = _session(row=_pretix_row())
    service = pretix_connection.ConnectionService(session, SETTINGS)
    out = await service.save(_pretix_in(), actor="ada")
    assert out.token_set and out.allowed_hosts == ("pretix.test",)
    assert audits[0]["data"]["tokenChanged"] is False
    await service.save(_pretix_in(clearToken=True), actor="ada")
    assert audits[1]["data"]["tokenChanged"] is True
    await service.save(PretixIn(), actor="ada")
    assert audits[2]["data"]["baseUrl"] is None
    assert (await service.read()).organizer == "stupa"


async def test_the_pretix_connection_refuses_a_host_and_a_move_without_token(
    audits: list[dict[str, Any]],
) -> None:
    service = pretix_connection.ConnectionService(_session(row=_pretix_row()), SETTINGS)
    with pytest.raises(ValidationProblem) as host:
        await service.save(_pretix_in(baseUrl="https://evil.test"), actor="ada")
    assert host.value.code == "pretix_host_not_allowed"
    with pytest.raises(ValidationProblem) as token:
        await service.save(_pretix_in(organizer="other"), actor="ada")
    assert token.value.code == "token_required"
    assert audits == []


async def test_the_pretix_client_and_test() -> None:
    made: list[tuple[Any, ...]] = []

    def factory(*args: Any) -> Any:
        made.append(args)
        return _PretixClient(error=None if len(made) == 1 else "unauthorized")

    complete = pretix_connection.ConnectionService(_session(row=_pretix_row()), SETTINGS, factory)
    assert await complete.test() == pretix_connection.ConnectionTestOut(ok=True, name="stupa")
    failed = await complete.test()
    assert (failed.ok, failed.error) == (False, "unauthorized")
    assert made[0] == ("https://pretix.test", "stupa", "secret", ("pretix.test",))
    empty = pretix_connection.ConnectionService(_session(row=_pretix_row(token=None)), SETTINGS)
    assert await empty.client() is None
    assert (await empty.test()).error == "not_configured"


def _mollie_row(**kw: Any) -> Any:
    values: dict[str, Any] = {
        "token": "live_secret",
        "organization": "Studierendenschaft",
        "fee_budget_id": None,
        "unassigned_budget_id": None,
        "read_ok_at": None,
        "read_error": None,
    }
    return SimpleNamespace(**{**values, **kw})


class _MollieClient:
    def __init__(self, error: str | None) -> None:
        self.error = error

    async def organization(self) -> str:
        if self.error:
            raise MollieError(self.error)  # pyright: ignore[reportArgumentType]
        return "Studierendenschaft"


async def test_the_mollie_connection_saves_and_audits(audits: list[dict[str, Any]]) -> None:
    fee = uuid.uuid4()
    service = mollie_connection.ConnectionService(_session(row=_mollie_row()))
    out = await service.save(MollieIn.model_validate({"feeBudgetId": str(fee)}), actor="ada")
    assert out.token_set
    assert audits[0]["data"] == {
        "tokenChanged": False,
        "feeBudgetId": str(fee),
        "unassignedBudgetId": None,
    }
    other = MollieIn.model_validate({"token": "live_new", "unassignedBudgetId": str(fee)})
    await service.save(other, actor="ada")
    assert audits[1]["data"]["tokenChanged"] is True
    assert (await service.read()).organization == "Studierendenschaft"


async def test_the_mollie_client_and_test() -> None:
    errors = [None, "unauthorized"]
    session = _session(row=_mollie_row())
    service = mollie_connection.ConnectionService(session, lambda _t: _MollieClient(errors.pop(0)))  # pyright: ignore[reportArgumentType]
    assert await service.test() == mollie_connection.ConnectionTestOut(
        ok=True, name="Studierendenschaft"
    )
    assert (await service.test()).error == "unauthorized"
    assert session.executed == 3
    empty = mollie_connection.ConnectionService(_session(row=_mollie_row(token=None)))
    assert await empty.client() is None
    assert (await empty.test()).error == "not_configured"


def _found(slug: str = "fest", public_url: str | None = "https://pretix.test/stupa/fest/") -> Any:
    return SimpleNamespace(
        slug=slug, name="Fest", date_from=date(2027, 3, 12), public_url=public_url
    )


async def test_the_link_is_set_and_gives_the_event_its_shop(audits: list[dict[str, Any]]) -> None:
    link = SimpleNamespace(id=uuid.uuid4(), slug="alt")
    session = _session(answers=[ACTOR_ID, link, link])
    event: Any = SimpleNamespace(id=EVENT_ID, shop_url=None)
    assert await links.set_link(session, event, _found(), "ada") is link
    assert session.executed == 2
    assert audits[0]["data"] == {"slug": "fest"}
    session = _session(answers=[ACTOR_ID, None, link])
    event = SimpleNamespace(id=EVENT_ID, shop_url="https://shop.test")
    await links.set_link(session, event, _found(public_url=None), "ada")
    assert session.executed == 1


async def test_a_taken_event_is_refused() -> None:
    await links.check_free(_session(answers=[None]), EVENT_ID, "fest")
    await links.check_free(_session(answers=[EVENT_ID]), EVENT_ID, "fest")
    with pytest.raises(ConflictError):
        await links.check_free(_session(answers=[uuid.uuid4()]), EVENT_ID, "fest")


async def test_the_link_is_removed_and_gets_its_cost_centre(
    audits: list[dict[str, Any]],
) -> None:
    link = SimpleNamespace(id=uuid.uuid4(), slug="fest")
    session = _session(row=link, found=object())
    await links.remove_link(session, EVENT_ID, "ada")
    budget = uuid.uuid4()
    assert await links.set_income_budget(session, EVENT_ID, budget, "ada") is link
    await links.set_income_budget(session, EVENT_ID, None, "ada")
    assert [a["data"].get("incomeBudgetId") for a in audits] == [None, str(budget), None]
    session.found = None
    with pytest.raises(ValidationProblem):
        await links.set_income_budget(session, EVENT_ID, budget, "ada")
    with pytest.raises(NotFoundError):
        await links.remove_link(_session(row=None), EVENT_ID, "ada")
    refreshed = _session()
    await links.mark_refreshed(refreshed, None, datetime.now(UTC))
    await links.mark_refreshed(refreshed, link, datetime.now(UTC))  # pyright: ignore[reportArgumentType]
    assert refreshed.executed == 1


class _Budgets:
    def __init__(self, _session: Any, *, actor: str) -> None:
        self.actor = actor

    async def book_expense(self, data: Any, **_kw: Any) -> Any:
        return SimpleNamespace(id=uuid.uuid4())

    async def create_sub_booking(self, _parent: uuid.UUID, data: Any, **_kw: Any) -> Any:
        return SimpleNamespace(id=uuid.uuid4())


def _entry(**kw: Any) -> booking.Entry:
    values: dict[str, Any] = {
        "author": "Mollie",
        "kind": "expense",
        "budget_id": uuid.uuid4(),
        "amount": Decimal("0.60"),
        "on": date(2026, 11, 28),
        "text": "Gebühren",
        "reference": "stl_1",
    }
    return booking.Entry(**{**values, **kw})


async def test_the_booking_links_its_event_and_its_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(booking, "BudgetTreeService", _Budgets)
    session = _session()
    event = (EVENT_ID, ACTOR_ID)
    parts = (
        booking.Part(Decimal("0.32"), "Fest", event),
        booking.Part(Decimal("0.28"), "Ohne", None),
    )
    assert isinstance(await booking.book(session, _entry(event=event, parts=parts)), uuid.UUID)
    assert len(session.added) == 2


async def test_a_failed_booking_gives_its_cause(monkeypatch: pytest.MonkeyPatch) -> None:
    async def closed(_session: Any, _entry: Any) -> uuid.UUID:
        raise ConflictError("closed", code="fiscal_year_closed")

    async def invalid(_session: Any, _entry: Any) -> uuid.UUID:
        raise ValueError("too large")

    monkeypatch.setattr(booking, "_make", closed)
    assert await booking.book(_session(), _entry()) == "fiscal_year_closed"
    monkeypatch.setattr(booking, "_make", invalid)
    assert await booking.book(_session(), _entry()) == booking.INVALID
