"""Unit: a job of a feature that is off does nothing.

§F/administration/admin/000757: the worker does not run the jobs of a feature that is
off and does not send its mails.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.site_config.features import Feature, FeatureSwitches
from worker.calendars import fetch_external_calendars
from worker.deadlines import _process_votes
from worker.features import job_feature_on
from worker.polls import process_poll_reminders
from worker.protocol import heal_public_protocols
from worker.todos import archive_done_todos, process_todo_due

#: A time after the hour of the due reminder in Berlin.
NOON = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@asynccontextmanager
async def _no_queries() -> AsyncGenerator[None]:
    """Stand in for a session without one: a job that goes on to query fails the test."""
    yield None


class _Maker:
    """Count the sessions that a job opens."""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> AbstractAsyncContextManager[None]:
        self.opened += 1
        return _no_queries()


def _off(monkeypatch: pytest.MonkeyPatch, feature: Feature) -> None:
    async def read(_session: object) -> FeatureSwitches:
        return FeatureSwitches(**{feature.value: False})

    monkeypatch.setattr("app.modules.site_config.features.active_switches", read)


async def test_the_switch_is_read_in_its_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    maker = _Maker()
    assert await job_feature_on(maker, Feature.TODOS) is True  # type: ignore[arg-type]
    _off(monkeypatch, Feature.TODOS)
    assert await job_feature_on(maker, Feature.TODOS) is False  # type: ignore[arg-type]
    assert maker.opened == 2


@pytest.mark.parametrize(
    ("feature", "job", "result"),
    [
        (Feature.TODOS, lambda ctx: archive_done_todos(ctx, NOON), 0),
        (Feature.TODOS, lambda ctx: process_todo_due(ctx, NOON), 0),
        (Feature.CALENDAR, lambda ctx: fetch_external_calendars(ctx, NOON), 0),
        (Feature.VOTING, lambda ctx: process_poll_reminders(ctx, NOON), 0),
        (Feature.VOTING, lambda ctx: _process_votes(ctx, NOON), 0),
        (Feature.MEETINGS, heal_public_protocols, "off"),
    ],
)
async def test_a_job_of_a_feature_that_is_off_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
    feature: Feature,
    job: Callable[[dict[str, Any]], Awaitable[object]],
    result: object,
) -> None:
    _off(monkeypatch, feature)
    maker = _Maker()
    keys = ("todos", "calendars", "polls", "protocol", "deadlines")
    ctx: dict[str, Any] = {
        **{f"{key}_sessionmaker": maker for key in keys},
        "sessionmaker": maker,
        "settings": object(),
        "calendars_fetcher": object(),
    }
    assert await job(ctx) == result
    assert maker.opened == 1
