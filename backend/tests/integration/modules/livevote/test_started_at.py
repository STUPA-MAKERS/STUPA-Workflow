"""The start sets ``started_at`` once, and MeetingOut carries the agenda.

The tests run on a real Postgres. The detail, the list and the timeline all carry
``startedAt``, ``agendaItemCount`` and ``currentAgendaItem``.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.deps import get_current_principal
from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.flow.models import FlowVersion
from app.modules.forms.models import FormVersion
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from tests.integration.modules.livevote.conftest import admin, audit_actions, seed

pytestmark = pytest.mark.integration


async def test_start_sets_started_at_once(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """Set `started_at` once on the start.

    A repeated start is a no-op: the stamp stays, and no second entry is written.
    """
    s = await seed(maker, status="planned")
    with TestClient(api) as client:
        started = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "live"})
        assert started.status_code == 200, started.text
        first = started.json()["startedAt"]
        assert first is not None
        again = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "live"})
        assert again.status_code == 200, again.text
        assert again.json()["startedAt"] == first
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        assert meeting.started_at is not None
    entries = await audit_actions(maker, target_id=s.meeting_id)
    assert [e.data["changes"] for e in entries] == [{"status": {"from": "planned", "to": "live"}}]


async def test_meeting_out_carries_the_agenda_summary(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """Carry the agenda summary in the meeting view.

    Only the protokollant moves the current agenda item.
    """
    s = await seed(maker, status="live", items=3)
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        app_type = ApplicationType(
            gremium_id=s.gremium_id, key=f"t-{tag}", name_i18n={}, has_budget=False
        )
        session.add(app_type)
        await session.flush()
        form_version = FormVersion(application_type_id=app_type.id, version=1)
        flow_version = FlowVersion(version=1)
        session.add_all([form_version, flow_version])
        await session.flush()
        application = Application(
            type_id=app_type.id,
            form_version_id=form_version.id,
            flow_version_id=flow_version.id,
            data={"title": "Sommerfest"},
        )
        session.add(application)
        await session.flush()
        app_item = MeetingAgendaItem(
            meeting_id=s.meeting_id, application_id=application.id, position=3
        )
        session.add(app_item)
        await session.flush()
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        meeting.current_agenda_item_id = s.item_ids[1]
        keeper = await session.get(PrincipalRow, meeting.protokollant_id)
        assert keeper is not None
        keeper_sub = keeper.sub
        await session.commit()

    with TestClient(api) as client:
        detail = client.get(f"/api/meetings/{s.meeting_id}").json()
        assert detail["agendaItemCount"] == 4
        assert detail["currentAgendaItem"] == {"position": 2, "title": "TOP 2"}

        api.dependency_overrides[get_current_principal] = lambda: Principal(sub=keeper_sub)
        moved = client.patch(
            f"/api/meetings/{s.meeting_id}", json={"currentAgendaItemId": str(app_item.id)}
        )
        api.dependency_overrides[get_current_principal] = admin
        assert moved.status_code == 200, moved.text
        assert moved.json()["currentAgendaItem"] == {"position": 4, "title": "Sommerfest"}

        listed = [m for m in client.get("/api/meetings").json() if m["id"] == str(s.meeting_id)]
        assert listed[0]["agendaItemCount"] == 4
        assert listed[0]["currentAgendaItem"] == {"position": 4, "title": "Sommerfest"}
        timeline = client.get("/api/meetings/timeline?direction=upcoming").json()["items"]
        row = next(m for m in timeline if m["id"] == str(s.meeting_id))
        assert row["currentAgendaItem"]["title"] == "Sommerfest"
        assert row["startedAt"] is None


async def test_list_and_timeline_carry_the_agenda_count(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """The overview shows "n TOPs" on each row: every list shape counts the agenda.

    The planned meeting of 20.06.2026 lies in the past of the test run.
    """
    live = await seed(maker, status="live", items=2)
    planned = await seed(maker, status="planned", items=0)
    with TestClient(api) as client:
        upcoming = client.get(
            "/api/meetings/timeline",
            params={"direction": "upcoming", "gremiumId": str(live.gremium_id)},
        ).json()["items"]
        assert [(m["id"], m["agendaItemCount"]) for m in upcoming] == [(str(live.meeting_id), 2)]
        past = client.get(
            "/api/meetings/timeline",
            params={"direction": "past", "gremiumId": str(planned.gremium_id)},
        ).json()["items"]
        assert [(m["id"], m["agendaItemCount"]) for m in past] == [(str(planned.meeting_id), 0)]
        hits = client.get(
            "/api/meetings/timeline",
            params={"q": "GV", "gremiumId": str(live.gremium_id)},
        ).json()["items"]
        assert [m["agendaItemCount"] for m in hits] == [2]


async def test_list_filters_by_the_planned_date(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """The calendar reads one month: ``dateFrom`` and ``dateTo`` include both ends."""
    s = await seed(maker, status="planned", items=3)
    gid = str(s.gremium_id)
    with TestClient(api) as client:

        def ids(**params: str) -> list[str]:
            res = client.get("/api/meetings", params={"gremiumId": gid, **params})
            assert res.status_code == 200, res.text
            return [m["id"] for m in res.json()]

        assert ids(dateFrom="2026-06-01", dateTo="2026-06-30") == [str(s.meeting_id)]
        assert ids(dateFrom="2026-06-20", dateTo="2026-06-20") == [str(s.meeting_id)]
        assert ids(dateFrom="2026-06-21") == []
        assert ids(dateTo="2026-06-19") == []
        listed = client.get(
            "/api/meetings", params={"gremiumId": gid, "dateFrom": "2026-06-01"}
        ).json()
        assert listed[0]["agendaItemCount"] == 3
        bad = client.get("/api/meetings", params={"dateFrom": "2026-07-01", "dateTo": "2026-06-01"})
        assert bad.status_code == 422
        assert bad.headers["content-type"] == "application/problem+json"
        assert bad.json()["code"] == "invalid_date_range"


async def _keeper_sub(maker: async_sessionmaker[AsyncSession], meeting_id: uuid.UUID) -> str:
    async with maker() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None
        keeper = await session.get(PrincipalRow, meeting.protokollant_id)
        assert keeper is not None
        return keeper.sub


async def _item_times(
    maker: async_sessionmaker[AsyncSession], item_ids: list[uuid.UUID]
) -> list[object]:
    async with maker() as session:
        rows = [await session.get(MeetingAgendaItem, item_id) for item_id in item_ids]
        return [row.started_at if row is not None else None for row in rows]


async def test_a_move_to_a_top_records_its_time_once(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§000870: the first move to a TOP sets its time, and a move back keeps it."""
    s = await seed(maker, status="live", items=3)
    keeper = await _keeper_sub(maker, s.meeting_id)
    api.dependency_overrides[get_current_principal] = lambda: Principal(sub=keeper)
    try:
        with TestClient(api) as client:
            for item_id in (s.item_ids[0], s.item_ids[1]):
                moved = client.patch(
                    f"/api/meetings/{s.meeting_id}", json={"currentAgendaItemId": str(item_id)}
                )
                assert moved.status_code == 200, moved.text
            first, second, never = await _item_times(maker, s.item_ids)
            assert first is not None
            assert second is not None
            assert never is None
            back = client.patch(
                f"/api/meetings/{s.meeting_id}", json={"currentAgendaItemId": str(s.item_ids[0])}
            )
            assert back.status_code == 200, back.text
    finally:
        api.dependency_overrides[get_current_principal] = admin
    assert (await _item_times(maker, s.item_ids))[0] == first


async def test_a_planned_meeting_stamps_its_current_top_at_the_start(
    maker: async_sessionmaker[AsyncSession], api: FastAPI
) -> None:
    """§000870: a planned meeting records no time; the start stamps the current TOP."""
    s = await seed(maker, status="planned", items=2)
    async with maker() as session:
        meeting = await session.get(Meeting, s.meeting_id)
        assert meeting is not None
        meeting.current_agenda_item_id = s.item_ids[0]
        await session.commit()
    assert await _item_times(maker, s.item_ids) == [None, None]
    with TestClient(api) as client:
        started = client.patch(f"/api/meetings/{s.meeting_id}", json={"status": "live"})
        assert started.status_code == 200, started.text
    first, second = await _item_times(maker, s.item_ids)
    assert first is not None
    assert second is None
