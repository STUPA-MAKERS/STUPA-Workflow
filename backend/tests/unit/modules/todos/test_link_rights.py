"""``LinkRights``: the change right of each link kind (spec 001404)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.calendar.models import Appointment
from app.modules.calendar.rules import Viewer
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.todos import link_rights
from app.modules.todos.link_rights import LinkRights
from app.modules.voting.models import Vote
from app.shared.errors import ForbiddenError
from tests.unit.modules.todos.fakes import FakeAccess, ScriptedSession, board, card, column

GREMIUM = uuid.UUID(int=7)
ME = uuid.UUID(int=8)


def _rights(session: ScriptedSession, **kw: Any) -> LinkRights:
    return LinkRights(session, FakeAccess(**kw))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kind", "perm"),
    [
        ("gremium", "admin.gremien"),
        ("invoice", "budget.book"),
        ("expense", "budget.book"),
        ("order", "order.manage"),
        ("budget", "budget.structure"),
        ("ticket", "ticket.manage"),
    ],
)
async def test_global_rights(kind: str, perm: str) -> None:
    rights = _rights(ScriptedSession())
    target = uuid.uuid4()
    assert await rights.can_change(kind, target, Principal(sub="a", permissions={perm})) is True
    assert await rights.can_change(kind, target, Principal(sub="a")) is False


async def test_unknown_kind_changes_nothing() -> None:
    assert (
        await _rights(ScriptedSession()).can_change("nope", uuid.uuid4(), Principal(sub="a"))
        is False
    )


async def test_application_follows_the_edit_right(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed: set[uuid.UUID] = set()

    async def _edit(app_id: uuid.UUID, *_a: Any) -> None:
        if app_id not in allowed:
            raise ForbiddenError("no")

    monkeypatch.setattr(link_rights, "require_app_edit", _edit)
    rights = _rights(ScriptedSession())
    app = uuid.uuid4()
    assert await rights.can_change("application", app, Principal(sub="a")) is False
    allowed.add(app)
    assert await rights.can_change("application", app, Principal(sub="a")) is True


async def test_meeting_item_and_vote_use_the_gremium_rights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held: set[str] = set()

    async def _has(_s: Any, _p: Any, perm: str, gremium_id: uuid.UUID) -> bool:
        return gremium_id == GREMIUM and perm in held

    monkeypatch.setattr(link_rights, "has_gremium_permission", _has)
    session = ScriptedSession()
    meeting = Meeting(id=uuid.uuid4(), gremium_id=GREMIUM)
    item = MeetingAgendaItem(id=uuid.uuid4(), meeting_id=meeting.id)
    in_meeting = Vote(id=uuid.uuid4(), meeting_id=meeting.id, eligible_group="x")
    standalone = Vote(id=uuid.uuid4(), meeting_id=None, eligible_group=str(GREMIUM))
    broken = Vote(id=uuid.uuid4(), meeting_id=None, eligible_group="stupa")
    session.put(meeting, item, in_meeting, standalone, broken)
    rights = _rights(session)
    who = Principal(sub="a")
    for kind, target in (("meeting", meeting.id), ("agenda_item", item.id)):
        assert await rights.can_change(kind, target, who) is False
    held.add("session.manage")
    for kind, target in (("meeting", meeting.id), ("agenda_item", item.id)):
        assert await rights.can_change(kind, target, who) is True
    assert await rights.can_change("agenda_item", uuid.uuid4(), who) is False
    held.clear()
    held.add("vote.manage")
    assert await rights.can_change("vote", in_meeting.id, who) is True
    assert await rights.can_change("vote", standalone.id, who) is True
    assert await rights.can_change("vote", broken.id, who) is False
    assert await rights.can_change("vote", uuid.uuid4(), who) is False
    assert await rights.can_change("meeting", uuid.uuid4(), who) is False


async def test_appointment_creator_or_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _viewer(_self: Any, principal: Principal) -> Viewer:
        return Viewer(id=ME, manages=principal.has("calendar.manage"))

    monkeypatch.setattr(link_rights.AppointmentService, "viewer", _viewer)
    session = ScriptedSession()
    mine = Appointment(id=uuid.uuid4(), creator_id=ME)
    theirs = Appointment(id=uuid.uuid4(), creator_id=uuid.uuid4())
    session.put(mine, theirs)
    rights = _rights(session)
    assert await rights.can_change("appointment", mine.id, Principal(sub="a")) is True
    assert await rights.can_change("appointment", theirs.id, Principal(sub="a")) is False
    manager = Principal(sub="a", permissions={"calendar.manage"})
    assert await rights.can_change("appointment", theirs.id, manager) is True
    assert await rights.can_change("appointment", uuid.uuid4(), manager) is False


async def test_card_follows_the_board_write_right() -> None:
    session = ScriptedSession()
    b = board()
    c = card(b, column(b.id))
    session.put(b, c)
    assert await _rights(session, write=True).can_change("todo", c.id, Principal(sub="a"))
    assert not await _rights(session, write=False).can_change("todo", c.id, Principal(sub="a"))
    assert not await _rights(session).can_change("todo", uuid.uuid4(), Principal(sub="a"))
