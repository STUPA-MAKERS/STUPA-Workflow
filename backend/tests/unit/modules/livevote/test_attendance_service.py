"""Unit-Tests AttendanceService: Anwesenheit ist nach dem Schließen eingefroren
(#attendance-lock) — das finalisierte Protokoll trägt die Listen, nachträgliche
Änderungen würden PDF und System auseinanderlaufen lassen."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.livevote.attendance_service import AttendanceService
from app.shared.errors import ConflictError
from tests._support.flow_fakes import fake_session, result


def _meeting(status: str = "closed") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), gremium_id=uuid4(), status=status)


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
