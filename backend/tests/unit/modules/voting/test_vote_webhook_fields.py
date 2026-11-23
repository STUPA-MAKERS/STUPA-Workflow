"""The webhook fields of a vote (§F/integrations/webhooks/002410, 002412)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from app.modules.gremien.models import Gremium
from app.modules.voting.models import Vote
from app.modules.voting.webhook_fields import emit_vote_event
from app.modules.webhooks.catalog import EVENTS
from app.modules.webhooks.models import Webhook
from tests.unit.conftest import ActiveWebhooks


class _Session:
    def __init__(self, gremium: Gremium | None) -> None:
        self.gremium = gremium
        self.added: list[Any] = []

    async def scalar(self, _stmt: object) -> Gremium | None:
        return self.gremium

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _hook(event: str) -> Webhook:
    hook = Webhook(
        name="h",
        url="https://h.test/h",
        active=True,
        subscriptions=[{"event": event, "fields": sorted(EVENTS[event].field_keys)}],
        gremium_ids=[],
        type_ids=[],
        state_keys=[],
    )
    hook.id = uuid.uuid4()
    return hook


async def test_closed_vote_with_gremium(active_webhooks: ActiveWebhooks) -> None:
    """A closed vote sends its result and the totals, never a ballot."""
    gremium = Gremium(name="StuPa", slug="stupa")
    gremium.id = uuid.uuid4()
    active_webhooks.hooks = [_hook("vote.closed")]
    vote = Vote(
        eligible_group=str(gremium.id),
        question="Q?",
        kind="vote",
        meeting_id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        closes_at=dt.datetime(2026, 11, 23, tzinfo=dt.UTC),
        result="passed",
    )
    vote.id = uuid.uuid4()
    session = _Session(gremium)
    n = await emit_vote_event(session, "vote.closed", vote, counts={"yes": 2})  # type: ignore[arg-type]
    assert n == 1
    data = session.added[0].payload["data"]
    assert data["gremium"] == {"id": str(gremium.id), "name": "StuPa"}
    assert data["counts"] == {"yes": 2}
    assert data["result"] == "passed"
    assert data["meetingId"] == str(vote.meeting_id)
    assert data["closesAt"] == "2026-11-23T00:00:00+00:00"


async def test_opened_vote_without_gremium(active_webhooks: ActiveWebhooks) -> None:
    active_webhooks.hooks = [_hook("vote.opened")]
    vote = Vote(eligible_group="all", question=None, kind="vote")
    vote.id = uuid.uuid4()
    session = _Session(None)
    await emit_vote_event(session, "vote.opened", vote)  # type: ignore[arg-type]
    data = session.added[0].payload["data"]
    assert data["gremium"] is None
    assert data["meetingId"] is None
    assert data["applicationId"] is None
    assert data["closesAt"] is None
    assert "counts" not in data
