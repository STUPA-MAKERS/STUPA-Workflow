"""Unit tests without a DB: Gremium roles and memberships (#42).

The focus is the pure overlap invariant. Two terms of office must not overlap, and a
later term without an overlap stays allowed. The tests also cover the service branches:
a conflict on an overlap and a success on a gap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.admin.gremium_roles import GremiumRoleService, intervals_overlap
from app.modules.admin.models import GremiumMembership, GremiumRole
from app.modules.admin.schemas import GremiumMembershipCreate
from app.shared.errors import ConflictError, NotFoundError
from tests._support.auth_fakes import fake_session, result


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def test_overlap_basic_true() -> None:
    assert intervals_overlap(
        _dt("2026-01-01"), _dt("2026-06-01"), _dt("2026-03-01"), _dt("2026-09-01")
    )


def test_adjacent_intervals_do_not_overlap() -> None:
    # [Jan, Jun) and [Jun, Dec) touch, so they do not overlap (half-open intervals).
    assert not intervals_overlap(
        _dt("2026-01-01"), _dt("2026-06-01"), _dt("2026-06-01"), _dt("2026-12-01")
    )


def test_disjoint_intervals_do_not_overlap() -> None:
    assert not intervals_overlap(
        _dt("2026-01-01"), _dt("2026-03-01"), _dt("2026-06-01"), _dt("2026-09-01")
    )


def test_open_ended_overlaps_everything_after() -> None:
    # An open end (None) overlaps every later entry.
    assert intervals_overlap(_dt("2026-01-01"), None, _dt("2030-01-01"), None)


def test_open_start_overlaps_everything_before() -> None:
    assert intervals_overlap(None, _dt("2026-06-01"), _dt("2020-01-01"), _dt("2026-03-01"))


def test_two_open_intervals_always_overlap() -> None:
    assert intervals_overlap(None, None, None, None)


def _role(gremium_id=None) -> GremiumRole:
    r = GremiumRole(gremium_id=gremium_id or uuid4(), key="vorsitz", name_i18n={"de": "Vorsitz"})
    r.id = uuid4()
    return r


def _membership(pid, gid, frm, until) -> GremiumMembership:
    m = GremiumMembership(
        principal_id=pid, gremium_id=gid, gremium_role_id=uuid4(), valid_from=frm, valid_until=until
    )
    m.id = uuid4()
    return m


async def test_create_membership_rejects_overlap() -> None:
    pid, gid = uuid4(), uuid4()
    existing = _membership(pid, gid, _dt("2026-01-01"), _dt("2026-12-31"))
    # gets: the GremiumRole and the principal existence check. scalars: the memberships.
    db = fake_session(result(existing), gets=[_role(gid), object()])
    payload = GremiumMembershipCreate(
        principalId=pid, gremiumRoleId=uuid4(), validFrom="2026-06-01", validUntil="2026-09-01"
    )
    with pytest.raises(ConflictError):
        await GremiumRoleService(db).create_membership(gid, payload, "admin")


async def test_create_membership_unknown_principal_404() -> None:
    # An unknown principal_id gives a 404 instead of an FK IntegrityError on the commit.
    gid = uuid4()
    db = fake_session(gets=[_role(gid)])  # the second get (principal) returns None
    payload = GremiumMembershipCreate(principalId=uuid4(), gremiumRoleId=uuid4())
    with pytest.raises(NotFoundError):
        await GremiumRoleService(db).create_membership(gid, payload, "admin")


async def test_create_membership_allows_consecutive_term() -> None:
    pid, gid = uuid4(), uuid4()
    existing = _membership(pid, gid, _dt("2025-01-01"), _dt("2026-01-01"))
    db = fake_session(
        result(existing),  # existing memberships
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[_role(gid), object()],  # the role and the principal existence check
    )

    async def _flush_assign() -> None:  # the DB would set the PK, but the fake does not
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        db.flushed += 1

    db.flush = _flush_assign
    payload = GremiumMembershipCreate(
        principalId=pid, gremiumRoleId=uuid4(), validFrom="2026-01-01", validUntil="2027-01-01"
    )
    out = await GremiumRoleService(db).create_membership(gid, payload, "admin")
    assert out.valid_from is not None
    assert db.committed == 1


async def test_create_membership_db_constraint_overlap_409() -> None:
    # AUD-029: the row passes the Python fast-path check because no overlap is known.
    # A concurrent insert then fires the EXCLUDE constraint on the commit, which raises
    # IntegrityError. The service must translate that to ConflictError (409), not 500.
    pid, gid = uuid4(), uuid4()
    db = fake_session(
        result(),  # no existing membership, so the fast path finds no conflict
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[_role(gid), object()],
    )

    async def _flush_assign() -> None:
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        db.flushed += 1

    async def _raise_integrity() -> None:
        raise IntegrityError("INSERT", {}, Exception("ex_gremium_membership_no_overlap"))

    rollbacks = {"n": 0}

    async def _rollback() -> None:
        rollbacks["n"] += 1

    db.flush = _flush_assign
    db.commit = _raise_integrity
    db.rollback = _rollback
    payload = GremiumMembershipCreate(
        principalId=pid, gremiumRoleId=uuid4(), validFrom="2026-01-01", validUntil="2027-01-01"
    )
    with pytest.raises(ConflictError):
        await GremiumRoleService(db).create_membership(gid, payload, "admin")
    assert rollbacks["n"] == 1
