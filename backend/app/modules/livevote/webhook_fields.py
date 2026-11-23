"""The webhook fields of a meeting and the emit of its events.

The meeting service calls `emit_meeting_event` in the transaction of the create, the start
or the close (§F/integrations/webhooks/002410, 002417).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, time
from typing import TYPE_CHECKING, Any

from app.modules.applications.webhook_fields import link, ref
from app.modules.gremien.models import Gremium
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.meetings.models import Meeting
    from app.modules.webhooks.catalog import WebhookEventName


def _iso(value: date | time | None) -> str | None:
    return None if value is None else value.isoformat()


async def emit_meeting_event(
    session: AsyncSession, name: WebhookEventName, meeting: Meeting
) -> int:
    """Emit a meeting event with the fields of the meeting.

    Returns:
        The number of new deliveries.
    """

    async def fields() -> Mapping[str, Any]:
        gremium = await session.get(Gremium, meeting.gremium_id)
        return {
            "title": meeting.title,
            "gremium": None if gremium is None else ref(gremium.id, gremium.name),
            "date": _iso(meeting.date),
            "startTime": _iso(meeting.start_time),
            "endTime": _iso(meeting.end_time),
            "location": meeting.location,
            "status": meeting.status,
            "url": link(f"/meetings/{meeting.id}"),
        }

    return await emit_event(
        session,
        WebhookEvent(
            name=name, ids={"meetingId": meeting.id}, fields=fields, gremium_id=meeting.gremium_id
        ),
    )
