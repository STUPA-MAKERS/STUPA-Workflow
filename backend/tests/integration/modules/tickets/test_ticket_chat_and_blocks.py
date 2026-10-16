"""Integration: note files and sender blocks of the tickets (real Postgres).

Covers the files of a ticket note (bind, read gate, download, quarantine, removal
with the note, the anonymized ticket) and the sender blocks (block, unblock, the
list, the delete, the held-back report in both match directions, the erasure and the
Auskunft read).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.files.drafts import hash_draft_token
from app.modules.files.models import Attachment
from app.modules.files.service import FilesService
from app.modules.privacy.service import erase_email
from app.modules.tickets.models import Ticket, TicketNote, TicketSenderBlock
from app.modules.tickets.service import erase_sender_blocks, sender_blocks_of
from app.settings import Settings
from tests._support.memory_storage import MemoryStorage, wire_storage
from tests.integration.modules.tickets.conftest import (
    ADMIN,
    MANAGER,
    PLAIN,
    Api,
    add_principal,
)

pytestmark = pytest.mark.integration

_REPORT = {"kind": "bug", "title": "Knopf geht nicht", "body": "Beim Klick passiert nichts."}


async def _draft(
    maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    storage: MemoryStorage,
    token: str,
    *,
    name: str = "beleg.pdf",
    scan: str | None = "clean",
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
                scanned=scan is not None,
                scan_result=scan,
                draft_token_hash=hash_draft_token(token, settings.magic_link_secret),
                draft_expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.commit()
    return draft_id


async def _ticket(
    maker: async_sessionmaker[AsyncSession],
    *,
    reporter: uuid.UUID | None = None,
    email: str | None = None,
    anonymized: bool = False,
) -> uuid.UUID:
    async with maker() as session:
        row = Ticket(
            kind="bug",
            title="Fehler",
            body="x",
            reporter_principal_id=reporter,
            reporter_email=email if reporter is None else None,
            anonymized_at=datetime.now(UTC) if anonymized else None,
        )
        session.add(row)
        await session.commit()
        return row.id


async def _by_number(maker: async_sessionmaker[AsyncSession], number: str) -> Ticket | None:
    async with maker() as session:
        return await session.scalar(select(Ticket).where(Ticket.number == int(number[2:])))


# -- note files ------------------------------------------------------------------


async def test_a_note_binds_its_files_and_a_manager_downloads_them(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    ticket_id = await _ticket(maker, email="x@example.org")
    storage = MemoryStorage()
    wire_storage(api.app, storage)
    clean = await _draft(maker, settings, storage, "tok", name="a.pdf")
    pending = await _draft(maker, settings, storage, "tok", name="b.pdf", scan=None)
    api.login(MANAGER)
    with TestClient(api.app) as client:
        note = client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={"body": "", "attachmentIds": [str(clean), str(pending)], "draftToken": "tok"},
        )
        assert note.status_code == 201, note.text
        out = note.json()
        assert [(a["filename"], a["scanState"]) for a in out["attachments"]] == [
            ("a.pdf", "clean"),
            ("b.pdf", "scanning"),
        ]
        detail = client.get(f"/api/tickets/{ticket_id}").json()
        assert [a["id"] for a in detail["notes"][0]["attachments"]] == [str(clean), str(pending)]
        assert detail["attachments"] == []
        url = client.get(f"/api/attachments/{clean}")
        assert url.status_code == 200, url.text
        assert url.json()["url"] == f"/api/attachments/{clean}/download"
        down = client.get(f"/api/attachments/{clean}/download")
        assert down.status_code == 200 and down.content == b"%PDF-1.4\n"
        assert client.get(f"/api/attachments/{pending}/download").status_code == 409
        # The application delete route never reaches a message file.
        assert client.delete(f"/api/attachments/{clean}").status_code == 404

        # Without ticket.manage the file does not exist.
        api.login(PLAIN)
        for path in (f"/api/attachments/{clean}", f"/api/attachments/{clean}/download"):
            resp = client.get(path)
            assert resp.status_code == 404
            assert resp.headers["content-type"].startswith("application/problem+json")
    async with maker() as session:
        row = await session.get(Attachment, clean)
        assert row is not None
        assert row.ticket_note_id is not None and row.application_id is None
        assert row.draft_token_hash is None and row.draft_expires_at is None


async def test_a_quarantined_note_file_never_downloads(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email)
    ticket_id = await _ticket(maker, email="x@example.org")
    storage = MemoryStorage()
    wire_storage(api.app, storage)
    draft = await _draft(maker, settings, storage, "tok")
    api.login(MANAGER)
    with TestClient(api.app) as client:
        resp = client.post(
            f"/api/tickets/{ticket_id}/notes",
            json={"body": "Bild", "attachmentIds": [str(draft)], "draftToken": "tok"},
        )
        assert resp.status_code == 201, resp.text
        async with maker() as session:
            await session.execute(
                update(Attachment)
                .where(Attachment.id == draft)
                .values(scan_result="infected:Eicar", storage_key=None)
            )
            await session.commit()
        detail = client.get(f"/api/tickets/{ticket_id}").json()
        assert detail["notes"][0]["attachments"][0]["scanState"] == "quarantined"
        assert client.get(f"/api/attachments/{draft}").status_code == 410
        assert client.get(f"/api/attachments/{draft}/download").status_code == 410


async def test_a_note_rejects_foreign_drafts_and_files_on_an_anonymized_ticket(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email)
    ticket_id = await _ticket(maker, email="x@example.org")
    gone = await _ticket(maker, email="y@example.org", anonymized=True)
    storage = MemoryStorage()
    draft = await _draft(maker, settings, storage, "tok")
    api.login(MANAGER)
    with TestClient(api.app) as client:
        url = f"/api/tickets/{ticket_id}/notes"
        no_token = client.post(url, json={"body": "x", "attachmentIds": [str(draft)]})
        assert no_token.status_code == 422
        assert no_token.json()["errors"][0]["field"] == "draftToken"
        foreign = client.post(
            url, json={"body": "x", "attachmentIds": [str(draft)], "draftToken": "other"}
        )
        assert foreign.status_code == 422
        assert foreign.json()["code"] == "draft_attachments_missing"
        empty = client.post(url, json={"body": "  "})
        assert empty.status_code == 422
        assert empty.json()["errors"][0]["field"] == "body"
        too_many = client.post(
            url,
            json={
                "body": "x",
                "attachmentIds": [str(uuid.uuid4()) for _ in range(6)],
                "draftToken": "tok",
            },
        )
        assert too_many.status_code == 422
        anonymized = client.post(
            f"/api/tickets/{gone}/notes",
            json={"body": "x", "attachmentIds": [str(draft)], "draftToken": "tok"},
        )
        assert anonymized.status_code == 422
        assert anonymized.json()["code"] == "ticket_anonymized"
    async with maker() as session:
        row = await session.get(Attachment, draft)
        assert row is not None and row.ticket_note_id is None


async def test_removing_a_note_or_a_ticket_removes_the_note_files(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    ticket_id = await _ticket(maker, email="x@example.org")
    storage = MemoryStorage()
    first = await _draft(maker, settings, storage, "tok", name="a.pdf")
    second = await _draft(maker, settings, storage, "tok", name="b.pdf")
    api.login(MANAGER)
    with TestClient(api.app) as client:
        notes = []
        for draft in (first, second):
            resp = client.post(
                f"/api/tickets/{ticket_id}/notes",
                json={"body": "n", "attachmentIds": [str(draft)], "draftToken": "tok"},
            )
            assert resp.status_code == 201, resp.text
            notes.append(resp.json()["id"])
        assert client.delete(f"/api/tickets/{ticket_id}/notes/{notes[0]}").status_code == 204
    async with maker() as session:
        assert await session.get(Attachment, first) is None
        assert await session.get(Attachment, second) is not None
        # A note marked deleted hides its remaining files.
        await session.execute(
            update(TicketNote)
            .where(TicketNote.id == uuid.UUID(notes[1]))
            .values(deleted_at=datetime.now(UTC))
        )
        await session.commit()
    wire_storage(api.app, storage)
    with TestClient(api.app) as client:
        assert client.get(f"/api/attachments/{second}").status_code == 404
    async with maker() as session:
        files = FilesService(session, storage=storage, settings=settings)  # pyright: ignore[reportArgumentType]
        await files.delete_for_ticket(ticket_id, actor="test")
        await session.commit()
        assert await session.get(Attachment, second) is None
    assert f"drafts/{second}/b.pdf" not in storage.blobs


# -- sender blocks ---------------------------------------------------------------


async def test_a_blocked_account_reports_into_the_void(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    pid = await add_principal(maker, sub=PLAIN.sub, email="Pia@Example.org", name="Pia")
    ticket_id = await _ticket(maker, reporter=pid)
    with TestClient(api.app) as client:
        api.login(MANAGER)
        blocked = client.post(f"/api/tickets/{ticket_id}/block-sender")
        assert blocked.status_code == 200, blocked.text
        assert blocked.json()["senderBlocked"] is True
        # A second block changes nothing.
        assert client.post(f"/api/tickets/{ticket_id}/block-sender").status_code == 200

        api.login(PLAIN)
        first = client.post("/api/tickets", json=_REPORT)
        assert first.status_code == 201, first.text
        assert set(first.json()) == {"number"}
        # Signed out with the account's address, in another case: held back too.
        api.login(None)
        second = client.post("/api/tickets", json={**_REPORT, "email": "PIA@example.org"})
        assert second.status_code == 201
        assert api.mails.calls == []
        assert await _by_number(maker, first.json()["number"]) is None
        assert await _by_number(maker, second.json()["number"]) is None

        api.login(MANAGER)
        (row,) = client.get("/api/tickets/blocked-senders").json()
        assert row["kind"] == "principal"
        assert row["person"]["principalId"] == str(pid)
        assert row["blockedBy"]["displayName"] == "Mia"
        assert row["hitCount"] == 2 and row["lastHitAt"] is not None
        assert row["sourceTicket"]["id"] == str(ticket_id)

        lifted = client.delete(f"/api/tickets/{ticket_id}/block-sender")
        assert lifted.status_code == 200 and lifted.json()["senderBlocked"] is False
        assert client.delete(f"/api/tickets/{ticket_id}/block-sender").status_code == 200
        api.login(PLAIN)
        third = client.post("/api/tickets", json=_REPORT)
        assert third.status_code == 201
    # The held-back reports used numbers, so the next real one follows them.
    numbers = [int(r.json()["number"][2:]) for r in (first, second, third)]
    assert numbers == sorted(numbers) and len(set(numbers)) == 3
    stored = await _by_number(maker, third.json()["number"])
    assert stored is not None and stored.reporter_principal_id == pid
    assert len(api.mails.calls) == 1


async def test_a_blocked_address_also_holds_back_its_account(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=PLAIN.sub, email="gast@example.org")
    ticket_id = await _ticket(maker, email="Gast@Example.org")
    with TestClient(api.app) as client:
        api.login(MANAGER)
        assert client.post(f"/api/tickets/{ticket_id}/block-sender").status_code == 200
        (row,) = client.get("/api/tickets/blocked-senders").json()
        assert row["kind"] == "email" and row["email"] == "gast@example.org"
        assert row["person"] is None and row["blockedBy"] is None

        api.login(None)
        assert (
            client.post("/api/tickets", json={**_REPORT, "email": "GAST@example.org"}).status_code
            == 201
        )
        api.login(PLAIN)
        assert client.post("/api/tickets", json=_REPORT).status_code == 201
        # Another address still reports.
        api.login(None)
        other = client.post("/api/tickets", json={**_REPORT, "email": "else@example.org"})
        assert other.status_code == 201
        assert await _by_number(maker, other.json()["number"]) is not None
    async with maker() as session:
        count = await session.scalar(select(func.count()).select_from(Ticket))
        hits = await session.scalar(select(TicketSenderBlock.hit_count))
    assert count == 2  # the source ticket and the other report
    assert hits == 2


async def test_a_block_of_the_other_identity_shows_and_lifts_on_the_ticket(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    pid = await add_principal(maker, sub=PLAIN.sub, email="Ada@Example.org")
    by_mail = await _ticket(maker, email="ada@example.org")
    by_account = await _ticket(maker, reporter=pid)
    with TestClient(api.app) as client:
        api.login(MANAGER)
        assert client.post(f"/api/tickets/{by_mail}/block-sender").status_code == 200
        # The e-mail block swallows the reports of the account, so the account ticket
        # shows the sender as blocked.
        assert client.get(f"/api/tickets/{by_account}").json()["senderBlocked"] is True
        lifted = client.delete(f"/api/tickets/{by_account}/block-sender")
        assert lifted.status_code == 200 and lifted.json()["senderBlocked"] is False
        assert client.get("/api/tickets/blocked-senders").json() == []
        assert client.get(f"/api/tickets/{by_mail}").json()["senderBlocked"] is False

        # The other way round: an account block shows and lifts on the e-mail ticket.
        assert client.post(f"/api/tickets/{by_account}/block-sender").status_code == 200
        assert client.get(f"/api/tickets/{by_mail}").json()["senderBlocked"] is True
        assert client.delete(f"/api/tickets/{by_mail}/block-sender").status_code == 200
        assert client.get("/api/tickets/blocked-senders").json() == []
        api.login(PLAIN)
        report = client.post("/api/tickets", json=_REPORT)
        assert report.status_code == 201
    assert await _by_number(maker, report.json()["number"]) is not None


async def test_the_block_routes_refuse_the_caller_an_unknown_sender_and_non_managers(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    me = await add_principal(maker, sub=MANAGER.sub, email="Mgr@Example.org")
    own = await _ticket(maker, reporter=me)
    own_address = await _ticket(maker, email="mgr@example.org")
    gone = await _ticket(maker, email="z@example.org", anonymized=True)
    with TestClient(api.app) as client:
        api.login(MANAGER)
        for tid in (own, own_address):
            resp = client.post(f"/api/tickets/{tid}/block-sender")
            assert resp.status_code == 422
            assert resp.json()["code"] == "sender_is_self"
        for method in ("POST", "DELETE"):
            resp = client.request(method, f"/api/tickets/{gone}/block-sender")
            assert resp.status_code == 409
            assert resp.json()["code"] == "ticket_sender_unknown"
        assert client.post(f"/api/tickets/{uuid.uuid4()}/block-sender").status_code == 404
        missing = client.delete(f"/api/tickets/blocked-senders/{uuid.uuid4()}")
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert client.get("/api/tickets/blocked-senders").json() == []

        api.login(PLAIN)
        assert client.get("/api/tickets/blocked-senders").status_code == 403
        assert client.post(f"/api/tickets/{gone}/block-sender").status_code == 403
        api.login(None)
        assert client.get("/api/tickets/blocked-senders").status_code == 401


async def test_the_list_delete_lifts_a_block(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _ticket(maker, email="a@example.org")
    with TestClient(api.app) as client:
        api.login(ADMIN)
        assert client.post(f"/api/tickets/{ticket_id}/block-sender").status_code == 200
        (row,) = client.get("/api/tickets/blocked-senders").json()
        assert client.delete(f"/api/tickets/blocked-senders/{row['id']}").status_code == 204
        assert client.get("/api/tickets/blocked-senders").json() == []
        assert client.get(f"/api/tickets/{ticket_id}").json()["senderBlocked"] is False


async def test_the_erasure_and_the_auskunft_cover_the_blocks(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    pid = await add_principal(maker, email="u@example.org")
    async with maker() as session:
        session.add_all(
            [
                TicketSenderBlock(principal_id=pid),
                TicketSenderBlock(email="u@example.org"),
                TicketSenderBlock(email="other@example.org"),
            ]
        )
        await session.commit()
    async with maker() as session:
        mine = await sender_blocks_of(session, principal_id=pid, email="U@example.org")
        assert len(mine) == 2
        only_address = await sender_blocks_of(session, principal_id=None, email="u@example.org")
        assert [b.email for b in only_address] == ["u@example.org"]
        await erase_sender_blocks(session, principal_id=pid)
        await session.commit()
        assert len(await sender_blocks_of(session, principal_id=pid, email="u@example.org")) == 1
        await erase_email(session, "U@Example.org", actor="dpo")
        await session.commit()
        rest = (await session.scalars(select(TicketSenderBlock.email))).all()
    assert rest == ["other@example.org"]


async def test_deleting_the_account_drops_its_block(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    pid = await add_principal(maker, email="v@example.org")
    async with maker() as session:
        session.add(TicketSenderBlock(principal_id=pid))
        await session.commit()
    async with maker() as session:
        from app.modules.auth.models import Principal as PrincipalRow

        row = await session.get(PrincipalRow, pid)
        assert row is not None
        await session.delete(row)
        await session.commit()
        assert await session.scalar(select(func.count()).select_from(TicketSenderBlock)) == 0
