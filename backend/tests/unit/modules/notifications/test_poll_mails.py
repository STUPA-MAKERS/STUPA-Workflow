"""The poll mails ``poll_started`` and ``poll_reminder`` (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.modules.notifications import polls
from app.modules.notifications.links import vote_link
from app.modules.voting.models import Vote
from app.settings import load_settings
from tests.unit.modules.todos.fakes import ScriptedSession

SETTINGS = load_settings()
NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
GID = uuid4()


def _poll(**over: Any) -> Vote:
    data: dict[str, Any] = {
        "id": uuid4(),
        "kind": "poll",
        "meeting_id": None,
        "eligible_group": str(GID),
        "question": "Wohin?",
        "status": "open",
        "closes_at": datetime(2026, 10, 30, 11, 0, tzinfo=UTC),
    }
    data.update(over)
    return Vote(**data)


class _Mails:
    calls: list[dict[str, Any]] = []
    result = True

    def __init__(self, _session: Any, *, queue: Any, settings: Any) -> None:
        self.queue = queue

    async def send_kind_mail(self, recipients: list[str], **kw: Any) -> bool:
        _Mails.calls.append({"recipients": recipients, **kw})
        return _Mails.result


@pytest.fixture(autouse=True)
def mails(monkeypatch: pytest.MonkeyPatch) -> type[_Mails]:
    _Mails.calls = []
    _Mails.result = True
    monkeypatch.setattr(polls, "NotificationService", _Mails)
    return _Mails


def _members() -> list[tuple[str, str, list[str] | None]]:
    return [
        ("a", "a@example.org", ["vote.cast"]),
        ("b", "b@example.org", ["vote.cast", "vote.read"]),
        ("c", "c@example.org", ["vote.read"]),
        ("d", "", ["vote.cast"]),
        ("a", "a@example.org", None),
    ]


def test_end_text_and_link() -> None:
    assert polls._end_text(None, SETTINGS) == ""
    assert polls._end_text(datetime(2026, 10, 30, 11, 0, tzinfo=UTC), SETTINGS) == (
        "30.10.2026, 12:00"
    )
    link = vote_link(SETTINGS, "abc")
    assert link.url.endswith("/voting/abc")
    assert link.target == "poll"


async def test_eligible_members_keeps_the_voters_with_an_address() -> None:
    session = ScriptedSession(execute=[_members()])
    out = await polls.eligible_members(session, GID, NOW)  # type: ignore[arg-type]
    assert out == [("a", "a@example.org"), ("b", "b@example.org")]


async def test_start_mail_goes_to_every_voter(mails: type[_Mails]) -> None:
    vote = _poll()
    session = ScriptedSession(execute=[_members()], scalar=["StuPa"])
    sent = await polls.send_poll_mail(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        vote=vote,
        now=NOW,
        reminder=False,
    )
    assert sent is True
    # One mail per member: no recipient sees the others.
    assert [c["recipients"] for c in mails.calls] == [["a@example.org"], ["b@example.org"]]
    assert [c["idempotency_parts"] for c in mails.calls] == [
        ("poll_started", str(vote.id), "a"),
        ("poll_started", str(vote.id), "b"),
    ]
    call = mails.calls[0]
    assert call["kind"] == "poll_started"
    assert call["context"] == {
        "question": "Wohin?",
        "gremiumName": "StuPa",
        "closesAt": "30.10.2026, 12:00",
    }
    assert call["builtin_subject"] is polls.POLL_STARTED_SUBJECT


async def test_reminder_skips_the_members_who_answered(mails: type[_Mails]) -> None:
    vote = _poll(question=None)
    session = ScriptedSession(execute=[_members()], scalars=[["a"], []], scalar=[None])
    sent = await polls.send_poll_mail(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        vote=vote,
        now=NOW,
        reminder=True,
    )
    assert sent is True
    [call] = mails.calls
    assert call["recipients"] == ["b@example.org"]
    assert call["idempotency_parts"] == ("poll_reminder", str(vote.id), "b")
    assert call["kind"] == "poll_reminder"
    assert call["context"]["question"] == ""
    assert call["context"]["gremiumName"] == ""


async def test_reminder_without_anybody_left_sends_nothing(mails: type[_Mails]) -> None:
    session = ScriptedSession(execute=[_members()], scalars=[["a"], ["b"]])
    sent = await polls.send_poll_mail(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        vote=_poll(),
        now=NOW,
        reminder=True,
    )
    assert sent is False
    assert mails.calls == []


async def test_no_mail_when_every_member_opted_out(mails: type[_Mails]) -> None:
    mails.result = False
    session = ScriptedSession(execute=[_members()], scalar=["StuPa"])
    sent = await polls.send_poll_mail(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        vote=_poll(),
        now=NOW,
        reminder=False,
    )
    assert sent is False
    assert len(mails.calls) == 2


@pytest.mark.parametrize("over", [{"meeting_id": uuid4()}, {"kind": "motion"}])
async def test_no_mail_for_a_meeting_poll_or_a_motion(
    mails: type[_Mails], over: dict[str, Any]
) -> None:
    session = ScriptedSession()
    sent = await polls.send_poll_mail(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        vote=_poll(**over),
        now=NOW,
        reminder=False,
    )
    assert sent is False
    assert session.statements == []


class _Maker:
    def __init__(self, session: ScriptedSession) -> None:
        self.session = session

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> ScriptedSession:
        return self.session

    async def __aexit__(self, *_a: object) -> None:
        return None


async def test_notify_started_sends_for_an_open_poll(mails: type[_Mails]) -> None:
    vote = _poll()
    session = ScriptedSession(execute=[_members()], scalar=["StuPa"])
    session.put(vote)
    sent = await polls.notify_poll_started(
        SETTINGS,
        vote.id,
        None,
        now=NOW,
        sessionmaker=_Maker(session),  # type: ignore[arg-type]
    )
    assert sent is True
    assert len(mails.calls) == 2


@pytest.mark.parametrize("status", ["draft", None])
async def test_notify_started_skips_a_missing_or_closed_poll(
    mails: type[_Mails], status: str | None
) -> None:
    session = ScriptedSession()
    vote = _poll(status=status or "open")
    if status is not None:
        session.put(vote)
    sent = await polls.notify_poll_started(
        SETTINGS,
        vote.id,
        object(),
        now=NOW,
        sessionmaker=_Maker(session),  # type: ignore[arg-type]
    )
    assert sent is False
    assert mails.calls == []


async def test_notify_started_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken() -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(polls, "get_sessionmaker", _broken)
    assert await polls.notify_poll_started(SETTINGS, uuid4(), None, now=NOW) is False


def test_maker_default(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    monkeypatch.setattr(polls, "get_sessionmaker", lambda: marker)
    assert polls._maker(None) is marker
    assert polls._end_text(NOW + timedelta(hours=1), SETTINGS) == "01.10.2026, 13:00"
