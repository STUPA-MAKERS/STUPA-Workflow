"""The mails of a ticket in the erasure and in the data export (real Postgres).

§ F/administration/privacy/002747 an erasure anonymizes the mail tickets of the address
and names, for each Postfach, the count of the mails that stay on the mail server.
§ F/administration/privacy/002748 the data export holds the mail tickets of the address
with the public messages and without the internal ones.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tickets.models import (
    Ticket,
    TicketArea,
    TicketMail,
    TicketMailbox,
    TicketNote,
)
from tests.integration.modules.privacy.test_privacy import _seed_principal
from tests.integration.modules.privacy.test_privacy_router import (
    _as_dpo,
    app,
    client,
    session,
)

__all__ = ["app", "client", "session"]

pytestmark = pytest.mark.integration

_BOX = "buero@stupa.example"
_ANNA = "anna@example.org"


async def _mail_ticket(
    session: AsyncSession, *, sender: str = _ANNA, cc: tuple[str, ...] = ()
) -> Ticket:
    """Write a Bereich with a Postfach and one mail ticket with three mails.

    The ticket has the first mail of ``sender``, one more mail of the sender as a public
    message, one answer of the team to the sender and one internal message.
    """
    await session.execute(delete(Ticket))
    await session.execute(delete(TicketArea).where(TicketArea.platform.is_(False)))
    area = TicketArea(id=uuid.uuid4(), name=f"Büro {uuid.uuid4().hex[:6]}", notify_new=False)
    session.add(area)
    await session.flush()
    box = TicketMailbox(
        id=uuid.uuid4(),
        area_id=area.id,
        address=_BOX,
        imap_host="mail.stupa.example",
        imap_port=993,
        imap_user="buero",
        imap_password="x",
        smtp_host="mail.stupa.example",
        smtp_port=465,
        smtp_user="buero",
        smtp_password="x",
        done_folder="Erledigt",
        enabled=True,
    )
    ticket = Ticket(
        id=uuid.uuid4(),
        number=uuid.uuid4().hex[:8].upper(),
        area_id=area.id,
        kind=None,
        source="mail",
        title="Rechnung 42",
        body="Im Anhang.",
        status="new",
        reporter_email=sender,
        context={},
    )
    session.add_all([box, ticket])
    await session.flush()
    answer = TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, body="Danke, ist da.", visibility="public"
    )
    more = TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, body="Noch eine Seite.", visibility="public"
    )
    internal = TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, body="Nur für das Team.", visibility="internal"
    )
    session.add_all([answer, more, internal])
    await session.flush()
    session.add_all(
        [
            TicketMail(
                mailbox_id=box.id,
                ticket_id=ticket.id,
                direction="in",
                message_id="<m1@example.org>",
                from_address=sender,
                cc=list(cc),
            ),
            TicketMail(
                mailbox_id=box.id,
                ticket_id=ticket.id,
                note_id=more.id,
                direction="in",
                message_id="<m2@example.org>",
                from_address=sender,
                cc=list(cc),
            ),
            TicketMail(
                mailbox_id=box.id,
                ticket_id=ticket.id,
                note_id=answer.id,
                direction="out",
                message_id="<out1@stupa.example>",
                from_address=_BOX,
                to_addresses=[sender],
                state="sent",
            ),
        ]
    )
    await session.commit()
    return ticket


async def test_the_erasure_of_an_address_counts_the_mails_of_each_postfach(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    """Two imported mails and one sent mail give the Postfach with the count 3.

    §F/administration/privacy/002747
    """
    ticket = await _mail_ticket(session)
    _as_dpo(app)
    erased = client.post("/api/admin/privacy/erase-email", json={"email": "Anna@Example.org"})
    assert erased.status_code == 200, erased.text
    assert erased.json()["tickets"] == 1
    assert erased.json()["ticketMails"] == [{"mailbox": _BOX, "count": 3}]

    await session.refresh(ticket)
    assert ticket.anonymized_at is not None
    mails = (await session.scalars(select(TicketMail))).all()
    assert len(mails) == 3
    assert all(mail.from_address is None for mail in mails)
    again = client.post("/api/admin/privacy/erase-email", json={"email": _ANNA})
    assert again.json()["ticketMails"] == []


async def test_the_erasure_of_an_account_counts_the_mails_of_its_address(
    app: FastAPI, client: TestClient, session: AsyncSession
) -> None:
    await _mail_ticket(session)
    principal = await _seed_principal(session, email=_ANNA)
    await session.commit()
    _as_dpo(app)
    erased = client.post(f"/api/admin/privacy/principals/{principal.id}/erase")
    assert erased.status_code == 200, erased.text
    assert erased.json()["ticketMails"] == [{"mailbox": _BOX, "count": 3}]


def _rows(content: bytes, sheet: str) -> Sequence[Sequence[object]]:
    rows = load_workbook(BytesIO(content))[sheet].iter_rows(values_only=True)
    return [tuple(row) for row in rows][1:]


@pytest.mark.parametrize("role", ["sender", "cc"])
async def test_the_export_holds_the_mail_ticket_without_the_internal_message(
    app: FastAPI, client: TestClient, session: AsyncSession, role: str
) -> None:
    """The ticket of a sender or ``Cc`` address is in the export with its public messages.

    §F/administration/privacy/002748
    """
    if role == "sender":
        await _mail_ticket(session)
    else:
        await _mail_ticket(session, sender="other@example.org", cc=(_ANNA,))
    _as_dpo(app)
    exported = client.get("/api/admin/privacy/export", params={"email": _ANNA})
    assert exported.status_code == 200, exported.text
    tickets = _rows(exported.content, "Tickets")
    assert [row for row in tickets if "Rechnung 42" in row] != []
    texts = " ".join(
        str(cell) for row in _rows(exported.content, "Ticket-Nachrichten") for cell in row
    )
    assert "Danke, ist da." in texts
    assert "Noch eine Seite." in texts
    assert "Nur für das Team." not in texts
