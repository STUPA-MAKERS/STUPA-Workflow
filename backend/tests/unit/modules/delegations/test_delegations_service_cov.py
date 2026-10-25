"""Extra coverage for `DelegationService`.

These tests add the branches that `test_delegations_service_unit.py` leaves open.
They cover `_independently_eligible` for direct, OIDC and group-mapping sources.
They cover the empty case of `_names`, the 404 of `_gremium`, and `_direction` for a
missing or uninvolved caller.
They cover two special branches in `create`. A meeting without a date skips the
deadline check. A second non-voting delegation to the same person lets the loop
continue.
They cover the admin view of `list` and the full `meeting_context` with and without a
principal. They cover `recipients` with external search and needle filter.
They cover `vote_status` for every verdict branch.
Last, they cover the pool paths: the admin bypass of `_require_pool_manage`, the
member 404, and a duplicate with a member.

Like the existing suite, these tests use no real database. The `execute` and `get`
queues of the `flow_fakes` fake hit every branch deterministically.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.delegations.models import DelegationSubstitute
from app.modules.delegations.schemas import (
    DelegationCreate,
    DelegationOut,
    MeetingDelegationContext,
    RecipientOut,
    SubstituteCreate,
    VoteDelegationStatus,
)
from app.modules.delegations.service import (
    DelegationService,
    _independently_eligible,
    _membership_with_vote_cast,
    meeting_start_utc,
    voting_delegation_check,
)
from app.settings import load_settings
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationProblem,
)
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
GREMIUM_ID = uuid4()
MEETING_ID = uuid4()
VOTE_ID = uuid4()
FUTURE_DATE = (datetime.now(UTC) + timedelta(days=30)).date()


def _settings(*, voting: bool = False) -> Any:
    return load_settings(delegation_voting_enabled=voting)


def _svc(db: Any, *, voting: bool = False) -> DelegationService:
    return DelegationService(db, _settings(voting=voting))


def _actor(sub: str = "deleg", perms: set[str] | None = None) -> Principal:
    return Principal(sub=sub, roles=["member"], permissions=perms or set())


def _meeting(
    *,
    status: str = "planned",
    meeting_date: date | None = None,
    start_time: time | None = time(18, 0),
    dated: bool = True,
) -> SimpleNamespace:
    if meeting_date is None and dated:
        meeting_date = FUTURE_DATE
    return SimpleNamespace(
        id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        title="Sitzung",
        date=meeting_date,
        start_time=start_time,
        status=status,
    )


def _gremium(
    *,
    allow: bool = True,
    lead: int = 0,
    external: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=GREMIUM_ID,
        name="StuPa",
        allow_vote_delegation=allow,
        delegation_lead_minutes=lead,
        delegation_allow_external=external,
    )


def _me(sub: str = "deleg") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), sub=sub)


def _names(*rows: tuple[Any, str | None, str | None]) -> Any:
    return result(*rows)


def _membership(gremium_id: Any = GREMIUM_ID) -> Any:
    """Build the first query result of `_assert_can_view_gremium`.

    That query reads `gremium_member_ids`. `active_gremium_roles` returns
    `(gremium_id, role)` pairs. One matching row makes the view check pass at once,
    because the caller is a member of the Gremium.
    """
    return result((gremium_id, SimpleNamespace(permissions=[])))


def test_meeting_start_utc_none_without_date() -> None:
    assert meeting_start_utc(_meeting(dated=False), "Europe/Berlin") is None  # type: ignore[arg-type]


def test_meeting_start_utc_converts() -> None:
    m = _meeting(meeting_date=date(2026, 6, 20), start_time=time(18, 0))
    assert meeting_start_utc(m, "Europe/Berlin") == datetime(2026, 6, 20, 16, 0, tzinfo=UTC)  # type: ignore[arg-type]


async def test_voting_check_no_meeting() -> None:
    db = fake_session()
    assert await voting_delegation_check(db, "me", None, str(GREMIUM_ID), NOW) == (False, None)
    assert db.statements == []


async def test_voting_check_bad_group() -> None:
    db = fake_session()
    assert await voting_delegation_check(db, "me", MEETING_ID, "nope", NOW) == (False, None)


async def test_voting_check_outgoing_blocked() -> None:
    db = fake_session(result((True, True, "me")))
    assert await voting_delegation_check(db, "me", MEETING_ID, str(GREMIUM_ID), NOW) == (True, None)


async def test_voting_check_incoming_carries_delegator_sub() -> None:
    db = fake_session(result((False, True, "deg")))
    assert await voting_delegation_check(db, "me", MEETING_ID, str(GREMIUM_ID), NOW) == (
        False,
        "deg",
    )


async def test_voting_check_nonvoting_neutral() -> None:
    db = fake_session(result((True, False, "me"), (False, False, "x")))
    assert await voting_delegation_check(db, "me", MEETING_ID, str(GREMIUM_ID), NOW) == (
        False,
        None,
    )


async def test_meeting_not_found_raises() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="meeting"):
        await _svc(db)._meeting(MEETING_ID)


async def test_membership_vote_cast_handles_none_perms() -> None:
    """Ignore a role without permissions (None) without a crash."""
    db = fake_session(result(None, ["other"]))
    assert await _membership_with_vote_cast(db, uuid4(), GREMIUM_ID, NOW) is False


async def test_membership_vote_cast_true() -> None:
    db = fake_session(result(["vote.cast"]))
    assert await _membership_with_vote_cast(db, uuid4(), GREMIUM_ID, NOW) is True


async def test_eligible_via_membership_vote_cast() -> None:
    """Accept a membership with `vote.cast` without a further query."""
    db = fake_session(result(["vote.cast"]))
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is True


async def test_eligible_needs_a_vote_cast_membership() -> None:
    """Give the voting right only through a membership with `vote.cast`.

    A global role, a raw OIDC group or a global group mapping never gives the voting right
    in a Gremium. Only the membership query runs.
    """
    db = fake_session(result(), result(SimpleNamespace(id=uuid4())), result(([str(GREMIUM_ID)],)))
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is False
    assert len(db.statements) == 1


async def test_names_empty_set_returns_empty_dict() -> None:
    """Return an empty dict for an empty set without a query."""
    db = fake_session()
    svc = _svc(db)
    assert await svc._names(set()) == {}
    assert db.statements == []


async def test_gremium_not_found_raises() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="gremium"):
        await _svc(db)._gremium(GREMIUM_ID)


def test_direction_none_when_me_id_missing() -> None:
    d = SimpleNamespace(delegator_principal_id=uuid4(), delegate_principal_id=uuid4())
    assert DelegationService._direction(d, None) is None  # type: ignore[arg-type]


def test_direction_none_when_unrelated() -> None:
    d = SimpleNamespace(delegator_principal_id=uuid4(), delegate_principal_id=uuid4())
    assert DelegationService._direction(d, uuid4()) is None  # type: ignore[arg-type]


def test_direction_incoming_and_outgoing() -> None:
    me = uuid4()
    outgoing = SimpleNamespace(delegator_principal_id=me, delegate_principal_id=uuid4())
    incoming = SimpleNamespace(delegator_principal_id=uuid4(), delegate_principal_id=me)
    assert DelegationService._direction(outgoing, me) == "outgoing"  # type: ignore[arg-type]
    assert DelegationService._direction(incoming, me) == "incoming"  # type: ignore[arg-type]


def _create_db(
    *,
    meeting: SimpleNamespace,
    gremium: SimpleNamespace,
    me: SimpleNamespace,
    delegate: SimpleNamespace,
    pool_ids: list[Any],
    member_ids: list[Any],
    existing: list[tuple[Any, Any, bool]],
) -> Any:
    """Script the fake session for a create.

    The results, in order: the caller row, the delegate row, the eligibility (membership),
    the pool, the members, the create advisory lock (per meeting), the existing rows, the
    audit lock and the audit predecessor.
    """
    db = fake_session(
        result(me),
        result(delegate),
        result(["vote.cast"]),
        result(*pool_ids),
        result(*member_ids),
        result(),
        result(*existing),
        result(),
        result(),
        _names((me.id, "Me", None), (delegate.id, "Other", None)),
    )
    db.get_results = [meeting, gremium]
    return db


async def test_create_undated_meeting_skips_deadline() -> None:
    """Skip the deadline check for a meeting without a date (start None)."""
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(dated=False),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[],
    )
    out = await _svc(db).create(
        DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
    )
    assert out.meeting_date is None
    assert out.via_pool is False
    assert db.committed == 1


async def test_create_me_principal_missing_403() -> None:
    """Refuse a caller without a principal row with 403."""
    db = fake_session(result())
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="Delegator principal not found"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_nonvoting_existing_to_same_recipient_does_not_conflict() -> None:
    """Allow a non-voting delegation next to another non-voting row to the same person.

    The existing row of another delegator gives no 409. The loop continues and the service
    creates the new non-voting delegation.
    """
    me, delegate = _me(), _me("other")
    existing_row = (uuid4(), delegate.id, False)
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[existing_row],
    )
    out = await _svc(db).create(
        DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
    )
    assert out.delegate_voting is False
    assert db.committed == 1


async def test_create_voting_existing_other_recipient_no_conflict() -> None:
    """Allow a voting delegation while another voting row goes to somebody else.

    `payload.delegate_voting` is True and a voting row exists, but for another person, so
    there is no 409.
    """
    me, delegate = _me(), _me("other")
    existing_row = (uuid4(), uuid4(), True)
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[existing_row],
    )
    out = await _svc(db, voting=True).create(
        DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id, delegateVoting=True),
        _actor(),
    )
    assert out.delegate_voting is True
    assert db.committed == 1


def _joined_row(me_id: Any, *, outgoing: bool = True) -> tuple[Any, Any, Any]:
    d = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=me_id if outgoing else uuid4(),
        delegate_principal_id=uuid4() if outgoing else me_id,
        delegate_voting=True,
        via_pool=False,
        created_at=NOW,
    )
    return (d, _meeting(), _gremium())


async def test_list_admin_sees_all_with_meeting_filter() -> None:
    """Let an admin list all delegations with the meeting filter.

    The admin has no own-rows filter. The fake session returns the caller, who is still
    resolved for the direction, and the joined row. The caller is not involved, so the
    direction is None.
    """
    foreign = uuid4()
    row = _joined_row(foreign, outgoing=True)
    db = fake_session(
        result(_me()),
        result(row),
        _names(
            (row[0].delegator_principal_id, "X", None),
            (row[0].delegate_principal_id, "Y", None),
        ),
    )
    out = await _svc(db).list(_actor(perms={"admin.delegations"}), meeting_id=MEETING_ID)
    assert len(out) == 1
    assert out[0].direction is None


async def test_list_admin_without_principal_row_still_lists() -> None:
    """Let an admin without a principal row still list the rows.

    The fake session returns no caller and the joined row.
    """
    row = _joined_row(uuid4(), outgoing=True)
    db = fake_session(
        result(),
        result(row),
        _names(),
    )
    out = await _svc(db).list(_actor(perms={"admin.delegations"}))
    assert len(out) == 1
    assert out[0].direction is None


async def test_meeting_context_no_principal_row() -> None:
    """Build the meeting context for a caller without a principal row.

    Without the row `can_delegate` is False, and there are no recipients or delegations. The
    fake session returns the membership of the view check and no caller. The meeting has a
    date, so the deadline is set.
    """
    db = fake_session(
        _membership(),
        result(),
    )
    db.get_results = [_meeting(), _gremium()]
    ctx = await _svc(db, voting=True).meeting_context(MEETING_ID, _actor())
    assert isinstance(ctx, MeetingDelegationContext)
    assert ctx.can_delegate is False
    assert ctx.my_delegation is None
    assert ctx.incoming == []
    assert ctx.recipients == []
    assert ctx.deadline is not None
    assert ctx.meeting_started is False
    assert ctx.voting_delegation_enabled is True


async def test_meeting_context_full_with_outgoing_incoming_and_recipients() -> None:
    """Build the full meeting context with an outgoing and an incoming delegation.

    The fake session returns, in order: the membership of the view check, the caller, the
    eligibility (so `can_delegate` is True), the joined rows, the names of both rows, the
    member ids, the pool ids and the recipient names. The recipients list the pool first,
    with both names resolved.
    """
    me = _me()
    member_a = uuid4()
    pool_b = uuid4()
    out_row = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=me.id,
        delegate_principal_id=member_a,
        delegate_voting=False,
        via_pool=False,
        created_at=NOW,
    )
    in_row = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=pool_b,
        delegate_principal_id=me.id,
        delegate_voting=True,
        via_pool=True,
        created_at=NOW,
    )
    db = fake_session(
        _membership(),
        result(me),
        result(["vote.cast"]),
        result((out_row, _meeting(), _gremium()), (in_row, _meeting(), _gremium())),
        _names(
            (me.id, "Me", None),
            (member_a, "Alice", None),
            (pool_b, "Bob", None),
        ),
        result(member_a),
        result(pool_b),
        _names((member_a, "Alice", None), (pool_b, "Bob", None)),
    )
    db.get_results = [_meeting(), _gremium()]
    ctx = await _svc(db).meeting_context(MEETING_ID, _actor())
    assert ctx.can_delegate is True
    assert ctx.my_delegation is not None
    assert ctx.my_delegation.delegate_id == member_a
    assert len(ctx.incoming) == 1
    assert ctx.incoming[0].delegator_id == pool_b
    assert [r.principal_id for r in ctx.recipients] == [pool_b, member_a]
    assert ctx.recipients[0].via_pool is True
    assert ctx.recipients[1].is_member is True


async def test_meeting_context_undated_meeting_deadline_none() -> None:
    """Give a meeting without a date no deadline.

    The fake session returns the membership of the view check and the caller, then empty
    results: no eligibility, no joined rows, no names, no members and no pool. The caller
    cannot delegate, although the gremium allows it.
    """
    me = _me()
    db = fake_session(
        _membership(),
        result(me),
        result(),
        result(),
        _names(),
        result(),
        result(),
        _names(),
    )
    db.get_results = [_meeting(dated=False), _gremium()]
    ctx = await _svc(db).meeting_context(MEETING_ID, _actor())
    assert ctx.deadline is None
    assert ctx.deadline_passed is False
    assert ctx.can_delegate is False


async def test_recipients_no_principal_row_empty() -> None:
    """Return no recipients for a caller without a principal row."""
    db = fake_session(
        _membership(),
        result(),
    )
    db.get_results = [_meeting(), _gremium()]
    assert await _svc(db).recipients(MEETING_ID, "x", _actor()) == []


async def test_recipients_filters_by_needle_and_excludes_self() -> None:
    """Filter the recipients by the needle and leave out the caller.

    The fake session returns, in order: the membership of the view check, the caller, the
    members (the caller drops out), an empty pool and the names.
    """
    me = _me()
    alice = uuid4()
    bob = uuid4()
    db = fake_session(
        _membership(),
        result(me),
        result(alice, bob, me.id),
        result(),
        _names((alice, "Alice", None), (bob, "Bob", None)),
    )
    db.get_results = [_meeting(), _gremium(external=False)]
    out = await _svc(db).recipients(MEETING_ID, "ali", _actor())
    assert [r.principal_id for r in out] == [alice]
    assert out[0].is_member is True


async def test_recipients_external_search_dedups_and_sorts() -> None:
    """Deduplicate and sort the external search results.

    The fake session returns, in order: the membership of the view check, the caller, the
    members, the pool and the names. The external search finds the member again
    (deduplicated), a new external person and the caller, who drops out. The order is the
    pool first, then the members, then the external people.
    """
    me = _me()
    member = uuid4()
    pool = uuid4()
    extern_new = uuid4()
    db = fake_session(
        _membership(),
        result(me),
        result(member),
        result(pool),
        _names((member, "Member Mary", None), (pool, "Pool Pete", None)),
        result(
            (member, "Member Mary", "m@x"),
            (extern_new, "Extern Erik", "e@x"),
            (me.id, "Me", "me@x"),
        ),
    )
    db.get_results = [_meeting(), _gremium(external=True)]
    out = await _svc(db).recipients(MEETING_ID, "e", _actor())
    pids = {r.principal_id for r in out}
    assert member in pids
    assert pool in pids
    assert extern_new in pids
    assert me.id not in pids
    assert out[0].principal_id == pool
    extern_entry = next(r for r in out if r.principal_id == extern_new)
    assert extern_entry.via_pool is False
    assert extern_entry.is_member is False
    assert extern_entry.display_name == "Extern Erik"


async def test_recipients_external_flag_but_empty_needle_skips_search() -> None:
    """Skip the external search for an empty needle.

    The needle is empty after the strip, so only the member stays.
    """
    me = _me()
    member = uuid4()
    db = fake_session(
        _membership(),
        result(me),
        result(member),
        result(),
        _names((member, "Member", None)),
    )
    db.get_results = [_meeting(), _gremium(external=True)]
    out = await _svc(db).recipients(MEETING_ID, "   ", _actor())
    assert [r.principal_id for r in out] == [member]


def _vote(*, meeting_id: Any = MEETING_ID, eligible_group: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=VOTE_ID,
        meeting_id=meeting_id,
        eligible_group=eligible_group if eligible_group is not None else str(GREMIUM_ID),
    )


async def test_vote_status_not_found() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="vote"):
        await _svc(db).vote_status(VOTE_ID, _actor())


async def test_vote_status_no_meeting_is_empty() -> None:
    db = fake_session()
    db.get_results = [_vote(meeting_id=None)]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert isinstance(status, VoteDelegationStatus)
    assert status.blocked is False
    assert status.exercising is False


async def test_vote_status_no_principal_row_is_empty() -> None:
    """Return an empty vote status without a principal row."""
    db = fake_session(result())
    db.get_results = [_vote()]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is False


async def test_vote_status_non_uuid_group_is_empty() -> None:
    """Return an empty vote status for a group that is not a UUID."""
    db = fake_session(result(_me()))
    db.get_results = [_vote(eligible_group="not-a-uuid")]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is False
    assert status.exercising is False


async def test_vote_status_blocked_and_exercising() -> None:
    """Report a blocked own vote and an exercised delegated vote.

    The fake session returns the caller, the delegations and the names.
    """
    me = _me()
    to_id = uuid4()
    by_id = uuid4()
    outgoing = SimpleNamespace(
        delegator_principal_id=me.id,
        delegate_principal_id=to_id,
    )
    incoming = SimpleNamespace(
        delegator_principal_id=by_id,
        delegate_principal_id=me.id,
    )
    db = fake_session(
        result(me),
        result(outgoing, incoming),
        _names((to_id, "Vertreter", None), (by_id, "Vertretener", None)),
    )
    db.get_results = [_vote()]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is True
    assert status.exercising is True
    assert status.delegated_to_name == "Vertreter"
    assert status.delegated_by_name == "Vertretener"


async def test_vote_status_no_rows_empty_names() -> None:
    """Return an empty vote status without delegations.

    The fake session returns the caller, no delegations and no names.
    """
    me = _me()
    db = fake_session(
        result(me),
        result(),
        _names(),
    )
    db.get_results = [_vote()]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is False
    assert status.exercising is False
    assert status.delegated_to_name is None
    assert status.delegated_by_name is None


async def test_require_pool_manage_admin_short_circuits() -> None:
    """Let an admin manage the pool without a query."""
    db = fake_session()
    await _svc(db)._require_pool_manage(GREMIUM_ID, _actor(perms={"admin.delegations"}))
    assert db.statements == []


async def test_require_pool_manage_via_gremium_session_manage() -> None:
    """Let a holder of the gremium role `session.manage` manage the pool."""
    role = SimpleNamespace(permissions=["session.manage"])
    db = fake_session(result((GREMIUM_ID, role)))
    await _svc(db)._require_pool_manage(GREMIUM_ID, _actor())


async def test_require_pool_manage_other_gremium_denied() -> None:
    """Refuse `session.manage` of another Gremium with 403."""
    role = SimpleNamespace(permissions=["session.manage"])
    db = fake_session(result((uuid4(), role)))
    with pytest.raises(ForbiddenError, match="session.manage"):
        await _svc(db)._require_pool_manage(GREMIUM_ID, _actor())


async def test_substitute_create_member_not_found_404() -> None:
    """Answer 404 for an unknown member of a pool entry."""
    sub = _me("sub")
    member_id = uuid4()
    db = fake_session(
        result(sub),
        result(),
    )
    db.get_results = [_gremium()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, memberId=member_id, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_create_substitute_not_found_404() -> None:
    """Answer 404 for an unknown substitute of a pool entry."""
    db = fake_session(result())
    db.get_results = [_gremium()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=uuid4()),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_create_with_member_persists() -> None:
    """Persist a member-bound pool entry.

    The member and the substitute differ and no duplicate exists, so the service creates the
    row. The fake session returns, in order: the substitute, the member, no duplicate, the
    audit lock, the audit predecessor and the names.
    """
    sub = _me("sub")
    member = _me("member")
    db = fake_session(
        result(sub),
        result(member),
        result(),
        result(),
        result(),
        _names((sub.id, "Sub", None), (member.id, "Member", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitute_create(
        SubstituteCreate(gremiumId=GREMIUM_ID, memberId=member.id, substituteId=sub.id),
        _actor(perms={"admin.delegations"}),
    )
    assert out.member_id == member.id
    assert out.member_name == "Member"
    assert out.substitute_name == "Sub"
    assert db.committed == 1
    assert any(isinstance(a, DelegationSubstitute) for a in db.added)


async def test_substitute_create_no_member_dup_409() -> None:
    """Refuse a duplicate gremium-wide entry with 409.

    `member_id` is None, so the duplicate query takes the `is_(None)` branch, and a hit
    gives 409.
    """
    sub = _me("sub")
    db = fake_session(
        result(sub),
        result(SimpleNamespace(id=uuid4())),
    )
    db.get_results = [_gremium()]
    with pytest.raises(ConflictError):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_delete_success_audits() -> None:
    """Delete a pool entry and audit it.

    The fake session returns the audit lock and the audit predecessor.
    """
    row = SimpleNamespace(id=uuid4(), gremium_id=GREMIUM_ID)
    db = fake_session(result(), result())
    db.get_results = [row]
    await _svc(db).substitute_delete(row.id, _actor(perms={"admin.delegations"}))
    assert db.deleted == [row]
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_substitute_delete_not_found() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="substitute"):
        await _svc(db).substitute_delete(uuid4(), _actor(perms={"admin.delegations"}))


async def test_substitutes_list_with_member_resolves_both_names() -> None:
    """Resolve the member name and the substitute name of a pool entry.

    The fake session returns the membership of the view check and the substitutes.
    """
    member_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=member_id,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        _membership(),
        result(row),
        _names((member_id, "Member", None), (row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].member_id == member_id
    assert out[0].member_name == "Member"
    assert out[0].substitute_name == "Sub"


async def test_substitutes_list_gremium_not_found() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="gremium"):
        await _svc(db).substitutes_list(GREMIUM_ID, _actor())


async def test_out_created_at_falls_back_to_now() -> None:
    """Use the current time for a freshly inserted row without `created_at`."""
    me = _me()
    d = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=me.id,
        delegate_principal_id=uuid4(),
        delegate_voting=False,
        via_pool=False,
        created_at=None,
    )
    db = fake_session(_names((me.id, "Me", None), (d.delegate_principal_id, "Other", None)))
    rows: list[Any] = [(d, _meeting(), _gremium())]
    outs = await _svc(db)._out(rows, NOW, me.id)
    assert isinstance(outs[0], DelegationOut)
    assert outs[0].created_at == NOW
    assert outs[0].meeting_date == FUTURE_DATE.isoformat()


async def test_out_meeting_without_date_serializes_none() -> None:
    me = _me()
    d = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=me.id,
        delegate_principal_id=uuid4(),
        delegate_voting=False,
        via_pool=False,
        created_at=NOW,
    )
    db = fake_session(_names((me.id, "Me", None), (d.delegate_principal_id, "Other", None)))
    rows: list[Any] = [(d, _meeting(dated=False), _gremium())]
    outs = await _svc(db)._out(rows, NOW, me.id)
    assert outs[0].meeting_date is None


async def test_create_meeting_not_found() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="meeting"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_gremium_gate_forbidden() -> None:
    db = fake_session()
    db.get_results = [_meeting(), _gremium(allow=False)]
    with pytest.raises(ForbiddenError, match="not enabled"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_voting_disabled_validation() -> None:
    db = fake_session()
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ValidationProblem, match="disabled"):
        await _svc(db, voting=False).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4(), delegateVoting=True),
            _actor(),
        )


async def test_create_meeting_already_started_validation() -> None:
    db = fake_session()
    db.get_results = [_meeting(status="live"), _gremium()]
    with pytest.raises(ValidationProblem, match="started"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_delegate_not_found() -> None:
    """Answer 404 for an unknown delegate."""
    db = fake_session(result(_me()), result())
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_self_delegation_validation() -> None:
    """Refuse a delegation to oneself."""
    me = _me()
    db = fake_session(result(me), result(me))
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ValidationProblem, match="yourself"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=me.id), _actor())


async def test_create_not_eligible_forbidden() -> None:
    """Refuse a caller without an own vote.

    The membership, the direct grant and the OIDC groups are empty.
    """
    db = fake_session(
        result(_me()),
        result(_me("other")),
        result(),
        result(),
        result((None,)),
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="voting members"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_external_recipient_forbidden() -> None:
    """Refuse an external recipient.

    The pool and the members are empty, so the recipient is external.
    """
    delegate = _me("other")
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(),
        result(),
    )
    db.get_results = [_meeting(), _gremium(external=False)]
    with pytest.raises(ForbiddenError, match="substitute"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_after_lead_deadline_validation() -> None:
    """Refuse a create after the lead-time deadline.

    The recipient is a member, not in the pool, and the lead time is longer than the gap to
    the meeting.
    """
    delegate = _me("other")
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(),
        result(delegate.id),
    )
    db.get_results = [_meeting(), _gremium(lead=60 * 24 * 31)]
    with pytest.raises(ValidationProblem, match="deadline"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_double_outgoing_conflict() -> None:
    """Refuse a second outgoing delegation, because the own row exists."""
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(me.id, uuid4(), False)],
    )
    with pytest.raises(ConflictError, match="already delegated"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_chain_actor_is_recipient_validation() -> None:
    """Refuse a chain when somebody delegates to the caller."""
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(uuid4(), me.id, False)],
    )
    with pytest.raises(ValidationProblem, match="delegate on"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_chain_recipient_delegated_away_validation() -> None:
    """Refuse a chain when the recipient delegated as well."""
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(delegate.id, uuid4(), False)],
    )
    with pytest.raises(ValidationProblem, match="delegated their own"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_second_voting_delegation_conflict() -> None:
    """Refuse a second voting delegation, because the recipient carries a voting right."""
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(uuid4(), delegate.id, True)],
    )
    with pytest.raises(ConflictError, match="carries"):
        await _svc(db, voting=True).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id, delegateVoting=True),
            _actor(),
        )


async def test_list_non_admin_without_principal_is_empty() -> None:
    """Return an empty list for a non-admin without a principal row."""
    db = fake_session(result())
    assert await _svc(db).list(_actor()) == []


async def test_list_non_admin_with_principal_filters_self() -> None:
    """Filter the list to the own rows for a non-admin with a principal row."""
    me = _me()
    row = _joined_row(me.id, outgoing=True)
    db = fake_session(
        result(me),
        result(row),
        _names(
            (row[0].delegator_principal_id, "Me", None),
            (row[0].delegate_principal_id, "Other", None),
        ),
    )
    out = await _svc(db).list(_actor())
    assert len(out) == 1
    assert out[0].direction == "outgoing"


async def test_revoke_not_found() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="delegation"):
        await _svc(db).revoke(uuid4(), _actor())


async def test_revoke_foreign_non_admin_forbidden() -> None:
    """Refuse the revoke of a foreign delegation for a non-admin.

    The caller is not the delegator, and the meeting is planned, so the lead path does not
    apply.
    """
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_me()))
    db.get_results = [row, _meeting()]
    with pytest.raises(ForbiddenError, match="delegator"):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_owner_after_start_validation() -> None:
    """Refuse the revoke of the owner after the start.

    The caller has no `session.manage` role, and the meeting is live, so the row is not
    revocable.
    """
    me = _me()
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=me.id)
    db = fake_session(result(), result(me))
    db.get_results = [row, _meeting(status="live")]
    with pytest.raises(ValidationProblem, match="started"):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_owner_before_start_ok() -> None:
    """Let the owner revoke before the start.

    The meeting is planned and in the future, so the row is revocable. The fake session
    returns the caller, the audit lock and the audit predecessor.
    """
    me = _me()
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=me.id)
    db = fake_session(result(me), result(), result())
    db.get_results = [row, _meeting()]
    await _svc(db).revoke(row.id, _actor())
    assert db.deleted == [row]
    assert db.committed == 1


async def test_revoke_admin_skips_meeting_lookup() -> None:
    """Let an admin revoke without a meeting lookup."""
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_me()), result(), result())
    db.get_results = [row]
    await _svc(db).revoke(row.id, _actor(perms={"admin.delegations"}))
    assert db.deleted == [row]


async def test_substitute_create_member_equals_substitute_validation() -> None:
    """Refuse a pool entry whose member and substitute are one person."""
    sub = _me("sub")
    db = fake_session(result(sub), result(sub))
    db.get_results = [_gremium()]
    with pytest.raises(ValidationProblem, match="differ"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, memberId=sub.id, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitutes_list_row_without_member() -> None:
    """List a gremium-wide pool entry without a member name."""
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        _membership(),
        result(row),
        _names((row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].member_id is None
    assert out[0].member_name is None
    assert out[0].substitute_name == "Sub"


async def test_substitutes_list_non_member_403() -> None:
    """Refuse the roster to a non-member with 403.

    The caller has no admin or manage right, no membership, no pool place and no
    `session.manage`. All three view queries stay empty, so the roster with personal data
    does not leak to every logged-in user.
    """
    db = fake_session(
        result(),
        result(),
        result(),
    )
    db.get_results = [_gremium()]
    with pytest.raises(ForbiddenError, match="roster"):
        await _svc(db).substitutes_list(GREMIUM_ID, _actor())


async def test_substitutes_list_admin_role_bypasses_view_check() -> None:
    """Let the admin role read the roster without a view query."""
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(result(row), _names((row.substitute_principal_id, "Sub", None)))
    db.get_results = [_gremium()]
    admin = Principal(sub="a", roles=["admin"], permissions=set())
    out = await _svc(db).substitutes_list(GREMIUM_ID, admin)
    assert out[0].substitute_name == "Sub"


async def test_substitutes_list_pool_member_sees_roster() -> None:
    """Let a pool member read the roster.

    The caller is in the substitute pool of the Gremium but not a member, so the second view
    query hits.
    """
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        result(),
        result(GREMIUM_ID),
        result(row),
        _names((row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].substitute_name == "Sub"


async def test_substitutes_list_session_manage_sees_roster() -> None:
    """Let a holder of the gremium role `session.manage` read the roster.

    The first two view queries stay empty, and the third one hits.
    """
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        result(),
        result(),
        result((GREMIUM_ID, SimpleNamespace(permissions=["session.manage"]))),
        result(row),
        _names((row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].substitute_name == "Sub"


async def test_meeting_context_non_member_403() -> None:
    """Refuse the meeting context to a non-member with 403.

    The membership, the pool and the `session.manage` queries stay empty.
    """
    db = fake_session(
        result(),
        result(),
        result(),
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="roster"):
        await _svc(db).meeting_context(MEETING_ID, _actor())


async def test_recipients_non_member_403() -> None:
    """Refuse the recipients to a non-member with 403.

    The membership, the pool and the `session.manage` queries stay empty.
    """
    db = fake_session(
        result(),
        result(),
        result(),
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="roster"):
        await _svc(db).recipients(MEETING_ID, "x", _actor())


async def test_meeting_view_all_perm_bypasses_view_check() -> None:
    """Skip the view check for the global read permission `meeting.view_all`.

    An empty caller lookup is enough for `can_delegate` False.
    """
    db = fake_session(
        result(),
    )
    db.get_results = [_meeting(), _gremium()]
    viewer = Principal(sub="v", roles=["member"], permissions={"meeting.view_all"})
    ctx = await _svc(db).meeting_context(MEETING_ID, viewer)
    assert ctx.can_delegate is False


def test_escape_like_neutralises_wildcards() -> None:
    from app.modules.delegations.service import _escape_like

    assert _escape_like("a%b_c") == "a\\%b\\_c"
    assert _escape_like("100\\%") == "100\\\\\\%"
    assert _escape_like("plain") == "plain"


async def test_create_acquires_meeting_advisory_lock() -> None:
    """Serialize the create per meeting with `pg_advisory_xact_lock`.

    At least one advisory-lock statement runs before the insert, for the delegation and for
    the audit.
    """
    from sqlalchemy.sql.elements import TextClause

    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[],
    )
    await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor())
    locks = [s for s in db.statements if isinstance(s, TextClause)]
    assert any("pg_advisory_xact_lock" in str(s) for s in locks)


def test_recipient_out_is_camel_model() -> None:
    """Build a `RecipientOut` with camelCase aliases.

    The test also keeps the `RecipientOut` import in use.
    """
    r = RecipientOut(principal_id=uuid4(), via_pool=False, is_member=True)
    assert isinstance(r.principal_id, UUID)


async def test_view_gremium_admin_with_read_scope_passes() -> None:
    """Let an admin with the `read` scope pass without a query.

    The `read` scope carries `meeting.view_all`.
    """
    admin = Principal(
        sub="admin",
        roles=["admin"],
        permissions=set(),
        scope_permissions=frozenset({"application.read", "meeting.view_all"}),
    )
    db = fake_session()
    await _svc(db)._assert_can_view_gremium(GREMIUM_ID, admin)
    assert db.statements == []


async def test_view_gremium_admin_token_without_read_scope_denied() -> None:
    """Refuse an admin token without the `read` scope.

    A `budget:write` token of an admin holds neither `meeting.view_all` nor
    `admin.delegations`. Without a membership or a pool place it cannot read the roster of a
    foreign gremium, which carries names and email addresses.
    """
    admin = Principal(
        sub="admin",
        roles=["admin"],
        permissions=set(),
        scope_permissions=frozenset({"budget.structure", "budget.book"}),
    )
    db = fake_session(
        result(),
        result(),
    )
    with pytest.raises(ForbiddenError):
        await _svc(db)._assert_can_view_gremium(GREMIUM_ID, admin)
