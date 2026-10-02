"""Stored chain checks (Z6/O8): `verify_and_store`, the prune and the latest read.

The suite runs without a database. `stream_scalars` and `execute` read the prepared
results of `tests._support.audit_fakes` in order.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.audit import service as service_mod
from app.modules.audit.hashing import canonical_payload, compute_hash
from app.modules.audit.models import (
    MANUAL_VERIFICATION_COOLDOWN,
    VERIFICATION_KEEP,
    AuditEntry,
    AuditVerification,
)
from app.modules.audit.schemas import AuditVerificationOut
from app.modules.audit.service import AuditService
from app.shared.errors import ConflictError, RateLimitedError
from tests._support.audit_fakes import fake_session, result

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


class _Log:
    """Record the calls on the service logger.

    Another test can configure logging and stop the propagation to the root logger,
    so ``caplog`` is not reliable for the ``app.*`` loggers in the full suite.
    """

    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def info(self, msg: str, *args: Any) -> None:
        self.lines.append(("info", msg % args))

    def error(self, msg: str, *args: Any) -> None:
        self.lines.append(("error", msg % args))


@pytest.fixture
def log(monkeypatch: pytest.MonkeyPatch) -> _Log:
    rec = _Log()
    monkeypatch.setattr(service_mod, "logger", rec)
    return rec


def _entry(entry_id: int, *, prev: bytes | None = None) -> AuditEntry:
    canonical = canonical_payload(
        actor="a", action="login", target_type=None, target_id=None, at=_AT, data={}
    )
    return AuditEntry(
        id=entry_id,
        actor="a",
        action="login",
        target_type=None,
        target_id=None,
        at=_AT,
        data={},
        prev_hash=prev,
        hash=compute_hash(prev, canonical),
    )


async def test_verify_and_store_valid_chain(log: _Log) -> None:
    e1 = _entry(1)
    e2 = _entry(2, prev=e1.hash)
    # The first result answers the lock statement, the second feeds the stream.
    db = fake_session(result(None), result(e1, e2))

    row = await AuditService(db).verify_and_store(trigger="manual", triggered_by="admin-1")

    assert db.added == [row]
    assert row.valid is True
    assert row.checked == 2
    assert row.broken_at is None
    assert row.reason is None
    assert row.trigger == "manual"
    assert row.triggered_by == "admin-1"
    assert row.finished_at is not None
    assert row.started_at <= row.finished_at
    assert row.started_at.tzinfo is not None
    assert db.flushed == 1
    assert db.committed == 1
    # The lock and the prune run in the same transaction, before the commit.
    assert len(db.statements) == 2
    assert "pg_advisory_xact_lock" in str(db.statements[0])
    ((level, line),) = log.lines
    assert level == "info"
    assert "trigger=manual valid=True checked=2" in line
    assert "duration_ms=" in line


async def test_verify_and_store_broken_chain_logs_an_error(log: _Log) -> None:
    e1 = _entry(1)
    tampered = _entry(2, prev=b"\x00" * 32)
    db = fake_session(result(None), result(e1, tampered))

    row = await AuditService(db).verify_and_store(trigger="cron")

    assert row.valid is False
    assert row.checked == 1
    assert row.broken_at == 2
    assert row.reason == "prev_hash_mismatch"
    assert row.triggered_by is None
    ((level, line),) = log.lines
    assert level == "error"
    assert "reason=prev_hash_mismatch" in line


async def test_prune_deletes_past_the_newest_rows() -> None:
    db = fake_session()
    await AuditService(db).prune_verifications(keep=3)
    (stmt,) = db.statements
    sql = str(
        stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert sql.startswith("DELETE FROM audit_verification")
    assert "NOT IN" in sql
    assert "ORDER BY audit_verification.started_at DESC, audit_verification.id DESC" in sql
    assert "LIMIT 3" in sql
    # A failed check is never deleted.
    assert "audit_verification.valid IS true" in sql
    # The newest check of each trigger stays.
    assert "DISTINCT ON (audit_verification.trigger)" in sql


async def test_prune_default_keeps_one_hundred() -> None:
    assert VERIFICATION_KEEP == 100
    db = fake_session()
    await AuditService(db).prune_verifications()
    sql = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "LIMIT 100" in sql


async def test_latest_verification_returns_the_newest_row() -> None:
    row = AuditVerification(
        id=uuid.uuid4(),
        started_at=_AT,
        finished_at=_AT,
        valid=True,
        checked=5,
        trigger="cron",
    )
    db = fake_session(result(row))
    assert await AuditService(db).latest_verification() is row


async def test_latest_verification_none_before_the_first_check() -> None:
    assert await AuditService(fake_session()).latest_verification() is None


def test_verification_out_maps_the_row() -> None:
    rid = uuid.uuid4()
    row = AuditVerification(
        id=rid,
        started_at=_AT,
        finished_at=None,
        valid=False,
        checked=7,
        broken_at=8,
        reason="hash_mismatch",
        trigger="restore",
        triggered_by="admin-1",
    )
    out = AuditVerificationOut.from_row(row).model_dump(by_alias=True, mode="json")
    assert out == {
        "id": str(rid),
        "startedAt": "2026-06-06T12:00:00Z",
        "finishedAt": None,
        "valid": False,
        "checked": 7,
        "brokenAt": 8,
        "reason": "hash_mismatch",
        "trigger": "restore",
        "triggeredBy": "admin-1",
    }


async def test_manual_run_refuses_while_another_check_runs(log: _Log) -> None:
    db = fake_session(result(False))
    with pytest.raises(ConflictError) as exc:
        await AuditService(db).run_manual_verification(triggered_by="admin-1")
    assert exc.value.code == "audit_verify_running"
    assert "pg_try_advisory_xact_lock" in str(db.statements[0])
    assert db.added == []
    assert db.rolled_back == 1
    assert log.lines == []


async def test_manual_run_refuses_inside_the_cooldown(log: _Log) -> None:
    last = datetime.now(UTC) - timedelta(minutes=1)
    db = fake_session(result(True), result(last))
    with pytest.raises(RateLimitedError) as exc:
        await AuditService(db).run_manual_verification(triggered_by="admin-1")
    assert exc.value.code == "audit_verify_cooldown"
    assert exc.value.headers is not None
    retry_after = int(exc.value.headers["Retry-After"])
    assert 0 < retry_after <= int(MANUAL_VERIFICATION_COOLDOWN.total_seconds())
    assert db.added == []
    assert db.rolled_back == 1
    assert log.lines == []


async def test_manual_run_stores_a_check_after_the_cooldown(log: _Log) -> None:
    e1 = _entry(1)
    last = datetime.now(UTC) - MANUAL_VERIFICATION_COOLDOWN - timedelta(seconds=1)
    db = fake_session(result(True), result(last), result(e1))

    row = await AuditService(db).run_manual_verification(triggered_by="admin-1")

    assert db.added == [row]
    assert row.trigger == "manual"
    assert row.triggered_by == "admin-1"
    assert row.valid is True
    assert db.committed == 1
    assert db.rolled_back == 0
    # try-lock, the cooldown read and the prune. No second, blocking lock.
    assert len(db.statements) == 3
    assert not any("pg_advisory_xact_lock" in str(st) for st in db.statements)


async def test_manual_run_without_an_earlier_manual_check(log: _Log) -> None:
    db = fake_session(result(True), result(None), result())

    row = await AuditService(db).run_manual_verification(triggered_by="admin-1")

    assert row.trigger == "manual"
    assert row.checked == 0
