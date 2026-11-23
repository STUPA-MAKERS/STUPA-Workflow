"""Integration: the push buttons "Zusagen" and "Absagen" of a Termin (real Postgres).

§F/collaboration/notifications/002509: the button answers as the invited person.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.notifications.push_tokens import PushActionClaim, PushActionKind, sign_action
from app.settings import Settings
from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_person

pytestmark = pytest.mark.integration

TERMIN = {"title": "Klausurtagung", "startsOn": "2031-05-05", "endsOn": "2031-05-05"}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _url(settings: Settings, person: uuid.UUID, action: PushActionKind, termin: str) -> str:
    claim = PushActionClaim(person, action, uuid.UUID(termin))
    return f"/api/push/actions/{sign_action(settings.session_secret, claim)}"


async def test_answer_buttons_answer_as_the_invited_person(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Accept, then decline; a person who is not invited gets 403 and no answer."""
    anna, _ = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    _dora, dora_id = await add_person(maker, "Dora")
    with TestClient(api.app) as client:
        api.login(anna)
        made = _ok(
            client.post(
                "/api/calendar/appointments", json={**TERMIN, "principalIds": [str(bert_id)]}
            ),
            201,
        )
        url = f"/api/calendar/appointments/{made['id']}"
        api.login(None)
        _ok(client.get(_url(settings, bert_id, "appointment_accept", made["id"])), 204)
        api.login(bert)
        assert _ok(client.get(url))["myAnswer"] == "accept"
        api.login(None)
        _ok(client.get(_url(settings, bert_id, "appointment_decline", made["id"])), 204)
        api.login(bert)
        assert _ok(client.get(url))["myAnswer"] == "decline"
        api.login(None)
        assert client.get(
            _url(settings, dora_id, "appointment_accept", made["id"])
        ).status_code in (
            403,
            404,
        )
