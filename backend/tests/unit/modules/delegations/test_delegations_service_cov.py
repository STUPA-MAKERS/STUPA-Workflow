"""Zusatz-Coverage für den DelegationService (#delegation-rework).

Ergänzt ``test_delegations_service_unit.py`` um die dort noch offenen Zweige:
``_independently_eligible`` (direct/OIDC/group-mapping), ``_names``-Leerfall,
``_gremium``-404, ``_direction`` (None/unbeteiligt), die Branch-Sonderfälle in
``create`` (Sitzung ohne Termin → kein Deadline-Check; nicht-Stimm-Doppel zur
selben Person → Schleife läuft weiter), die Admin-Sicht von ``list``, der
komplette ``meeting_context`` (mit/ohne Principal), ``recipients`` (inkl.
externer Suche + Needle-Filter), ``vote_status`` (alle Verdikt-Zweige) und die
Pool-Pfade (Admin-Bypass von ``_require_pool_manage``, Member-404, Dup mit
Mitglied).

Wie die Bestands-Suite: keine echte DB — die ``execute``/``get``-Queues des
``flow_fakes``-Fakes treffen jede Verzweigung deterministisch.
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
    """Erste Query von ``_assert_can_view_gremium`` (gremium_member_ids):
    ``active_gremium_roles`` liefert ``(gremium_id, role)``-Paare; eine passende
    Zeile → die Sicht-Prüfung läuft sofort durch (Mitglied des Gremiums)."""
    return result((gremium_id, SimpleNamespace(permissions=[])))


# --------------------------------------------------------------------------- #
# meeting_start_utc / voting_delegation_check (Modul-Funktionen)
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# _meeting — 404
# --------------------------------------------------------------------------- #
async def test_meeting_not_found_raises() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="meeting"):
        await _svc(db)._meeting(MEETING_ID)


# --------------------------------------------------------------------------- #
# _membership_with_vote_cast — None-Permissions werden toleriert
# --------------------------------------------------------------------------- #
async def test_membership_vote_cast_handles_none_perms() -> None:
    # Eine Rolle ohne Permissions (None) darf nicht crashen und gilt nicht.
    db = fake_session(result(None, ["other"]))
    assert await _membership_with_vote_cast(db, uuid4(), GREMIUM_ID, NOW) is False


async def test_membership_vote_cast_true() -> None:
    db = fake_session(result(["vote.cast"]))
    assert await _membership_with_vote_cast(db, uuid4(), GREMIUM_ID, NOW) is True


# --------------------------------------------------------------------------- #
# _independently_eligible — alle Quellen einzeln
# --------------------------------------------------------------------------- #
async def test_eligible_via_membership_vote_cast() -> None:
    db = fake_session(result(["vote.cast"]))  # membership reicht → kein weiterer Query
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is True


async def test_eligible_via_direct_assignment() -> None:
    # membership leer → direct role_assignment trifft (Zeile 138).
    db = fake_session(
        result(),  # membership perms: keine vote.cast
        result(SimpleNamespace(id=uuid4())),  # direktes assignment
    )
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is True


async def test_eligible_via_oidc_group_direct() -> None:
    # membership + direct leer → OIDC-Gruppe == str(gremium_id) (Zeile 146).
    db = fake_session(
        result(),  # membership
        result(),  # direct
        result(([str(GREMIUM_ID)],)),  # oidc_groups enthält die Gremium-ID
    )
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is True


async def test_eligible_via_group_mapping() -> None:
    # OIDC-Gruppe ≠ Gremium-ID, aber group_mapping bildet sie ab (Zeile 149-159).
    db = fake_session(
        result(),  # membership
        result(),  # direct
        result((["fachschaft-info"],)),  # oidc_groups
        result(SimpleNamespace(id=uuid4())),  # mapping trifft
    )
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is True


async def test_eligible_group_mapping_miss_is_false() -> None:
    # OIDC-Gruppe vorhanden, aber kein Mapping → not eligible (Zeile 159 None).
    db = fake_session(
        result(),  # membership
        result(),  # direct
        result((["fachschaft-info"],)),  # oidc_groups
        result(),  # mapping leer
    )
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is False


async def test_eligible_no_oidc_groups_short_circuits() -> None:
    # Keine OIDC-Gruppen → früher Abbruch ohne Mapping-Query (Zeile 148).
    db = fake_session(
        result(),  # membership
        result(),  # direct
        result((None,)),  # oidc_groups: None
    )
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is False
    # Die Mapping-Abfrage darf gar nicht erst gelaufen sein.
    assert len(db.statements) == 3


async def test_eligible_principal_row_missing_no_oidc() -> None:
    # PrincipalRow-Lookup leer (row is None) → oidc bleibt leer.
    db = fake_session(
        result(),  # membership
        result(),  # direct
        result(),  # oidc_groups query: keine Zeile
    )
    assert await _independently_eligible(db, uuid4(), GREMIUM_ID, NOW) is False


# --------------------------------------------------------------------------- #
# _names — Leerfall
# --------------------------------------------------------------------------- #
async def test_names_empty_set_returns_empty_dict() -> None:
    db = fake_session()
    svc = _svc(db)
    assert await svc._names(set()) == {}
    # Kein Query bei leerer Menge.
    assert db.statements == []


# --------------------------------------------------------------------------- #
# _gremium — 404
# --------------------------------------------------------------------------- #
async def test_gremium_not_found_raises() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError, match="gremium"):
        await _svc(db)._gremium(GREMIUM_ID)


# --------------------------------------------------------------------------- #
# _direction — Sonderfälle
# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# create — Branch-Sonderfälle
# --------------------------------------------------------------------------- #
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
    db = fake_session(
        result(me),  # _principal_row(sub)
        result(delegate),  # _principal_row(pid)
        result(["vote.cast"]),  # eligibility: membership
        result(*pool_ids),  # pool
        result(*member_ids),  # members
        result(),  # create advisory-lock (pg_advisory_xact_lock je Sitzung)
        result(*existing),  # existing rows
        result(),  # audit lock
        result(),  # audit prev
        _names((me.id, "Me", None), (delegate.id, "Other", None)),
    )
    db.get_results = [meeting, gremium]
    return db


async def test_create_undated_meeting_skips_deadline() -> None:
    # Sitzung ohne Datum (start None) → Branch 409->420: kein Deadline-Block.
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
    # me is None (Zeile 385): _principal_row(sub) liefert nichts.
    db = fake_session(result())  # me lookup empty
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="Delegator principal not found"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor()
        )


async def test_create_nonvoting_existing_to_same_recipient_does_not_conflict() -> None:
    # Branch 442->429: bestehende NICHT-Stimm-Zeile an dieselbe Person → kein 409,
    # Schleife läuft weiter und die neue (Nicht-Stimm-)Delegation wird angelegt.
    me, delegate = _me(), _me("other")
    existing_row = (uuid4(), delegate.id, False)  # andere Person → selbe delegate, voting False
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
    # payload.delegate_voting True + bestehende Stimm-Zeile, aber an ANDERE Person
    # → 442-Bedingung false (delegate_id != delegate.id), kein 409.
    me, delegate = _me(), _me("other")
    existing_row = (uuid4(), uuid4(), True)  # Stimm-Delegation an jemand anderen
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


# --------------------------------------------------------------------------- #
# list — Admin-Sicht
# --------------------------------------------------------------------------- #
def _joined_row(
    me_id: Any, *, outgoing: bool = True
) -> tuple[Any, Any, Any]:
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
    # Admin (kein me-Filter) + meeting_id-Filter (Zeile 483 + 484->493 false-Zweig).
    foreign = uuid4()
    row = _joined_row(foreign, outgoing=True)
    db = fake_session(
        result(_me()),  # me lookup (admin still resolved for direction)
        result(row),  # joined
        _names(
            (row[0].delegator_principal_id, "X", None),
            (row[0].delegate_principal_id, "Y", None),
        ),
    )
    out = await _svc(db).list(_actor(perms={"admin.delegations"}), meeting_id=MEETING_ID)
    assert len(out) == 1
    # Aufrufer unbeteiligt → direction None.
    assert out[0].direction is None


async def test_list_admin_without_principal_row_still_lists() -> None:
    # Admin, aber kein PrincipalRow → me None, trotzdem keine Leer-Rückgabe.
    row = _joined_row(uuid4(), outgoing=True)
    db = fake_session(
        result(),  # me lookup empty
        result(row),  # joined
        _names(),
    )
    out = await _svc(db).list(_actor(perms={"admin.delegations"}))
    assert len(out) == 1
    assert out[0].direction is None


# --------------------------------------------------------------------------- #
# meeting_context
# --------------------------------------------------------------------------- #
async def test_meeting_context_no_principal_row() -> None:
    # me is None → can_delegate False, keine Empfänger/Delegationen.
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(),  # me lookup empty
    )
    db.get_results = [_meeting(), _gremium()]
    ctx = await _svc(db, voting=True).meeting_context(MEETING_ID, _actor())
    assert isinstance(ctx, MeetingDelegationContext)
    assert ctx.can_delegate is False
    assert ctx.my_delegation is None
    assert ctx.incoming == []
    assert ctx.recipients == []
    assert ctx.deadline is not None  # Sitzung hat Termin
    assert ctx.meeting_started is False
    assert ctx.voting_delegation_enabled is True


async def test_meeting_context_full_with_outgoing_incoming_and_recipients() -> None:
    me = _me()
    member_a = uuid4()
    pool_b = uuid4()
    # Eine ausgehende + eine eingehende Delegation des Aufrufers.
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
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(me),  # me lookup
        result(["vote.cast"]),  # eligibility membership → can_delegate True
        result((out_row, _meeting(), _gremium()), (in_row, _meeting(), _gremium())),  # joined
        _names(  # names for _out (delegator/delegate ids of both rows)
            (me.id, "Me", None),
            (member_a, "Alice", None),
            (pool_b, "Bob", None),
        ),
        result(member_a),  # member_ids
        result(pool_b),  # pool_ids
        _names((member_a, "Alice", None), (pool_b, "Bob", None)),  # recipient names
    )
    db.get_results = [_meeting(), _gremium()]
    ctx = await _svc(db).meeting_context(MEETING_ID, _actor())
    assert ctx.can_delegate is True
    assert ctx.my_delegation is not None
    assert ctx.my_delegation.delegate_id == member_a
    assert len(ctx.incoming) == 1
    assert ctx.incoming[0].delegator_id == pool_b
    # Empfänger: Pool zuerst (sort key not via_pool), beide aufgelöst.
    assert [r.principal_id for r in ctx.recipients] == [pool_b, member_a]
    assert ctx.recipients[0].via_pool is True
    assert ctx.recipients[1].is_member is True


async def test_meeting_context_undated_meeting_deadline_none() -> None:
    me = _me()
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(me),  # me lookup
        result(),  # eligibility membership empty
        result(),  # direct empty
        result((None,)),  # oidc None → not eligible
        result(),  # joined empty
        _names(),  # _out names (empty)
        result(),  # member_ids empty
        result(),  # pool_ids empty
        _names(),  # recipient names
    )
    db.get_results = [_meeting(dated=False), _gremium()]
    ctx = await _svc(db).meeting_context(MEETING_ID, _actor())
    assert ctx.deadline is None
    assert ctx.deadline_passed is False
    assert ctx.can_delegate is False  # eligible False even though allow True


# --------------------------------------------------------------------------- #
# recipients
# --------------------------------------------------------------------------- #
async def test_recipients_no_principal_row_empty() -> None:
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(),  # me lookup empty
    )
    db.get_results = [_meeting(), _gremium()]
    assert await _svc(db).recipients(MEETING_ID, "x", _actor()) == []


async def test_recipients_filters_by_needle_and_excludes_self() -> None:
    me = _me()
    alice = uuid4()
    bob = uuid4()
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(me),  # me lookup
        result(alice, bob, me.id),  # members (me.id wird via - {me.id} entfernt)
        result(),  # pool empty
        _names((alice, "Alice", None), (bob, "Bob", None)),  # names
    )
    db.get_results = [_meeting(), _gremium(external=False)]
    out = await _svc(db).recipients(MEETING_ID, "ali", _actor())
    assert [r.principal_id for r in out] == [alice]
    assert out[0].is_member is True


async def test_recipients_external_search_dedups_and_sorts() -> None:
    me = _me()
    member = uuid4()
    pool = uuid4()
    extern_new = uuid4()
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(me),  # me lookup
        result(member),  # members
        result(pool),  # pool
        _names((member, "Member Mary", None), (pool, "Pool Pete", None)),  # names
        # externe Suche: member ist schon drin (dedup), extern_new neu, me ausgeschlossen
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
    # Sortierung: Pool zuerst (not via_pool False), dann Mitglieder, dann externe.
    assert out[0].principal_id == pool
    extern_entry = next(r for r in out if r.principal_id == extern_new)
    assert extern_entry.via_pool is False
    assert extern_entry.is_member is False
    assert extern_entry.display_name == "Extern Erik"


async def test_recipients_external_flag_but_empty_needle_skips_search() -> None:
    me = _me()
    member = uuid4()
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(me),  # me lookup
        result(member),  # members
        result(),  # pool
        _names((member, "Member", None)),  # names
    )
    db.get_results = [_meeting(), _gremium(external=True)]
    out = await _svc(db).recipients(MEETING_ID, "   ", _actor())  # needle leer nach strip
    # Keine externe Suche (needle leer) → nur member, kein zusätzlicher Query.
    assert [r.principal_id for r in out] == [member]


# --------------------------------------------------------------------------- #
# vote_status
# --------------------------------------------------------------------------- #
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
    db = fake_session(result())  # me lookup empty
    db.get_results = [_vote()]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is False


async def test_vote_status_non_uuid_group_is_empty() -> None:
    db = fake_session(result(_me()))  # me lookup ok
    db.get_results = [_vote(eligible_group="not-a-uuid")]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is False
    assert status.exercising is False


async def test_vote_status_blocked_and_exercising() -> None:
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
        result(me),  # me lookup
        result(outgoing, incoming),  # delegations
        _names((to_id, "Vertreter", None), (by_id, "Vertretener", None)),  # names
    )
    db.get_results = [_vote()]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is True
    assert status.exercising is True
    assert status.delegated_to_name == "Vertreter"
    assert status.delegated_by_name == "Vertretener"


async def test_vote_status_no_rows_empty_names() -> None:
    me = _me()
    db = fake_session(
        result(me),  # me lookup
        result(),  # no delegations
        _names(),  # names (empty set)
    )
    db.get_results = [_vote()]
    status = await _svc(db).vote_status(VOTE_ID, _actor())
    assert status.blocked is False
    assert status.exercising is False
    assert status.delegated_to_name is None
    assert status.delegated_by_name is None


# --------------------------------------------------------------------------- #
# _require_pool_manage — Admin-Bypass + gremium-perm-Pfad
# --------------------------------------------------------------------------- #
async def test_require_pool_manage_admin_short_circuits() -> None:
    db = fake_session()  # keine Query nötig
    await _svc(db)._require_pool_manage(GREMIUM_ID, _actor(perms={"admin.delegations"}))
    assert db.statements == []


async def test_require_pool_manage_via_gremium_session_manage() -> None:
    # active_gremium_roles liefert (gremium, role mit session.manage) → erlaubt.
    role = SimpleNamespace(permissions=["session.manage"])
    db = fake_session(result((GREMIUM_ID, role)))
    await _svc(db)._require_pool_manage(GREMIUM_ID, _actor())  # kein Raise


async def test_require_pool_manage_other_gremium_denied() -> None:
    # session.manage nur in einem ANDEREN Gremium → 403.
    role = SimpleNamespace(permissions=["session.manage"])
    db = fake_session(result((uuid4(), role)))
    with pytest.raises(ForbiddenError, match="session.manage"):
        await _svc(db)._require_pool_manage(GREMIUM_ID, _actor())


# --------------------------------------------------------------------------- #
# substitute_create — Member-Pfade
# --------------------------------------------------------------------------- #
async def test_substitute_create_member_not_found_404() -> None:
    sub = _me("sub")
    member_id = uuid4()
    db = fake_session(
        result(sub),  # substitute principal
        result(),  # member principal lookup empty → 404
    )
    db.get_results = [_gremium()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, memberId=member_id, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_create_substitute_not_found_404() -> None:
    db = fake_session(result())  # substitute lookup empty
    db.get_results = [_gremium()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=uuid4()),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_create_with_member_persists() -> None:
    # Member != Substitute, kein Dup → angelegt + Member-Namen aufgelöst.
    sub = _me("sub")
    member = _me("member")
    db = fake_session(
        result(sub),  # substitute principal
        result(member),  # member principal
        result(),  # duplicate probe empty (member-specific branch)
        result(),  # audit lock
        result(),  # audit prev
        _names((sub.id, "Sub", None), (member.id, "Member", None)),  # final names
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
    # member_id None → Dup-Query nutzt is_(None)-Zweig; Treffer → 409.
    sub = _me("sub")
    db = fake_session(
        result(sub),  # substitute principal
        result(SimpleNamespace(id=uuid4())),  # dup found
    )
    db.get_results = [_gremium()]
    with pytest.raises(ConflictError):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_delete_success_audits() -> None:
    row = SimpleNamespace(id=uuid4(), gremium_id=GREMIUM_ID)
    db = fake_session(result(), result())  # audit lock + prev
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


# --------------------------------------------------------------------------- #
# substitutes_list — mit Member-Zeile (member_principal_id gesetzt)
# --------------------------------------------------------------------------- #
async def test_substitutes_list_with_member_resolves_both_names() -> None:
    member_id = uuid4()
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=member_id,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(row),  # substitutes
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


# --------------------------------------------------------------------------- #
# _out — direkte Abdeckung created_at-Fallback + DelegationOut-Form
# --------------------------------------------------------------------------- #
async def test_out_created_at_falls_back_to_now() -> None:
    me = _me()
    d = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=me.id,
        delegate_principal_id=uuid4(),
        delegate_voting=False,
        via_pool=False,
        created_at=None,  # frisch eingefügt → Fallback now
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


# --------------------------------------------------------------------------- #
# create — restliche Guards (Gates/Ketten/Deadline) für Standalone-Coverage
# --------------------------------------------------------------------------- #
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
    db = fake_session(result(_me()), result())  # me ok, delegate missing
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_self_delegation_validation() -> None:
    me = _me()
    db = fake_session(result(me), result(me))  # delegate == me
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ValidationProblem, match="yourself"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=me.id), _actor())


async def test_create_not_eligible_forbidden() -> None:
    db = fake_session(
        result(_me()),
        result(_me("other")),
        result(),  # membership empty
        result(),  # direct empty
        result((None,)),  # oidc None
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="voting members"):
        await _svc(db).create(DelegationCreate(meetingId=MEETING_ID, delegateId=uuid4()), _actor())


async def test_create_external_recipient_forbidden() -> None:
    delegate = _me("other")
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(),  # pool empty
        result(),  # members empty → extern
    )
    db.get_results = [_meeting(), _gremium(external=False)]
    with pytest.raises(ForbiddenError, match="substitute"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_after_lead_deadline_validation() -> None:
    delegate = _me("other")
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(),  # pool empty
        result(delegate.id),  # member
    )
    db.get_results = [_meeting(), _gremium(lead=60 * 24 * 31)]  # Vorlauf > Termin-Abstand
    with pytest.raises(ValidationProblem, match="deadline"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_double_outgoing_conflict() -> None:
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(me.id, uuid4(), False)],  # eigene Zeile existiert
    )
    with pytest.raises(ConflictError, match="already delegated"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_chain_actor_is_recipient_validation() -> None:
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(uuid4(), me.id, False)],  # jemand delegiert an mich
    )
    with pytest.raises(ValidationProblem, match="delegate on"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_chain_recipient_delegated_away_validation() -> None:
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(delegate.id, uuid4(), False)],  # Empfänger delegierte selbst
    )
    with pytest.raises(ValidationProblem, match="delegated their own"):
        await _svc(db).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
        )


async def test_create_second_voting_delegation_conflict() -> None:
    me, delegate = _me(), _me("other")
    db = _create_db(
        meeting=_meeting(),
        gremium=_gremium(),
        me=me,
        delegate=delegate,
        pool_ids=[],
        member_ids=[delegate.id],
        existing=[(uuid4(), delegate.id, True)],  # Empfänger trägt schon ein Stimmrecht
    )
    with pytest.raises(ConflictError, match="carries"):
        await _svc(db, voting=True).create(
            DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id, delegateVoting=True),
            _actor(),
        )


# --------------------------------------------------------------------------- #
# list / revoke — Standalone-Coverage
# --------------------------------------------------------------------------- #
async def test_list_non_admin_without_principal_is_empty() -> None:
    db = fake_session(result())  # me lookup empty + nicht-Admin
    assert await _svc(db).list(_actor()) == []


async def test_list_non_admin_with_principal_filters_self() -> None:
    # Nicht-Admin mit PrincipalRow → eigener (or-)Filter wird angehängt (Zeile 487).
    me = _me()
    row = _joined_row(me.id, outgoing=True)
    db = fake_session(
        result(me),  # me lookup
        result(row),  # joined
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
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_me()))  # me ist nicht der Delegierende
    db.get_results = [row]
    with pytest.raises(ForbiddenError, match="delegator"):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_owner_after_start_validation() -> None:
    me = _me()
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=me.id)
    db = fake_session(result(me))
    db.get_results = [row, _meeting(status="live")]  # Sitzung läuft → _revocable False (Zeile 302)
    with pytest.raises(ValidationProblem, match="started"):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_owner_before_start_ok() -> None:
    me = _me()
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=me.id)
    db = fake_session(result(me), result(), result())  # audit lock + prev
    db.get_results = [row, _meeting()]  # planned + Zukunft → revocable
    await _svc(db).revoke(row.id, _actor())
    assert db.deleted == [row]
    assert db.committed == 1


async def test_revoke_admin_skips_meeting_lookup() -> None:
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_me()), result(), result())
    db.get_results = [row]  # kein Meeting-Lookup nötig (Admin)
    await _svc(db).revoke(row.id, _actor(perms={"admin.delegations"}))
    assert db.deleted == [row]


# --------------------------------------------------------------------------- #
# substitute_create — member == substitute (Zeile 757)
# --------------------------------------------------------------------------- #
async def test_substitute_create_member_equals_substitute_validation() -> None:
    sub = _me("sub")
    db = fake_session(result(sub), result(sub))  # substitute + member sind dieselbe Person
    db.get_results = [_gremium()]
    with pytest.raises(ValidationProblem, match="differ"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, memberId=sub.id, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


# --------------------------------------------------------------------------- #
# substitutes_list — Zeile ohne Member (Branch 730->728)
# --------------------------------------------------------------------------- #
async def test_substitutes_list_row_without_member() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,  # kein Mitglied → Zweig 731 wird übersprungen
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        _membership(),  # _assert_can_view_gremium: Mitglied
        result(row),
        _names((row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].member_id is None
    assert out[0].member_name is None
    assert out[0].substitute_name == "Sub"


# --------------------------------------------------------------------------- #
# #sec-audit: _assert_can_view_gremium — Cross-Tenant-Sicht verriegeln
# --------------------------------------------------------------------------- #
async def test_substitutes_list_non_member_403() -> None:
    # Kein Admin/Manage, keine Mitgliedschaft, kein Pool, kein session.manage:
    # alle drei Sicht-Queries leer → 403 (zuvor: PII für jeden eingeloggten Nutzer).
    db = fake_session(
        result(),  # gremium_member_ids leer
        result(),  # _pool_member_gremium_ids leer
        result(),  # gremium_ids_with_permission(session.manage) leer
    )
    db.get_results = [_gremium()]
    with pytest.raises(ForbiddenError, match="roster"):
        await _svc(db).substitutes_list(GREMIUM_ID, _actor())


async def test_substitutes_list_admin_role_bypasses_view_check() -> None:
    # admin-Rolle → keine Sicht-Query nötig, direkter Durchlauf.
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
    # Stellvertreter-Pool des Gremiums (aber kein Mitglied) → zweite Query trifft.
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        result(),  # gremium_member_ids leer
        result(GREMIUM_ID),  # _pool_member_gremium_ids: im Pool
        result(row),
        _names((row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].substitute_name == "Sub"


async def test_substitutes_list_session_manage_sees_roster() -> None:
    # Träger der Gremium-Rolle session.manage → dritte Query trifft.
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(
        result(),  # gremium_member_ids leer
        result(),  # _pool_member_gremium_ids leer
        result((GREMIUM_ID, SimpleNamespace(permissions=["session.manage"]))),  # mit Recht
        result(row),
        _names((row.substitute_principal_id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].substitute_name == "Sub"


async def test_meeting_context_non_member_403() -> None:
    db = fake_session(
        result(),  # gremium_member_ids leer
        result(),  # pool leer
        result(),  # session.manage leer
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="roster"):
        await _svc(db).meeting_context(MEETING_ID, _actor())


async def test_recipients_non_member_403() -> None:
    db = fake_session(
        result(),  # gremium_member_ids leer
        result(),  # pool leer
        result(),  # session.manage leer
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="roster"):
        await _svc(db).recipients(MEETING_ID, "x", _actor())


async def test_meeting_view_all_perm_bypasses_view_check() -> None:
    # meeting.view_all (globale Lese-Permission) → keine Sicht-Query.
    db = fake_session(
        result(),  # me lookup empty (genügt für can_delegate False)
    )
    db.get_results = [_meeting(), _gremium()]
    viewer = Principal(sub="v", roles=["member"], permissions={"meeting.view_all"})
    ctx = await _svc(db).meeting_context(MEETING_ID, viewer)
    assert ctx.can_delegate is False


# --------------------------------------------------------------------------- #
# #sec: LIKE-Escape im externen Empfänger-Typeahead
# --------------------------------------------------------------------------- #
def test_escape_like_neutralises_wildcards() -> None:
    from app.modules.delegations.service import _escape_like

    assert _escape_like("a%b_c") == "a\\%b\\_c"
    assert _escape_like("100\\%") == "100\\\\\\%"
    assert _escape_like("plain") == "plain"


# --------------------------------------------------------------------------- #
# #race: create serialisiert je Sitzung mit pg_advisory_xact_lock
# --------------------------------------------------------------------------- #
async def test_create_acquires_meeting_advisory_lock() -> None:
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
    await _svc(db).create(
        DelegationCreate(meetingId=MEETING_ID, delegateId=delegate.id), _actor()
    )
    # Mindestens ein Advisory-Lock-Statement vor dem Insert (Delegation + Audit-Kette).
    locks = [s for s in db.statements if isinstance(s, TextClause)]
    assert any("pg_advisory_xact_lock" in str(s) for s in locks)


# --------------------------------------------------------------------------- #
# RecipientOut wird verwendet — Importe stabil halten
# --------------------------------------------------------------------------- #
def test_recipient_out_is_camel_model() -> None:
    r = RecipientOut(principal_id=uuid4(), via_pool=False, is_member=True)
    assert isinstance(r.principal_id, UUID)
