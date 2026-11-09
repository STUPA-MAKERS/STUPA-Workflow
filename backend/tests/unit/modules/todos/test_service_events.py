"""``TodoService``: the Event writes and reads (specs 000478-000488) with a scripted session."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.livevote.models import MeetingAgendaItem
from app.modules.todos import events as todo_events
from app.modules.todos.links import Resolved
from app.modules.todos.models import (
    TodoCard,
    TodoCardEvent,
    TodoCardLabel,
    TodoCheckItem,
    TodoEvent,
    TodoEventSeries,
)
from app.modules.todos.schemas import CardCreate, EventIn
from app.modules.todos.service import TodoService
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from tests.unit.modules.todos.fakes import (
    ME,
    USER,
    FakeAccess,
    FakeFiles,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
    link,
)

OUT = object()
TOKEN = Principal(sub="t", scope_permissions=frozenset({"vote.cast"}))
APP = uuid.UUID(int=31)
SERIES = uuid.UUID(int=41)


class EventSession(ScriptedSession):
    """A scripted session that keeps the event rows apart, because their key is the card id."""

    def __init__(self, **kw: Any) -> None:
        super().__init__(**kw)
        self.event_rows: dict[uuid.UUID, TodoCardEvent] = {}

    def add(self, obj: Any) -> None:
        if isinstance(obj, TodoCardEvent):
            self.added.append(obj)
            self.event_rows[obj.card_id] = obj
            return
        super().add(obj)

    async def get(self, model: type, ident: Any, **kw: Any) -> Any:
        if model is TodoCardEvent:
            return self.event_rows.get(ident)
        return await super().get(model, ident, **kw)


def _svc(session: ScriptedSession, links: FakeLinks | None = None, **kw: Any) -> TodoService:
    service = TodoService(
        session,  # type: ignore[arg-type]
        access=FakeAccess(**kw),  # type: ignore[arg-type]
        links=links or FakeLinks(),  # type: ignore[arg-type]
        files=FakeFiles(),  # type: ignore[arg-type]
    )

    async def _detail(*_a: Any) -> Any:
        return OUT

    async def _details(pairs: Any, _p: Any) -> Any:
        return [c.id for c, _b in pairs]

    service._detail = _detail  # type: ignore[method-assign]
    service._details = _details  # type: ignore[method-assign]
    return service


def _setup(kind: str = "gremium", **kw: Any) -> tuple[EventSession, Any, Any, Any, TodoService]:
    b = board(kind=kind)
    col = column(b.id)
    c = card(b, col, **kw)
    session = EventSession()
    session.put(b, col, c)
    return session, b, col, c, _svc(session)


def _event_of(card_id: uuid.UUID, **kw: Any) -> TodoCardEvent:
    return TodoCardEvent(card_id=card_id, **kw)


async def test_link_view_needs_a_link_of_the_card() -> None:
    session, _b, _col, c, _ = _setup()
    item = MeetingAgendaItem(id=uuid.uuid4(), body="Text")
    session.put(item)
    mine = link(c.id, agenda_item_id=item.id)
    foreign = link(uuid.uuid4(), agenda_item_id=item.id)
    session.put(mine, foreign)
    links = FakeLinks(resolved={("agenda_item", item.id): Resolved(accessible=True, title="TOP")})
    session.scalars_q.append([])
    service = _svc(session, links)
    with pytest.raises(NotFoundError):
        await service.link_view(c.id, uuid.uuid4(), USER)
    with pytest.raises(NotFoundError):
        await service.link_view(c.id, foreign.id, USER)
    view = await service.link_view(c.id, mine.id, USER)
    assert (view.kind, view.title) == ("agenda_item", "TOP")
    assert [(f.key, f.value) for f in view.facts] == [("body", "Text")]


async def test_cards_keep_the_order_and_leave_out_unknown_and_unreadable() -> None:
    session = EventSession()
    readable, hidden = board(), board()
    first = card(readable, column(readable.id))
    second = card(readable, column(readable.id))
    secret = card(hidden, column(hidden.id))
    session.scalars_q[:] = [[first, second, secret], [readable, hidden]]

    class _Only(FakeAccess):
        async def can_read(self, b: Any, _p: Any) -> bool:
            return b.id == readable.id

    service = _svc(session)
    service.access = _Only()  # type: ignore[assignment]
    got = await service.cards([second.id, uuid.uuid4(), secret.id, first.id, second.id], USER)
    assert got == [second.id, first.id]


async def test_tile_of_an_archived_card_is_not_found() -> None:
    _session, _b, _col, c, service = _setup(archived_at=SimpleNamespace())
    with pytest.raises(NotFoundError):
        await service.tile(c.id, USER)


async def test_add_link_on_an_event_refuses_an_element_of_another_event() -> None:
    session, _b, _col, c, _ = _setup()
    session.event_rows[c.id] = _event_of(c.id)
    service = _svc(session, FakeLinks(readable=[("application", APP)]))
    session.scalar_q[:] = [c, None, uuid.uuid4()]
    with pytest.raises(ConflictError) as exc:
        await service.add_link(c.id, "application", APP, USER)
    assert exc.value.code == "event_link_taken"
    assert session.committed == 0
    session.scalar_q[:] = [c, None, None]
    assert await service.add_link(c.id, "application", APP, USER) is OUT
    assert session.committed == 1


@pytest.mark.parametrize(
    ("kind", "payload", "code"),
    [
        ("personal", EventIn(), "event_personal_board"),
        ("gremium", EventIn(endsOn=date(2026, 5, 1)), "event_dates_invalid"),
        (
            "gremium",
            EventIn(startsOn=date(2026, 5, 2), endsOn=date(2026, 5, 1)),
            "event_dates_invalid",
        ),
        ("gremium", EventIn(seriesId=SERIES), "series_not_found"),
    ],
)
async def test_set_event_checks_the_event_data(kind: str, payload: EventIn, code: str) -> None:
    session, _b, _col, c, service = _setup(kind=kind)
    session.scalar_q.append(c)
    with pytest.raises(ValidationProblem) as exc:
        await service.set_event(c.id, payload, USER)
    assert exc.value.code == code
    assert session.event_rows == {}


async def test_set_event_makes_a_todo_an_event_after_the_one_event_check() -> None:
    session, b, _col, c, service = _setup()
    session.put(TodoEventSeries(id=SERIES, name="Sommerfest", created_by=ME))
    payload = EventIn(
        startsOn=date(2026, 6, 1),
        endsOn=date(2026, 6, 2),
        place="  Mensa ",
        participants=80,
        seriesId=SERIES,
    )
    session.scalar_q[:] = [c, uuid.uuid4()]
    session.scalars_q.append([link(c.id, application_id=APP)])
    with pytest.raises(ConflictError) as exc:
        await service.set_event(c.id, payload, USER)
    assert exc.value.code == "event_link_taken"
    assert session.event_rows == {}
    session.scalar_q[:] = [c, None]
    session.scalars_q.append([link(c.id, application_id=APP)])
    assert await service.set_event(c.id, payload, USER) is OUT
    row = session.event_rows[c.id]
    assert (row.starts_on, row.ends_on, row.place, row.participants, row.series_id) == (
        date(2026, 6, 1),
        date(2026, 6, 2),
        "Mensa",
        80,
        SERIES,
    )
    assert session.committed == 1
    assert b.updated_at is not None


async def test_set_event_updates_an_existing_event_without_the_check() -> None:
    session, _b, _col, c, service = _setup()
    row = _event_of(c.id, place="Alt", participants=3, series_id=SERIES)
    session.event_rows[c.id] = row
    session.scalar_q.append(c)
    await service.set_event(c.id, EventIn(startsOn=date(2026, 7, 1), place="   "), USER)
    assert (row.starts_on, row.ends_on, row.place, row.participants, row.series_id) == (
        date(2026, 7, 1),
        None,
        None,
        None,
        None,
    )
    assert session.scalar_q == [] and session.committed == 1


async def test_remove_event_never_turns_an_event_back() -> None:
    session, _b, _col, c, service = _setup()
    with pytest.raises(NotFoundError):
        await service.remove_event(c.id, USER)
    session.event_rows[c.id] = _event_of(c.id)
    with pytest.raises(ConflictError) as exc:
        await service.remove_event(c.id, USER)
    assert exc.value.code == "event_permanent"


async def test_follow_up_needs_an_event() -> None:
    session, _b, _col, c, service = _setup()
    session.scalar_q.append(c)
    with pytest.raises(ValidationProblem) as exc:
        await service.follow_up(c.id, USER)
    assert exc.value.code == "not_an_event"


async def test_follow_up_copies_title_labels_place_series_and_an_open_checklist() -> None:
    session, b, col, c, service = _setup(title="Sommerfest 2026", description_md="Plan")
    done = column(b.id, "Erledigt", 1, is_done=True)
    session.event_rows[c.id] = _event_of(
        c.id, place="Wiese", series_id=SERIES, starts_on=date(2026, 6, 1), participants=99
    )
    label_id = uuid.uuid4()
    items = [
        TodoCheckItem(id=uuid.uuid4(), card_id=c.id, text="Bühne", done=True, position=0),
        TodoCheckItem(id=uuid.uuid4(), card_id=c.id, text="Flyer", done=False, position=1),
    ]
    session.scalar_q.append(c)
    session.scalars_q[:] = [[done, col], [label_id], items, []]
    assert await service.follow_up(c.id, USER) is OUT
    (new,) = [o for o in session.added if isinstance(o, TodoCard)]
    assert (new.title, new.description_md, new.column_id, new.due_date) == (
        "Sommerfest 2026",
        "Plan",
        done.id,
        None,
    )
    assert new.completed_at is not None and new.rank
    assert [o.label_id for o in session.added if isinstance(o, TodoCardLabel)] == [label_id]
    copies = [o for o in session.added if isinstance(o, TodoCheckItem)]
    assert [(i.text, i.done, i.position, i.card_id) for i in copies] == [
        ("Bühne", False, 0, new.id),
        ("Flyer", False, 1, new.id),
    ]
    row = session.event_rows[new.id]
    assert (row.place, row.series_id, row.starts_on, row.participants) == (
        "Wiese",
        SERIES,
        None,
        None,
    )
    assert [e.kind for e in session.added if isinstance(e, TodoEvent)] == ["created"]
    assert session.committed == 1


async def test_series_lists_by_name_and_filters() -> None:
    rows = [TodoEventSeries(id=SERIES, name="Sommerfest", created_by=ME)]
    session = EventSession(scalars=[rows, rows])
    service = _svc(session)
    out = await service.series(None, USER)
    assert [(s.id, s.name) for s in out] == [(SERIES, "Sommerfest")]
    await service.series("  50%_ ", USER)
    sql = str(session.statements[-1])
    assert "lower" in sql.lower() and "LIKE" in sql.upper()
    assert "WHERE" not in str(session.statements[0]).upper()


async def test_create_series_needs_a_writable_shared_board() -> None:
    shared = board()
    session = EventSession(scalars=[[shared]])
    service = _svc(session, write=False)
    with pytest.raises(ForbiddenError) as exc:
        await service.create_series("Fest", USER)
    assert exc.value.code == "todo_write_required"
    token = _svc(EventSession())
    with pytest.raises(ForbiddenError):
        await token.create_series("Fest", TOKEN)


async def test_create_series_checks_the_name() -> None:
    shared = board()
    session = EventSession(scalars=[[shared], [shared], [shared]], scalar=[uuid.uuid4(), None])
    service = _svc(session)
    with pytest.raises(ValidationProblem) as blank:
        await service.create_series("   ", USER)
    assert blank.value.code == "series_name_blank"
    with pytest.raises(ConflictError) as taken:
        await service.create_series("Fest", USER)
    assert taken.value.code == "series_exists"
    out = await service.create_series("  Sommerfest ", USER)
    assert out.name == "Sommerfest"
    (row,) = [o for o in session.added if isinstance(o, TodoEventSeries)]
    assert (row.id, row.created_by) == (out.id, ME)
    assert session.committed == 1


async def test_writable_events_list_the_events_of_writable_boards() -> None:
    assert await _svc(EventSession()).writable_events("x", TOKEN) == []
    shared = board(name="StuPa")
    col = column(shared.id)
    fest = card(shared, col, title="Fest")
    row = _event_of(fest.id, starts_on=date(2026, 6, 1), ends_on=date(2026, 6, 2))
    session = EventSession(scalars=[[shared], [shared]], execute=[[(fest, row)]])
    service = _svc(session)
    out = await service.writable_events(" Fe ", USER)
    assert [(e.id, e.board_name, e.title, e.starts_on, e.ends_on) for e in out] == [
        (fest.id, "StuPa", "Fest", date(2026, 6, 1), date(2026, 6, 2))
    ]
    assert "LIKE" in str(session.statements[-1]).upper()
    await service.writable_events(None, USER)
    assert "LIKE" not in str(session.statements[-1]).upper()
    session = EventSession(scalars=[[shared]])
    assert await _svc(session, write=False).writable_events(None, USER) == []


async def test_search_and_calendar_events_need_the_token_scope() -> None:
    session = EventSession()
    service = _svc(session)
    assert await service.search_events("Fest", TOKEN, limit=5) == []
    assert await service.calendar_events(TOKEN) == []
    assert session.statements == []
    b = board()
    found = (card(b, column(b.id)), b, _event_of(uuid.uuid4()))
    session.execute_q[:] = [[found], [found]]
    assert await service.search_events("Fest", USER, limit=5) == [found]
    assert await service.calendar_events(USER) == [found]


async def test_create_an_event_checks_the_event_and_its_links() -> None:
    session, b, col, _c, service = _setup()
    service.links = FakeLinks(readable=[("application", APP)])  # type: ignore[assignment]
    session.scalars_q.append([col])
    payload = CardCreate.model_validate(
        {
            "boardId": b.id,
            "title": "Fest",
            "links": [{"kind": "application", "targetId": APP}],
            "event": {"startsOn": "2026-06-01", "place": "Hof"},
        }
    )
    session.scalar_q.append(uuid.uuid4())
    with pytest.raises(ConflictError) as exc:
        await service.create(payload, USER)
    assert exc.value.code == "event_link_taken"
    session.scalars_q[:] = [[col], []]
    session.scalar_q.append(None)
    await service.create(payload, USER)
    (new,) = [o for o in session.added if isinstance(o, TodoCard)]
    row = session.event_rows[new.id]
    assert (row.starts_on, row.place) == (date(2026, 6, 1), "Hof")


async def test_event_facts_sum_decide_and_list_the_editions() -> None:
    session, b, col, c, service = _setup()
    other = card(b, col, title="Fest 2025", archived_at=SimpleNamespace())
    other_row = _event_of(other.id, starts_on=date(2025, 6, 1))
    decided = (
        SimpleNamespace(id=APP, data={"title": "Antrag"}, amount=Decimal("100.00")),
        SimpleNamespace(
            vote_id=None, decided_at=None, approved_amount=Decimal("80.00"), conditions=["Beleg"]
        ),
    )
    session.scalar_q.append(3)
    session.scalars_q[:] = [
        [link(c.id, application_id=APP)],
        [link(c.id, application_id=APP)],
    ]
    session.execute_q[:] = [
        [(other, b, other_row)],
        [(APP, Decimal("100.00"), Decimal("80.00"), True)],
        [(*decided, "StuPa")],
    ]
    facts = SimpleNamespace(events={c.id: _event_of(c.id, series_id=SERIES)})
    assert await service._event_facts([], facts, USER) == {}  # type: ignore[arg-type]
    out = (await service._event_facts([c], facts, USER))[c.id]  # type: ignore[arg-type]
    assert (out.totals.requested, out.totals.approved) == ("100.00", "80.00")
    (decision,) = out.decisions
    assert (decision.kind, decision.amount, decision.conditions, decision.meeting_title) == (
        "decision",
        "80.00",
        ["Beleg"],
        "StuPa",
    )
    (edition,) = out.editions
    assert (edition.id, edition.board_name, edition.archived, edition.totals.requested) == (
        other.id,
        b.name,
        True,
        "0.00",
    )
    assert out.hidden_editions == 2


async def test_event_facts_without_amount() -> None:
    session, _b, _col, c, service = _setup()
    session.scalars_q[:] = [[], [link(c.id, vote_id=APP)]]
    vote = SimpleNamespace(
        id=APP, question="Frage", application_id=None, closed_at=None, result="passed"
    )
    session.execute_q[:] = [[(vote, None, None)]]
    facts = SimpleNamespace(events={c.id: _event_of(c.id)})
    out = (await service._event_facts([c], facts, USER))[c.id]  # type: ignore[arg-type]
    assert [(d.kind, d.amount) for d in out.decisions] == [("vote", None)]
    assert out.editions == [] and out.hidden_editions == 0
    assert todo_events.Totals().balance == Decimal("0.00")
