"""#11: a `relative_submitted` deadline counts from `received_on` (real Postgres).

User decision 2026-10-06: the reference "ab Einreichung" is the received date of an
application captured on behalf of the applicant, at the local time of day of the
capture. Without a received date it stays `created_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.applications.schemas import OnBehalfCreate
from app.modules.applications.service import ApplicationsService
from app.settings import get_settings
from tests.integration.modules.applications.test_relative_changed_deadline import (
    _create,
    _due,
    _seed,
    session,  # noqa: F401 - the fixture of the shared seed
)

pytestmark = pytest.mark.integration


async def test_captured_deadline_counts_from_the_received_date(
    session: AsyncSession,  # noqa: F811
) -> None:
    type_id = await _seed(session, "relative_submitted")
    tz = ZoneInfo(get_settings().local_timezone)
    today = datetime.now(tz).date()
    received = today - timedelta(days=5)
    out, _ = await ApplicationsService(session).create_on_behalf(
        OnBehalfCreate.model_validate(
            {
                "typeId": str(type_id),
                "data": {"title": "Papier"},
                "applicantName": "Gisela",
                "applicantEmail": "gisela-deadline@example.org",
                "receivedOn": received.isoformat(),
            }
        ),
        actor="clerk",
        today=today,
    )
    app = await session.get(Application, out.id)
    assert app is not None
    deadline = await _due(session, app.id)
    local_due = deadline.due_at.astimezone(tz)
    assert local_due.date() == received + timedelta(days=3)
    # The time of day is the time of the capture.
    capture_time = app.created_at.astimezone(tz).timetz().replace(tzinfo=None)
    assert local_due.timetz().replace(tzinfo=None) == capture_time


async def test_own_submission_counts_from_created_at(
    session: AsyncSession,  # noqa: F811
) -> None:
    type_id = await _seed(session, "relative_submitted")
    app = await _create(session, type_id)
    assert app.received_on is None
    deadline = await _due(session, app.id)
    assert deadline.due_at == app.created_at + timedelta(days=3)
