"""Link targets: the per-kind read rule, the hidden target, and the picker search."""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.applications.service import ApplicationsService
from app.modules.auth.principal import Principal
from app.modules.livevote.service import MeetingService
from app.modules.tickets.service import TicketService
from app.modules.todos import links as links_mod
from app.modules.todos.links import HIDDEN, PER_KIND, LinkResolver, card_url
from app.shared.errors import ForbiddenError
from tests.unit.modules.todos.fakes import FakeAccess, ScriptedSession, board, card, column

G1 = uuid.UUID(int=21)
APP = uuid.UUID(int=31)
APP2 = uuid.UUID(int=32)
MEETING = uuid.UUID(int=41)
ITEM = uuid.UUID(int=51)
TICKET = uuid.UUID(int=61)
STATE = uuid.UUID(int=71)
USER = Principal(sub="u")
READER = Principal(sub="r", permissions={"application.read", "ticket.manage"})


@pytest.fixture
def meeting_scope(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"scope": ({G1}, set()), "calls": 0}

    async def _scope(_self: Any, _principal: Principal) -> Any:
        box["calls"] += 1
        return box["scope"]

    monkeypatch.setattr(MeetingService, "meeting_read_scope", _scope)
    return box


def _app(app_id: uuid.UUID, **kw: Any) -> Any:
    return SimpleNamespace(
        id=app_id,
        data=kw.get("data", {"title": " Antrag "}),
        email_confirmed_at=kw.get("confirmed", date(2026, 1, 1)),
        current_state_id=kw.get("state", STATE),
    )


def _meeting(meeting_id: uuid.UUID = MEETING, gremium: uuid.UUID = G1) -> Any:
    return SimpleNamespace(
        id=meeting_id, gremium_id=gremium, title="Sitzung", date=date(2026, 5, 1)
    )


def test_card_url() -> None:
    assert card_url(G1, APP) == f"/todos/{G1}?card={APP}"


async def test_resolve_skips_empty_kinds_and_hides_missing_targets() -> None:
    resolver = LinkResolver(ScriptedSession(scalars=[[]]), FakeAccess())  # type: ignore[arg-type]
    out = await resolver.resolve([("ticket", TICKET)], READER)
    assert out == {("ticket", TICKET): HIDDEN}
    assert await resolver.resolve([], READER) == {}


