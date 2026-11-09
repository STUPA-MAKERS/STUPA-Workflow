"""Unit tests for MeetingPresence: join, leave, dedupe, multi-tab."""

from __future__ import annotations

from uuid import uuid4

from app.modules.livevote.presence import MeetingPresence

MID = uuid4()


def test_join_and_leave_track_names() -> None:
    p = MeetingPresence()
    cid, _ = p.join(MID, "sub-a", "Alice")
    assert p.names(MID) == ["Alice"]
    p.join(MID, "sub-b", "Bob")
    assert p.names(MID) == ["Alice", "Bob"]
    assert [v.name for v in p.leave(MID, cid)] == ["Bob"]


def test_same_user_two_tabs_stays_until_last_leaves() -> None:
    """Keep a user with two tabs until the last tab leaves.

    The list holds one entry per user, and the second tab keeps the user in it.
    """
    p = MeetingPresence()
    c1, _ = p.join(MID, "sub-a", "Alice")
    c2, _ = p.join(MID, "sub-a", "Alice")
    assert p.names(MID) == ["Alice"]
    assert [v.name for v in p.leave(MID, c1)] == ["Alice"]
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


def test_viewers_carry_principal_id_and_name() -> None:
    """Keep the principal id next to the name, so the client can load the avatar (000574)."""
    p = MeetingPresence()
    pid = uuid4()
    _, viewers = p.join(MID, "sub-a", "Alice", pid)
    p.join(MID, "sub-b", "bob")
    assert [(v.id, v.name) for v in p.viewers(MID)] == [(pid, "Alice"), (None, "bob")]
    assert viewers[0].id == pid


def test_viewers_event_dumps_id_and_name() -> None:
    from app.modules.livevote.connection import _viewers_event
    from app.modules.livevote.presence import Viewer

    pid = uuid4()
    event = _viewers_event([Viewer(pid, "Alice"), Viewer(None, "Bob")]).dump()
    assert event == {
        "type": "viewers",
        "viewers": [{"id": str(pid), "name": "Alice"}, {"id": None, "name": "Bob"}],
    }
