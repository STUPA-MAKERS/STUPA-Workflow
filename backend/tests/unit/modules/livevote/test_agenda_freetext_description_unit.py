"""The description of a new free-text agenda item: the body rule, the quote, the route."""

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
from app.modules.livevote.schemas import AgendaAddBody, MeetingOut
from app.modules.meetings.agenda_service import AgendaService, block_quote
from tests.unit.modules.todos.fakes import ScriptedSession

MEETING = uuid.uuid4()
GREMIUM = uuid.uuid4()


def test_description_goes_only_with_a_title() -> None:
    """§000861: the body takes a description only for a free-text item."""
    body = AgendaAddBody.model_validate({"title": "TOP", "description": "Info"})
    assert body.description == "Info"
    for bad in (
        {"applicationId": str(uuid.uuid4()), "description": "x"},
        {"todoId": str(uuid.uuid4()), "description": "x"},
    ):
        with pytest.raises(ValidationError):
            AgendaAddBody.model_validate(bad)


def test_block_quote_prefixes_every_line() -> None:
    """§000861: each line of the description gets the prefix ``> ``."""
    assert block_quote("  Eins\r\nZwei  \n\nDrei\n\n") == "> Eins\n> Zwei\n>\n> Drei"
    assert block_quote("solo") == "> solo"


def _service(session: ScriptedSession) -> AgendaService:
    service = AgendaService(session)  # type: ignore[arg-type]

    async def _meeting(_mid: uuid.UUID, *, for_update: bool = False) -> Any:
        return SimpleNamespace(id=MEETING, status="planned")

    async def _next(_mid: uuid.UUID) -> int:
        return 0

    async def _audit(_action: Any, **_kw: Any) -> None:
        return None

    service._meeting = _meeting  # type: ignore[method-assign]
    service._next_position = _next  # type: ignore[method-assign]
    service._audit = _audit
    return service


async def test_a_description_starts_the_text_as_a_quote() -> None:
    """§000861: the text of the new free-text item is the description as a quote."""
    session = ScriptedSession()
    service = _service(session)
    assert await service.add_in_tx(MEETING, title=" Bericht ", description="Zeile 1\nZeile 2")
    item = session.added[0]
    assert (item.title, item.body) == ("Bericht", "> Zeile 1\n> Zeile 2")


async def test_no_or_a_blank_description_leaves_the_text_empty() -> None:
    """§000861: a free-text item without a description has no text."""
    for description in (None, "  \n "):
        session = ScriptedSession()
        assert await _service(session).add_in_tx(MEETING, title="Bericht", description=description)
        assert session.added[0].body is None


def test_the_route_passes_the_description() -> None:
    """§000861: ``POST …/agenda`` hands the description to the service."""
    calls: list[Any] = []

    class _Meetings:
        async def get(self, _mid: uuid.UUID, _p: Principal) -> MeetingOut:
            return MeetingOut(
                id=MEETING,
                gremiumId=GREMIUM,
                title="GV",
                status="planned",
                createdAt=datetime(2026, 6, 8, tzinfo=UTC),
                canWrite=True,
            )

    class _Agenda:
        async def add(self, *args: Any, **kw: Any) -> list[Any]:
            calls.append((args, kw))
            return []

    app = create_app()
    app.dependency_overrides[get_meeting_service] = lambda: _Meetings()
    app.dependency_overrides[get_agenda_service] = lambda: _Agenda()
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p")
    resp = TestClient(app).post(
        f"/api/meetings/{MEETING}/agenda", json={"title": "Bericht", "description": "Info"}
    )
    assert resp.status_code == 200
    assert calls[0][1]["description"] == "Info"