async def test_applications_by_permission_and_by_access(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ScriptedSession(
        scalars=[[_app(APP), _app(APP2, state=None, data={})]],
        execute=[[(STATE, {"de": "Neu"})]],
    )
    out = await LinkResolver(session, FakeAccess()).resolve(  # type: ignore[arg-type]
        [("application", APP), ("application", APP2)], READER
    )
    first = out[("application", APP)]
    assert (first.accessible, first.title, first.url) == (True, "Antrag", f"/applications/{APP}")
    assert first.detail is not None and first.detail.state_label == {"de": "Neu"}
    second = out[("application", APP2)]
    assert second.title == "" and second.detail is not None and second.detail.state_label is None

    async def _deny(_db: Any, app_id: uuid.UUID, _p: Any, _a: Any) -> None:
        if app_id == APP:
            raise ForbiddenError("no")

    monkeypatch.setattr(links_mod, "resolve_app_read", _deny)
    unconfirmed = _app(uuid.uuid4(), confirmed=None)
    session = ScriptedSession(scalars=[[_app(APP), _app(APP2, state=None), unconfirmed]])
    out = await LinkResolver(session, FakeAccess()).resolve(  # type: ignore[arg-type]
        [("application", APP), ("application", APP2), ("application", unconfirmed.id)], USER
    )
    assert not out[("application", APP)].accessible
    assert out[("application", APP2)].accessible
    assert not out[("application", unconfirmed.id)].accessible


async def test_meetings_follow_the_meeting_scope(meeting_scope: dict[str, Any]) -> None:
    other = _meeting(uuid.uuid4(), gremium=uuid.uuid4())
    delegated = _meeting(uuid.uuid4(), gremium=uuid.uuid4())
    meeting_scope["scope"] = ({G1}, {delegated.id})
    session = ScriptedSession(scalars=[[_meeting(), other, delegated]])
    resolver = LinkResolver(session, FakeAccess())  # type: ignore[arg-type]
    out = await resolver.resolve(
        [("meeting", MEETING), ("meeting", other.id), ("meeting", delegated.id)], USER
    )
    seen = out[("meeting", MEETING)]
    assert seen.url == f"/meetings/{MEETING}"
    assert seen.detail is not None and seen.detail.date == "2026-05-01"
    assert not out[("meeting", other.id)].accessible
    assert out[("meeting", delegated.id)].accessible
    meeting_scope["scope"] = (None, set())
    resolver = LinkResolver(ScriptedSession(scalars=[[other]]), FakeAccess())  # type: ignore[arg-type]
    assert (await resolver.resolve([("meeting", other.id)], USER))[("meeting", other.id)].accessible


async def test_agenda_items_carry_the_top_number_and_the_application_title(
    meeting_scope: dict[str, Any],
) -> None:
    free = SimpleNamespace(id=ITEM, application_id=None, title="Freitext")
    with_app = SimpleNamespace(id=uuid.uuid4(), application_id=APP, title=None)
    hidden = SimpleNamespace(id=uuid.uuid4(), application_id=None, title="x")
    session = ScriptedSession(
        execute=[
            [(free, _meeting()), (with_app, _meeting()), (hidden, _meeting(gremium=uuid.uuid4()))],
            [(ITEM, 1), (with_app.id, 2)],
            [(APP, {"title": "Antrag"})],
        ]
    )
    out = await LinkResolver(session, FakeAccess()).resolve(  # type: ignore[arg-type]
        [("agenda_item", ITEM), ("agenda_item", with_app.id), ("agenda_item", hidden.id)], USER
    )
    item = out[("agenda_item", ITEM)]
    assert item.title == "Freitext" and item.url == f"/meetings/{MEETING}?item={ITEM}"
    assert item.detail is not None and item.detail.position == 1
    assert item.detail.meeting_title == "Sitzung"
    assert out[("agenda_item", with_app.id)].title == "Antrag"
    assert not out[("agenda_item", hidden.id)].accessible
    assert "row_number" in str(session.statements[1])


async def test_agenda_items_none_visible(meeting_scope: dict[str, Any]) -> None:
    meeting_scope["scope"] = (set(), set())
    item = SimpleNamespace(id=ITEM, application_id=APP, title=None)
    session = ScriptedSession(execute=[[(item, _meeting())]])
    out = await LinkResolver(session, FakeAccess()).resolve(  # type: ignore[arg-type]
        [("agenda_item", ITEM)], USER
    )
    assert out[("agenda_item", ITEM)] == HIDDEN
    assert len(session.statements) == 1


async def test_free_agenda_items_need_no_title_lookup(meeting_scope: dict[str, Any]) -> None:
    item = SimpleNamespace(id=ITEM, application_id=None, title=None)
    session = ScriptedSession(execute=[[(item, _meeting())], [(ITEM, 3)]])
    out = await LinkResolver(session, FakeAccess()).resolve(  # type: ignore[arg-type]
        [("agenda_item", ITEM)], USER
    )
    assert out[("agenda_item", ITEM)].title == ""
    assert len(session.statements) == 2


async def test_tickets_need_ticket_manage() -> None:
    ticket = SimpleNamespace(id=TICKET, title="Fehler", number=4, status="new")
    session = ScriptedSession(scalars=[[ticket]])
    resolver = LinkResolver(session, FakeAccess())  # type: ignore[arg-type]
    out = await resolver.resolve([("ticket", TICKET)], READER)
    detail = out[("ticket", TICKET)].detail
    assert detail is not None and detail.number == "T-0004" and detail.status == "new"
    assert not (await resolver.resolve([("ticket", TICKET)], USER))[("ticket", TICKET)].accessible


async def test_todos_follow_the_board_rule() -> None:
    b = board(name="StuPa")
    col = column(b.id, "Erledigt", is_done=True)
    c = card(b, col, title="Plakat")
    resolver = LinkResolver(ScriptedSession(execute=[[(c, b, col)]]), FakeAccess())  # type: ignore[arg-type]
    seen = (await resolver.resolve([("todo", c.id)], USER))[("todo", c.id)]
    assert seen.title == "Plakat" and seen.url == card_url(b.id, c.id)
    assert seen.detail is not None and seen.detail.is_done is True
    denied = LinkResolver(ScriptedSession(execute=[[(c, b, col)]]), FakeAccess(read=False))  # type: ignore[arg-type]
    assert not await denied.readable("todo", c.id, USER)


async def test_search_every_kind(
    monkeypatch: pytest.MonkeyPatch, meeting_scope: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    async def _apps(_self: Any, **kw: Any) -> Any:
        seen["apps"] = kw
        return SimpleNamespace(items=[SimpleNamespace(id=APP)])

    async def _tickets(_self: Any, **kw: Any) -> Any:
        seen["tickets"] = kw
        return SimpleNamespace(items=[SimpleNamespace(id=TICKET)])

    monkeypatch.setattr(ApplicationsService, "list_applications", _apps)
    monkeypatch.setattr(TicketService, "list", _tickets)
    b = board()
    col = column(b.id)
    c = card(b, col, title="Plakat drucken")
    ticket = SimpleNamespace(id=TICKET, title="Fehler", number=4, status="new")
    session = ScriptedSession(
        scalars=[[_app(APP)], [MEETING], [_meeting()], [ITEM], [ticket], [c.id]],
        execute=[
            [(STATE, {})],
            [(SimpleNamespace(id=ITEM, application_id=None, title="TOP"), _meeting())],
            [(ITEM, 1)],
            [(c, b, col)],
        ],
    )
    resolver = LinkResolver(session, FakeAccess())  # type: ignore[arg-type]
    hits = await resolver.search(" pla ", "all", READER, exclude_card_id=uuid.uuid4())
    assert [h.kind for h in hits] == ["application", "meeting", "agenda_item", "ticket", "todo"]
    assert seen["apps"]["q"] == "pla" and seen["apps"]["owner_sub"] is None
    assert seen["apps"]["limit"] == PER_KIND
    assert seen["tickets"] == {"q": "pla", "limit": PER_KIND}
    todo_sql = str(session.statements[-2])
    assert "todo_card.id !=" in todo_sql


async def test_search_without_rights(
    monkeypatch: pytest.MonkeyPatch, meeting_scope: dict[str, Any]
) -> None:
    seen: dict[str, Any] = {}

    async def _apps(_self: Any, **kw: Any) -> Any:
        seen.update(kw)
        return SimpleNamespace(items=[])

    monkeypatch.setattr(ApplicationsService, "list_applications", _apps)
    meeting_scope["scope"] = (None, set())
    session = ScriptedSession(scalars=[[], [], []])
    resolver = LinkResolver(session, FakeAccess())  # type: ignore[arg-type]
    assert await resolver.search("x", "application", USER) == []
    assert seen["owner_sub"] == "u" and seen["hide_pii_in_search"] is True
    assert await resolver.search("x", "ticket", USER) == []
    assert await resolver.search("x", "meeting", USER) == []
    assert "gremium_id IN" not in str(session.statements[-1])
    assert await resolver.search("x", "agenda_item", USER) == []
    assert await resolver.search("x", "todo", USER) == []
    assert "!=" not in str(session.statements[-1])
