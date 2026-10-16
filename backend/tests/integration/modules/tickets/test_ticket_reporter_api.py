"""Integration: the view of the reporter on its own tickets (real Postgres).

Covers ``/tickets/mine``: the list, the detail with the public notes only, the
messages of the reporter, the 404 for another account, the sender block, the file
read gate of public and internal notes, the anonymization of the reporter's notes and
the flag ``has_reported_tickets`` of ``/auth/me``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.files.drafts import hash_draft_token
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.service import TicketService
from app.settings import Settings
from tests._support.memory_storage import MemoryStorage, wire_storage
from tests.integration.modules.tickets.conftest import MANAGER, Api, add_principal

pytestmark = pytest.mark.integration

REPORTER = Principal(sub="reporter-sub", email="rep@example.org")
STRANGER = Principal(sub="stranger-sub", email="stranger@example.org")
_REPORT = {"kind": "question", "title": "Wie geht das?", "body": "Ich finde den Knopf nicht."}


async def _draft(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage: MemoryStorage,
    token: str,
    name: str,
) -> uuid.UUID:
    draft_id = uuid.uuid4()
    key = f"drafts/{draft_id}/{name}"
    await storage.put(key, b"%PDF-1.4\n", "application/pdf")
    async with maker() as session:
        session.add(
            Attachment(
                id=draft_id,
                filename=name,
                mime="application/pdf",
                size=9,
                storage_key=key,
                scanned=True,
                scan_result="clean",
                draft_token_hash=hash_draft_token(token, settings.magic_link_secret),
                draft_expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.commit()
    return draft_id


async def test_the_reporter_reads_and_answers_only_the_public_thread(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    reporter_id = await add_principal(maker, sub=REPORTER.sub, email=REPORTER.email, name="Rex")
    await add_principal(maker, sub=STRANGER.sub, email=STRANGER.email, name="Sam")
    storage = MemoryStorage()
    wire_storage(api.app, storage)
    internal_file = await _draft(maker, settings, storage, "tok-a", "intern.pdf")
    public_file = await _draft(maker, settings, storage, "tok-b", "antwort.pdf")

    with TestClient(api.app) as client:
        api.login(REPORTER)
        assert client.get("/api/auth/me").json()["has_reported_tickets"] is False
        created = client.post("/api/tickets", json=_REPORT)
        assert created.status_code == 201, created.text
        assert client.get("/api/auth/me").json()["has_reported_tickets"] is True
        mine = client.get("/api/tickets/mine").json()
        assert mine["total"] == 1
        ticket_id = mine["items"][0]["id"]
        assert mine["items"][0]["number"] == created.json()["number"]

        api.login(MANAGER)
        internal = client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={
                "body": "nur intern",
                "attachmentIds": [str(internal_file)],
                "draftToken": "tok-a",
            },
        )
        assert internal.status_code == 201, internal.text
        assert internal.json()["visibility"] == "internal"
        public = client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={
                "body": "Oben rechts.",
                "visibility": "public",
                "attachmentIds": [str(public_file)],
                "draftToken": "tok-b",
            },
        )
        assert public.status_code == 201, public.text
        assert public.json()["visibility"] == "public"
        assert (
            client.patch(f"/api/tickets/{ticket_id}", json={"status": "in_progress"}).status_code
            == 200
        )

        api.login(REPORTER)
        detail = client.get(f"/api/tickets/mine/{ticket_id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert [n["body"] for n in body["notes"]] == ["Oben rechts."]
        assert body["notes"][0]["author"]["displayName"] == "Mia"
        assert body["canReply"] is True
        assert [(e["payload"]["from"], e["payload"]["to"]) for e in body["events"]] == [
            ("new", "in_progress")
        ]
        assert "assignee" not in body and "context" not in body
        # The file of the public note opens, the file of the internal note does not exist.
        assert client.get(f"/api/attachments/{public_file}/download").status_code == 200
        assert client.get(f"/api/attachments/{internal_file}/download").status_code == 404
        # The team routes stay closed.
        assert client.get(f"/api/tickets/{ticket_id}").status_code == 403

        answer = client.post(f"/api/tickets/mine/{ticket_id}/notes", json={"body": "Danke!"})
        assert answer.status_code == 201, answer.text
        assert answer.json()["visibility"] == "public"
        assert answer.json()["isOwn"] is True
        note_id = answer.json()["id"]
        edited = client.patch(
            f"/api/tickets/mine/{ticket_id}/notes/{note_id}", json={"body": "Danke sehr!"}
        )
        assert edited.status_code == 200
        team_note = public.json()["id"]
        assert (
            client.patch(
                f"/api/tickets/mine/{ticket_id}/notes/{team_note}", json={"body": "x"}
            ).status_code
            == 403
        )

        api.login(MANAGER)
        notes = client.get(f"/api/tickets/{ticket_id}").json()["notes"]
        assert [(n["body"], n["fromReporter"]) for n in notes] == [
            ("nur intern", False),
            ("Oben rechts.", False),
            ("Danke sehr!", True),
        ]

        # Another account never sees the ticket or its files.
        api.login(STRANGER)
        assert client.get("/api/tickets/mine").json()["total"] == 0
        assert client.get(f"/api/tickets/mine/{ticket_id}").status_code == 404
        assert (
            client.post(f"/api/tickets/mine/{ticket_id}/notes", json={"body": "x"}).status_code
            == 404
        )
        assert client.get(f"/api/attachments/{public_file}/download").status_code == 404

        # A block keeps the thread readable and stops the messages.
        api.login(MANAGER)
        assert client.post(f"/api/tickets/{ticket_id}/block-sender").status_code == 200
        api.login(REPORTER)
        assert client.get(f"/api/tickets/mine/{ticket_id}").json()["canReply"] is False
        blocked = client.post(f"/api/tickets/mine/{ticket_id}/notes", json={"body": "x"})
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "sender_blocked"

    # The anonymization takes the reporter off the ticket and off its notes.
    async with maker() as session:
        ticket = await session.get(Ticket, uuid.UUID(ticket_id))
        assert ticket is not None
        files = FilesService(session, storage=storage, settings=settings)  # pyright: ignore[reportArgumentType]
        await TicketService(session, files=files).anonymize(ticket, actor="test")
        await session.commit()
        authors = (
            await session.scalars(
                select(TicketNote.author_id).where(TicketNote.ticket_id == ticket.id)
            )
        ).all()
        assert reporter_id not in authors
        assert None in authors
    with TestClient(api.app) as client:
        api.login(REPORTER)
        assert client.get(f"/api/tickets/mine/{ticket_id}").status_code == 404
        assert client.get("/api/auth/me").json()["has_reported_tickets"] is False
        api.login(MANAGER)
        notes = client.get(f"/api/tickets/{ticket_id}").json()["notes"]
        assert notes[-1]["author"] == {"principalId": None, "displayName": None}
