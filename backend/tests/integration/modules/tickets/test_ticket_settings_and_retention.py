"""Integration: the help and ticket settings and the ticket retention (real Postgres).

Covers ``GET/PUT /admin/help-tickets`` with the new active version and the patched
draft, the public config, the retention cron with its attachments, and the ticket
anonymization of an account erasure.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.models import SiteConfigVersion
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.privacy.service import PrincipalService
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from tests._support.files_fakes import FakeStorage
from tests.integration.modules.tickets.conftest import ADMIN, Api, add_principal
from worker.tickets import anonymize_tickets

pytestmark = pytest.mark.integration

_SETTINGS = {
    "wikiUrl": "https://wiki.example.org/hilfe",
    "publicEnabled": False,
    "notifyNew": False,
    "retentionMonths": 3,
}


async def test_the_settings_save_as_a_new_active_version(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    api.login(ADMIN)
    with TestClient(api.app) as client:
        assert client.get("/api/admin/help-tickets").json()["retentionMonths"] == 12
        draft = client.put("/api/admin/site-config/draft", json={"appName": "Entwurf"})
        assert draft.status_code == 200, draft.text
        saved = client.put("/api/admin/help-tickets", json=_SETTINGS)
        assert saved.status_code == 200, saved.text
        assert saved.json() == _SETTINGS
        assert client.get("/api/admin/help-tickets").json() == _SETTINGS
        config = client.get("/api/admin/site-config").json()
        assert config["active"]["tickets"]["publicEnabled"] is False
        assert config["active"]["appName"] != "Entwurf"
        assert config["hasDraftChanges"] is True
        assert config["draft"]["appName"] == "Entwurf"
        assert config["draft"]["help"]["wikiUrl"] == _SETTINGS["wikiUrl"]
        api.login(None)
        public = client.get("/api/site-config").json()
        assert public["help"] == {"wikiUrl": _SETTINGS["wikiUrl"]}
        assert public["tickets"] == {"publicEnabled": False}
        assert "tickets" not in public["branding"]
        refused = client.post(
            "/api/tickets",
            json={"kind": "bug", "title": "t", "body": "b", "email": "a@example.org"},
        )
        assert refused.status_code == 403
        api.login(ADMIN)
        activated = client.post("/api/admin/site-config/activate")
        assert activated.status_code == 200
        assert activated.json()["active"]["tickets"]["retentionMonths"] == 3
        bad = client.put("/api/admin/help-tickets", json={**_SETTINGS, "wikiUrl": "x"})
        assert bad.status_code == 422
    async with maker() as session:
        versions = (
            await session.scalars(select(SiteConfigVersion).order_by(SiteConfigVersion.version))
        ).all()
    assert [(v.version, v.active) for v in versions] == [(2, False), (3, True)]


async def _closed_ticket(
    maker: async_sessionmaker[AsyncSession], *, months_ago: int, **kw: object
) -> Ticket:
    async with maker() as session:
        ticket = Ticket(
            kind="bug",
            title="alt",
            body="b",
            status="done",
            context={"url": "https://x"},
            closed_at=datetime.now(UTC) - timedelta(days=31 * months_ago),
            **kw,
        )
        session.add(ticket)
        await session.flush()
        session.add(
            Attachment(
                ticket_id=ticket.id,
                filename="a.png",
                mime="image/png",
                size=3,
                storage_key=f"tickets/{ticket.id}",
                scanned=True,
                scan_result="clean",
            )
        )
        await session.commit()
        return ticket


async def test_the_retention_cron_anonymizes_old_closed_tickets(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    author = await add_principal(maker, name="Ada")
    old = await _closed_ticket(maker, months_ago=13, reporter_email="old@example.org")
    fresh = await _closed_ticket(maker, months_ago=1, reporter_email="new@example.org")
    async with maker() as session:
        session.add(TicketNote(ticket_id=old.id, author_id=author, body="bleibt"))
        await session.commit()
    storage = FakeStorage()
    ctx = {"tickets_sessionmaker": maker, "object_storage": storage}
    assert await anonymize_tickets(ctx) == 1
    assert await anonymize_tickets(ctx) == 0
    assert storage.removed == [f"tickets/{old.id}"]
    async with maker() as session:
        row = await session.get(Ticket, old.id)
        assert row is not None
        assert (row.reporter_email, row.context, row.title) == (None, {}, "alt")
        assert row.anonymized_at is not None
        kept = await session.get(Ticket, fresh.id)
        assert kept is not None
        assert kept.anonymized_at is None
        files = (await session.scalars(select(Attachment.ticket_id))).all()
        assert files == [fresh.id]
        notes = (await session.scalars(select(TicketNote.body))).all()
        assert notes == ["bleibt"]


async def test_the_erasure_anonymizes_the_tickets_of_the_account(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    reporter = await add_principal(maker, name="Rita")
    ticket = await _closed_ticket(maker, months_ago=0, reporter_principal_id=reporter)
    api.login(ADMIN)
    with TestClient(api.app) as client:
        detail = client.get(f"/api/tickets/{ticket.id}").json()
        assert detail["reporter"]["displayName"] == "Rita"
    async with maker() as session:
        storage = FakeStorage()
        await PrincipalService(session).erase(
            reporter, actor="admin", files=FilesService(session, storage=storage)
        )
    with TestClient(api.app) as client:
        detail = client.get(f"/api/tickets/{ticket.id}").json()
    assert detail["reporter"] == {
        "principalId": None,
        "displayName": None,
        "email": None,
        "anonymized": True,
    }
    assert detail["context"] == {}
    assert detail["attachments"] == []
    assert detail["anonymizedAt"] is not None


async def test_the_retention_cron_drops_the_reporter_from_the_timeline(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    reporter = await add_principal(maker, name="Rita")
    worker = await add_principal(maker, name="Otto")
    ticket = await _closed_ticket(maker, months_ago=13, reporter_principal_id=reporter)
    async with maker() as session:
        session.add_all(
            [
                TicketEvent(ticket_id=ticket.id, actor_id=reporter, kind="created"),
                TicketEvent(
                    ticket_id=ticket.id,
                    actor_id=worker,
                    kind="status",
                    payload={"from": "new", "to": "done"},
                    created_at=datetime.now(UTC) + timedelta(seconds=1),
                ),
            ]
        )
        await session.commit()
    ctx = {"tickets_sessionmaker": maker, "object_storage": FakeStorage()}
    assert await anonymize_tickets(ctx) == 1
    api.login(ADMIN)
    with TestClient(api.app) as client:
        detail = client.get(f"/api/tickets/{ticket.id}").json()
    assert detail["reporter"]["anonymized"] is True
    events = {e["kind"]: e["actor"] for e in detail["events"]}
    assert events["created"] is None
    assert events["status"] == {"principalId": str(worker), "displayName": "Otto"}
    assert "Rita" not in str(detail)


async def test_the_erasure_anonymizes_the_reports_under_the_account_e_mail(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    reporter = await add_principal(maker, name="Rita", email="rita@example.org")
    bare = await _closed_ticket(maker, months_ago=0, reporter_email="Rita@Example.org")
    foreign = await _closed_ticket(maker, months_ago=0, reporter_email="else@example.org")
    async with maker() as session:
        await PrincipalService(session).erase(
            reporter, actor="admin", files=FilesService(session, storage=FakeStorage())
        )
    async with maker() as session:
        row = await session.get(Ticket, bare.id)
        assert row is not None
        assert (row.reporter_email, row.context) == (None, {})
        assert row.anonymized_at is not None
        kept = await session.get(Ticket, foreign.id)
        assert kept is not None
        assert kept.anonymized_at is None
