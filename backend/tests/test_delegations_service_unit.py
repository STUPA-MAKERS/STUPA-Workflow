"""TDD: DelegationService (#delegation-rework) — sitzungsgebundene Vertretungen.

Jede Service-Verzweigung wird über die Ergebnis-Queues des Fakes
(``flow_fakes``: ``execute``-Queue + ``get``-Queue) deterministisch getroffen —
keine echte DB. Abgedeckt: Feature-Gates (Gremium/Stimmrecht), Deadline (Vorlauf
vs. Pool), Empfänger-Kreis (Mitglied/Pool/extern), Ketten-Verbot, Widerruf,
Stimmrechts-Verdikt (:func:`voting_delegation_check`) und Stellvertreter-Pool.

``execute``-Reihenfolge in ``create``: me → delegate → Eligibility (membership-
vote.cast, ggf. direct/oidc/mapping) → Pool → Mitglieder → bestehende Zeilen →
audit(lock, prev) → Namen. ``get``-Reihenfolge: meeting → gremium.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.delegations import service as delegations_service
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.delegations.schemas import DelegationCreate, SubstituteCreate
from app.modules.delegations.service import (
    DelegationService,
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
from tests.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
GREMIUM_ID = uuid4()
MEETING_ID = uuid4()
TZ = "Europe/Berlin"
# Der Service rechnet mit der ECHTEN Uhr (datetime.now) — Sitzungstermine daher
# relativ zu heute, damit die Suite nicht mit der Zeit kippt.
FUTURE_DATE = (datetime.now(UTC) + timedelta(days=30)).date()
PAST_DATE = (datetime.now(UTC) - timedelta(days=2)).date()


def _settings(*, voting: bool = False) -> Any:
    return load_settings(delegation_voting_enabled=voting)


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


def _delegate(sub: str = "other") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), sub=sub)


def _payload(delegate_id: Any, *, voting: bool = False) -> DelegationCreate:
    return DelegationCreate(meetingId=MEETING_ID, delegateId=delegate_id, delegateVoting=voting)


def _names(*rows: tuple[Any, str | None, str | None]):  # noqa: ANN202
    return result(*rows)


def _svc(db: Any, *, voting: bool = False) -> DelegationService:
    return DelegationService(db, _settings(voting=voting))


# --------------------------------------------------------------------------- #
# meeting_start_utc
# --------------------------------------------------------------------------- #
def test_meeting_start_utc_none_without_date() -> None:
    assert meeting_start_utc(_meeting(dated=False), TZ) is None  # type: ignore[arg-type]


def test_meeting_start_utc_converts_local_to_utc() -> None:
    # 2026-06-20 ist Sommerzeit (CEST, UTC+2): 18:00 lokal → 16:00 UTC.
    m = _meeting(meeting_date=date(2026, 6, 20))
    assert meeting_start_utc(m, TZ) == datetime(2026, 6, 20, 16, 0, tzinfo=UTC)  # type: ignore[arg-type]


def test_meeting_start_utc_midnight_without_time() -> None:
    m = _meeting(meeting_date=date(2026, 6, 20), start_time=None)
    assert meeting_start_utc(m, TZ) == datetime(2026, 6, 19, 22, 0, tzinfo=UTC)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# voting_delegation_check — sitzungsgebunden
# --------------------------------------------------------------------------- #
async def test_check_no_meeting_is_normal_without_query() -> None:
    db = fake_session()
    assert await voting_delegation_check(db, "me", None, str(GREMIUM_ID), NOW) == (
        False,
        None,
    )
    assert db.statements == []


async def test_check_non_uuid_group_is_normal() -> None:
    db = fake_session()
    assert await voting_delegation_check(db, "me", MEETING_ID, "stupa", NOW) == (
        False,
        None,
    )


async def test_check_outgoing_voting_blocked() -> None:
    # Zeile: (is_delegator, delegate_voting, delegator_sub)
    db = fake_session(result((True, True, "me")))
    assert await voting_delegation_check(db, "me", MEETING_ID, str(GREMIUM_ID), NOW) == (True, None)


async def test_check_incoming_voting_exercised() -> None:
    # Eingehende Stimm-Delegation → delegator_sub für die Vertretungs-Stimme.
    db = fake_session(result((False, True, "delegator-1")))
    assert await voting_delegation_check(db, "me", MEETING_ID, str(GREMIUM_ID), NOW) == (
        False,
        "delegator-1",
    )


async def test_check_nonvoting_rows_are_neutral() -> None:
    db = fake_session(result((True, False, "me"), (False, False, "other")))
    assert await voting_delegation_check(db, "me", MEETING_ID, str(GREMIUM_ID), NOW) == (
        False,
        None,
    )


# --------------------------------------------------------------------------- #
# create — happy paths
# --------------------------------------------------------------------------- #
def _happy_db(
    *,
    meeting: SimpleNamespace | None = None,
    gremium: SimpleNamespace | None = None,
    me: SimpleNamespace | None = None,
    delegate: SimpleNamespace | None = None,
    pool_ids: list[Any] | None = None,
    member_ids: list[Any] | None = None,
    existing: list[tuple[Any, Any, bool]] | None = None,
) -> Any:
    me = me or _me()
    delegate = delegate or _delegate()
    db = fake_session(
        result(me),  # _principal_row(sub)
        result(delegate),  # _principal_row(pid)
        result(["vote.cast"]),  # Eligibility: membership mit vote.cast
        result(*(pool_ids or [])),  # Pool-Empfänger
        result(*(member_ids if member_ids is not None else [delegate.id])),
        result(*(existing or [])),  # bestehende Delegationen der Sitzung
        result(),  # audit advisory lock
        result(),  # audit prev-hash
        _names((me.id, "Me", None), (delegate.id, "Other", None)),
    )
    db.get_results = [meeting or _meeting(), gremium or _gremium()]
    db._me = me  # type: ignore[attr-defined]
    db._delegate = delegate  # type: ignore[attr-defined]
    return db


async def test_create_persists_and_audits() -> None:
    db = _happy_db()
    out = await _svc(db).create(_payload(db._delegate.id), _actor())
    assert out.meeting_id == MEETING_ID
    assert out.gremium_id == GREMIUM_ID
    assert out.direction == "outgoing"
    assert out.revocable is True
    assert db.committed == 1
    persisted = [a for a in db.added if isinstance(a, MeetingDelegation)]
    assert len(persisted) == 1
    assert persisted[0].delegator_principal_id == db._me.id
    assert persisted[0].via_pool is False
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_create_voting_enabled_ok() -> None:
    db = _happy_db()
    out = await _svc(db, voting=True).create(_payload(db._delegate.id, voting=True), _actor())
    assert out.delegate_voting is True


async def test_create_pool_recipient_bypasses_lead_deadline() -> None:
    # Vorlauf 31 Tage, Sitzung in 30 → normale Deadline vorbei; Pool geht bis Beginn.
    delegate = _delegate()
    db = _happy_db(
        gremium=_gremium(lead=60 * 24 * 31),
        delegate=delegate,
        pool_ids=[delegate.id],
        member_ids=[],
    )
    out = await _svc(db).create(_payload(delegate.id), _actor())
    assert out.via_pool is True


async def test_create_external_allowed_when_flag_set() -> None:
    delegate = _delegate()
    db = _happy_db(gremium=_gremium(external=True), delegate=delegate, member_ids=[], pool_ids=[])
    out = await _svc(db).create(_payload(delegate.id), _actor())
    assert out.via_pool is False


# --------------------------------------------------------------------------- #
# create — Gates & Guards
# --------------------------------------------------------------------------- #
async def test_create_meeting_not_found_404() -> None:
    db = fake_session()
    db.get_results = [None]
    with pytest.raises(NotFoundError):
        await _svc(db).create(_payload(uuid4()), _actor())


async def test_create_gremium_gate_403() -> None:
    db = fake_session()
    db.get_results = [_meeting(), _gremium(allow=False)]
    with pytest.raises(ForbiddenError, match="not enabled"):
        await _svc(db).create(_payload(uuid4()), _actor())


async def test_create_voting_disabled_422() -> None:
    db = fake_session()
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ValidationProblem) as ei:
        await _svc(db, voting=False).create(_payload(uuid4(), voting=True), _actor())
    assert ei.value.status == 422
    assert db.committed == 0


async def test_create_meeting_started_422() -> None:
    db = fake_session()
    db.get_results = [_meeting(status="live"), _gremium()]
    with pytest.raises(ValidationProblem, match="started"):
        await _svc(db).create(_payload(uuid4()), _actor())


async def test_create_unknown_delegate_404() -> None:
    db = fake_session(result(_me()), result())  # me ok, delegate fehlt
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(NotFoundError):
        await _svc(db).create(_payload(uuid4()), _actor())


async def test_create_self_delegation_422() -> None:
    me = _me()
    db = fake_session(result(me), result(me))  # delegate == me
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ValidationProblem, match="yourself"):
        await _svc(db).create(_payload(me.id), _actor())


async def test_create_not_voting_member_403() -> None:
    # Eligibility-Queries alle leer: membership ohne vote.cast, kein direct,
    # keine OIDC-Gruppen → 403 (nur die eigene Stimme ist delegierbar).
    db = fake_session(
        result(_me()),
        result(_delegate()),
        result(),  # membership perms leer
        result(),  # direct assignment leer
        result((None,)),  # oidc_groups: None
    )
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="voting members"):
        await _svc(db).create(_payload(uuid4()), _actor())


async def test_create_external_without_flag_403() -> None:
    delegate = _delegate()
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(),  # Pool leer
        result(),  # Mitglieder leer → Empfänger ist extern
    )
    db.get_results = [_meeting(), _gremium(external=False)]
    with pytest.raises(ForbiddenError, match="substitute"):
        await _svc(db).create(_payload(delegate.id), _actor())


async def test_create_after_lead_deadline_422() -> None:
    # Sitzung in 30 Tagen, Vorlauf 31 Tage → Deadline liegt in der Vergangenheit.
    delegate = _delegate()
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(),  # Pool leer
        result(delegate.id),  # Mitglied
    )
    db.get_results = [_meeting(), _gremium(lead=60 * 24 * 31)]
    with pytest.raises(ValidationProblem, match="deadline"):
        await _svc(db).create(_payload(delegate.id), _actor())


async def test_create_pool_after_meeting_start_422() -> None:
    # Auch Pool-Delegationen enden mit Sitzungsbeginn (Sitzung gestern).
    delegate = _delegate()
    db = fake_session(
        result(_me()),
        result(delegate),
        result(["vote.cast"]),
        result(delegate.id),  # Pool
        result(),  # Mitglieder leer
    )
    db.get_results = [
        _meeting(meeting_date=PAST_DATE),
        _gremium(),
    ]
    with pytest.raises(ValidationProblem, match="deadline"):
        await _svc(db).create(_payload(delegate.id), _actor())


async def test_create_double_outgoing_409() -> None:
    db = _happy_db()
    me, delegate = db._me, db._delegate
    db._results[5] = result((me.id, uuid4(), False))  # bestehende eigene Zeile
    with pytest.raises(ConflictError, match="already delegated"):
        await _svc(db).create(_payload(delegate.id), _actor())


async def test_create_chain_when_actor_is_recipient_422() -> None:
    db = _happy_db()
    me, delegate = db._me, db._delegate
    db._results[5] = result((uuid4(), me.id, False))  # jemand delegiert an mich
    with pytest.raises(ValidationProblem, match="delegate on"):
        await _svc(db).create(_payload(delegate.id), _actor())


async def test_create_chain_when_recipient_delegated_away_422() -> None:
    db = _happy_db()
    delegate = db._delegate
    db._results[5] = result((delegate.id, uuid4(), False))  # Empfänger delegierte selbst
    with pytest.raises(ValidationProblem, match="delegated their own"):
        await _svc(db).create(_payload(delegate.id), _actor())


async def test_create_second_voting_delegation_to_same_recipient_409() -> None:
    db = _happy_db()
    delegate = db._delegate
    db._results[5] = result((uuid4(), delegate.id, True))  # trägt schon ein Stimmrecht
    with pytest.raises(ConflictError, match="carries"):
        await _svc(db, voting=True).create(_payload(delegate.id, voting=True), _actor())


# --------------------------------------------------------------------------- #
# list / revoke
# --------------------------------------------------------------------------- #
def _joined_row(
    me_id: Any, *, outgoing: bool = True, meeting: SimpleNamespace | None = None
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
    return (d, meeting or _meeting(), _gremium())


async def test_list_maps_direction_and_names() -> None:
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
    assert out[0].delegate_name == "Other"
    assert out[0].meeting_title == "Sitzung"


async def test_list_incoming_direction() -> None:
    me = _me()
    row = _joined_row(me.id, outgoing=False)
    db = fake_session(result(me), result(row), _names())
    out = await _svc(db).list(_actor())
    assert out[0].direction == "incoming"


async def test_list_without_principal_row_is_empty() -> None:
    db = fake_session(result())
    assert await _svc(db).list(_actor()) == []


async def test_revoke_deletes_and_audits() -> None:
    me = _me()
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=me.id)
    db = fake_session(result(me), result(), result())
    db.get_results = [row, _meeting()]
    await _svc(db).revoke(row.id, _actor())
    assert db.deleted == [row]
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_revoke_not_found_404() -> None:
    db = fake_session(result(_me()))
    with pytest.raises(NotFoundError):
        await _svc(db).revoke(uuid4(), _actor())


async def test_revoke_foreign_without_admin_403() -> None:
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_me()))
    db.get_results = [row]
    with pytest.raises(ForbiddenError):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_after_meeting_start_422() -> None:
    me = _me()
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=me.id)
    db = fake_session(result(me))
    db.get_results = [row, _meeting(status="live")]
    with pytest.raises(ValidationProblem, match="started"):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_admin_bypasses_deadline() -> None:
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_me()), result(), result())
    db.get_results = [row]  # kein Meeting-Lookup nötig (Admin)
    await _svc(db).revoke(row.id, _actor(perms={"admin.delegations"}))
    assert db.deleted == [row]


# --------------------------------------------------------------------------- #
# Stellvertreter-Pool
# --------------------------------------------------------------------------- #
async def test_substitute_create_requires_manage_403() -> None:
    db = fake_session(result())  # active_gremium_roles → leer
    payload = SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=uuid4())
    with pytest.raises(ForbiddenError, match="session.manage"):
        await _svc(db).substitute_create(payload, _actor())


async def test_substitute_create_admin_persists_and_audits() -> None:
    sub = _delegate()
    db = fake_session(
        result(sub),  # substitute principal
        result(),  # Duplikats-Probe leer
        result(),  # audit lock
        result(),  # audit prev
        _names((sub.id, "Sub", None)),
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitute_create(
        SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=sub.id),
        _actor(perms={"admin.delegations"}),
    )
    assert out.substitute_id == sub.id
    assert out.member_id is None
    assert db.committed == 1
    assert any(isinstance(a, DelegationSubstitute) for a in db.added)


async def test_substitute_create_duplicate_409() -> None:
    sub = _delegate()
    db = fake_session(result(sub), result(SimpleNamespace(id=uuid4())))
    db.get_results = [_gremium()]
    with pytest.raises(ConflictError):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_create_member_equals_substitute_422() -> None:
    sub = _delegate()
    db = fake_session(result(sub), result(sub))
    db.get_results = [_gremium()]
    with pytest.raises(ValidationProblem, match="differ"):
        await _svc(db).substitute_create(
            SubstituteCreate(gremiumId=GREMIUM_ID, memberId=sub.id, substituteId=sub.id),
            _actor(perms={"admin.delegations"}),
        )


async def test_substitute_delete_not_found_404() -> None:
    db = fake_session()
    with pytest.raises(NotFoundError):
        await _svc(db).substitute_delete(uuid4(), _actor(perms={"admin.delegations"}))


async def test_substitute_delete_ok() -> None:
    row = SimpleNamespace(id=uuid4(), gremium_id=GREMIUM_ID)
    db = fake_session(result(), result())  # audit lock + prev
    db.get_results = [row]
    await _svc(db).substitute_delete(row.id, _actor(perms={"admin.delegations"}))
    assert db.deleted == [row]


async def test_substitutes_list_resolves_names() -> None:
    row = SimpleNamespace(
        id=uuid4(),
        gremium_id=GREMIUM_ID,
        member_principal_id=None,
        substitute_principal_id=uuid4(),
        created_at=NOW,
    )
    db = fake_session(result(row), _names((row.substitute_principal_id, "Sub", None)))
    db.get_results = [_gremium()]
    out = await _svc(db).substitutes_list(GREMIUM_ID, _actor())
    assert out[0].substitute_name == "Sub"
    assert out[0].member_id is None


def test_module_exposes_voting_hook() -> None:
    assert hasattr(delegations_service, "voting_delegation_check")


def test_gremium_id_constant_is_uuid() -> None:
    assert isinstance(GREMIUM_ID, UUID)
    _ = timedelta  # genutzt von zukünftigen Fenster-Tests; Import stabil halten
