"""The webhook fields of a vote and the emit of `vote.opened` and `vote.closed`.

The service calls `emit_vote_event` in the transaction of the open or the close
(§F/integrations/webhooks/002410, 002417). `counts` holds the totals of the options only,
never a ballot, because every vote is secret. The Gremium of the vote is the Gremium whose
id is the `eligible_group`; another group key gives no Gremium.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import String, cast, select

from app.modules.applications.webhook_fields import link
from app.modules.gremien.models import Gremium
from app.modules.webhooks.events import WebhookEvent, emit_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.voting.models import Vote
    from app.modules.webhooks.catalog import WebhookEventName


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _str(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


async def emit_vote_event(
    session: AsyncSession,
    name: WebhookEventName,
    vote: Vote,
    *,
    counts: Mapping[str, int] | None = None,
) -> int:
    """Emit a vote event. `counts` is set for `vote.closed`.

    Returns:
        The number of new deliveries.
    """
    gremium = await session.scalar(
        select(Gremium).where(cast(Gremium.id, String) == vote.eligible_group)
    )
    gremium_ref = {"id": str(getattr(gremium, "id", "")), "name": getattr(gremium, "name", "")}

    async def fields() -> Mapping[str, Any]:
        return {
            "question": vote.question,
            "kind": vote.kind,
            "gremium": gremium_ref if gremium is not None else None,
            "meetingId": _str(vote.meeting_id),
            "applicationId": _str(vote.application_id),
            "closesAt": _iso(vote.closes_at),
            "url": link(f"/voting/{vote.id}"),
            "result": vote.result,
            "counts": dict(counts or {}),
        }

    return await emit_event(
        session,
        WebhookEvent(
            name=name,
            ids={"voteId": vote.id},
            fields=fields,
            gremium_id=getattr(gremium, "id", None),
        ),
    )
