"""Unit tests of the view of the reporter on its own tickets (scripted session).

The integration suite runs the same paths against Postgres
(``tests/integration/modules/tickets/test_ticket_reporter_api.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.files.schemas import AttachmentOut, MessageAttachmentOut
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from app.modules.tickets.schemas import NoteCreate, ReporterNoteCreate
from app.modules.tickets.service import (
    TicketService,
    has_reported_tickets,
    reporter_reads_file,
)
from app.shared.errors import ForbiddenError, NotFoundError
from tests.unit.modules.tickets.fakes import FakeFiles, ScriptedSession

ME = uuid.uuid4()
STAFF = uuid.uuid4()
REPORTER = Principal(sub="reporter-sub")
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _svc(session: ScriptedSession, files: FakeFiles | None = None) -> TicketService:
    return TicketService(session, files=files or FakeFiles())  # type: ignore[arg-type]


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": 7,
        "kind": "bug",
        "title": "Fehler",
        "body": "Text",
        "status": "in_progress",
        "reporter_principal_id": ME,
        "reporter_email": None,
        "assignee_id": STAFF,
        "duplicate_of_id": None,
        "context": {"url": "https://x"},
        "closed_at": None,
        "anonymized_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kw)
    return Ticket(**base)


def _note(ticket: Ticket, author: uuid.UUID | None, **kw: Any) -> TicketNote:
    return TicketNote(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        author_id=author,
        body="b",
        created_at=NOW,
        visibility=kw.pop("visibility", "public"),
        **kw,
    )


# -- the gate -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("account", "ticket_kw"),
    [
        (None, {}),
        (ME, {"reporter_principal_id": STAFF}),
        (ME, {"reporter_principal_id": None, "reporter_email": "me@x.org"}),
        (ME, {"anonymized_at": NOW, "reporter_principal_id": None}),
    ],
)
async def test_any_other_ticket_is_404(
    account: uuid.UUID | None, ticket_kw: dict[str, Any]
) -> None:
    ticket = _ticket(**ticket_kw)
    session = ScriptedSession(scalar=[account])
    session.put(ticket)
    with pytest.raises(NotFoundError):
        await _svc(session).reporter_detail(ticket.id, REPORTER)


async def test_an_unknown_ticket_is_404() -> None:
    session = ScriptedSession(scalar=[ME])
    with pytest.raises(NotFoundError):
        await _svc(session).reporter_detail(uuid.uuid4(), REPORTER)


# -- list ---------------------------------------------------------------------------


async def test_the_list_holds_only_the_own_live_tickets() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[1], scalars=[[ticket]])
    page = await _svc(session).reporter_list(
        ME, statuses=["new"], kinds=["bug"], q="T-0007", limit=10, offset=0
    )
    assert page.total == 1
    assert page.items[0].number == "T-0007"
    sql = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "ticket.reporter_principal_id" in sql
    assert "ticket.anonymized_at IS NULL" in sql
    assert "ticket.number = 7" in sql
    assert "reporter_email" not in sql.split("WHERE", 1)[1]


async def test_the_list_without_filters() -> None:
    session = ScriptedSession(scalar=[0], scalars=[[]])
    page = await _svc(session).reporter_list(ME, q="  ")
    assert (page.items, page.total) == ([], 0)
    sql = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "LIKE" not in sql.split("WHERE", 1)[1]


async def test_the_list_search_without_a_number_matches_text_only() -> None:
    session = ScriptedSession(scalar=[0], scalars=[[]])
    await _svc(session).reporter_list(ME, q="drucker")
    sql = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "ticket.number =" not in sql


# -- detail -------------------------------------------------------------------------


async def test_the_detail_shows_public_notes_and_status_changes_only() -> None:
    ticket = _ticket()
    staff_note = _note(ticket, STAFF)
    own_note = _note(ticket, ME)
    gone = _note(ticket, None)
    status = TicketEvent(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        actor_id=STAFF,
        kind="status",
        payload={"from": "new", "to": "in_progress", "duplicateOf": "T-0001"},
        created_at=NOW,
    )
    report_file = AttachmentOut(
        id=uuid.uuid4(),
        filename="a.png",
        mime="image/png",
        size=3,
        scanned=True,
        is_comparison_offer=False,
    )
    shot = MessageAttachmentOut(
        id=uuid.uuid4(), filename="b.png", mime="image/png", size=3, scan_state="clean"
    )
    files = FakeFiles(attachments=[report_file], messages={staff_note.id: [shot]})
    session = ScriptedSession(
        scalar=[ME, None],
        scalars=[[staff_note, own_note, gone], [status]],
        execute=[[(STAFF, None, "staff@x.org"), (ME, "Me", "me@x.org")]],
    )
    session.put(ticket)
    out = await _svc(session, files).reporter_detail(ticket.id, REPORTER)
    notes_sql = str(session.statements[1].compile(compile_kwargs={"literal_binds": True}))
    assert "ticket_note.visibility = 'public'" in notes_sql
    assert "ticket_note.deleted_at IS NULL" in notes_sql
    events_sql = str(session.statements[2].compile(compile_kwargs={"literal_binds": True}))
    assert "ticket_event.kind = 'status'" in events_sql
    assert out.can_reply is True
    assert out.attachments[0].filename == "a.png"
    first, second, third = out.notes
    # The name only: the e-mail of a holder of ticket.manage never reaches the reporter.
    assert first.author.principal_id == STAFF
    assert first.author.display_name is None
    assert first.attachments == [shot]
    assert first.is_own is False
    assert second.is_own is True
    assert second.from_reporter is True
    assert third.author.principal_id is None
    (event,) = out.events
    assert event.payload == {"from": "new", "to": "in_progress"}
    dumped = out.model_dump(by_alias=True)
    for hidden in ("assignee", "context", "reporter", "senderBlocked"):
        assert hidden not in dumped


async def test_the_detail_of_a_blocked_reporter_offers_no_reply() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, uuid.uuid4()], scalars=[[], []])
    session.put(ticket)
    out = await _svc(session).reporter_detail(ticket.id, REPORTER)
    assert out.can_reply is False
    assert out.notes == []


# -- messages -----------------------------------------------------------------------


async def test_a_message_of_the_reporter_is_public() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, None], execute=[[(ME, "Me", "me@x.org")]])
    session.put(ticket)
    out = await _svc(session).reporter_add_note(
        ticket.id, ReporterNoteCreate.model_validate({"body": "danke"}), REPORTER, pepper="p"
    )
    (note,) = [o for o in session.added if isinstance(o, TicketNote)]
    assert note.visibility == "public"
    assert note.author_id == ME
    assert out.visibility == "public"
    assert out.from_reporter is True
    assert out.is_own is True
    assert ticket.updated_at != NOW
    assert session.get_kw[0] == {}


async def test_a_message_with_files_locks_the_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.tickets import service as svc_mod

    async def _check(_s: object, **_kw: Any) -> str:
        return "tok"

    async def _bind(_s: object, **_kw: Any) -> None:
        return None

    monkeypatch.setattr(svc_mod, "check_message_drafts", _check)
    monkeypatch.setattr(svc_mod, "bind_drafts", _bind)
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, None], execute=[[(ME, "Me", None)]])
    session.put(ticket)
    payload = ReporterNoteCreate.model_validate(
        {"body": "", "attachmentIds": [str(uuid.uuid4())], "draftToken": "tok"}
    )
    await _svc(session).reporter_add_note(ticket.id, payload, REPORTER, pepper="p")
    assert session.get_kw[0] == {"with_for_update": True, "populate_existing": True}


async def test_a_blocked_reporter_cannot_write() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, uuid.uuid4()])
    session.put(ticket)
    with pytest.raises(ForbiddenError) as exc:
        await _svc(session).reporter_add_note(
            ticket.id, ReporterNoteCreate.model_validate({"body": "x"}), REPORTER, pepper="p"
        )
    assert exc.value.code == "sender_blocked"
    assert session.added == []


async def test_a_message_on_another_ticket_is_404() -> None:
    ticket = _ticket(reporter_principal_id=STAFF)
    session = ScriptedSession(scalar=[ME])
    session.put(ticket)
    with pytest.raises(NotFoundError):
        await _svc(session).reporter_add_note(
            ticket.id, ReporterNoteCreate.model_validate({"body": "x"}), REPORTER, pepper="p"
        )


async def test_the_reporter_edits_and_deletes_an_own_message() -> None:
    ticket = _ticket()
    note = _note(ticket, ME)
    files = FakeFiles()
    session = ScriptedSession(scalar=[ME, ME, ME, ME], execute=[[(ME, "Me", None)]])
    session.put(ticket, note)
    service = _svc(session, files)
    out = await service.reporter_edit_note(ticket.id, note.id, "neu", REPORTER)
    assert out.body == "neu"
    assert note.edited_at is not None
    await service.reporter_delete_note(ticket.id, note.id, REPORTER)
    assert note.deleted_at is not None
    assert files.removed == [("ticket_note", [note.id], "reporter-sub")]


async def test_the_reporter_cannot_change_a_message_of_the_team() -> None:
    ticket = _ticket()
    note = _note(ticket, STAFF)
    session = ScriptedSession(scalar=[ME, ME, ME, ME])
    session.put(ticket, note)
    service = _svc(session)
    with pytest.raises(ForbiddenError):
        await service.reporter_edit_note(ticket.id, note.id, "x", REPORTER)
    with pytest.raises(ForbiddenError):
        await service.reporter_delete_note(ticket.id, note.id, REPORTER)


async def test_the_reporter_cannot_change_a_message_on_another_ticket() -> None:
    ticket = _ticket(reporter_principal_id=STAFF)
    note = _note(ticket, ME)
    session = ScriptedSession(scalar=[ME, ME])
    session.put(ticket, note)
    service = _svc(session)
    with pytest.raises(NotFoundError):
        await service.reporter_edit_note(ticket.id, note.id, "x", REPORTER)
    with pytest.raises(NotFoundError):
        await service.reporter_delete_note(ticket.id, note.id, REPORTER)


# -- the team side ------------------------------------------------------------------


async def test_a_team_note_keeps_its_visibility() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[STAFF], execute=[[(STAFF, "Ada", None)]])
    session.put(ticket)
    manager = Principal(sub="staff", permissions={"ticket.manage"})
    out = await _svc(session).add_note(
        ticket.id,
        NoteCreate.model_validate({"body": "x", "visibility": "public"}),
        manager,
        pepper="p",
    )
    assert out.visibility == "public"
    assert out.from_reporter is False
    assert out.author.display_name == "Ada"


# -- files and the tab --------------------------------------------------------------


@pytest.mark.parametrize("kind", ["ticket", "ticket_note"])
async def test_reporter_reads_file(kind: str) -> None:
    owner = uuid.uuid4()
    session = ScriptedSession(scalar=[ME, owner])
    assert await reporter_reads_file(session, REPORTER, kind=kind, owner_id=owner)  # type: ignore[arg-type]
    sql = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "ticket.anonymized_at IS NULL" in sql
    if kind == "ticket_note":
        assert "ticket_note.visibility = 'public'" in sql
        assert "ticket_note.deleted_at IS NULL" in sql


async def test_reporter_reads_no_file_without_an_account_a_match_or_another_owner() -> None:
    owner = uuid.uuid4()
    session = ScriptedSession(scalar=[None])
    assert not await reporter_reads_file(session, REPORTER, kind="ticket", owner_id=owner)  # type: ignore[arg-type]
    session = ScriptedSession(scalar=[ME, None])
    assert not await reporter_reads_file(session, REPORTER, kind="ticket", owner_id=owner)  # type: ignore[arg-type]
    session = ScriptedSession(scalar=[ME])
    assert not await reporter_reads_file(session, REPORTER, kind="comment", owner_id=owner)  # type: ignore[arg-type]


async def test_has_reported_tickets() -> None:
    assert not await has_reported_tickets(ScriptedSession(scalar=[None]), "s")  # type: ignore[arg-type]
    assert not await has_reported_tickets(ScriptedSession(scalar=[ME, None]), "s")  # type: ignore[arg-type]
    session = ScriptedSession(scalar=[ME, uuid.uuid4()])
    assert await has_reported_tickets(session, "s")  # type: ignore[arg-type]
    sql = str(session.statements[-1].compile(compile_kwargs={"literal_binds": True}))
    assert "ticket.anonymized_at IS NULL" in sql
