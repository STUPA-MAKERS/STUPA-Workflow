"""Unit tests for the pool seats in `delegations.pool_seat`.

A pool substitute votes for a missing member without a delegation. The fake
session answers `get`, `scalar` and `execute` from separate queues. The pool
read (`members_for_substitute`) and the global switch are replaced per test.
The integration suite runs the SQL against Postgres.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.delegations import pool_seat
from app.modules.delegations.models import MeetingDelegation
from tests._support.flow_fakes import fake_session, result

GREMIUM_ID = uuid4()
MEETING_ID = uuid4()
GROUP = str(GREMIUM_ID)


def _person(sub: str, name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), sub=sub, display_name=name)


def _meeting(status: str = "live", gremium_id: UUID = GREMIUM_ID) -> SimpleNamespace:
    return SimpleNamespace(id=MEETING_ID, status=status, gremium_id=gremium_id)


@pytest.fixture
def pool(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace the pool read."""
    state = SimpleNamespace(personal=set(), wide=False)

    async def _members(*_a: Any) -> tuple[set[UUID], bool]:
        return state.personal, state.wide

    monkeypatch.setattr(pool_seat, "members_for_substitute", _members)
    return state


def _db(
    deputy: Any,
    *executes: Any,
    meeting: Any = None,
) -> Any:
    """Queue the meeting, the substitute and the reads of `_find_seat`."""
    db = fake_session(*executes)
    db.get_results = [meeting or _meeting()]
    db.scalar_results = [deputy]
    return db


def _voters(*ids: UUID, perms: list[str] | None = None) -> Any:
    return result(*((i, perms if perms is not None else ["vote.cast"]) for i in ids))


async def test_clause_never_null() -> None:
    """The clause compares `created_by` NULL-safe, so its negation is safe."""
    delegate = aliased(PrincipalRow)
    sql = str(pool_seat.pool_seat_clause(delegate).compile(dialect=postgresql.dialect()))
    assert "IS NOT DISTINCT FROM" in sql
    assert "via_pool" in sql


async def test_no_meeting_or_free_group_has_no_seat(pool: SimpleNamespace) -> None:
    db = fake_session()
    assert await pool_seat.pool_seat_for(db, "x", None, GROUP) is None
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, "old-key") is None


@pytest.mark.parametrize(
    "meeting",
    [None, _meeting(status="planned"), _meeting(gremium_id=uuid4())],
)
async def test_meeting_not_live_gives_no_seat(pool: SimpleNamespace, meeting: Any) -> None:
    """Only a live meeting of the gremium of the vote has seats."""
    db = fake_session()
    db.get_results = [meeting]
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_unknown_substitute_has_no_seat(pool: SimpleNamespace) -> None:
    db = _db(None)
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_substitute_without_pool_entry_has_no_seat(pool: SimpleNamespace) -> None:
    db = _db(_person("x"))
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_personal_entry_takes_the_missing_member(pool: SimpleNamespace) -> None:
    """X stands in for A and B. B is present, so X takes the seat of A."""
    x, a, b = _person("x"), _person("a", "Anna"), _person("b", "Ben")
    pool.personal = {a.id, b.id}
    db = _db(x, result(), _voters(a.id, b.id), result(b.id), result(a))
    seat = await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP)
    assert seat is a


async def test_gremium_wide_entry_orders_personal_first_then_name(
    pool: SimpleNamespace,
) -> None:
    """A personal entry wins over the gremium-wide one, then the name orders."""
    x = _person("x")
    a, b, c = _person("a", "Zora"), _person("b", "anna"), _person("c", None)
    pool.personal = {a.id}
    pool.wide = True
    db = _db(x, result(), _voters(a.id, b.id, c.id), result(), result(c, b, a))
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is a


