"""Tests for the personnel election tools and the election form of the vote open body."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from antragsplattform_mcp import schemas as S
from antragsplattform_mcp.tools import _common, meetings


class _FakeApi:
    """Record each POST and answer with an empty vote."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    async def post(self, path: str, **kw: Any) -> dict[str, Any]:
        self.calls.append(("POST", path, kw.get("json")))
        return {}


@pytest.fixture
def fake_api(monkeypatch: pytest.MonkeyPatch) -> _FakeApi:
    fake = _FakeApi()
    monkeypatch.setattr(_common, "_client", fake)
    return fake


def test_draw_lot(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.vote_draw_lot("v1"))
    assert fake_api.calls == [("POST", "/votes/v1/draw-lot", None)]


def test_runoff(fake_api: _FakeApi) -> None:
    asyncio.run(meetings.vote_runoff("v1"))
    assert fake_api.calls == [("POST", "/votes/v1/runoff", None)]


def test_create_meeting_election(fake_api: _FakeApi) -> None:
    body = S.MeetingVoteOpenBody(
        agendaItemId="a1",
        kind="election",
        question="Wahl der Sitzungsleitung",
        seats=1,
        candidates=[
            S.ElectionCandidateIn(name="Anna", principalId="p1"),
            S.ElectionCandidateIn(name="Ben"),
        ],
    )
    asyncio.run(meetings.create_meeting_vote("m1", body))
    [(_, path, sent)] = fake_api.calls
    assert path == "/meetings/m1/votes"
    assert sent["kind"] == "election"
    assert sent["seats"] == 1
    assert sent["candidates"] == [{"name": "Anna", "principalId": "p1"}, {"name": "Ben"}]
    # No secret switch: the server default applies (on for an election).
    assert "secret" not in sent


def test_motion_body_keeps_the_motion_defaults() -> None:
    sent = S.dump_create(S.MeetingVoteOpenBody(agendaItemId="a1"))
    assert sent["kind"] == "motion"
    assert "secret" not in sent
