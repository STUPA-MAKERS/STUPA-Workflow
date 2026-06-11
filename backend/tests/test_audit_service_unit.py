"""TDD: AuditService — append-only record, verify_chain, query (T-23).

Unit-Suite ohne DB: ``execute`` über Ergebnis-Queue-Fake (``tests.audit_fakes``);
der Advisory-Lock-Aufruf konsumiert das erste Ergebnis (no-op im Fake).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.audit.actions import AuditAction
from app.modules.audit.hashing import canonical_payload, compute_hash
from app.modules.audit.models import AuditEntry
from app.modules.audit.service import AuditService, record
from tests.audit_fakes import fake_session, result

_AT = datetime(2026, 6, 6, 12, 0, 0, tzinfo=UTC)


def _entry(
    entry_id: int,
    *,
    actor: str | None = None,
    action: str = "login",
    target_type: str | None = None,
    target_id: str | None = None,
    data: dict[str, object] | None = None,
    prev: bytes | None = None,
) -> AuditEntry:
    payload = data or {}
    canonical = canonical_payload(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        at=_AT,
        data=payload,
    )
    return AuditEntry(
        id=entry_id,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        at=_AT,
        data=payload,
        prev_hash=prev,
        hash=compute_hash(prev, canonical),
    )


# --------------------------------------------------------------------------- record
async def test_record_genesis_has_no_prev() -> None:
    db = fake_session(result(), result())  # lock + leere prev-Abfrage
    entry = await AuditService(db).record(
        actor="admin-1", action=AuditAction.LOGIN, at=_AT
    )
    assert entry.prev_hash is None
    expected = compute_hash(
        None,
        canonical_payload(
            actor="admin-1",
            action="login",
            target_type=None,
            target_id=None,
            at=_AT,
            data={},
        ),
    )
    assert entry.hash == expected
    assert db.added == [entry]
    assert db.flushed == 1


async def test_record_links_to_previous_hash() -> None:
    prev = b"\xaa" * 32
    db = fake_session(result(), result(prev))
    entry = await AuditService(db).record(
        actor=None,
        action="config_activation",
        target_type="flow_version",
        target_id="fv-1",
        data={"active": True},
        at=_AT,
    )
    assert entry.prev_hash == prev
    expected = compute_hash(
        prev,
        canonical_payload(
            actor=None,
            action="config_activation",
            target_type="flow_version",
            target_id="fv-1",
            at=_AT,
            data={"active": True},
        ),
    )
    assert entry.hash == expected


async def test_record_defaults_timestamp_when_absent() -> None:
    db = fake_session(result(), result())
    entry = await AuditService(db).record(actor="a", action="export")
    assert entry.at.tzinfo is not None
    assert entry.data == {}


async def test_record_hook_function() -> None:
    db = fake_session(result(), result())
    entry = await record(db, actor="a", action=AuditAction.EXPORT, target_id="x")
    assert entry.action == "export"
    assert entry.target_id == "x"
    assert db.added == [entry]


# ----------------------------------------------------------------- verify_chain
async def test_verify_chain_valid() -> None:
    e1 = _entry(1, actor="a", action="login")
    e2 = _entry(2, actor="b", action="export", prev=e1.hash)
    db = fake_session(result(e1, e2))
    res = await AuditService(db).verify_chain()
    assert res.valid is True
    assert res.checked == 2
    assert res.broken_at is None


async def test_verify_chain_empty_is_valid() -> None:
    db = fake_session(result())
    res = await AuditService(db).verify_chain()
    assert res.valid is True
    assert res.checked == 0


async def test_verify_chain_detects_tampered_field() -> None:
    e1 = _entry(1, action="login")
    e2 = _entry(2, action="export", prev=e1.hash)
    e2.data = {"tampered": True}  # Hash passt nicht mehr zu den Feldern
    db = fake_session(result(e1, e2))
    res = await AuditService(db).verify_chain()
    assert res.valid is False
    assert res.reason == "hash_mismatch"
    assert res.broken_at == 2
    assert res.checked == 1


async def test_verify_chain_detects_broken_link() -> None:
    e1 = _entry(1, action="login")
    e2 = _entry(2, action="export", prev=b"\x00" * 32)  # falscher prev_hash (Lücke)
    db = fake_session(result(e1, e2))
    res = await AuditService(db).verify_chain()
    assert res.valid is False
    assert res.reason == "prev_hash_mismatch"
    assert res.broken_at == 2


async def test_verify_chain_detects_tampered_genesis() -> None:
    e1 = _entry(1, action="login")
    e1.action = "role_change"  # Genesis-Feld verändert → Hash stimmt nicht
    db = fake_session(result(e1))
    res = await AuditService(db).verify_chain()
    assert res.valid is False
    assert res.reason == "hash_mismatch"
    assert res.broken_at == 1


# ------------------------------------------------------------------------ query
async def test_query_no_filters() -> None:
    rows = [_entry(2, action="export"), _entry(1, action="login")]
    db = fake_session(result(5), result(*rows))
    page = await AuditService(db).query(limit=10, offset=0)
    assert page.total == 5
    assert page.items == rows
    assert page.limit == 10


async def test_query_all_filters_applied() -> None:
    rows = [_entry(1, actor="a", action="login", target_type="t", target_id="i")]
    db = fake_session(result(1), result(*rows))
    page = await AuditService(db).query(
        action="login",
        actor="a",
        target_type="t",
        target_id="i",
        since=_AT,
        until=_AT,
        limit=50,
        offset=0,
    )
    assert page.total == 1
    assert page.items == rows
