"""Integration: @-mentions in the ticket notes (real Postgres).

A team note mentions holders of ``ticket.manage`` only (422 ``mention_not_member``
otherwise). The create mails every mention, the edit only the added ones, and a
``null`` list keeps the stored mentions. The reporter routes take no mentions, the
reporter edit keeps them, and the view of the reporter shows none.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.router import get_mention_mail_sender
from app.settings import Settings
from tests.integration.modules.tickets.conftest import MANAGER, Api, add_principal

pytestmark = pytest.mark.integration


class _Mentions:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, list[uuid.UUID]]] = []

    async def send(
        self, _settings: Settings, note_id: uuid.UUID, ids: list[uuid.UUID], _pool: object
    ) -> None:
        self.calls.append((note_id, ids))


async def _ticket(maker: async_sessionmaker[AsyncSession], reporter: uuid.UUID) -> uuid.UUID:
    async with maker() as session:
        row = Ticket(kind="bug", title="Fehler", body="x", reporter_principal_id=reporter)
        session.add(row)
        await session.commit()
        return row.id


async def test_a_team_note_mentions_managers_and_mails_the_new_ones(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Mention managers in a team note and mail the new ones.

    At first every mention is new, and the mail drops the author itself. A stored mention of
    a person who lost ``ticket.manage`` stays on an edit. The reporter sees the public note
    without the mentions and cannot mention.
    """
    me = await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia", role="admin")
    ada = await add_principal(maker, name="Ada", role="admin")
    bob = await add_principal(maker, name="Bob", role="admin")
    plain = await add_principal(maker, name="Paul")
    reporter_sub = f"rep-{uuid.uuid4().hex[:6]}"
    reporter = await add_principal(maker, sub=reporter_sub, name="Rita")
    ticket_id = await _ticket(maker, reporter)
    mails = _Mentions()
    api.app.dependency_overrides[get_mention_mail_sender] = lambda: mails.send
    api.login(MANAGER)
    with TestClient(api.app) as client:
        bad = client.post(
            f"/api/tickets/{ticket_id}/notes", json={"body": "x", "mentions": [str(plain)]}
        )
        assert bad.status_code == 422, bad.text
        assert bad.json()["code"] == "mention_not_member"
        assert bad.json()["errors"][0]["field"] == "mentions"

        made = client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={
                "body": "@Ada bitte",
                "visibility": "public",
                "mentions": [str(ada), str(ada), str(me)],
            },
        )
        assert made.status_code == 201, made.text
        note = made.json()
        assert note["mentions"] == [
            {"principalId": str(ada), "displayName": "Ada"},
            {"principalId": str(me), "displayName": "Mia"},
        ]
        note_id = uuid.UUID(note["id"])
        assert mails.calls == [(note_id, [ada, me])]

        kept = client.patch(f"/api/tickets/{ticket_id}/notes/{note_id}", json={"body": "neu"})
        assert kept.status_code == 200, kept.text
        assert [m["principalId"] for m in kept.json()["mentions"]] == [str(ada), str(me)]
        assert len(mails.calls) == 1

        changed = client.patch(
            f"/api/tickets/{ticket_id}/notes/{note_id}",
            json={"body": "neu", "mentions": [str(bob), str(ada)]},
        )
        assert changed.status_code == 200, changed.text
        assert [m["principalId"] for m in changed.json()["mentions"]] == [str(bob), str(ada)]
        assert mails.calls[-1] == (note_id, [bob])

        refused = client.patch(
            f"/api/tickets/{ticket_id}/notes/{note_id}",
            json={"body": "neu", "mentions": [str(plain)]},
        )
        assert refused.status_code == 422
        assert refused.json()["code"] == "mention_not_member"

        async with maker() as session:
            row = await session.get(TicketNote, note_id)
            assert row is not None
            row.mentions = [str(plain), str(ada)]
            await session.commit()
        kept_old = client.patch(
            f"/api/tickets/{ticket_id}/notes/{note_id}",
            json={"body": "neu", "mentions": [str(plain), str(bob), str(ada)]},
        )
        assert kept_old.status_code == 200, kept_old.text
        assert mails.calls[-1] == (note_id, [bob])
        restored = client.patch(
            f"/api/tickets/{ticket_id}/notes/{note_id}",
            json={"body": "neu", "mentions": [str(bob), str(ada)]},
        )
        assert restored.status_code == 200, restored.text

        detail = client.get(f"/api/tickets/{ticket_id}").json()
        assert [m["displayName"] for m in detail["notes"][0]["mentions"]] == ["Bob", "Ada"]

        api.login(Principal(sub=reporter_sub))
        mine = client.get(f"/api/tickets/mine/{ticket_id}").json()
        assert mine["notes"][0]["mentions"] == []
        sent = client.post(
            f"/api/tickets/mine/{ticket_id}/notes", json={"body": "Hallo", "mentions": [str(ada)]}
        )
        assert sent.status_code == 422
        own = client.post(f"/api/tickets/mine/{ticket_id}/notes", json={"body": "Hallo"})
        assert own.status_code == 201, own.text
        assert own.json()["mentions"] == []
        own_id = own.json()["id"]
        edit = client.patch(
            f"/api/tickets/mine/{ticket_id}/notes/{own_id}",
            json={"body": "Hallo!", "mentions": [str(ada)]},
        )
        assert edit.status_code == 422
    async with maker() as session:
        row = await session.get(TicketNote, note_id)
        assert row is not None
        assert row.mentions == [str(bob), str(ada)]
