"""Worker tasks of the stored audit-chain check (Z6/O8).

The tests replace `AuditService.verify_and_store` and drive the tasks with a fake
sessionmaker. They pin down the cron schedule at 04:30, the trigger of each path,
the summary string and that a failed check after a restore only logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.audit.models import AuditVerification
from worker import audit_verify
from worker.main import WorkerSettings

_AT = datetime(2026, 10, 2, 2, 30, tzinfo=UTC)


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_exc: object) -> None: ...


class _Maker:
    def __init__(self) -> None:
        self.opened = 0

    def __call__(self) -> _Session:
        self.opened += 1
        return _Session()


def _row(*, valid: bool, trigger: str, by: str | None) -> AuditVerification:
    return AuditVerification(
        id=uuid.uuid4(),
        started_at=_AT,
        finished_at=_AT,
        valid=valid,
        checked=9 if valid else 3,
        broken_at=None if valid else 4,
        reason=None if valid else "hash_mismatch",
        trigger=trigger,
        triggered_by=by,
    )


class _Calls:
    """The recorded service calls, and the result that the next call gives."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []
        self.valid = True


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    """Replace the service call and record its arguments."""
    rec = _Calls()

    async def _verify_and_store(
        _self: object, *, trigger: str, triggered_by: str | None = None
    ) -> AuditVerification:
        rec.seen.append({"trigger": trigger, "triggered_by": triggered_by})
        return _row(valid=rec.valid, trigger=trigger, by=triggered_by)

    monkeypatch.setattr(
        audit_verify.AuditService, "verify_and_store", _verify_and_store
    )
    return rec


def test_cron_runs_at_four_thirty_independent_of_the_backup() -> None:
    jobs = [
        j for j in WorkerSettings.cron_jobs
        if j.coroutine is audit_verify.process_audit_verification
    ]
    assert len(jobs) == 1
    assert jobs[0].hour == 4
    assert jobs[0].minute == 30
    assert audit_verify.process_audit_verification in WorkerSettings.functions


async def test_cron_stores_a_check_with_trigger_cron(calls: _Calls) -> None:
    maker = _Maker()
    out = await audit_verify.process_audit_verification({"audit_sessionmaker": maker})
    assert out == "valid checked=9"
    assert calls.seen == [{"trigger": "cron", "triggered_by": None}]
    assert maker.opened == 1


async def test_cron_reports_a_broken_chain(calls: _Calls) -> None:
    calls.valid = False
    out = await audit_verify.process_audit_verification({"audit_sessionmaker": _Maker()})
    assert out == "broken checked=3 broken_at=4 reason=hash_mismatch"


async def test_cron_falls_back_to_the_app_sessionmaker(
    monkeypatch: pytest.MonkeyPatch, calls: _Calls
) -> None:
    maker = _Maker()
    monkeypatch.setattr(audit_verify, "get_sessionmaker", lambda: maker)
    assert await audit_verify.process_audit_verification({}) == "valid checked=9"
    assert maker.opened == 1


async def test_restore_check_carries_trigger_and_actor(calls: _Calls) -> None:
    out = await audit_verify.verify_after_restore(_Maker(), "admin-1")  # type: ignore[arg-type]
    assert out == "valid checked=9"
    assert calls.seen == [{"trigger": "restore", "triggered_by": "admin-1"}]


async def test_restore_check_failure_only_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """An old archive without the table must not turn a finished restore into a failure."""

    async def _boom(_self: object, **_kw: object) -> AuditVerification:
        raise RuntimeError('relation "audit_verification" does not exist')

    logged: list[str] = []
    monkeypatch.setattr(audit_verify.AuditService, "verify_and_store", _boom)
    # caplog misses the record when another test stops the logger propagation.
    monkeypatch.setattr(
        audit_verify.logger, "exception", lambda msg, *a: logged.append(msg % a)
    )
    assert await audit_verify.verify_after_restore(_Maker(), None) is None  # type: ignore[arg-type]
    assert logged == ["audit chain check after the restore failed"]
