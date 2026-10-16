"""Unit tests of the blocked senders and the note files of ``TicketService`` (no database).

The integration suite runs the same paths against Postgres
(``tests/integration/modules/tickets/test_ticket_chat_and_blocks.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.tickets import service as svc_mod
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote, TicketSenderBlock
from app.modules.tickets.schemas import TicketCreate
from app.modules.tickets.service import (
    SwallowedReport,
    TicketService,
    erase_sender_blocks,
    normalize_email,
    sender_blocks_of,
)
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.unit.modules.tickets.fakes import FakeFiles, ScriptedSession

ME = uuid.uuid4()
OTHER = uuid.uuid4()
VIEWER = Principal(sub="me-sub", permissions={"ticket.manage"})
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
        "status": "new",
        "reporter_principal_id": None,
        "reporter_email": " A@Example.org ",
        "assignee_id": None,
        "duplicate_of_id": None,
        "context": {},
        "closed_at": None,
        "anonymized_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kw)
    return Ticket(**base)


def _sql(stmt: object) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))  # type: ignore[attr-defined]


def test_normalize_email() -> None:
    assert normalize_email("  Ab@X.ORG ") == "ab@x.org"


# -- the report of a blocked sender -------------------------------------------------


async def test_matching_block_with_an_account_matches_the_account_and_its_email() -> None:
    block = uuid.uuid4()
    session = ScriptedSession(scalar=[block])
    assert await _svc(session).matching_block(reporter_id=ME, email=None) == block
    sql = _sql(session.statements[0])
    assert "ticket_sender_block.principal_id =" in sql
    assert "lower(CAST(principal.email AS VARCHAR))" in sql


async def test_matching_block_without_an_account_matches_the_email_and_its_account() -> None:
    session = ScriptedSession(scalar=[None])
    assert await _svc(session).matching_block(reporter_id=None, email=" A@X.org") is None
    sql = _sql(session.statements[0])
    assert "ticket_sender_block.email = 'a@x.org'" in sql
    assert "ticket_sender_block.principal_id IN" in sql


async def test_matching_block_without_any_reporter_asks_nothing() -> None:
    session = ScriptedSession()
    assert await _svc(session).matching_block(reporter_id=None, email=None) is None
    assert session.statements == []


async def test_a_blocked_report_takes_a_number_counts_the_hit_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _check(_s: object, **_kw: Any) -> None:
        calls.append("check")

    monkeypatch.setattr(svc_mod, "check_drafts", _check)
    block = uuid.uuid4()
    session = ScriptedSession(scalar=[block, 99])
    payload = TicketCreate.model_validate(
        {
            "kind": "bug",
            "title": "t",
            "body": "b",
            "attachmentIds": [str(uuid.uuid4())],
            "draftToken": "tok",
        }
    )
    out = await _svc(session).create(payload, reporter_id=None, email="a@x", pepper="p")
    assert out == SwallowedReport(number=99)
    assert out.id is None
    # The drafts were checked like a normal report, then nothing was stored.
    assert calls == ["check"]
    assert session.added == []
    from sqlalchemy.dialects import postgresql

    seq = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "nextval('ticket_number_seq')" in seq
    update = _sql(session.statements[2])
    assert update.startswith("UPDATE ticket_sender_block SET hit_count")
    assert str(block).replace("-", "") in update.replace("-", "")
    assert session.committed == 1


async def test_a_swallowed_report_without_a_number_counts_zero() -> None:
    session = ScriptedSession(scalar=[None])
    out = await _svc(session)._swallow(uuid.uuid4())
    assert out.number == 0


# -- the target of a block ------------------------------------------------------------


def test_the_block_target_of_each_reporter() -> None:
    assert TicketService.block_target(_ticket()) == ("email", "a@example.org")
    assert TicketService.block_target(_ticket(reporter_principal_id=ME, reporter_email=None)) == (
        "principal",
        ME,
    )
    assert TicketService.block_target(_ticket(anonymized_at=NOW)) is None
    assert TicketService.block_target(_ticket(reporter_email=None)) is None


async def test_sender_blocked_reads_the_target() -> None:
    session = ScriptedSession(scalar=[uuid.uuid4(), None])
    service = _svc(session)
    assert await service._sender_blocked(_ticket()) is True
    by_email = _sql(session.statements[0])
    assert "ticket_sender_block.email = 'a@example.org'" in by_email
    # A block of an account with that e-mail holds the sender back too.
    assert "ticket_sender_block.principal_id IN" in by_email
    account = _ticket(reporter_principal_id=ME, reporter_email=None)
    assert await service._sender_blocked(account) is False
    by_account = _sql(session.statements[1])
    assert "ticket_sender_block.principal_id =" in by_account
    # A block of the account e-mail holds the account back too.
    assert "lower(CAST(principal.email AS VARCHAR))" in by_account
    assert await service._sender_blocked(_ticket(anonymized_at=NOW)) is False
    assert len(session.statements) == 2


# -- block and unblock ------------------------------------------------------------------


async def test_block_of_an_unknown_ticket_is_404() -> None:
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).block_sender(uuid.uuid4(), VIEWER)


async def test_block_and_unblock_of_an_anonymized_ticket_are_409() -> None:
    ticket = _ticket(anonymized_at=NOW, reporter_email=None)
    session = ScriptedSession()
    session.put(ticket)
    for call in (_svc(session).block_sender, _svc(session).unblock_sender):
        with pytest.raises(ConflictError) as exc:
            await call(ticket.id, VIEWER)
        assert exc.value.code == "ticket_sender_unknown"


async def test_blocking_the_own_account_is_422() -> None:
    ticket = _ticket(reporter_principal_id=ME, reporter_email=None)
    session = ScriptedSession(scalar=[ME])
    session.put(ticket)
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).block_sender(ticket.id, VIEWER)
    assert exc.value.code == "sender_is_self"


async def test_blocking_the_own_address_is_422() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, "a@EXAMPLE.org"])
    session.put(ticket)
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).block_sender(ticket.id, VIEWER)
    assert exc.value.code == "sender_is_self"


@pytest.mark.parametrize(
    ("reporter", "scalars"),
    [
        ({"reporter_principal_id": OTHER, "reporter_email": None}, [ME]),
        ({"reporter_principal_id": OTHER, "reporter_email": None}, [None]),
        ({}, [ME, "other@x"]),
        ({}, [ME, None]),
        ({}, [None]),
    ],
)
async def test_block_stores_the_target_and_answers_the_detail(
    reporter: dict[str, Any], scalars: list[Any]
) -> None:
    ticket = _ticket(**reporter)
    session = ScriptedSession(scalar=list(scalars), scalars=[[], []])
    session.put(ticket)
    detail = await _svc(session).block_sender(ticket.id, VIEWER)
    assert detail.id == ticket.id
    insert = next(s for s in session.statements if "INSERT INTO ticket_sender_block" in _sql(s))
    sql = _sql(insert)
    assert "ON CONFLICT DO NOTHING" in sql
    if reporter:
        assert str(OTHER).replace("-", "") in sql.replace("-", "")
    else:
        assert "'a@example.org'" in sql
    assert session.committed == 1


async def test_unblock_deletes_the_target_and_answers_the_detail() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalars=[[], []])
    session.put(ticket)
    detail = await _svc(session).unblock_sender(ticket.id, VIEWER)
    assert detail.sender_blocked is False
    delete = _sql(session.statements[0])
    assert delete.startswith("DELETE FROM ticket_sender_block")
    assert "'a@example.org'" in delete
    # Every block that swallows the sender's reports goes, the account ones included.
    assert "ticket_sender_block.principal_id IN" in delete
    assert session.committed == 1


# -- the list of the blocks ----------------------------------------------------------------


async def test_blocked_senders_map_people_addresses_and_sources() -> None:
    source = uuid.uuid4()
    gone = uuid.uuid4()
    account = TicketSenderBlock(
        id=uuid.uuid4(),
        principal_id=OTHER,
        email=None,
        source_ticket_id=source,
        created_by=ME,
        created_at=NOW,
        hit_count=3,
        last_hit_at=NOW,
    )
    address = TicketSenderBlock(
        id=uuid.uuid4(),
        principal_id=None,
        email="x@y.org",
        source_ticket_id=gone,
        created_by=None,
        created_at=NOW,
        hit_count=0,
        last_hit_at=None,
    )
    orphan = TicketSenderBlock(
        id=uuid.uuid4(),
        principal_id=uuid.uuid4(),
        email=None,
        source_ticket_id=None,
        created_by=None,
        created_at=NOW,
        hit_count=0,
    )
    session = ScriptedSession(
        scalars=[[account, address, orphan]],
        execute=[[(OTHER, "Otto", "otto@x"), (ME, "Ada", None)], [(source, 12)]],
    )
    first, second, third = await _svc(session).blocked_senders()
    assert first.kind == "principal"
    assert first.person is not None
    assert first.person.display_name == "Otto"
    assert first.email == "otto@x"
    assert first.blocked_by is not None
    assert first.blocked_by.display_name == "Ada"
    assert first.source_ticket is not None
    assert first.source_ticket.number == "T-0012"
    assert (first.hit_count, first.last_hit_at) == (3, NOW)
    assert second.kind == "email"
    assert (second.person, second.email, second.blocked_by) == (None, "x@y.org", None)
    # The source ticket is gone: no number to show.
    assert second.source_ticket is None
    # A deleted account: a deleted person and no e-mail.
    assert third.person is not None
    assert third.person.principal_id is None
    assert third.email is None
    dumped = first.model_dump(by_alias=True, mode="json")
    assert set(dumped) >= {"blockedAt", "blockedBy", "sourceTicket", "hitCount", "lastHitAt"}


async def test_blocked_senders_without_sources_ask_for_no_numbers() -> None:
    session = ScriptedSession(scalars=[[]])
    assert await _svc(session).blocked_senders() == []
    assert len(session.statements) == 1


async def test_delete_block() -> None:
    block = uuid.uuid4()
    session = ScriptedSession(execute=[[(block,)], []])
    await _svc(session).delete_block(block)
    assert session.committed == 1
    with pytest.raises(NotFoundError):
        await _svc(session).delete_block(block)


# -- privacy helpers ------------------------------------------------------------------------


async def test_erase_sender_blocks() -> None:
    session = ScriptedSession()
    await erase_sender_blocks(session, principal_id=ME, email=" A@X ")  # type: ignore[arg-type]
    sql = _sql(session.statements[0])
    assert "ticket_sender_block.principal_id =" in sql
    assert "ticket_sender_block.email = 'a@x'" in sql
    await erase_sender_blocks(session, email="b@x")  # type: ignore[arg-type]
    assert "principal_id" not in _sql(session.statements[1]).split("WHERE")[1]
    await erase_sender_blocks(session)  # type: ignore[arg-type]
    assert len(session.statements) == 2


async def test_sender_blocks_of() -> None:
    row = TicketSenderBlock(id=uuid.uuid4(), email="a@x", created_at=NOW, hit_count=0)
    session = ScriptedSession(scalars=[[row], []])
    assert await sender_blocks_of(session, principal_id=ME, email="A@x") == [row]  # type: ignore[arg-type]
    assert "principal_id =" in _sql(session.statements[0])
    assert await sender_blocks_of(session, principal_id=None, email="a@x") == []  # type: ignore[arg-type]
    assert "principal_id" not in _sql(session.statements[1]).split("WHERE")[1]


# -- the files of the notes in the detail ---------------------------------------------------


async def test_detail_lists_the_files_of_each_note_and_the_block_state() -> None:
    ticket = _ticket()
    with_file = TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, author_id=ME, body="", created_at=NOW
    )
    without = TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, author_id=ME, body="n", created_at=NOW
    )
    shot = MessageAttachmentOut(
        id=uuid.uuid4(), filename="a.png", mime="image/png", size=3, scan_state="scanning"
    )
    files = FakeFiles(messages={with_file.id: [shot]})
    created = TicketEvent(
        id=uuid.uuid4(), ticket_id=ticket.id, kind="created", payload={}, created_at=NOW
    )
    session = ScriptedSession(
        scalar=[ME, uuid.uuid4()],
        scalars=[[with_file, without], [created]],
        execute=[[(ME, "Ada", None)]],
    )
    session.put(ticket)
    detail = await _svc(session, files).detail(ticket.id, VIEWER)
    assert files.asked == [("ticket_note", [with_file.id, without.id])]
    assert detail.notes[0].attachments == [shot]
    assert detail.notes[1].attachments == []
    assert detail.sender_blocked is True
    dumped = detail.model_dump(by_alias=True, mode="json")
    assert dumped["senderBlocked"] is True
    assert dumped["notes"][0]["attachments"][0]["scanState"] == "scanning"
