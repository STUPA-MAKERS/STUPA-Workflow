"""The webhook fields of an Event and the emit of its events (F/collaboration/events/003034).

The service calls `emit_event_event` in the transaction of the create, the change, the
status change and the delete (F/integrations/webhooks/002410). The Gremium filter of a
webhook reads the Gremium of the team of the Event, because an Event has none of its
own. An Event of a free team has none, so only the Antragsart and Gremium filters that
are empty hold it back: an event without a value passes a filter.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.modules.applications.webhook_fields import link
from app.modules.events.models import format_event_number
from app.modules.teams.members import gremien_of_teams, team_names
from app.modules.webhooks.catalog import WebhookEventName
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.events.models import Event


def _iso(value: object) -> str | None:
    return None if value is None else value.isoformat()  # type: ignore[attr-defined]


def event_fields(row: Event, team_name: str | None) -> Mapping[str, Any]:
    """Return the fields of every event of an Event."""
    return {
        "number": format_event_number(row.number),
        "title": row.title,
        "status": row.status,
        "startsOn": _iso(row.starts_on),
        "startTime": _iso(row.start_time),
        "endsOn": _iso(row.ends_on),
        "endTime": _iso(row.end_time),
        "place": row.place,
        "participants": row.participants,
        "shopUrl": row.shop_url,
        "teamName": team_name,
        "url": link(f"/events?id={row.id}"),
    }


async def emit_event_event(
    session: AsyncSession,
    row: Event,
    name: WebhookEventName,
    *,
    previous: str | None = None,
) -> int:
    """Emit ``event.created``, ``event.updated``, ``event.status_changed`` or ``event.deleted``.

    Args:
        session: The session of the write.
        row: The Event after the write, or before the delete.
        name: The name of the webhook event.
        previous: The status before a status change.

    Returns:
        The number of new deliveries.
    """
    gremium = (await gremien_of_teams(session, [row.team_id])).get(row.team_id)
    snapshot = event_fields(row, (await team_names(session, [row.team_id])).get(row.team_id))

    async def fields() -> Mapping[str, Any]:
        return snapshot if previous is None else {**snapshot, "fromStatus": previous}

    return await emit_event(
        session,
        WebhookEvent(name=name, ids={"eventId": row.id}, fields=fields, gremium_id=gremium),
    )
