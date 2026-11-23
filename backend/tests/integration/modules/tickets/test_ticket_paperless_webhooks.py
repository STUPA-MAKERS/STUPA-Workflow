"""Integration: the Paperless action and the webhook events of a ticket (real Postgres).

Covers the action `In Paperless ablegen` with its job in the worker
(§F/integrations/ticket-mail/002742) and the events `ticket.message` and `ticket.status`
of a sender message from a mail and of a status change by the team
(§F/integrations/webhooks/002750, 002751).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.files.models import Attachment
from app.modules.paperless.connection import ConnectionService
from app.modules.paperless.models import PaperlessFiling, PaperlessSettings
from app.modules.paperless.schemas import ConnectionIn
from app.modules.webhooks.models import Webhook, WebhookDelivery
from app.settings import Settings
from tests._support.paperless_fakes import BASE_URL, TOKEN, FakePaperless
from tests._support.paperless_fakes import HOST as PAPERLESS_HOST
from tests.integration.modules.tickets.conftest import MANAGER, Api, add_principal
from tests.integration.modules.tickets.mail_support import ADDRESS, PDF, Stack, raw_mail
from worker.paperless import process_paperless_filings

pytestmark = pytest.mark.integration

Maker = async_sessionmaker[AsyncSession]

ARCHIVIST = Principal(
    sub="archive-sub",
    email="archive@example.org",
    permissions={"ticket.manage", "paperless.use"},
)
_RUN = datetime.now(UTC) + timedelta(days=1)


def _mail_with_pdf() -> bytes:
    message = EmailMessage()
    message["From"] = "Anna Beispiel <anna@example.org>"
    message["To"] = ADDRESS
    message["Subject"] = "Rechnung 42"
    message["Message-ID"] = "<invoice@example.org>"
    message.set_content("Die Rechnung liegt bei.")
    message.add_attachment(PDF, maintype="application", subtype="pdf", filename="rechnung.pdf")
    return bytes(message)


async def _ticket_with_file(stack: Stack, *, clean: bool = True) -> tuple[uuid.UUID, uuid.UUID]:
    """Import a mail with one PDF. Return the ids of the ticket and of the file."""
    stack.inbox.put(_mail_with_pdf())
    await stack.run()
    ticket = (await stack.tickets())[-1]
    async with stack.maker() as session:
        file = await session.scalar(select(Attachment).where(Attachment.ticket_id == ticket.id))
        assert file is not None
        if clean:
            await session.execute(
                update(Attachment)
                .where(Attachment.id == file.id)
                .values(scanned=True, scan_result="clean")
            )
        await session.commit()
        return ticket.id, file.id


def _paperless_settings(settings: Settings) -> Settings:
    return settings.model_copy(update={"paperless_host_allowlist": [PAPERLESS_HOST]})


async def _connect(maker: Maker, settings: Settings) -> None:
    async with maker() as session:
        await ConnectionService(session, _paperless_settings(settings)).save(
            ConnectionIn.model_validate({"baseUrl": BASE_URL, "token": TOKEN}),
            actor="admin-sub",
            now=datetime.now(UTC),
        )
        await session.commit()


@pytest.fixture
async def paperless(maker: Maker) -> Any:
    """Start and end without a connection and without a filing."""

    async def _wipe() -> None:
        async with maker() as session:
            await session.execute(delete(PaperlessFiling))
            await session.execute(delete(PaperlessSettings))
            await session.commit()

    await _wipe()
    yield FakePaperless()
    await _wipe()


async def _login(api: Api, maker: Maker, principal: Principal) -> TestClient:
    await add_principal(maker, sub=principal.sub, email=principal.email, name="Maria Muster")
    api.login(principal)
    return TestClient(api.app)


def _path(ticket_id: uuid.UUID, file_id: uuid.UUID) -> str:
    return f"/api/tickets/{ticket_id}/files/{file_id}/paperless"


async def test_the_action_needs_paperless_use(
    api: Api, stack: Stack, maker: Maker, settings: Settings, paperless: FakePaperless
) -> None:
    """A person with the work right and without `paperless.use` gets 403.

    §F/integrations/ticket-mail/002742
    """
    await _connect(maker, settings)
    ticket_id, file_id = await _ticket_with_file(stack)
    client = await _login(api, maker, MANAGER)
    assert client.post(_path(ticket_id, file_id)).status_code == 403
    assert client.get(f"/api/tickets/{ticket_id}").json()["paperless"] is None


async def test_the_action_is_off_without_a_connection(
    api: Api, stack: Stack, maker: Maker, paperless: FakePaperless
) -> None:
    ticket_id, file_id = await _ticket_with_file(stack)
    client = await _login(api, maker, ARCHIVIST)
    answer = client.post(_path(ticket_id, file_id))
    assert (answer.status_code, answer.json()["code"]) == (409, "paperless_off")
    assert client.get(f"/api/tickets/{ticket_id}").json()["paperless"] is None


async def test_only_a_clean_file_of_the_ticket_is_filed(
    api: Api, stack: Stack, maker: Maker, settings: Settings, paperless: FakePaperless
) -> None:
    await _connect(maker, settings)
    ticket_id, file_id = await _ticket_with_file(stack, clean=False)
    client = await _login(api, maker, ARCHIVIST)
    answer = client.post(_path(ticket_id, file_id))
    assert (answer.status_code, answer.json()["code"]) == (409, "file_not_clean")
    assert client.post(_path(ticket_id, uuid.uuid4())).status_code == 404
    assert client.get(f"/api/tickets/{ticket_id}").json()["paperless"] == {"files": []}


async def test_the_worker_files_the_file_with_the_ticket_number(
    api: Api, stack: Stack, maker: Maker, settings: Settings, paperless: FakePaperless
) -> None:
    """The action opens one job, and the worker files the document.

    §F/integrations/ticket-mail/002742
    """
    await _connect(maker, settings)
    ticket_id, file_id = await _ticket_with_file(stack)
    client = await _login(api, maker, ARCHIVIST)
    number = client.get(f"/api/tickets/{ticket_id}").json()["number"]

    first = client.post(_path(ticket_id, file_id))
    assert first.status_code == 202
    assert first.json() == {
        "id": str(file_id),
        "filename": "rechnung.pdf",
        "state": "pending",
        "url": None,
    }
    assert client.post(_path(ticket_id, file_id)).status_code == 202
    async with maker() as session:
        assert len((await session.scalars(select(PaperlessFiling))).all()) == 1

    ctx: dict[str, Any] = {
        "settings": _paperless_settings(settings),
        "object_storage": stack.storage,
        "typst_client": None,
        "paperless_sessionmaker": maker,
        "paperless_client_factory": paperless.client,
    }
    filed = sum([await process_paperless_filings(ctx, _RUN + timedelta(days=d)) for d in (0, 1)])
    assert filed == 1
    upload = paperless.uploads[0]
    assert upload["title"] == f"{number} – rechnung.pdf"
    assert upload["bytes"] == PDF.decode()
    assert paperless.name_of("document_types", upload["document_type"]) == "Ticket"

    files = client.get(f"/api/tickets/{ticket_id}").json()["paperless"]["files"]
    assert [(f["state"], f["url"] is not None) for f in files] == [("filed", True)]


async def _hook(maker: Maker, *events: str) -> uuid.UUID:
    async with maker() as session:
        await session.execute(delete(WebhookDelivery))
        await session.execute(delete(Webhook))
        hook = Webhook(
            name="chat",
            url="https://hook.example.org/t",
            active=True,
            secret=b"k",
            subscriptions=[
                {"event": event, "fields": ["number", "body", "fromStatus", "toStatus"]}
                for event in events
            ],
            gremium_ids=[],
            type_ids=[],
            state_keys=[],
        )
        session.add(hook)
        await session.commit()
        return hook.id


async def _deliveries(maker: Maker) -> list[tuple[str, dict[str, Any]]]:
    async with maker() as session:
        rows = await session.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at))
        out = [(row.event, dict(row.payload["data"])) for row in rows.all()]
        await session.execute(delete(WebhookDelivery))
        await session.execute(delete(Webhook))
        await session.commit()
        return out


async def test_a_sender_message_is_an_event_and_a_team_message_is_not(
    api: Api, stack: Stack, maker: Maker
) -> None:
    """One sender mail and one team message give one `ticket.message`.

    The first mail is no `ticket.message`. §F/integrations/webhooks/002750
    """
    await _hook(maker, "ticket.message")
    stack.inbox.put(raw_mail(message_id="<m1@example.org>"))
    await stack.run()
    ticket = (await stack.tickets())[-1]
    client = await _login(api, maker, MANAGER)
    team = client.post(
        f"/api/tickets/{ticket.id}/notes", json={"body": "Intern.", "visibility": "internal"}
    )
    assert team.status_code == 201
    stack.inbox.put(
        raw_mail(
            message_id="<m2@example.org>",
            body="Noch eine Frage.",
            In_Reply_To="<m1@example.org>",
        )
    )
    await stack.run()
    events = await _deliveries(maker)
    assert [event for event, _ in events] == ["ticket.message"]
    assert events[0][1]["body"] == "Noch eine Frage."


async def test_each_status_change_is_an_event(api: Api, stack: Stack, maker: Maker) -> None:
    """A change by the team and a change without a person give one event each.

    §F/integrations/webhooks/002751
    """
    await _hook(maker, "ticket.status")
    stack.inbox.put(raw_mail(message_id="<m1@example.org>"))
    await stack.run()
    ticket = (await stack.tickets())[-1]
    client = await _login(api, maker, MANAGER)
    assert client.patch(f"/api/tickets/{ticket.id}", json={"status": "waiting"}).status_code == 200
    stack.inbox.put(raw_mail(message_id="<m2@example.org>", In_Reply_To="<m1@example.org>"))
    await stack.run()
    statuses = [(d["fromStatus"], d["toStatus"]) for _event, d in await _deliveries(maker)]
    assert statuses == [("new", "waiting"), ("waiting", "in_progress")]
