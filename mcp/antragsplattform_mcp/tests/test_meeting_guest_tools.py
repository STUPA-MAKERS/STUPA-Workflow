"""Tests for the guest tools of a public meeting (#17).

The tools only forward to the lead routes; no tool casts a ballot.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, meetings


class _FakeApi:
    """Record each call and answer with an empty object."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def get(self, path: str, **kw: Any) -> Any:
        self.calls.append(("GET", path, kw.get("json")))
        return []

    async def post(self, path: str, **kw: Any) -> Any:
        self.calls.append(("POST", path, kw.get("json")))
        return {}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_guest_lead_tools_forward_to_the_lead_routes(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.list_meeting_guests("m1"))
    asyncio.run(meetings.admit_meeting_guest("m1", "g1"))
    asyncio.run(meetings.reject_meeting_guest("m1", "g1"))
    asyncio.run(meetings.remove_meeting_guest("m1", "g1"))
    asyncio.run(meetings.rename_meeting_guest("m1", "g1", "Gast Name"))
    asyncio.run(meetings.admit_all_meeting_guests("m1"))
    asyncio.run(meetings.get_meeting_join_link("m1"))
    asyncio.run(meetings.rotate_meeting_join_code("m1"))
    assert fake_api.calls == [
        ("GET", "/meetings/m1/guests", None),
        ("POST", "/meetings/m1/guests/g1/admit", None),
        ("POST", "/meetings/m1/guests/g1/reject", None),
        ("POST", "/meetings/m1/guests/g1/remove", None),
        ("POST", "/meetings/m1/guests/g1/rename", {"displayName": "Gast Name"}),
        ("POST", "/meetings/m1/guests/admit-all", None),
        ("GET", "/meetings/m1/join-link", None),
        ("POST", "/meetings/m1/join-code/rotate", None),
    ]


def test_meeting_schemas_carry_the_public_fields() -> None:
    create = S.MeetingCreate(gremiumId="g", title="t", publicJoin=True, guestsMode="watch")
    assert S.dump_create(create)["guestsMode"] == "watch"
    patch = S.MeetingPatch(publicJoin=False)
    assert S.dump_patch(patch) == {"publicJoin": False}
    vote = S.MeetingVoteOpenBody(agendaItemId="i", guestsVote=False)
    assert S.dump_create(vote)["guestsVote"] is False


def test_no_tool_casts_a_ballot() -> None:
    names = [name for name in dir(meetings) if "ballot" in name or name.startswith("cast")]
    assert names == []
