"""Integration: the push button "Erledigt" of a to-do (real Postgres).

§F/collaboration/notifications/002509: the button acts through the signed token as the
person it names, with the rights that person has now, and allows nothing else.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications.push_tokens import PushActionClaim, sign_action
from app.settings import Settings
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _url(settings: Settings, person: uuid.UUID, card: str) -> str:
    claim = PushActionClaim(person, "todo_done", uuid.UUID(card))
    return f"/api/push/actions/{sign_action(settings.session_secret, claim)}"


async def test_done_button_moves_the_card_as_the_named_person(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    """Move the card into done without a session; a second press changes nothing.

    A person without the write right on the board, a forged token and an inactive
    account all get 404.
    """
    gid, board = await add_gremium(maker, "Push")
    pia, pia_id = await add_person(maker, "Pia")
    _ole, ole_id = await add_person(maker, "Ole")
    await add_member(maker, gid, pia_id, "todo.write")
    with TestClient(api.app) as client:
        api.login(pia)
        columns = _ok(client.get(f"/api/todos/boards/{board}"))["columns"]
        done = next(c for c in columns if c["isDone"])
        card = _ok(
            client.post("/api/todos/cards", json={"boardId": str(board), "title": "Plakat"}), 201
        )
        api.login(None)
        _ok(client.get(_url(settings, pia_id, card["id"])), 204)
        _ok(client.get(_url(settings, pia_id, card["id"])), 204)
        api.login(pia)
        assert _ok(client.get(f"/api/todos/cards/{card['id']}"))["columnId"] == done["id"]
        api.login(None)
        _ok(client.get(_url(settings, ole_id, card["id"])), 404)
        _ok(client.get(_url(settings, pia_id, str(uuid.uuid4()))), 404)
        _ok(client.get(_url(settings, uuid.uuid4(), card["id"])), 404)
        _ok(client.get("/api/push/actions/forged-token"), 404)
        async with maker() as session:
            await session.execute(
                update(PrincipalRow).where(PrincipalRow.id == pia_id).values(active=False)
            )
            await session.commit()
        _ok(client.get(_url(settings, pia_id, card["id"])), 404)
