"""The estimated duration of an agenda item (spec 001140): bounds, add, change, route."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.livevote.router import get_agenda_service, get_meeting_service
from app.modules.livevote.schemas import AgendaAddBody, AgendaDurationBody, MeetingOut
from app.modules.meetings.agenda_service import AgendaService
from app.modules.meetings.models import MeetingAgendaItem
from app.shared.errors import ConflictError
from tests.unit.modules.todos.fakes import ScriptedSession

MEETING = uuid.uuid4()
GREMIUM = uuid.uuid4()
ITEM = uuid.uuid4()


def test_a_duration_outside_1_to_480_is_refused() -> None:
    """§001140: the duration is a whole number from 1 to 480, or empty."""
    assert AgendaDurationBody.model_validate({"minutes": 1}).minutes == 1
    assert AgendaDurationBody.model_validate({"minutes": 480}).minutes == 480
    assert AgendaDurationBody.model_validate({"minutes": None}).minutes is None
    for bad in (0, 481, -5, 2.5):
        with pytest.raises(ValidationError):
            AgendaDurationBody.model_validate({"minutes": bad})
    assert (
        AgendaAddBody.model_validate({"title": "T", "estimatedMinutes": 10}).estimated_minutes == 10
    )
    with pytest.raises(ValidationError):
        AgendaAddBody.model_validate({"title": "T", "estimatedMinutes": 0})


def _service(session: ScriptedSession, status: str, audits: list[Any]) -> AgendaService:
    service = AgendaService(session)  # type: ignore[arg-type]

    async def _meeting(_mid: uuid.UUID, *, for_update: bool = False) -> Any:
        return SimpleNamespace(id=MEETING, status=status)

    async def _next(_mid: uuid.UUID) -> int:
        return 0

    async def _audit(action: Any, **kw: Any) -> None:
        audits.append((action, kw))

    async def _list(_mid: uuid.UUID) -> list[Any]:
        return []

    service._meeting = _meeting  # type: ignore[method-assign]
    service._next_position = _next  # type: ignore[method-assign]
    service._audit = _audit
    service.list = _list  # type: ignore[method-assign]
    return service


async def test_a_new_freetext_item_takes_the_duration() -> None:
    """§001140: the add stores the estimate on the new item."""
    session = ScriptedSession()
    assert await _service(session, "planned", []).add_in_tx(
        MEETING, title="Bericht", estimated_minutes=15
    )
    assert session.added[0].estimated_minutes == 15


def _row(minutes: int | None) -> MeetingAgendaItem:
    return MeetingAgendaItem(
        id=ITEM, meeting_id=MEETING, application_id=None, title="T", estimated_minutes=minutes
    )


async def test_set_duration_changes_clears_and_audits_once() -> None:
    """§001140: a change writes ``agenda_item_update``; the same value writes nothing."""
    audits: list[Any] = []
    row = _row(None)
    service = _service(ScriptedSession(), "live", audits)

    async def _item(_mid: uuid.UUID, _iid: uuid.UUID) -> MeetingAgendaItem:
        return row

    service.item = _item  # type: ignore[method-assign]
    await service.set_duration(MEETING, ITEM, 20, actor="p")
    assert row.estimated_minutes == 20
    await service.set_duration(MEETING, ITEM, 20, actor="p")
    await service.set_duration(MEETING, ITEM, None, actor="p")
    assert row.estimated_minutes is None
    assert [kw["fields"] for _a, kw in audits] == [["estimatedMinutes"], ["estimatedMinutes"]]


async def test_set_duration_on_a_closed_meeting_is_refused() -> None:
    """§001140: the duration follows the add and the move, so a closed meeting refuses it."""
    service = _service(ScriptedSession(), "closed", [])
    with pytest.raises(ConflictError) as err:
        await service.set_duration(MEETING, ITEM, 10, actor="p")
    assert err.value.code == "meeting_closed"


def _app(calls: list[Any], *, can_write: bool = True) -> TestClient:
    class _Meetings:
        async def get(self, _mid: uuid.UUID, _p: Principal) -> MeetingOut:
            return MeetingOut(
                id=MEETING,
                gremiumId=GREMIUM,
                title="GV",
                status="planned",
                createdAt=datetime(2026, 6, 8, tzinfo=UTC),
                canWrite=can_write,
            )

        async def broadcast_agenda(self, *args: Any) -> None:
            calls.append(("broadcast", args))

    class _Agenda:
        async def add(self, *args: Any, **kw: Any) -> list[Any]:
            calls.append(("add", kw))
            return []

        async def set_duration(self, *args: Any, **kw: Any) -> list[Any]:
            calls.append(("set_duration", args))
            return []

    app = create_app()
    app.dependency_overrides[get_meeting_service] = lambda: _Meetings()
    app.dependency_overrides[get_agenda_service] = lambda: _Agenda()
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p")
    return TestClient(app)


def test_the_routes_pass_the_duration() -> None:
    """§001140: the add and ``PUT …/duration`` hand the minutes to the service."""
    calls: list[Any] = []
    client = _app(calls)
    resp = client.post(
        f"/api/meetings/{MEETING}/agenda", json={"title": "Bericht", "estimatedMinutes": 15}
    )
    assert resp.status_code == 200
    assert calls[0] == ("add", calls[0][1])
    assert calls[0][1]["estimated_minutes"] == 15
    resp = client.put(f"/api/meetings/{MEETING}/agenda/{ITEM}/duration", json={"minutes": 30})
    assert resp.status_code == 200
    assert ("set_duration", (MEETING, ITEM, 30)) in calls
    assert (
        client.put(
            f"/api/meetings/{MEETING}/agenda/{ITEM}/duration", json={"minutes": 0}
        ).status_code
        == 422
    )


def test_the_duration_route_needs_the_write_right() -> None:
    """§001140: only a person who may change the agenda sets the duration."""
    calls: list[Any] = []
    resp = _app(calls, can_write=False).put(
        f"/api/meetings/{MEETING}/agenda/{ITEM}/duration", json={"minutes": 30}
    )
    assert resp.status_code == 403
    assert calls == []


def test_the_public_shapes_carry_no_duration() -> None:
    """§001145: the guest view and the public protocol carry no time plan."""
    from app.modules.livevote.public_schemas import GuestAgendaItem
    from app.modules.protocol.public import PublicTop, PublicTopOut

    for model in (GuestAgendaItem, PublicTop, PublicTopOut):
        fields = {f.alias or name for name, f in model.model_fields.items()} | set(
            model.model_fields
        )
        assert not fields & {"estimatedMinutes", "estimated_minutes"}
