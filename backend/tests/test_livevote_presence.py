"""Unit-Tests MeetingPresence (#live-viewers): Join/Leave, Dedupe, Multi-Tab."""

from __future__ import annotations

from uuid import uuid4

from app.modules.livevote.presence import MeetingPresence

MID = uuid4()


def test_join_and_leave_track_names() -> None:
    p = MeetingPresence()
    cid, names = p.join(MID, "sub-a", "Alice")
    assert names == ["Alice"]
    _, names = p.join(MID, "sub-b", "Bob")
    assert names == ["Alice", "Bob"]
    assert p.leave(MID, cid) == ["Bob"]


def test_same_user_two_tabs_stays_until_last_leaves() -> None:
    p = MeetingPresence()
    c1, _ = p.join(MID, "sub-a", "Alice")
    c2, names = p.join(MID, "sub-a", "Alice")
    assert names == ["Alice"]  # dedupliziert je Nutzer
    assert p.leave(MID, c1) == ["Alice"]  # Tab 2 hält sie in der Liste
    assert p.leave(MID, c2) == []


def test_meetings_are_isolated() -> None:
    p = MeetingPresence()
    other = uuid4()
    p.join(MID, "sub-a", "Alice")
    assert p.names(other) == []


def test_names_sorted_case_insensitive() -> None:
    p = MeetingPresence()
    p.join(MID, "s1", "zoe")
    p.join(MID, "s2", "Anna")
    assert p.names(MID) == ["Anna", "zoe"]