async def test_member_without_vote_cast_has_no_seat(pool: SimpleNamespace) -> None:
    x, a = _person("x"), _person("a")
    pool.personal = {a.id}
    db = _db(x, result(), _voters(a.id, perms=[]), result())
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_member_with_null_permissions_has_no_seat(pool: SimpleNamespace) -> None:
    x, a = _person("x"), _person("a")
    pool.personal = {a.id}
    db = _db(x, result(), result((a.id, None)), result())
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_substitute_never_takes_its_own_seat(pool: SimpleNamespace) -> None:
    """A substitute who is a member and in the gremium-wide pool skips itself."""
    x = _person("x")
    pool.wide = True
    db = _db(x, result(), _voters(x.id), result())
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_delegated_members_have_no_free_seat(pool: SimpleNamespace) -> None:
    """A member who gives or receives a delegation in the meeting has no free seat."""
    x, a, b, c = _person("x"), _person("a"), _person("b"), _person("c")
    pool.personal = {a.id, b.id}
    db = _db(x, result((a.id, c.id, True), (c.id, b.id, False)), _voters(a.id, b.id), result())
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_substitute_who_delegated_claims_nothing(pool: SimpleNamespace) -> None:
    """No chains: a substitute who delegated the own vote takes no seat."""
    x, a, c = _person("x"), _person("a"), _person("c")
    pool.personal = {a.id}
    db = _db(x, result((x.id, c.id, False)))
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_substitute_holds_at_most_one_seat(pool: SimpleNamespace) -> None:
    """A substitute with a voting delegation in the meeting takes no second seat."""
    x, a, b = _person("x"), _person("a"), _person("b")
    pool.personal = {a.id, b.id}
    db = _db(x, result((a.id, x.id, True)))
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is None


async def test_non_voting_delegation_to_substitute_leaves_a_seat(
    pool: SimpleNamespace,
) -> None:
    x, a, b = _person("x"), _person("a"), _person("b")
    pool.personal = {a.id, b.id}
    db = _db(x, result((a.id, x.id, False)), _voters(a.id, b.id), result(), result(b))
    assert await pool_seat.pool_seat_for(db, "x", MEETING_ID, GROUP) is b


async def test_claim_stores_the_seat_and_audits(pool: SimpleNamespace) -> None:
    """The claim locks, stores a pool seat row and writes `delegation_grant`."""
    x, a = _person("x"), _person("a")
    pool.personal = {a.id}
    db = _db(x, result(), result(), _voters(a.id), result(), result(a))
    assert await pool_seat.claim_pool_seat(db, "x", MEETING_ID, GROUP) == "a"
    assert "pg_advisory_xact_lock" in str(db.statements[0])
    row = next(o for o in db.added if isinstance(o, MeetingDelegation))
    assert row.delegator_principal_id == a.id
    assert row.delegate_principal_id == x.id
    assert (row.delegate_voting, row.via_pool, row.created_by) == (True, True, "x")
    audit = next(o for o in db.added if type(o).__name__ == "AuditEntry")
    assert audit.action == "delegation_grant"
    assert audit.data["poolSeat"] is True
    assert db.committed == 0


async def test_claim_without_seat_writes_nothing(pool: SimpleNamespace) -> None:
    db = _db(None, result())
    assert await pool_seat.claim_pool_seat(db, "x", MEETING_ID, GROUP) is None
    assert db.added == []


async def test_claim_without_meeting_takes_no_lock(pool: SimpleNamespace) -> None:
    db = fake_session()
    assert await pool_seat.claim_pool_seat(db, "x", None, GROUP) is None
    assert db.statements == []


async def test_release_frees_only_a_pool_seat() -> None:
    row = SimpleNamespace(id=uuid4())
    db = fake_session()
    db.scalar_results = [row]
    assert await pool_seat.release_pool_seat(db, MEETING_ID, uuid4(), "a") is True
    assert db.deleted == [row]
    audit = next(o for o in db.added if type(o).__name__ == "AuditEntry")
    assert audit.action == "delegation_revoke"
    assert audit.data["poolSeat"] is True


async def test_release_without_seat_changes_nothing() -> None:
    db = fake_session()
    assert await pool_seat.release_pool_seat(db, MEETING_ID, uuid4(), "a") is False
    assert db.deleted == []


async def test_release_of_sub() -> None:
    row = SimpleNamespace(id=uuid4())
    db = fake_session()
    db.scalar_results = [uuid4(), row]
    assert await pool_seat.release_pool_seat_of(db, MEETING_ID, "a") is True
    assert db.deleted == [row]


async def test_release_of_unknown_sub() -> None:
    db = fake_session()
    assert await pool_seat.release_pool_seat_of(db, MEETING_ID, "nobody") is False
