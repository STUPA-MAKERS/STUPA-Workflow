"""Unit tests for AttendanceService.

The close of a meeting freezes the attendance (#attendance-lock). The final protocol
carries the lists. A later change makes the PDF and the system disagree.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.livevote import attendance_service as attendance_mod
from app.modules.livevote.attendance_service import AttendanceService
from app.shared.errors import ConflictError
from tests._support.flow_fakes import FakeSession, fake_session, result


def _meeting(status: str = "closed") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        gremium_id=uuid4(),
        status=status,
        date=None,
        start_time=None,
        started_at=None,
        closed_at=None,
    )


async def test_set_self_conflict_when_closed() -> None:
    meeting = _meeting("closed")
    db = fake_session(result(meeting))
    with pytest.raises(ConflictError):
        await AttendanceService(db).set_self(meeting.id, "present", "sub-1")
    assert db.committed == 0


async def test_set_for_conflict_when_closed() -> None:
    meeting = _meeting("closed")
    db = fake_session(result(meeting))
    with pytest.raises(ConflictError):
        await AttendanceService(db).set_for(meeting.id, uuid4(), "absent", "sub-1")
    assert db.committed == 0


# Z2, O15, O23, A7 and F12: the attendance rules.


def _member(sub: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), sub=sub, display_name=sub, email=f"{sub}@x")


def _row(principal_id: object, *, status: str, source: str, note: str | None = None) -> Any:
    return SimpleNamespace(principal_id=principal_id, status=status, source=source, note=note)


@pytest.fixture
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the audit writes. The real `record` would consume the fake results."""
    calls: list[dict[str, Any]] = []

    async def _record(_session: Any, **kw: Any) -> None:
        calls.append(kw)

    monkeypatch.setattr(attendance_mod, "audit_record", _record)
    return calls


async def test_set_self_conflict_when_lead_set_it(audit_calls: list[dict[str, Any]]) -> None:
    """O15: the record of the meeting lead wins over the own report."""
    meeting = _meeting("live")
    me = _member("me")
    row = _row(me.id, status="absent", source="lead")
    db = fake_session(result(meeting), result(me), result(row))
    with pytest.raises(ConflictError) as ei:
        await AttendanceService(db).set_self(meeting.id, "present", "me")
    assert ei.value.code == "attendance_set_by_lead"
    assert row.status == "absent"
    assert db.committed == 0


async def test_set_self_excused_with_note_and_no_audit(
    audit_calls: list[dict[str, Any]],
) -> None:
    meeting = _meeting("planned")
    me = _member("me")
    db = fake_session(result(meeting), result(me), result(), result(meeting), result(me))
    out = await AttendanceService(db).set_self(
        meeting.id, "excused", "me", note="ill", replace_note=True
    )
    [added] = db.added
    assert (added.status, added.source, added.note) == ("excused", "self", "ill")
    assert audit_calls == []  # the own report is not audited
    assert db.committed == 1
    assert out[0].principal_id == me.id


async def test_set_self_keeps_note_while_excused() -> None:
    meeting = _meeting("live")
    me = _member("me")
    row = _row(me.id, status="excused", source="self", note="ill")
    db = fake_session(result(meeting), result(me), result(row), result(meeting))
    await AttendanceService(db).set_self(meeting.id, "excused", "me")
    assert row.note == "ill"


async def test_set_self_present_drops_note() -> None:
    meeting = _meeting("live")
    me = _member("me")
    row = _row(me.id, status="excused", source="self", note="ill")
    db = fake_session(result(meeting), result(me), result(row), result(), result(meeting))
    await AttendanceService(db).set_self(meeting.id, "present", "me", note=None, replace_note=False)
    assert (row.status, row.note) == ("present", None)


async def test_set_self_present_conflict_with_delegation() -> None:
    """O23 also holds for the own report: a delegator cannot report "present"."""
    meeting = _meeting("live")
    me = _member("me")
    db = fake_session(result(meeting), result(me), result(), result(uuid4()))
    with pytest.raises(ConflictError) as ei:
        await AttendanceService(db).set_self(meeting.id, "present", "me")
    assert ei.value.code == "delegation_active"
    assert db.added == []
    assert db.committed == 0


async def test_set_self_excused_skips_the_delegation_check() -> None:
    """A delegator may still report the own excuse."""
    meeting = _meeting("live")
    me = _member("me")
    db = fake_session(result(meeting), result(me), result(), result(meeting))
    await AttendanceService(db).set_self(meeting.id, "excused", "me")
    [added] = db.added
    assert (added.status, added.source) == ("excused", "self")
    assert db.committed == 1


class _RacingSession(FakeSession):
    """A session whose flush fails as with a parallel first insert of the same record."""

    async def flush(self) -> None:
        raise IntegrityError("INSERT", {}, Exception("uq_attendance_meeting_principal"))


@pytest.mark.parametrize("lead", [False, True])
async def test_parallel_first_write_gives_conflict(
    audit_calls: list[dict[str, Any]], lead: bool
) -> None:
    """A lost race on the unique constraint gives 409, not 500, and no audit entry."""
    meeting = _meeting("live")
    me = _member("me")
    db = _RacingSession([result(meeting), result(me), result()])
    svc = AttendanceService(cast(Any, db))
    with pytest.raises(ConflictError) as ei:
        if lead:
            await svc.set_for(meeting.id, me.id, "absent", "lead")
        else:
            await svc.set_self(meeting.id, "excused", "me")
    assert ei.value.code == "conflict"
    assert db.rolled_back == 1
    assert db.committed == 0
    assert audit_calls == []


