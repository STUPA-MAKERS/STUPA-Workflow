"""``LinkService``: links between any two elements (specs 001400-001409)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.todos.link_service import LinkService
from app.modules.todos.links import Resolved
from app.modules.todos.models import Link
from app.modules.todos.schemas import TodoEventBrief, TodoLinkedCard, TodoLinkTarget
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from tests.unit.modules.todos.fakes import (
    ME,
    NOW,
    USER,
    FakeAccess,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
    link_row,
)

APP = uuid.UUID(int=11)
INVOICE = uuid.UUID(int=12)
TICKET = uuid.UUID(int=13)


class _Rights:
    def __init__(self, *ends: tuple[str, uuid.UUID]) -> None:
        self.ok = set(ends)

    async def can_change(self, kind: str, target_id: uuid.UUID, _p: Any) -> bool:
        return (kind, target_id) in self.ok


class _Todos:
    """The parts of ``TodoService`` that the link service uses."""

    def __init__(self, session: ScriptedSession, links: FakeLinks) -> None:
        self.session = session
        self.links = links
        self.access = FakeAccess()
        self.b = board()
        self.col = column(self.b.id)
        self.cards: dict[uuid.UUID, Any] = {}
        self.notes: list[tuple[uuid.UUID, tuple[str, uuid.UUID], bool]] = []
        self.checked: list[tuple[uuid.UUID, tuple[str, uuid.UUID]]] = []
        self.taken = False
        self.linked: dict[uuid.UUID, TodoLinkedCard] = {}

    def add_card(self) -> Any:
        c = card(self.b, self.col)
        self.cards[c.id] = c
        return c

    async def card_end(self, card_id: uuid.UUID, _p: Any, *, write: bool) -> Any:
        assert write is False
        return self.cards[card_id], self.b

    async def check_new_link(self, c: Any, other: tuple[str, uuid.UUID]) -> None:
        self.checked.append((c.id, other))
        if self.taken:
            raise ConflictError("taken", code="event_link_taken")

    def note_link(self, c: Any, _b: Any, other: Any, _actor: Any, *, added: bool) -> None:
        self.notes.append((c.id, other, added))

    async def actor_of(self, _p: Any) -> uuid.UUID:
        return ME

    async def linked_cards(self, ids: Any, _p: Any) -> dict[uuid.UUID, TodoLinkedCard]:
        return {i: self.linked[i] for i in ids if i in self.linked}


def _service(
    session: ScriptedSession, *, readable: Any = (), resolved: Any = None, change: Any = ()
) -> tuple[LinkService, _Todos]:
    todos = _Todos(session, FakeLinks(readable=readable, resolved=resolved))
    service = LinkService(session, todos, _Rights(*change))  # type: ignore[arg-type]
    return service, todos


def _edge(
    own: tuple[str, uuid.UUID], other: tuple[str, uuid.UUID], at: datetime
) -> tuple[Any, ...]:
    return (uuid.uuid4(), own[0], own[1], other[0], other[1], ME, at)


async def test_the_list_needs_read_access() -> None:
    service, _ = _service(ScriptedSession())
    with pytest.raises(NotFoundError):
        await service.of("application", APP, USER)


async def test_the_list_puts_the_event_first_then_kinds_then_newest() -> None:
    """§F/collaboration/links/001407: Event first, kind order, newest first in a kind."""
    session = ScriptedSession()
    own = ("application", APP)
    service, todos = _service(session, readable=[own], change=[own])
    event_card, plain_card, hidden_card = (uuid.uuid4() for _ in range(3))
    later, earlier = uuid.uuid4(), uuid.uuid4()
    base = TodoLinkedCard(
        id=plain_card,
        board_id=uuid.uuid4(),
        board_name="B",
        title="t",
        column_name="c",
        is_done=False,
    )
    todos.linked = {
        plain_card: base,
        event_card: base.model_copy(update={"id": event_card, "event": TodoEventBrief()}),
    }
    session.execute_q.append(
        [
            _edge(own, ("invoice", earlier), NOW),
            _edge(own, ("todo", plain_card), NOW),
            _edge(own, ("invoice", later), NOW + timedelta(days=1)),
            _edge(own, ("todo", event_card), NOW),
            _edge(own, ("todo", hidden_card), NOW),
            _edge(own, ("meeting", uuid.uuid4()), NOW),
        ]
    )
    service.todos.links.resolved = {  # type: ignore[attr-defined]
        ("invoice", later): Resolved(True, "R-2", "/invoices"),
        ("invoice", earlier): Resolved(True, "R-1", "/invoices"),
    }
    out = await service.of(*own, USER)
    assert out.can_link is True
    assert [(row.kind, row.title) for row in out.links] == [
        ("todo", None),
        ("meeting", None),
        ("invoice", "R-2"),
        ("invoice", "R-1"),
        ("todo", None),
    ]
    assert out.links[0].target_id == event_card and out.links[-1].target_id == plain_card
    assert all(row.removable for row in out.links)
    assert todos.links.grants is False


async def test_only_a_card_grants_and_a_row_is_removable_by_the_other_end() -> None:
    """§F/collaboration/links/001405 and 001404: card links resolve with the grant."""
    session = ScriptedSession()
    me = ("todo", uuid.uuid4())
    service, todos = _service(session, readable=[me], change=[("invoice", INVOICE)])
    session.execute_q.append(
        [_edge(me, ("invoice", INVOICE), NOW), _edge(me, ("application", APP), NOW)]
    )
    service.todos.links.resolved = {  # type: ignore[attr-defined]
        ("invoice", INVOICE): Resolved(True, "R", "/invoices"),
        ("application", APP): Resolved(True, "A", granted=True),
    }
    out = await service.of(*me, USER)
    assert todos.links.grants is True
    assert out.can_link is False
    assert {row.kind: row.removable for row in out.links} == {
        "application": False,
        "invoice": True,
    }


async def test_add_checks_the_ends_and_the_rights() -> None:
    session = ScriptedSession()
    app, inv = ("application", APP), ("invoice", INVOICE)
    service, _ = _service(session, readable=[app], change=[app])
    with pytest.raises(ValidationProblem) as exc:
        await service.add(app, app, USER)
    assert exc.value.code == "link_self"
    with pytest.raises(ValidationProblem) as exc:
        await service.add(app, inv, USER)
    assert exc.value.code == "link_target_not_found"
    service, _ = _service(session, readable=[app, inv])
    with pytest.raises(ForbiddenError) as forbidden:
        await service.add(app, inv, USER)
    assert forbidden.value.code == "link_forbidden"
    service, _ = _service(session, readable=[app, inv], change=[inv])
    session.scalar_q.append(link_row(app, inv))
    with pytest.raises(ConflictError) as exc:
        await service.add(app, inv, USER)
    assert exc.value.code == "link_exists"
    assert session.committed == 0


async def test_add_links_two_elements_and_notes_the_card_ends() -> None:
    """§F/collaboration/links/001400: a card links a ticket; both ends are stored once."""
    session = ScriptedSession()
    service, todos = _service(session)
    c = todos.add_card()
    me, ticket = ("todo", c.id), ("ticket", TICKET)
    todos.links.ok = {me, ticket}
    service = replace(service, rights=_Rights(me))
    session.scalar_q.append(None)
    await service.add(me, ticket, USER)
    (new,) = [o for o in session.added if isinstance(o, Link)]
    assert new.has_end(me) and new.has_end(ticket)
    assert todos.checked == [(c.id, ticket)] and todos.notes == [(c.id, ticket, True)]
    assert session.committed == 0


async def test_add_between_two_cards_notes_both_and_keeps_an_event_to_itself() -> None:
    session = ScriptedSession()
    service, todos = _service(session)
    one, two = todos.add_card(), todos.add_card()
    a, b = ("todo", one.id), ("todo", two.id)
    todos.links.ok = {a, b}
    service = replace(service, rights=_Rights(a))
    todos.taken = True
    session.scalar_q.append(None)
    with pytest.raises(ConflictError):
        await service.add(a, b, USER)
    assert session.added == []
    todos.taken = False
    session.scalar_q.append(None)
    await service.add(a, b, USER)
    assert sorted(todos.notes) == sorted([(one.id, b, True), (two.id, a, True)])


async def test_add_refuses_a_kind_whose_feature_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _kinds(_s: Any) -> tuple[str, ...]:
        return ("application",)

    monkeypatch.setattr("app.modules.todos.link_service.link_kinds_on", _kinds)
    service, _ = _service(ScriptedSession())
    with pytest.raises(ValidationProblem) as exc:
        await service.add(("application", APP), ("ticket", TICKET), USER)
    assert exc.value.code == "link_target_not_found"


async def test_remove_takes_the_link_from_both_ends() -> None:
    """§F/collaboration/links/001401: the removal from either end deletes the one row."""
    session = ScriptedSession()
    service, todos = _service(session)
    c = todos.add_card()
    me, app = ("todo", c.id), ("application", APP)
    row = link_row(app, me)
    session.put(row)
    with pytest.raises(NotFoundError):
        await service.remove(uuid.uuid4(), USER)
    todos.links.ok = {me, app}
    with pytest.raises(ForbiddenError):
        await service.remove(row.id, USER)
    service = replace(service, rights=_Rights(app))
    await service.remove(row.id, USER)
    assert session.deleted == [row]
    assert todos.notes == [(c.id, app, False)] and session.committed == 0


async def test_view_needs_a_readable_card_end() -> None:
    session = ScriptedSession()
    service, todos = _service(session)
    c = todos.add_card()
    me, app, inv = ("todo", c.id), ("application", APP), ("invoice", INVOICE)
    on_card = link_row(me, inv)
    plain = link_row(app, inv)
    session.put(on_card, plain)
    with pytest.raises(NotFoundError):
        await service.view(uuid.uuid4(), USER)
    with pytest.raises(NotFoundError):
        await service.view(plain.id, USER)
    with pytest.raises(NotFoundError):
        await service.view(on_card.id, USER)
    todos.links.ok = {me}
    with pytest.raises(NotFoundError):
        await service.view(on_card.id, USER)


async def test_targets_leave_out_the_element_and_its_links() -> None:
    """§F/collaboration/links/001408."""
    session = ScriptedSession()
    service, todos = _service(session)
    me = ("invoice", INVOICE)
    hits = [
        TodoLinkTarget(kind="invoice", target_id=INVOICE, title="self"),
        TodoLinkTarget(kind="application", target_id=APP, title="linked"),
        TodoLinkTarget(kind="ticket", target_id=TICKET, title="free"),
    ]
    todos.links.hits = hits
    assert await service.targets("ab", "all", USER) == hits
    session.execute_q.append([_edge(me, ("application", APP), NOW)])
    out = await service.targets("ab", "all", USER, exclude=me)
    assert [t.title for t in out] == ["free"]
    card_id = uuid.uuid4()
    session.execute_q.append([])
    await service.targets("", "todo", USER, exclude=("todo", card_id))
    assert todos.links.searched[-1] == ("", "todo", card_id)


def test_the_stored_order_is_stable() -> None:
    """§F/collaboration/links/001402: one pair, one order, whatever the call order."""
    one, other = ("todo", uuid.UUID(int=5)), ("application", uuid.UUID(int=9))
    first = Link.between(one, other, ME)
    second = Link.between(other, one, ME, datetime(2026, 1, 1, tzinfo=UTC))
    assert (first.a_kind, first.a_id, first.b_kind, first.b_id) == (
        second.a_kind,
        second.a_id,
        second.b_kind,
        second.b_id,
    )
    assert first.a_kind == "application" and first.other(other) == one
    same = Link.between(("todo", uuid.UUID(int=7)), ("todo", uuid.UUID(int=3)), ME)
    assert (same.a_id, same.b_id) == (uuid.UUID(int=3), uuid.UUID(int=7))


async def test_the_card_ends_lock_in_the_order_of_their_boards() -> None:
    """Two changes of the same two cards lock the boards in one order."""
    session = ScriptedSession()
    service, todos = _service(session)
    one, two = todos.add_card(), todos.add_card()
    low, high = sorted([uuid.uuid4(), uuid.uuid4()], key=str)
    one.board_id, two.board_id = high, low
    session.put(one, two)
    order: list[uuid.UUID] = []

    async def card_end(card_id: uuid.UUID, _p: Any, *, write: bool) -> Any:
        order.append(card_id)
        return todos.cards[card_id], todos.b

    todos.card_end = card_end
    ends = await service._cards([("todo", one.id), ("todo", two.id), ("ticket", TICKET)], USER)
    assert order == [two.id, one.id] and [end for end, _c, _b in ends] == [
        ("todo", two.id),
        ("todo", one.id),
    ]
