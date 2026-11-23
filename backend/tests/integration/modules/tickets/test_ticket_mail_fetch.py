"""Integration: the fetch of the mails of a Postfach (real Postgres, scripted inbox).

Covers the worker job ``fetch_ticket_mails`` with the import of a mail as a ticket, a
message or an event (specs 002722 to 002732 and 002739 to 002741). The inbox is a
scripted object, so no test opens a socket; the database, the importer and the routes
are the real ones.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from app.modules.files.scanner import ScanVerdict
from app.modules.files.service import FilesService
from app.modules.tickets.mail_client import MailAccount, MailError
from app.modules.tickets.models import (
    Ticket,
    TicketArea,
    TicketEvent,
    TicketMail,
    TicketMailbox,
    TicketNote,
    TicketSenderBlock,
)
from app.modules.tickets.service import TicketService
from app.settings import Settings
from tests._support.files_fakes import FakeStorage
from tests._support.notifications_fakes import FakeQueue
from tests.integration.modules.tickets.conftest import MANAGER, Api, add_principal
from worker.ticket_mail import fetch_ticket_mails

pytestmark = pytest.mark.integration

HOST = "mail.stupa.example"
ADDRESS = "buero@stupa.example"
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


@pytest.fixture(autouse=True)
def _areas(clean: Engine) -> Iterator[None]:
    def _wipe() -> None:
        with clean.begin() as conn:
            conn.execute(text("DELETE FROM ticket"))
            conn.execute(text("DELETE FROM ticket_sender_block"))
            conn.execute(text("DELETE FROM ticket_area WHERE NOT platform"))

    _wipe()
    yield
    _wipe()


@dataclass
class Scripted:
    """A scripted inbox: the mails by UID, and the moves that the job asked for."""

    mails: dict[int, bytes] = field(default_factory=dict)
    moved: list[tuple[int, str]] = field(default_factory=list)
    opened: list[MailAccount] = field(default_factory=list)
    uid_validity: int = 1
    fail: str | None = None

    def open(self, account: MailAccount) -> Scripted:
        self.opened.append(account)
        if self.fail is not None:
            raise MailError(self.fail)
        return self

    def put(self, source: bytes) -> int:
        uid = max([0, *self.mails, *(uid for uid, _folder in self.moved)]) + 1
        self.mails[uid] = source
        return uid

    def uids_after(self, last_uid: int) -> list[int]:
        return sorted(uid for uid in self.mails if uid > last_uid)

    def size(self, uid: int) -> int:
        return len(self.mails[uid])

    def fetch(self, uid: int) -> bytes:
        return self.mails[uid]

    def move(self, uid: int, folder: str) -> None:
        del self.mails[uid]
        self.moved.append((uid, folder))

    def close(self) -> None:
        return None


class _Scanner:
    async def scan(self, _data: bytes) -> ScanVerdict:
        return ScanVerdict(clean=True)


@dataclass
class Stack:
    """One Bereich with a Postfach, its scripted inbox and the context of the job."""

    maker: async_sessionmaker[AsyncSession]
    area_id: uuid.UUID
    box_id: uuid.UUID
    inbox: Scripted
    storage: FakeStorage
    ctx: dict[str, Any]

    async def run(self) -> int:
        return await fetch_ticket_mails(self.ctx)

    async def box(self) -> TicketMailbox:
        async with self.maker() as session:
            row = await session.get(TicketMailbox, self.box_id)
            assert row is not None
            return row

    async def tickets(self) -> list[Ticket]:
        async with self.maker() as session:
            return list(
                (await session.scalars(select(Ticket).order_by(Ticket.created_at, Ticket.id))).all()
            )

    async def notes(self, ticket_id: uuid.UUID) -> list[TicketNote]:
        async with self.maker() as session:
            return list(
                (
                    await session.scalars(
                        select(TicketNote)
                        .where(TicketNote.ticket_id == ticket_id)
                        .order_by(TicketNote.created_at, TicketNote.id)
                    )
                ).all()
            )


async def _box(
    maker: async_sessionmaker[AsyncSession], name: str, *, enabled: bool = True
) -> tuple[uuid.UUID, uuid.UUID]:
    async with maker() as session:
        area = TicketArea(id=uuid.uuid4(), name=name, notify_new=False)
        session.add(area)
        await session.flush()
        box = TicketMailbox(
            id=uuid.uuid4(),
            area_id=area.id,
            address=ADDRESS,
            imap_host=HOST,
            imap_port=993,
            imap_user="buero",
            imap_password="geheim-imap",
            smtp_host=HOST,
            smtp_port=465,
            smtp_user="buero",
            smtp_password="geheim-smtp",
            done_folder="Erledigt",
            enabled=enabled,
        )
        session.add(box)
        await session.commit()
        return area.id, box.id


@pytest.fixture
async def stack(maker: async_sessionmaker[AsyncSession], settings: Settings) -> Stack:
    area_id, box_id = await _box(maker, "AStA-Büro")
    inbox = Scripted()
    storage = FakeStorage()
    ctx: dict[str, Any] = {
        "settings": settings.model_copy(update={"ticket_mail_host_allowlist": [HOST]}),
        "ticket_mail_sessionmaker": maker,
        "ticket_mail_inbox": inbox.open,
        "object_storage": storage,
        "scanner": _Scanner(),
    }
    return Stack(maker, area_id, box_id, inbox, storage, ctx)


def _mail(
    *,
    sender: str = "Anna Beispiel <anna@example.org>",
    subject: str | None = "Raumanfrage",
    body: str = "Ich brauche einen Raum.",
    message_id: str | None = None,
    **headers: str,
) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ADDRESS
    if subject is not None:
        message["Subject"] = subject
    if message_id is not None:
        message["Message-ID"] = message_id
    for name, value in headers.items():
        message[name.replace("_", "-")] = value
    message.set_content(body)
    return bytes(message)


async def test_a_new_mail_becomes_a_ticket_with_the_values_of_the_mail(stack: Stack) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    assert await stack.run() == 1
    (ticket,) = await stack.tickets()
    assert ticket.area_id == stack.area_id
    assert (ticket.source, ticket.status) == ("mail", "new")
    assert (ticket.title, ticket.body) == ("Raumanfrage", "Ich brauche einen Raum.")
    assert (ticket.reporter_email, ticket.reporter_name) == ("anna@example.org", "Anna Beispiel")
    assert ticket.reporter_principal_id is None
    assert stack.inbox.moved == [(1, "Erledigt")]
    box = await stack.box()
    assert (box.last_uid, box.uid_validity, box.failures, box.last_error) == (1, 1, 0, None)
    assert box.fetched_at is not None


async def test_a_mail_without_a_subject_gets_the_title_ohne_betreff(stack: Stack) -> None:
    stack.inbox.put(_mail(subject=None))
    await stack.run()
    (ticket,) = await stack.tickets()
    assert ticket.title == "Ohne Betreff"


async def test_the_fetch_opens_no_connection_while_the_switch_is_off(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    async with maker() as session:
        row = await session.get(TicketMailbox, stack.box_id)
        assert row is not None
        row.enabled = False
        await session.commit()
    stack.inbox.put(_mail())
    assert await stack.run() == 0
    assert stack.inbox.opened == []
    assert await stack.tickets() == []


async def test_a_host_outside_the_allowlist_gets_no_connection(stack: Stack) -> None:
    stack.ctx["settings"] = stack.ctx["settings"].model_copy(
        update={"ticket_mail_host_allowlist": []}
    )
    stack.inbox.put(_mail())
    assert await stack.run() == 0
    assert stack.inbox.opened == []
    box = await stack.box()
    assert (box.failures, box.last_error) == (1, "mail_host_not_allowed")


async def test_a_failed_commit_leaves_the_mail_for_the_next_run(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = AsyncSession.commit
    calls: list[int] = []

    async def _commit(self: AsyncSession) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("commit failed")
        await real(self)

    monkeypatch.setattr(AsyncSession, "commit", _commit)
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    assert await stack.run() == 0
    assert await stack.tickets() == []
    assert stack.inbox.moved == []
    box = await stack.box()
    assert (box.last_uid, box.failures, box.last_error) == (0, 1, "import_failed")
    assert await stack.run() == 1
    assert len(await stack.tickets()) == 1
    assert stack.inbox.moved == [(1, "Erledigt")]
    assert (await stack.box()).failures == 0


async def test_a_failure_of_one_postfach_does_not_stop_the_others(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    _area, broken = await _box(maker, "Kaputt")
    good = stack.inbox
    bad = Scripted(fail="login_failed")

    def _open(account: MailAccount) -> Scripted:
        return (bad if len(good.opened) + len(bad.opened) == 0 else good).open(account)

    async with maker() as session:
        first = await session.get(TicketMailbox, broken)
        second = await session.get(TicketMailbox, stack.box_id)
        assert first is not None
        assert second is not None
        first.created_at = datetime.now(UTC) - timedelta(days=1)
        await session.commit()
    stack.ctx["ticket_mail_inbox"] = _open
    good.put(_mail())
    assert await stack.run() == 1
    async with maker() as session:
        row = await session.get(TicketMailbox, broken)
        assert row is not None
        assert (row.failures, row.last_error) == (1, "login_failed")
    assert (await stack.box()).failures == 0


async def test_the_same_mail_is_imported_one_time(stack: Stack) -> None:
    source = _mail(message_id="<m1@example.org>")
    stack.inbox.put(source)
    await stack.run()
    stack.inbox.put(source)
    assert await stack.run() == 0
    assert len(await stack.tickets()) == 1
    assert stack.inbox.mails == {}
    assert [uid for uid, _folder in stack.inbox.moved] == [1, 2]


async def test_a_mail_without_a_message_id_is_imported_one_time(stack: Stack) -> None:
    source = _mail()
    stack.inbox.put(source)
    await stack.run()
    stack.inbox.put(source)
    await stack.run()
    assert len(await stack.tickets()) == 1


async def test_a_new_uidvalidity_starts_from_the_first_mail(stack: Stack) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    await stack.run()
    stack.inbox.uid_validity = 2
    stack.inbox.moved.clear()
    stack.inbox.mails[1] = _mail(message_id="<m2@example.org>", subject="Zweite")
    assert await stack.run() == 1
    assert [t.title for t in await stack.tickets()] == ["Raumanfrage", "Zweite"]
    assert (await stack.box()).uid_validity == 2


async def test_an_answer_joins_its_ticket_through_the_headers(stack: Stack) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    await stack.run()
    stack.inbox.put(
        _mail(
            message_id="<m2@example.org>",
            subject="Ganz anderer Betreff",
            body="Noch eine Frage.",
            In_Reply_To="<m1@example.org>",
        )
    )
    assert await stack.run() == 1
    (ticket,) = await stack.tickets()
    (note,) = await stack.notes(ticket.id)
    assert (note.body, note.visibility, note.author_id) == ("Noch eine Frage.", "public", None)


async def test_the_newest_ticket_wins_with_more_than_one_hit(stack: Stack) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>", subject="Alt"))
    await stack.run()
    stack.inbox.put(_mail(message_id="<m2@example.org>", subject="Neu"))
    await stack.run()
    stack.inbox.put(
        _mail(message_id="<m3@example.org>", References="<m1@example.org> <m2@example.org>")
    )
    await stack.run()
    old, new = await stack.tickets()
    assert await stack.notes(old.id) == []
    assert len(await stack.notes(new.id)) == 1


async def test_an_answer_of_the_sender_sets_a_waiting_ticket_to_in_progress(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    await stack.run()
    async with maker() as session:
        ticket = (await session.scalars(select(Ticket))).one()
        ticket.status = "waiting"
        await session.commit()
    stack.inbox.put(_mail(message_id="<m2@example.org>", In_Reply_To="<m1@example.org>"))
    await stack.run()
    (ticket,) = await stack.tickets()
    assert ticket.status == "in_progress"


async def test_a_late_answer_opens_a_follow_up_ticket(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    await stack.run()
    async with maker() as session:
        ticket = (await session.scalars(select(Ticket))).one()
        ticket.status = "done"
        ticket.closed_at = datetime.now(UTC) - timedelta(days=15)
        await session.commit()
    stack.inbox.put(_mail(message_id="<m2@example.org>", In_Reply_To="<m1@example.org>"))
    assert await stack.run() == 1
    old, new = await stack.tickets()
    assert (old.status, new.status, new.follow_up_of_id) == ("done", "new", old.id)


async def test_the_number_in_the_subject_joins_only_a_mail_of_a_participant(
    stack: Stack,
) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>", Cc="Bernd <bernd@example.org>"))
    await stack.run()
    (ticket,) = await stack.tickets()
    marker = f"Re: Raumanfrage [T-{ticket.number}]"
    stack.inbox.put(_mail(sender="fremd@example.org", subject=marker, body="Fremd"))
    stack.inbox.put(_mail(subject=marker, body="Absender"))
    stack.inbox.put(_mail(sender="bernd@example.org", subject=marker, body="Cc"))
    assert await stack.run() == 3
    first, stranger = await stack.tickets()
    assert first.id == ticket.id
    assert (stranger.reporter_email, stranger.body) == ("fremd@example.org", "Fremd")
    assert [n.body for n in await stack.notes(ticket.id)] == ["Absender", "Cc"]


async def test_the_source_is_kept_and_the_anonymization_deletes_it(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    source = _mail(message_id="<m1@example.org>")
    stack.inbox.put(source)
    await stack.run()
    (ticket,) = await stack.tickets()
    async with maker() as session:
        mail = (await session.scalars(select(TicketMail))).one()
    assert mail.source_key is not None
    assert stack.storage.objects[mail.source_key] == (source, "message/rfc822")
    assert (mail.source_scan, mail.source_size) == ("clean", len(source))
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email)
    api.login(MANAGER)
    with TestClient(api.app) as client:
        api.app.state.object_storage = stack.storage
        detail = client.get(f"/api/tickets/{ticket.id}").json()
        assert detail["reporter"] == {
            "principalId": None,
            "displayName": "Anna Beispiel",
            "email": "anna@example.org",
            "anonymized": False,
        }
        assert [(m["source"], m["noteId"], m["fromAddress"]) for m in detail["mails"]] == [
            ("clean", None, "anna@example.org")
        ]
        got = client.get(f"/api/tickets/{ticket.id}/mails/{mail.id}/source")
        assert got.status_code == 200, got.text
        assert got.content == source
        assert got.headers["content-type"].startswith("message/rfc822")
        assert "attachment" in got.headers["content-disposition"]
    async with maker() as session:
        row = await session.get(Ticket, ticket.id)
        assert row is not None
        files = FilesService(session, storage=stack.storage)
        await TicketService(session, files=files).anonymize(row, actor="system:test")
        await session.commit()
    assert mail.source_key not in stack.storage.objects
    async with maker() as session:
        after = (await session.scalars(select(TicketMail))).one()
        gone = await session.get(Ticket, ticket.id)
    assert (after.source_key, after.from_address, after.subject) == (None, None, None)
    assert after.message_id == "<m1@example.org>"
    assert gone is not None
    assert (gone.reporter_email, gone.reporter_name) == (None, None)
    with TestClient(api.app) as client:
        api.app.state.object_storage = stack.storage
        assert client.get(f"/api/tickets/{ticket.id}/mails/{mail.id}/source").status_code == 404


async def test_a_source_without_a_clean_scan_stays_closed(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    stack.ctx["scanner"] = None
    stack.inbox.put(_mail())
    await stack.run()
    (ticket,) = await stack.tickets()
    async with maker() as session:
        mail = (await session.scalars(select(TicketMail))).one()
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email)
    api.login(MANAGER)
    with TestClient(api.app) as client:
        api.app.state.object_storage = stack.storage
        closed = client.get(f"/api/tickets/{ticket.id}/mails/{mail.id}/source")
        assert closed.status_code == 409
        assert closed.json()["code"] == "mail_source_closed"
        assert client.get(f"/api/tickets/{ticket.id}").json()["mails"][0]["source"] == "closed"


async def test_a_small_file_is_a_file_and_a_too_large_file_is_named(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    stack.ctx["settings"] = stack.ctx["settings"].model_copy(
        update={"attachment_max_bytes": len(PDF) + 10}
    )
    scans: list[uuid.UUID] = []

    class _Scans:
        async def enqueue(self, attachment_id: uuid.UUID) -> None:
            scans.append(attachment_id)

    stack.ctx["scan_queue"] = _Scans()
    message = EmailMessage()
    message["From"] = "anna@example.org"
    message["Subject"] = "Rechnung"
    message.set_content("Im Anhang.")
    message.add_attachment(PDF, maintype="application", subtype="pdf", filename="klein.pdf")
    message.add_attachment(PDF * 3, maintype="application", subtype="pdf", filename="gross.pdf")
    stack.inbox.put(bytes(message))
    await stack.run()
    (ticket,) = await stack.tickets()
    async with maker() as session:
        files = (await session.scalars(select(Attachment))).all()
    assert [(f.filename, f.ticket_id, f.scanned) for f in files] == [
        ("klein.pdf", ticket.id, False)
    ]
    assert scans == [files[0].id]
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email)
    api.login(MANAGER)
    with TestClient(api.app) as client:
        detail = client.get(f"/api/tickets/{ticket.id}").json()
    assert detail["mails"][0]["skipped"] == [
        {"name": "gross.pdf", "size": len(PDF) * 3, "reason": "size"}
    ]
    assert [a["filename"] for a in detail["attachments"]] == ["klein.pdf"]


async def test_an_automatic_answer_is_an_event_and_no_message(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    await stack.run()
    stack.inbox.put(
        _mail(
            message_id="<auto@example.org>",
            subject="Abwesend",
            In_Reply_To="<m1@example.org>",
            Auto_Submitted="auto-replied",
        )
    )
    assert await stack.run() == 0
    (ticket,) = await stack.tickets()
    assert await stack.notes(ticket.id) == []
    async with maker() as session:
        events = (
            await session.scalars(select(TicketEvent).where(TicketEvent.kind == "mail_auto"))
        ).all()
    assert [(e.ticket_id, e.payload["subject"]) for e in events] == [(ticket.id, "Abwesend")]
    assert stack.inbox.mails == {}


async def test_an_automatic_mail_without_a_ticket_stays_in_the_inbox(stack: Stack) -> None:
    stack.inbox.put(_mail(subject="Newsletter", Precedence="bulk"))
    assert await stack.run() == 0
    assert await stack.tickets() == []
    assert stack.inbox.moved == []
    assert list(stack.inbox.mails) == [1]
    assert (await stack.box()).last_uid == 1


async def test_a_mail_with_the_address_of_an_account_is_no_ticket_of_the_account(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub="anna-sub", email="anna@example.org", name="Anna")
    stack.inbox.put(_mail())
    await stack.run()
    (ticket,) = await stack.tickets()
    assert ticket.reporter_principal_id is None
    api.login(Principal(sub="anna-sub", email="anna@example.org"))
    with TestClient(api.app) as client:
        mine = client.get("/api/tickets/mine")
        assert mine.status_code == 200, mine.text
        assert mine.json()["items"] == []


async def test_the_mail_of_a_blocked_sender_becomes_no_ticket(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    async with maker() as session:
        session.add(TicketSenderBlock(email="anna@example.org"))
        await session.commit()
    stack.inbox.put(_mail())
    assert await stack.run() == 0
    assert await stack.tickets() == []
    async with maker() as session:
        block = (await session.scalars(select(TicketSenderBlock))).one()
        mails = await session.scalar(select(func.count()).select_from(TicketMail))
    assert block.hit_count == 1
    assert mails == 0
    assert stack.inbox.moved == [(1, "Erledigt")]


async def test_one_address_opens_at_most_20_tickets_an_hour(stack: Stack) -> None:
    for index in range(21):
        stack.inbox.put(_mail(message_id=f"<m{index}@example.org>", subject=f"Nr {index}"))
    stack.inbox.put(_mail(sender="bernd@example.org", message_id="<b@example.org>"))
    assert await stack.run() == 21
    tickets = await stack.tickets()
    assert sum(t.reporter_email == "anna@example.org" for t in tickets) == 20
    assert list(stack.inbox.mails) == [21]
    assert (await stack.box()).last_uid == 20
    assert await stack.run() == 0
    assert list(stack.inbox.mails) == [21]


async def test_a_mail_from_the_address_of_the_postfach_stays_in_the_inbox(stack: Stack) -> None:
    stack.inbox.put(_mail(sender=ADDRESS))
    assert await stack.run() == 0
    assert await stack.tickets() == []
    assert stack.inbox.moved == []


async def test_the_team_gets_a_mail_for_a_new_ticket_and_for_an_answer(
    stack: Stack, maker: async_sessionmaker[AsyncSession]
) -> None:
    queue = FakeQueue()
    stack.ctx["mail_queue"] = queue
    await add_principal(maker, email="team@example.org", role="admin")
    async with maker() as session:
        area = await session.get(TicketArea, stack.area_id)
        assert area is not None
        area.notify_new = True
        await session.commit()
    stack.inbox.put(_mail(message_id="<m1@example.org>"))
    await stack.run()
    stack.inbox.put(_mail(message_id="<m2@example.org>", In_Reply_To="<m1@example.org>"))
    await stack.run()
    assert [m.to for m in queue.messages] == [("team@example.org",), ("team@example.org",)]
    created, message = queue.messages
    assert "Anna Beispiel" in created.text
    assert "Ich brauche einen Raum." in message.text
    stack.inbox.put(
        _mail(
            message_id="<m3@example.org>",
            In_Reply_To="<m1@example.org>",
            Auto_Submitted="auto-replied",
        )
    )
    await stack.run()
    assert len(queue.messages) == 2