async def test_set_for_present_conflict_with_delegation(
    audit_calls: list[dict[str, Any]],
) -> None:
    """O23: no "present" while a delegation of the member exists."""
    meeting = _meeting("live")
    member = _member("a")
    db = fake_session(result(meeting), result(member), result(uuid4()))
    with pytest.raises(ConflictError) as ei:
        await AttendanceService(db).set_for(meeting.id, member.id, "present", "lead")
    assert ei.value.code == "delegation_active"
    assert db.added == []
    assert audit_calls == []


async def test_set_for_present_without_delegation_audits(
    audit_calls: list[dict[str, Any]],
) -> None:
    meeting = _meeting("live")
    member = _member("a")
    row = _row(member.id, status="excused", source="self", note="secret reason")
    db = fake_session(
        result(meeting),
        result(member),
        result(),  # no delegation
        result(row),
        result(meeting),
        result(member),
        result(row),
    )
    out = await AttendanceService(db).set_for(meeting.id, member.id, "present", "lead")
    assert (row.status, row.source, row.note) == ("present", "lead", None)
    [entry] = audit_calls
    assert entry["action"].value == "attendance_set"
    assert entry["actor"] == "lead"
    assert entry["target_type"] == "meeting"
    assert entry["target_id"] == str(meeting.id)
    assert entry["data"] == {
        "principalId": str(member.id),
        "status": {"from": "excused", "to": "present"},
        "source": {"from": "self", "to": "lead"},
    }
    assert "secret reason" not in repr(entry)
    assert out[0].note is None


async def test_set_for_excused_keeps_member_note(audit_calls: list[dict[str, Any]]) -> None:
    meeting = _meeting("live")
    member = _member("a")
    row = _row(member.id, status="excused", source="self", note="ill")
    db = fake_session(
        result(meeting), result(member), result(row), result(meeting), result(member), result(row)
    )
    out = await AttendanceService(db).set_for(meeting.id, member.id, "excused", "lead")
    assert (row.source, row.note) == ("lead", "ill")
    # The lead sees the note.
    assert out[0].note == "ill"
    assert "ill" not in repr(audit_calls)


async def test_set_for_new_record_audits_from_none(audit_calls: list[dict[str, Any]]) -> None:
    meeting = _meeting("planned")
    member = _member("a")
    db = fake_session(result(meeting), result(member), result(), result(meeting))
    await AttendanceService(db).set_for(
        meeting.id, member.id, "excused", "lead", note="travel", replace_note=True
    )
    [added] = db.added
    assert (added.status, added.source, added.note) == ("excused", "lead", "travel")
    assert audit_calls[0]["data"]["status"] == {"from": None, "to": "excused"}
    assert audit_calls[0]["data"]["source"] == {"from": None, "to": "lead"}


async def test_reset_deletes_record_and_audits(audit_calls: list[dict[str, Any]]) -> None:
    meeting = _meeting("live")
    pid = uuid4()
    row = _row(pid, status="absent", source="lead")
    db = fake_session(result(meeting), result(row), result(meeting))
    await AttendanceService(db).reset(meeting.id, pid, "lead")
    assert db.deleted == [row]
    assert db.committed == 1
    [entry] = audit_calls
    assert entry["action"].value == "attendance_reset"
    assert entry["data"] == {
        "principalId": str(pid),
        "status": {"from": "absent", "to": None},
        "source": {"from": "lead", "to": None},
    }


async def test_reset_without_record_is_a_no_op(audit_calls: list[dict[str, Any]]) -> None:
    meeting = _meeting("live")
    db = fake_session(result(meeting), result(), result(meeting))
    await AttendanceService(db).reset(meeting.id, uuid4(), "lead")
    assert db.deleted == []
    assert db.committed == 0
    assert audit_calls == []


async def test_reset_conflict_when_closed() -> None:
    meeting = _meeting("closed")
    db = fake_session(result(meeting))
    with pytest.raises(ConflictError):
        await AttendanceService(db).reset(meeting.id, uuid4(), "lead")


async def test_roster_note_only_for_self_and_lead() -> None:
    """A7: the reason of an excuse is personal data."""
    meeting = _meeting("live")
    me, other = _member("me"), _member("other")
    rows = [
        _row(me.id, status="excused", source="self", note="mine"),
        _row(other.id, status="excused", source="self", note="theirs"),
    ]

    async def roster(*, can_write: bool) -> dict[str, str | None]:
        db = fake_session(result(meeting), result(me, other), result(*rows))
        out = await AttendanceService(db).roster(meeting.id, "me", can_write=can_write)
        return {o.display_name or "": o.note for o in out}

    assert await roster(can_write=False) == {"me": "mine", "other": None}
    assert await roster(can_write=True) == {"me": "mine", "other": "theirs"}


async def test_roster_marks_the_vote_and_the_keeper_right() -> None:
    """O6 and O20: the flags come from the union of the active gremium roles."""
    meeting = _meeting("live")
    voter, keeper, both, former = _member("v"), _member("k"), _member("b"), _member("f")
    perms = result(
        (voter.id, ["vote.cast"]),
        (keeper.id, ["protocol.write"]),
        # Two memberships: one role gives the vote, the other the minutes.
        (both.id, ["vote.cast"]),
        (both.id, None),
        (both.id, ["protocol.write"]),
    )
    db = fake_session(result(meeting), result(voter, keeper, both, former), result(), perms)
    out = await AttendanceService(db).roster(meeting.id, "nobody")
    flags = {o.display_name: (o.can_vote, o.can_keep_protocol) for o in out}
    assert flags == {
        "v": (True, False),
        "k": (False, True),
        "b": (True, True),
        "f": (False, False),
    }
