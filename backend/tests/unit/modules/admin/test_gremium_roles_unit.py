"""Unit tests without a DB: Gremium roles and memberships.

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
from app.modules.admin.schemas import GremiumMembershipCreate, GremiumMembershipUpdate
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
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


# PATCH /admin/gremium-memberships/{id}: role change plus term change under the
# same overlap invariant as the create.


def _flush_with_ids(db) -> None:  # noqa: ANN001
    async def _flush_assign() -> None:
        for o in db.added:
            if getattr(o, "id", None) is None:
                o.id = uuid4()
        db.flushed += 1

    db.flush = _flush_assign


async def test_update_membership_not_found_404() -> None:
    db = fake_session()  # get() returns None
    with pytest.raises(NotFoundError):
        await GremiumRoleService(db).update_membership(
            uuid4(), GremiumMembershipUpdate(validFrom=None), "admin"
        )


async def test_update_membership_unknown_role_404() -> None:
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, None, None)
    db = fake_session(gets=[row, None])  # the membership, then no role
    with pytest.raises(NotFoundError):
        await GremiumRoleService(db).update_membership(
            row.id, GremiumMembershipUpdate(gremiumRoleId=uuid4()), "admin"
        )


async def test_update_membership_foreign_role_409() -> None:
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, None, None)
    db = fake_session(gets=[row, _role(uuid4())])  # role of ANOTHER gremium
    with pytest.raises(ConflictError):
        await GremiumRoleService(db).update_membership(
            row.id, GremiumMembershipUpdate(gremiumRoleId=uuid4()), "admin"
        )


async def test_update_membership_inverted_window_422() -> None:
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, None, None)
    db = fake_session(gets=[row])
    with pytest.raises(ValidationProblem):
        await GremiumRoleService(db).update_membership(
            row.id,
            GremiumMembershipUpdate(validFrom="2027-01-01", validUntil="2026-01-01"),
            "admin",
        )


async def test_update_membership_overlap_409() -> None:
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, _dt("2026-01-01"), _dt("2026-06-01"))
    other = _membership(pid, gid, _dt("2026-06-01"), _dt("2026-12-01"))
    db = fake_session(result(row, other), gets=[row])
    with pytest.raises(ConflictError):
        await GremiumRoleService(db).update_membership(
            row.id, GremiumMembershipUpdate(validUntil="2026-09-01"), "admin"
        )


async def test_update_membership_ignores_own_row_and_commits() -> None:
    # The row under edit must not conflict with itself, so the patch passes.
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, _dt("2026-01-01"), _dt("2026-06-01"))
    new_role = _role(gid)
    db = fake_session(
        result(row),  # only the row itself exists
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        gets=[row, new_role],
    )
    _flush_with_ids(db)
    out = await GremiumRoleService(db).update_membership(
        row.id,
        GremiumMembershipUpdate(gremiumRoleId=new_role.id, validUntil="2026-09-01"),
        "admin",
    )
    assert out.gremium_role_id == new_role.id
    assert out.valid_until is not None and out.valid_until.startswith("2026-09-01")
    assert row.valid_from == _dt("2026-01-01")  # untouched fields survive
    assert db.committed == 1


async def test_update_membership_clears_open_end() -> None:
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, _dt("2026-01-01"), _dt("2026-06-01"))
    db = fake_session(result(row), result(), result(), gets=[row])
    _flush_with_ids(db)
    out = await GremiumRoleService(db).update_membership(
        row.id, GremiumMembershipUpdate(validUntil=None), "admin"
    )
    assert out.valid_until is None and row.valid_until is None


async def test_update_membership_db_constraint_overlap_409() -> None:
    # The Python fast path sees no overlap. A concurrent write then fires the
    # EXCLUDE constraint on the flush, and that must give 409, not 500.
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, None, None)
    db = fake_session(result(row), gets=[row])
    rollbacks = {"n": 0}

    async def _raise_integrity() -> None:
        raise IntegrityError("UPDATE", {}, Exception("ex_gremium_membership_no_overlap"))

    async def _rollback() -> None:
        rollbacks["n"] += 1

    db.flush = _raise_integrity
    db.rollback = _rollback
    with pytest.raises(ConflictError):
        await GremiumRoleService(db).update_membership(
            row.id, GremiumMembershipUpdate(validFrom="2026-01-01"), "admin"
        )
    assert rollbacks["n"] == 1


def test_parse_dt_invalid_gives_422_not_500() -> None:
    from app.modules.admin.gremium_roles import _parse_dt

    assert _parse_dt(None) is None
    assert _parse_dt("") is None
    assert _parse_dt("2026-01-01") == _dt("2026-01-01")
    with pytest.raises(ValidationProblem) as ei:
        _parse_dt("not-a-date")
    assert ei.value.status == 422


async def test_update_membership_invalid_date_422() -> None:
    pid, gid = uuid4(), uuid4()
    row = _membership(pid, gid, None, None)
    db = fake_session(gets=[row])
    with pytest.raises(ValidationProblem):
        await GremiumRoleService(db).update_membership(
            row.id, GremiumMembershipUpdate(validFrom="not-a-date"), "admin"
        )
