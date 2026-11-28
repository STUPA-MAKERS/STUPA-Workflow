"""Router tests of the pretix and Mollie integrations with fake services (no database).

They call each route function directly, so every line after a database call runs in the
trace: the commit, the result, the 404 without a connection, the 503 of pretix, the 409 of
a taken event, the 429 of the refresh, the 403 of `Daten abrufen` and the closed features.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.event_sales import router as mod
from app.modules.event_sales.outcome import Failure, Outcome
from app.modules.event_sales.sync import Available, Factories
from app.modules.pretix.client import ErrorCode, PretixError
from app.modules.pretix.schemas import IncomeBudgetIn, LinkIn
from app.modules.site_config.features import Feature, FeatureDisabledError
from app.settings import load_settings
from app.shared.errors import (
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ServiceUnavailableError,
)

NOW = datetime(2026, 11, 28, 8, 0, tzinfo=UTC)
EVENT_ID = uuid.uuid4()
PERSON = Principal(sub="ada", permissions={"budget.book", "pretix.use"})
TOKEN = Principal(sub="bot", scope_permissions=frozenset({"budget.book"}))
SETTINGS = load_settings()
FACTORIES = Factories()


@dataclass
class _FakeDb:
    commits: int = 0
    slugs: list[str] = field(default_factory=list[str])

    async def commit(self) -> None:
        self.commits += 1

    async def scalars(self, _query: Any) -> Any:
        return SimpleNamespace(all=lambda: self.slugs)


@dataclass
class _Client:
    error: ErrorCode | None = None

    async def events(self) -> list[Any]:
        if self.error:
            raise PretixError(self.error)
        return [
            SimpleNamespace(slug="fest", name="Fest", date_from=date(2027, 3, 12)),
            SimpleNamespace(slug="ball", name="Ball", date_from=None),
        ]

    async def event(self, slug: str) -> Any:
        if self.error:
            raise PretixError(self.error)
        return SimpleNamespace(slug=slug)


class _Connection:
    client_value: Any = None

    def __init__(self, *_a: Any) -> None:
        pass

    async def read(self) -> str:
        return "read"

    async def save(self, _data: Any, *, actor: str) -> str:
        return f"saved by {actor}"

    async def test(self) -> str:
        return "tested"

    async def client(self) -> Any:
        return type(self).client_value

    async def row(self) -> str:
        return "row"


class _FakeEvents:
    def __init__(self, teams: list[Any] | None = None) -> None:
        self.read: list[uuid.UUID] = []
        self._teams = teams or []

    async def get(self, event_id: uuid.UUID, _p: Principal) -> str:
        self.read.append(event_id)
        return "event"

    async def teams(self, _p: Principal) -> list[Any]:
        return self._teams


def _Db(**kw: Any) -> Any:
    return _FakeDb(**kw)


def _Events(teams: list[Any] | None = None) -> Any:
    return _FakeEvents(teams)


def _row(**kw: Any) -> Any:
    return SimpleNamespace(error=None, updated_at=NOW, **kw)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    seen: list[tuple[str, Any]] = []
    _Connection.client_value = _Client()
    monkeypatch.setattr(mod, "pretix_connection", SimpleNamespace(ConnectionService=_Connection))
    monkeypatch.setattr(mod, "mollie_connection", SimpleNamespace(ConnectionService=_Connection))

    async def check_free(_db: Any, _id: uuid.UUID, slug: str) -> None:
        seen.append(("check_free", slug))

    async def set_link(_db: Any, _event: Any, found: Any, actor: str) -> str:
        seen.append(("set_link", (found.slug, actor)))
        return "link"

    async def remove_link(_db: Any, event_id: uuid.UUID, actor: str) -> None:
        seen.append(("remove_link", (event_id, actor)))

    async def set_income_budget(_db: Any, _id: uuid.UUID, budget: Any, actor: str) -> str:
        seen.append(("income", (budget, actor)))
        return "link"

    async def mark_refreshed(_db: Any, link: Any, now: datetime) -> None:
        seen.append(("refreshed", now))

    async def link_out(_db: Any, link: Any) -> str:
        return f"out {link}"

    async def run(_db: Any, _s: Any, **kw: Any) -> Outcome:
        seen.append(("run", kw["pretix"]))
        return Outcome(2, (Failure("pretix", "order", "ABC12", "fiscal_year_closed"),))

    async def failed_bookings(_db: Any) -> list[Any]:
        return [_row(source="order", source_key="ABC12", source_id="tr_1")]

    async def event_sales(_db: Any, event_id: uuid.UUID, _p: Any, ctx: Any) -> Any:
        return (event_id, ctx)

    async def active_features(_db: Any) -> frozenset[Feature]:
        return frozenset({Feature.PRETIX})

    links = SimpleNamespace(
        check_free=check_free,
        set_link=set_link,
        remove_link=remove_link,
        set_income_budget=set_income_budget,
        mark_refreshed=mark_refreshed,
        link_of=_link_of,
    )
    monkeypatch.setattr(mod, "links", links)
    monkeypatch.setattr(mod, "link_out", link_out)
    monkeypatch.setattr(mod, "run", run)
    monkeypatch.setattr(mod, "event_sales", event_sales)
    monkeypatch.setattr(mod, "active_features", active_features)
    monkeypatch.setattr(mod, "pretix_sync", SimpleNamespace(failed_bookings=failed_bookings))
    monkeypatch.setattr(mod, "mollie_sync", SimpleNamespace(failed_bookings=failed_bookings))
    _LINK["value"] = None
    return seen


_LINK: dict[str, Any] = {"value": None}


async def _link_of(_db: Any, _id: uuid.UUID) -> Any:
    return _LINK["value"]


def _available(monkeypatch: pytest.MonkeyPatch, *, pretix: bool, mollie: bool) -> None:
    async def available(_db: Any, _s: Any) -> Available:
        return Available(pretix=pretix, mollie=mollie)

    monkeypatch.setattr(mod, "available", available)


async def test_the_admin_routes_answer_and_commit(calls: list[tuple[str, Any]]) -> None:
    db = _Db()
    data: Any = object()
    assert await mod.read_pretix_connection(PERSON, db, SETTINGS) == "read"
    assert await mod.save_pretix_connection(data, PERSON, db, SETTINGS) == "saved by ada"
    assert await mod.test_pretix_connection(PERSON, db, SETTINGS, FACTORIES) == "tested"
    assert await mod.read_mollie_connection(PERSON, db) == "read"
    assert await mod.save_mollie_connection(data, PERSON, db) == "saved by ada"
    assert await mod.test_mollie_connection(PERSON, db, FACTORIES) == "tested"
    assert db.commits == 6
    pretix = await mod.list_pretix_failed(PERSON, db)
    mollie = await mod.list_mollie_failed(PERSON, db)
    assert [(i.key, i.error) for i in pretix.items] == [("ABC12", "")]
    assert [i.key for i in mollie.items] == ["tr_1"]


async def test_a_token_cannot_call_pretix_or_mollie(calls: list[tuple[str, Any]]) -> None:
    db = _Db()
    with pytest.raises(ForbiddenError):
        await mod.test_pretix_connection(TOKEN, db, SETTINGS, FACTORIES)
    with pytest.raises(ForbiddenError):
        await mod.test_mollie_connection(TOKEN, db, FACTORIES)
    assert db.commits == 0


async def test_the_picker_marks_the_taken_events(calls: list[tuple[str, Any]]) -> None:
    db = _Db(slugs=["ball"])
    out = await mod.list_pretix_events(PERSON, db, SETTINGS, FACTORIES)
    assert [(e.slug, e.taken) for e in out] == [("fest", False), ("ball", True)]


async def test_the_picker_without_pretix(calls: list[tuple[str, Any]]) -> None:
    _Connection.client_value = None
    with pytest.raises(NotFoundError):
        await mod.list_pretix_events(PERSON, _Db(), SETTINGS, FACTORIES)
    _Connection.client_value = _Client(error="unreachable")
    with pytest.raises(ServiceUnavailableError):
        await mod.list_pretix_events(PERSON, _Db(), SETTINGS, FACTORIES)


async def test_the_link_is_set_removed_and_gets_its_cost_centre(
    calls: list[tuple[str, Any]],
) -> None:
    db = _Db()
    events = _Events()
    out = await mod.set_pretix_link(
        EVENT_ID, LinkIn(slug="fest"), PERSON, db, SETTINGS, events, FACTORIES
    )
    assert out == "out link"
    budget = uuid.uuid4()
    body = IncomeBudgetIn.model_validate({"budgetId": budget})
    assert await mod.set_income_budget(EVENT_ID, body, PERSON, db, events) == "out link"
    response = await mod.remove_pretix_link(EVENT_ID, PERSON, db, events)
    assert response.status_code == 204
    assert ("set_link", ("fest", "ada")) in calls
    assert ("income", (budget, "ada")) in calls
    assert ("remove_link", (EVENT_ID, "ada")) in calls
    assert db.commits == 3
    assert events.read == [EVENT_ID] * 3


@pytest.mark.parametrize(
    ("client", "error"),
    [
        (None, NotFoundError),
        (_Client(error="not_found"), NotFoundError),
        (_Client(error="unreachable"), ServiceUnavailableError),
    ],
)
async def test_the_link_fails_without_pretix_or_its_event(
    calls: list[tuple[str, Any]], client: Any, error: type[Exception]
) -> None:
    _Connection.client_value = client
    db = _Db()
    with pytest.raises(error):
        await mod.set_pretix_link(
            EVENT_ID, LinkIn(slug="fest"), PERSON, db, SETTINGS, _Events(), FACTORIES
        )
    assert db.commits == 0


async def test_a_token_cannot_link(calls: list[tuple[str, Any]]) -> None:
    for call in (
        mod.set_pretix_link(
            EVENT_ID, LinkIn(slug="f"), TOKEN, _Db(), SETTINGS, _Events(), FACTORIES
        ),
        mod.remove_pretix_link(EVENT_ID, TOKEN, _Db(), _Events()),
        mod.set_income_budget(EVENT_ID, IncomeBudgetIn(), TOKEN, _Db(), _Events()),
        mod.list_pretix_events(TOKEN, _Db(), SETTINGS, FACTORIES),
    ):
        with pytest.raises(ForbiddenError):
            await call


async def test_the_section_reads_the_context(calls: list[tuple[str, Any]]) -> None:
    db = _Db()
    result: Any = await mod.read_event_sales(EVENT_ID, PERSON, db, SETTINGS, _Events())
    event_id, ctx = result
    assert event_id == EVENT_ID
    assert (ctx.pretix_on, ctx.mollie_on) == (True, False)
    assert db.commits == 1


async def test_the_refresh_runs_once_a_minute(calls: list[tuple[str, Any]]) -> None:
    db = _Db()
    out = await mod.refresh_event_sales(EVENT_ID, PERSON, db, SETTINGS, _Events(), FACTORIES)
    assert out.booked == 2
    assert [f.cause for f in out.failures] == ["fiscal_year_closed"]
    assert ("run", EVENT_ID) in calls
    _LINK["value"] = SimpleNamespace(refreshed_at=datetime.now(UTC) - timedelta(seconds=20))
    with pytest.raises(RateLimitedError):
        await mod.refresh_event_sales(EVENT_ID, PERSON, db, SETTINGS, _Events(), FACTORIES)
    _LINK["value"] = SimpleNamespace(refreshed_at=datetime.now(UTC) - timedelta(minutes=2))
    await mod.refresh_event_sales(EVENT_ID, PERSON, db, SETTINGS, _Events(), FACTORIES)
    assert db.commits == 2
    with pytest.raises(ForbiddenError):
        await mod.refresh_event_sales(EVENT_ID, TOKEN, db, SETTINGS, _Events(), FACTORIES)


async def test_the_sync_state_tells_the_integrations(
    calls: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch, pretix=True, mollie=False)
    out = await mod.read_sync_state(PERSON, _Db(), SETTINGS)
    assert (out.pretix, out.mollie) == (True, False)


async def test_the_sync_needs_the_right_of_its_page(
    calls: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch, pretix=True, mollie=True)
    reader = Principal(sub="reader")
    db = _Db()
    with pytest.raises(ForbiddenError):
        await mod.run_sync(reader, db, SETTINGS, _Events(), FACTORIES, "bookings")
    with pytest.raises(ForbiddenError):
        await mod.run_sync(reader, db, SETTINGS, _Events(), FACTORIES, "events")
    with pytest.raises(ForbiddenError):
        await mod.run_sync(TOKEN, db, SETTINGS, _Events(), FACTORIES, "bookings")
    out = await mod.run_sync(reader, db, SETTINGS, _Events(["team"]), FACTORIES, "events")
    assert out.booked == 2
    out = await mod.run_sync(PERSON, db, SETTINGS, _Events(), FACTORIES, "bookings")
    assert ("run", "active") in calls
    assert db.commits == 2


async def test_the_sync_is_closed_without_an_integration(
    calls: list[tuple[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _available(monkeypatch, pretix=False, mollie=False)
    with pytest.raises(FeatureDisabledError):
        await mod.run_sync(PERSON, _Db(), SETTINGS, _Events(), FACTORIES, "bookings")


def test_the_helpers() -> None:
    assert isinstance(mod.get_factories(), Factories)
    assert isinstance(mod._today(SETTINGS), date)
