"""The webhook events of a ticket: fields, Gremium filter and the status pair."""

from __future__ import annotations

import uuid
from typing import Any

from app.modules.tickets.models import Ticket, TicketArea
from app.modules.tickets.webhook_fields import (
    emit_ticket_created,
    emit_ticket_message,
    emit_ticket_status,
)
from app.modules.webhooks.catalog import EVENTS
from app.modules.webhooks.models import Webhook
from tests._support.webhooks_fakes import FakeSession
from tests.unit.conftest import ActiveWebhooks

GREMIUM_A = uuid.uuid4()
GREMIUM_B = uuid.uuid4()


def _hook(event: str, *, gremiums: list[uuid.UUID] | None = None) -> Webhook:
    hook = Webhook(
        name="h",
        url="https://hook.test/h",
        active=True,
        secret=b"k",
        subscriptions=[{"event": event, "fields": sorted(EVENTS[event].field_keys)}],
        gremium_ids=[str(g) for g in gremiums or []],
        type_ids=[],
        state_keys=[],
    )
    hook.id = uuid.uuid4()
    return hook


def _stack(gremium_id: uuid.UUID | None) -> tuple[FakeSession, Ticket]:
    area = TicketArea(name="Finanzen", gremium_id=gremium_id)
    area.id = uuid.uuid4()
    session = FakeSession()
    session.store[area.id] = area
    ticket = Ticket(
        id=uuid.uuid4(),
        number="7K3QX9MD",
        area_id=area.id,
        kind=None,
        source="mail",
        title="Rechnung 42",
        body="Im Anhang.",
        status="new",
    )
    return session, ticket


def _data(session: FakeSession) -> list[dict[str, Any]]:
    return [row.payload["data"] for row in session.added]


async def test_created_names_the_area_and_the_source(active_webhooks: ActiveWebhooks) -> None:
    """`ticket.created` holds the Bereich and the source. §F/integrations/webhooks/002749."""
    active_webhooks.hooks = [_hook("ticket.created", gremiums=[GREMIUM_A])]
    session, ticket = _stack(GREMIUM_A)
    count = await emit_ticket_created(session, ticket, reporter_email="a@b.test")  # type: ignore[arg-type]
    assert count == 1
    data = _data(session)[0]
    assert data["area"] == {"id": str(ticket.area_id), "name": "Finanzen"}
    assert data["source"] == "mail"
    assert data["number"] == "T-7K3QX9MD"
    assert data["reporterEmail"] == "a@b.test"


async def test_created_follows_the_gremium_filter(active_webhooks: ActiveWebhooks) -> None:
    """A ticket of Gremium A gives a webhook of Gremium B no delivery.

    §F/integrations/webhooks/002749
    """
    active_webhooks.hooks = [_hook("ticket.created", gremiums=[GREMIUM_B])]
    session, ticket = _stack(GREMIUM_A)
    assert await emit_ticket_created(session, ticket, reporter_email=None) == 0  # type: ignore[arg-type]
    assert session.added == []


async def test_an_area_without_gremium_passes_the_filter(
    active_webhooks: ActiveWebhooks,
) -> None:
    """A Bereich without a Gremium passes the Gremium filter. §F/integrations/webhooks/002749."""
    active_webhooks.hooks = [_hook("ticket.created", gremiums=[GREMIUM_B])]
    session, ticket = _stack(None)
    assert await emit_ticket_created(session, ticket, reporter_email=None) == 1  # type: ignore[arg-type]


async def test_message_holds_the_text(active_webhooks: ActiveWebhooks) -> None:
    """`ticket.message` holds number, title, Bereich, link and text.

    §F/integrations/webhooks/002750
    """
    active_webhooks.hooks = [_hook("ticket.message")]
    session, ticket = _stack(GREMIUM_A)
    assert await emit_ticket_message(session, ticket, body="Noch eine Frage.") == 1  # type: ignore[arg-type]
    data = _data(session)[0]
    assert set(data) == {"number", "title", "area", "url", "body"}
    assert data["body"] == "Noch eine Frage."
    assert data["url"].endswith(f"/tickets/{ticket.id}")


async def test_status_holds_both_statuses(active_webhooks: ActiveWebhooks) -> None:
    """`ticket.status` holds the old and the new status. §F/integrations/webhooks/002751."""
    active_webhooks.hooks = [_hook("ticket.status")]
    session, ticket = _stack(GREMIUM_A)
    assert await emit_ticket_status(session, ticket, old="new", new="done") == 1  # type: ignore[arg-type]
    data = _data(session)[0]
    assert (data["fromStatus"], data["toStatus"]) == ("new", "done")
    assert session.added[0].event == "ticket.status"


async def test_the_same_status_is_no_event(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("ticket.status")]
    session, ticket = _stack(GREMIUM_A)
    assert await emit_ticket_status(session, ticket, old="done", new="done") == 0  # type: ignore[arg-type]


async def test_no_subscriber_reads_no_area(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("ticket.created")]
    session, ticket = _stack(GREMIUM_A)
    session.store.clear()
    assert await emit_ticket_message(session, ticket, body="x") == 0  # type: ignore[arg-type]
