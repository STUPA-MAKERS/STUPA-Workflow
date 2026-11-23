"""The webhook fields of a protocol and the emit of `protocol.finalized`.

The render step calls `emit_protocol_finalized` in the transaction that sets the protocol
to final (§F/integrations/webhooks/002410, 002417). `publicUrl` is the public page of the
protocol, or None while the protocol is held back from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.modules.applications.webhook_fields import link, ref
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.meetings.protocol_models import Protocol


async def emit_protocol_finalized(session: AsyncSession, protocol: Protocol) -> int:
    """Emit `protocol.finalized`.

    Returns:
        The number of new deliveries.
    """

    async def fields() -> Mapping[str, Any]:
        meeting = await session.get(Meeting, protocol.meeting_id)
        gremium = await session.get(Gremium, protocol.gremium_id)
        return {
            "meetingTitle": None if meeting is None else meeting.title,
            "gremium": None if gremium is None else ref(gremium.id, gremium.name),
            "finalizedAt": None
            if protocol.finalized_at is None
            else protocol.finalized_at.isoformat(),
            "publicUrl": None if protocol.public_withheld else link(f"/protocols/{protocol.id}"),
        }

    return await emit_event(
        session,
        WebhookEvent(
            name="protocol.finalized",
            ids={"protocolId": protocol.id, "meetingId": protocol.meeting_id},
            fields=fields,
            gremium_id=protocol.gremium_id,
        ),
    )
