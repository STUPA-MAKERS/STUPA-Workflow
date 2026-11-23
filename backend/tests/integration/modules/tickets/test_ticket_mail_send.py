"""Integration: the answers by mail of a ticket (real Postgres, scripted SMTP send).

Covers the public message on a mail ticket, the worker job ``send_ticket_mails``, the
confirmation of a new ticket and the ticket by hand for an address (specs 002712,
002722 and 002733 to 002738). ``Stack.send`` stands for the SMTP client, so no test
opens a socket.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.files.models import Attachment
from app.modules.tickets.mail_send import MAX_ATTEMPTS
from app.modules.tickets.models import TicketArea, TicketMailbox
from tests.integration.modules.tickets.conftest import MANAGER, Api, add_principal
from tests.integration.modules.tickets.mail_support import ADDRESS, HOST, PDF, Stack, raw_mail

pytestmark = pytest.mark.integration


async def _set_box(stack: Stack, **values: object) -> None:
    async with stack.maker() as session:
        box = await session.get(TicketMailbox, stack.box_id)
        assert box is not None
        for name, value in values.items():
            setattr(box, name, value)
        await session.commit()


async def _mail_ticket(stack: Stack, **headers: str) -> uuid.UUID:
    """Import one mail of Anna and return the id of its ticket."""
    stack.inbox.put(raw_mail(message_id="<m1@example.org>", **headers))
    await stack.run()
    return (await stack.tickets())[-1].id


async def _login(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Maria Muster")
    api.login(MANAGER)


def _note(client: TestClient, ticket_id: uuid.UUID, **body: Any) -> Any:
    return client.post(
        f"/api/tickets/{ticket_id}/notes", json={"body": "Der Raum ist frei.", **body}
    )


async def test_a_public_message_goes_out_as_a_mail_and_an_internal_one_never(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _login(api, maker)
    with TestClient(api.app) as client:
        assert _note(client, ticket_id, body="Nur für das Team.").status_code == 201
        assert _note(client, ticket_id, visibility="public").status_code == 201
        detail = client.get(f"/api/tickets/{ticket_id}").json()
    assert [m["state"] for m in detail["mails"]] == [None, "sending"]
    assert await stack.deliver() == 1
    ((account, message),) = stack.sent
    assert (account.host, account.port, account.password) == (HOST, 465, "geheim-smtp")
    assert message.get_content().strip() == "Der Raum ist frei."
    assert message["To"] == "anna@example.org"
    assert [m.state for m in await stack.mails()] == [None, "sent"]
    assert await stack.deliver() == 0


async def test_a_sent_mail_carries_the_thread_headers_and_the_number(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    (ticket,) = await stack.tickets()
    await _login(api, maker)
    with TestClient(api.app) as client:
        assert _note(client, ticket_id, visibility="public").status_code == 201
        await stack.deliver()
        assert _note(client, ticket_id, visibility="public", body="Noch etwas.").status_code == 201
        await stack.deliver()
    first, second = (message for _account, message in stack.sent)
    assert first["Subject"] == f"Re: Raumanfrage [T-{ticket.number}]"
    assert first["In-Reply-To"] == "<m1@example.org>"
    assert first["References"] == "<m1@example.org>"
    assert first["Message-ID"].endswith("@stupa.example>")
    assert second["In-Reply-To"] == first["Message-ID"]
    assert second["References"] == f"<m1@example.org> {first['Message-ID']}"
    stored = [m.message_id for m in await stack.mails()]
    assert stored == ["<m1@example.org>", first["Message-ID"], second["Message-ID"]]
    assert "Auto-Submitted" not in first


async def test_an_answer_to_a_sent_mail_comes_back_to_the_ticket(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _login(api, maker)
    with TestClient(api.app) as client:
        assert _note(client, ticket_id, visibility="public").status_code == 201
    await stack.deliver()
    sent_id = stack.sent[0][1]["Message-ID"]
    stack.inbox.put(raw_mail(message_id="<m2@example.org>", body="Danke!", In_Reply_To=sent_id))
    await stack.run()
    assert len(await stack.tickets()) == 1
    assert [n.body for n in await stack.notes(ticket_id)] == ["Der Raum ist frei.", "Danke!"]


async def test_an_answer_goes_to_the_sender_and_to_the_cc_addresses_of_the_thread(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack, Cc=f"Ben <ben@example.org>, {ADDRESS}")
    await _login(api, maker)
    with TestClient(api.app) as client:
        detail = client.get(f"/api/tickets/{ticket_id}").json()
        assert detail["mailAnswer"] == {
            "to": ["anna@example.org"],
            "cc": ["ben@example.org"],
            "enabled": True,
        }
        assert _note(client, ticket_id, visibility="public").status_code == 201
        chosen = _note(
            client,
            ticket_id,
            visibility="public",
            to=["anna@example.org"],
            cc=["Carla@Example.org", ADDRESS],
        )
        assert chosen.status_code == 201, chosen.text
        nobody = _note(client, ticket_id, visibility="public", to=[], cc=[])
        assert nobody.status_code == 422
        assert nobody.json()["code"] == "mail_without_recipient"
        after = client.get(f"/api/tickets/{ticket_id}").json()
    await stack.deliver()
    first, second = (message for _account, message in stack.sent)
    assert (first["To"], first["Cc"]) == ("anna@example.org", "ben@example.org")
    assert (second["To"], second["Cc"]) == ("anna@example.org", "carla@example.org")
    assert after["mailAnswer"]["cc"] == ["ben@example.org", "carla@example.org"]
    assert [m["to"] for m in after["mails"]] == [[], ["anna@example.org"], ["anna@example.org"]]


async def test_a_sent_mail_comes_from_the_postfach_with_the_signature(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _login(api, maker)
    with TestClient(api.app) as client:
        assert _note(client, ticket_id, visibility="public").status_code == 201
        await stack.deliver()
        await _set_box(stack, signature="Viele Grüße\n{name}, AStA-Büro")
        assert _note(client, ticket_id, visibility="public").status_code == 201
        await stack.deliver()
    plain, named = (message for _account, message in stack.sent)
    assert plain["From"] == f"AStA-Büro <{ADDRESS}>"
    assert "Maria Muster" not in plain.get_content()
    assert named.get_content().strip() == (
        "Der Raum ist frei.\n\nViele Grüße\nMaria Muster, AStA-Büro"
    )


async def test_a_public_message_answers_409_while_the_postfach_is_off(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _set_box(stack, enabled=False)
    await _login(api, maker)
    with TestClient(api.app) as client:
        refused = _note(client, ticket_id, visibility="public")
        assert refused.status_code == 409
        assert refused.json()["code"] == "mailbox_off"
        assert _note(client, ticket_id).status_code == 201
        assert client.get(f"/api/tickets/{ticket_id}").json()["mailAnswer"]["enabled"] is False
    assert [n.visibility for n in await stack.notes(ticket_id)] == ["internal"]
    assert await stack.deliver() == 0
    assert stack.sent == []


async def test_the_worker_sends_no_mail_after_the_switch_goes_off(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _login(api, maker)
    with TestClient(api.app) as client:
        assert _note(client, ticket_id, visibility="public").status_code == 201
    await _set_box(stack, enabled=False)
    assert await stack.deliver() == 0
    assert stack.sent == []
    (_first, waiting) = await stack.mails()
    assert (waiting.state, waiting.attempts, waiting.send_error) == ("sending", 1, "mailbox_off")


async def test_eight_failed_sends_end_in_failed_and_resend_starts_again(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _login(api, maker)
    with TestClient(api.app) as client:
        assert _note(client, ticket_id, visibility="public").status_code == 201
        stack.send_fails = "connect_failed"
        start = datetime.now(UTC)
        assert await stack.deliver(start) == 0
        (_in, mail) = await stack.mails()
        assert (mail.state, mail.attempts, mail.send_error) == ("sending", 1, "connect_failed")
        assert mail.next_try_at is not None
        assert mail.next_try_at - start == timedelta(minutes=1)
        assert await stack.deliver(start + timedelta(seconds=30)) == 0
        assert (await stack.mails())[1].attempts == 1
        for step in range(1, MAX_ATTEMPTS):
            await stack.deliver(start + timedelta(days=step))
        (_in, failed) = await stack.mails()
        assert (failed.state, failed.attempts) == ("failed", MAX_ATTEMPTS)
        detail = client.get(f"/api/tickets/{ticket_id}").json()
        assert [(m["state"], m["error"]) for m in detail["mails"]] == [
            (None, None),
            ("failed", "connect_failed"),
        ]
        await stack.deliver(start + timedelta(days=30))
        assert (await stack.mails())[1].attempts == MAX_ATTEMPTS
        again = client.post(f"/api/tickets/{ticket_id}/mails/{failed.id}/resend")
        assert again.status_code == 200, again.text
        assert again.json()["state"] == "sending"
        twice = client.post(f"/api/tickets/{ticket_id}/mails/{failed.id}/resend")
        assert twice.status_code == 409
        assert twice.json()["code"] == "mail_not_failed"
    stack.send_fails = None
    assert await stack.deliver() == 1
    assert [m.state for m in await stack.mails()] == [None, "sent"]


async def test_a_file_of_the_message_goes_with_the_mail_after_a_clean_scan(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    ticket_id = await _mail_ticket(stack)
    await _login(api, maker)
    with TestClient(api.app) as client:
        note_id = uuid.UUID(_note(client, ticket_id, visibility="public").json()["id"])
    await stack.storage.put("files/plan.pdf", PDF, "application/pdf")
    async with maker() as session:
        file = Attachment(
            id=uuid.uuid4(),
            ticket_note_id=note_id,
            filename="plan.pdf",
            mime="application/pdf",
            size=len(PDF),
            storage_key="files/plan.pdf",
            scanned=False,
        )
        session.add(file)
        await session.commit()
    start = datetime.now(UTC)
    assert await stack.deliver(start) == 0
    assert (await stack.mails())[1].send_error == "files_not_scanned"
    async with maker() as session:
        row = await session.get(Attachment, file.id)
        assert row is not None
        row.scanned = True
        row.scan_result = "clean"
        await session.commit()
    assert await stack.deliver(start + timedelta(minutes=2)) == 1
    (_account, message) = stack.sent[0]
    (attached,) = list(message.iter_attachments())
    assert attached.get_filename() == "plan.pdf"
    assert attached.get_content_type() == "application/pdf"
    assert attached.get_payload(decode=True) == PDF


async def test_a_new_mail_ticket_gets_one_confirmation_an_hour(stack: Stack) -> None:
    await _set_box(stack, confirm=True)
    stack.inbox.put(raw_mail(message_id="<m1@example.org>"))
    stack.inbox.put(raw_mail(message_id="<m2@example.org>", subject="Zweite Frage"))
    assert await stack.run() == 2
    first, _second = await stack.tickets()
    assert await stack.deliver() == 1
    ((_account, message),) = stack.sent
    assert message["To"] == "anna@example.org"
    assert message["Auto-Submitted"] == "auto-replied"
    assert message["Subject"] == f"Re: Raumanfrage [T-{first.number}]"
    assert message["In-Reply-To"] == "<m1@example.org>"
    assert f"T-{first.number}" in message.get_content()
    out = [m for m in await stack.mails() if m.direction == "out"]
    assert [(m.automatic, m.note_id, m.state) for m in out] == [(True, None, "sent")]


async def test_no_confirmation_while_the_switch_is_off(stack: Stack) -> None:
    stack.inbox.put(raw_mail(message_id="<m1@example.org>"))
    await stack.run()
    assert await stack.deliver() == 0
    assert [m.direction for m in await stack.mails()] == ["in"]


async def test_a_ticket_by_hand_for_an_address_needs_a_postfach_and_sends_the_message(
    stack: Stack, api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    async with maker() as session:
        bare = TicketArea(id=uuid.uuid4(), name="Ohne Postfach", notify_new=False)
        session.add(bare)
        await session.commit()
    await _login(api, maker)
    body = {"title": "Rückruf", "email": "Dora@Example.org", "message": "Wir melden uns."}
    with TestClient(api.app) as client:
        refused = client.post("/api/tickets/manual", json={**body, "areaId": str(bare.id)})
        assert refused.status_code == 422
        assert refused.json()["code"] == "ticket_area_without_mailbox"
        made = client.post("/api/tickets/manual", json={**body, "areaId": str(stack.area_id)})
        assert made.status_code == 201, made.text
        detail = made.json()
    assert detail["reporter"]["email"] == "dora@example.org"
    assert detail["mailAnswer"] == {"to": ["dora@example.org"], "cc": [], "enabled": True}
    assert await stack.deliver() == 1
    ((_account, message),) = stack.sent
    assert message["To"] == "dora@example.org"
    assert message["Subject"] == f"Rückruf [{detail['number']}]"
    assert "In-Reply-To" not in message
    assert message.get_content().strip() == "Wir melden uns."
