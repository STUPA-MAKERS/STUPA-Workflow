"""Shared fixtures of the unit tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meetings import present as present_mod
from app.modules.meetings.present import Present


@dataclass(slots=True)
class Presence:
    """The present count that each meeting of one test has; None reads no meeting."""

    here: Present | None = None


@pytest.fixture(autouse=True)
def presence(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Presence:
    """Stub the read of the present count, so a session fake needs no row for it.

    A test sets `presence.here` to give each meeting this count. A test of the read
    itself carries the marker `real_present` and reads through its own fake.
    """
    holder = Presence()
    if request.node.get_closest_marker("real_present") is not None:
        return holder

    async def _counts(_session: AsyncSession, meeting_ids: Sequence[UUID]) -> dict[UUID, Present]:
        return {} if holder.here is None else dict.fromkeys(meeting_ids, holder.here)

    monkeypatch.setattr(present_mod, "present_counts", _counts)
    return holder
