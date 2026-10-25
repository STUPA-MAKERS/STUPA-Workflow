"""An agenda item from a to-do card: the body rule, the service and the route."""

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
from app.modules.livevote import router as router_mod
from app.modules.livevote.agenda_service import AgendaService
from app.modules.livevote.models import MeetingAgendaItem
from app.modules.livevote.router import get_agenda_service, get_meeting_service
from app.modules.livevote.schemas import AgendaAddBody, MeetingOut
from app.modules.todos.live import BoardPings
from app.shared.errors import ConflictError
from tests.unit.modules.todos.fakes import ScriptedSession

MEETING = uuid.uuid4()
GREMIUM = uuid.uuid4()
CARD = uuid.uuid4()
BOARD = uuid.uuid4()


def test_the_body_takes_exactly_one_source() -> None:
    assert AgendaAddBody.model_validate({"todoId": str(CARD)}).todo_id == CARD
    assert AgendaAddBody.model_validate({"title": "TOP"}).title == "TOP"
    for body in (
        {},
        {"title": "x", "todoId": str(CARD)},
        {"applicationId": str(CARD), "title": "x"},
    ):
        with pytest.raises(ValidationError):
            AgendaAddBody.model_validate(body)


def _service(session: ScriptedSession, status: str = "live") -> tuple[AgendaService, list[Any]]:
    service = AgendaService(session)  # type: ignore[arg-type]
    audits: list[Any] = []

    async def _meeting(_mid: uuid.UUID, *, for_update: bool = False) -> Any:
        assert for_update
        return SimpleNamespace(id=MEETING, status=status)

    async def _next(_mid: uuid.UUID) -> int:
        return 3

    async def _audit(action: Any, **kw: Any) -> None:
        audits.append((action, kw))

    service._meeting = _meeting  # type: ignore[method-assign]
    service._next_position = _next  # type: ignore[method-assign]
    service._audit = _audit
    return service, audits


async def test_add_todo_in_tx_adds_the_item() -> None:
    session = ScriptedSession(scalar=[None])
    service, audits = _service(session)
    item = await service.add_todo_in_tx(MEETING, todo_id=CARD, title=" Plakat ", actor="p")
    assert (item.todo_id, item.title, item.position, item.application_id) == (
        CARD,
        "Plakat",
        3,
        None,
    )
    assert session.added == [item] and session.committed == 0
    assert audits[0][1]["todoId"] == str(CARD)


async def test_add_todo_in_tx_refuses_a_second_item_and_a_closed_meeting() -> None:
    service, _ = _service(ScriptedSession(scalar=[uuid.uuid4()]))
    with pytest.raises(ConflictError) as exc:
        await service.add_todo_in_tx(MEETING, todo_id=CARD, title="x")
    assert exc.value.code == "todo_already_on_agenda"
    closed, _ = _service(ScriptedSession(), status="closed")
    with pytest.raises(ConflictError) as exc:
        await closed.add_todo_in_tx(MEETING, todo_id=CARD, title="x")
    assert exc.value.code == "meeting_closed"


def test_the_route_adds_a_todo_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add a to-do item through the route.

    A card that got a link makes its board ping it after the commit.
    """
    calls: list[Any] = []
    session = ScriptedSession()

    class _Meetings:
        async def get(self, _mid: uuid.UUID, _p: Principal) -> MeetingOut:
            return MeetingOut(
                id=MEETING,
                gremiumId=GREMIUM,
                title="GV",
                status="live",
                createdAt=datetime(2026, 6, 8, tzinfo=UTC),
                canWrite=True,
            )

    class _Agenda:
        def __init__(self) -> None:
            self.session = session

        async def add_todo_in_tx(self, meeting_id: uuid.UUID, **kw: Any) -> Any:
            calls.append(("add", meeting_id, kw))
            return MeetingAgendaItem(id=uuid.uuid4(), meeting_id=meeting_id, todo_id=kw["todo_id"])

        async def list(self, _mid: uuid.UUID) -> list[Any]:
            return []

    class _Todos:
        def __init__(self, s: Any) -> None:
            assert s is session
            self.pings = BoardPings()

        async def card_for_agenda(self, card_id: uuid.UUID, gremium_id: uuid.UUID, _p: Any) -> Any:
            calls.append(("check", card_id, gremium_id))
            return SimpleNamespace(id=card_id, title="Plakat")

        async def link_agenda_item(self, card: Any, item_id: uuid.UUID, _p: Any) -> None:
            calls.append(("link", card.id, item_id))
            self.pings.touch(BOARD, card.id)

    class _Broker:
        def __init__(self) -> None:
            self.sent: list[tuple[str, dict[str, object]]] = []

        async def publish(self, channel: str, message: dict[str, object]) -> None:
            self.sent.append((channel, message))

    monkeypatch.setattr(router_mod, "TodoService", _Todos)
    app = create_app()
    broker = _Broker()
    app.state.broker = broker
    app.dependency_overrides[get_meeting_service] = lambda: _Meetings()
    app.dependency_overrides[get_agenda_service] = lambda: _Agenda()
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p")
    resp = TestClient(app).post(
        f"/api/meetings/{MEETING}/agenda", json={"todoId": str(CARD), "nonPublic": True}
    )
    assert resp.status_code == 200
    assert calls[0] == ("check", CARD, GREMIUM)
    assert calls[1][2] == {"todo_id": CARD, "title": "Plakat", "non_public": True, "actor": "p"}
    assert calls[2][0] == "link"
    assert session.committed == 1
    ping = {"type": "card", "boardId": str(BOARD), "cardId": str(CARD)}
    assert broker.sent == [(f"todo-board:{BOARD}", ping)]
