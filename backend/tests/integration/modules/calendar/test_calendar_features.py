"""Integration (real Postgres): the Kalender leaves out the parts of a feature that is off.

§F/administration/admin/000758: the Kalender omits the meetings while `Sitzungen` is off
and the cards and the Events while `Boards` is off.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.site_config_service import SiteConfigService
from app.modules.calendar import service as feed
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.site_config.features import FeatureSwitches
from app.modules.site_config.models import SiteConfigVersion
from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_gremium, add_member, add_person

pytestmark = pytest.mark.integration

SPAN = {"from": "2031-05-01", "to": "2031-05-31"}


@pytest.fixture(autouse=True)
async def _no_site_config(maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    """Remove the site-config versions after a test, so no switch leaks."""
    yield
    async with maker() as session:
        await session.execute(delete(SiteConfigVersion))
        await session.commit()


async def _switch(maker: async_sessionmaker[AsyncSession], **switches: bool) -> None:
    async with maker() as session:
        await SiteConfigService(session).put_features(FeatureSwitches(**switches), "test")
        await session.commit()


def _kinds(client: TestClient, path: str, **params: Any) -> list[str]:
    resp = client.get(path, params=params)
    assert resp.status_code == 200, resp.text
    return sorted(entry["kind"] for entry in resp.json()["items"])


async def test_the_calendar_omits_the_entries_of_a_feature_that_is_off(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    anna, anna_id = await add_person(maker, "Anna")
    stupa, board = await add_gremium(maker, "StuPa")
    await add_member(maker, stupa, anna_id, "todo.write")
    async with maker() as session:
        await session.execute(
            update(Gremium).where(Gremium.id == stupa).values(protocols_public=True)
        )
        session.add(
            Meeting(
                gremium_id=stupa,
                title="Sitzung Mai",
                date=date(2031, 5, 6),
                start_time=time(18, 0),
                end_time=time(20, 0),
            )
        )
        await session.commit()
    with TestClient(api.app) as client:
        api.login(anna)
        cards = "/api/todos/cards"
        card = {"boardId": str(board), "title": "Bericht Mai", "dueDate": "2031-05-08"}
        assert client.post(cards, json=card).status_code == 201
        fest = client.post(cards, json={"boardId": str(board), "title": "Maifest"})
        assert fest.status_code == 201
        event = {"startsOn": "2031-05-30", "endsOn": "2031-05-30"}
        assert client.put(f"{cards}/{fest.json()['id']}/event", json=event).status_code == 200

        def seen() -> tuple[list[str], list[str], list[str]]:
            return (
                _kinds(client, "/api/calendar/entries", **SPAN),
                _kinds(client, "/api/calendar/search", q="Mai"),
                _kinds(client, "/api/public/calendar/entries", **SPAN),
            )

        every = ["card", "event", "meeting"]
        assert seen() == (every, every, ["meeting"])
        async with maker() as session:
            assert len(await feed.member_meetings(session, anna.sub)) == 1

        await _switch(maker, meetings=False)
        assert seen() == (["card", "event"], ["card", "event"], [])
        async with maker() as session:
            assert await feed.member_meetings(session, anna.sub) == []

        await _switch(maker, todos=False)
        assert seen() == (["meeting"], ["meeting"], ["meeting"])

        await _switch(maker)
        assert seen() == (every, every, ["meeting"])
