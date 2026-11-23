"""Fan a domain event out to the webhooks that subscribe to it.

A domain module calls `emit_event` inside the transaction of its change
(§F/integrations/webhooks/002417). The function reads the active webhooks, keeps those
that subscribe to the event and whose filters let it pass (§F/integrations/webhooks/002410,
002414), and adds one `pending` delivery per webhook to the session. The body holds the
event name, `occurredAt`, the ID keys and a `data` object with exactly the fields that the
webhook chose (§F/integrations/webhooks/002412). The caller commits: a rollback removes the
deliveries with the change. The worker cron `enqueue_pending_webhooks` then hands each new
delivery to the `deliver_webhook` job.

The field values come from `fields`, a coroutine function of the caller. The function runs
at most once per event and only when a webhook needs a field, so an event that nobody
subscribes to costs one small query. This module imports no domain module: the caller
reads its own tables (§S/backend/python/000643).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select

from app.modules.webhooks.catalog import EVENTS, WebhookEventName
from app.modules.webhooks.models import Webhook, WebhookDelivery

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("app.webhooks")

FieldsFn = Callable[[], Awaitable[Mapping[str, Any]]]


async def _no_fields() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    """One domain event for the webhooks.

    Attributes:
        ids: The ID keys of the event (catalog `id_keys`), always in the body.
        fields: Returns every field of the event. Only the chosen ones go out.
        gremium_id: The Gremium of the event for the filter, or None.
        type_id: The Antragsart of the event for the filter, or None.
        state_key: The target status of `application.transition` for the filter.
    """

    name: WebhookEventName
    ids: Mapping[str, UUID | None]
    fields: FieldsFn = _no_fields
    gremium_id: UUID | None = None
    type_id: UUID | None = None
    state_key: str | None = None
    occurred_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))


def _passes(hook: Webhook, event: WebhookEvent) -> bool:
    """Tell whether the filters of `hook` let `event` pass (§F/integrations/webhooks/002414).

    An empty list lets every value pass. An event without a value passes that filter.
    """
    checks = (
        (hook.gremium_ids, None if event.gremium_id is None else str(event.gremium_id)),
        (hook.type_ids, None if event.type_id is None else str(event.type_id)),
        (hook.state_keys if event.name == "application.transition" else [], event.state_key),
    )
    return all(not allowed or value is None or value in allowed for allowed, value in checks)


def subscribed_fields(hook: Webhook, event: str) -> list[str] | None:
    """Return the chosen fields of `event` for `hook`, or None when it does not subscribe."""
    for entry in hook.subscriptions or []:
        if entry.get("event") == event:
            return [str(key) for key in entry.get("fields") or []]
    return None


def build_body(event: WebhookEvent, chosen: list[str], values: Mapping[str, Any]) -> dict[str, Any]:
    """Return the body of one delivery: event, time, IDs and the chosen fields."""
    known = EVENTS[event.name].field_keys
    return {
        "event": event.name,
        "occurredAt": event.occurred_at.isoformat(),
        **{key: None if value is None else str(value) for key, value in event.ids.items()},
        "data": {key: values.get(key) for key in chosen if key in known},
    }


async def active_webhooks(session: AsyncSession) -> Sequence[Webhook]:
    """Return the active webhooks. The table is small, so the filter runs in Python."""
    return (await session.scalars(select(Webhook).where(Webhook.active.is_(True)))).all()


async def has_subscriber(session: AsyncSession, name: str) -> bool:
    """Return True when an active webhook subscribes to the event `name`.

    An emit site asks first, so an event without a subscriber reads no field and builds
    no event.
    """
    return any(subscribed_fields(hook, name) is not None for hook in await active_webhooks(session))


async def emit_event(session: AsyncSession, event: WebhookEvent) -> int:
    """Add one pending delivery per subscribed webhook that the filters let pass.

    The caller commits. The function flushes nothing, so it adds no round trip to a
    transaction without a subscriber.

    Returns:
        The number of new deliveries.
    """
    hooks = await active_webhooks(session)
    targets = [
        (hook, chosen)
        for hook in hooks
        if (chosen := subscribed_fields(hook, event.name)) is not None and _passes(hook, event)
    ]
    if not targets:
        return 0
    values = await event.fields() if any(chosen for _, chosen in targets) else {}
    for hook, chosen in targets:
        session.add(
            WebhookDelivery(
                webhook_id=hook.id,
                event=event.name,
                payload=build_body(event, chosen, values),
                status="pending",
                attempts=0,
            )
        )
    logger.info("webhook event %s: %d deliveries", event.name, len(targets))
    return len(targets)
