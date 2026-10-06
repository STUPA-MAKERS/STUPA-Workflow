"""Unit tests for the lead entry during a live meeting (O6).

The fake session answers each `execute`, `get` and `scalar` from a queue. The
conftest of this package replaces the pool helpers in the service with helpers
that read one queued result each. The integration suite proves the SQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.delegations import service as service_mod
from app.modules.delegations.router import get_delegation_service
from app.modules.delegations.schemas import DelegationCreate
from app.modules.delegations.service import DelegationService
from app.settings import load_settings
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from tests._support.flow_fakes import FakeSession, fake_session, result

GREMIUM_ID = uuid4()
MEETING_ID = uuid4()
FUTURE = (datetime.now(UTC) + timedelta(days=30)).date()
_ADMIN = {"admin.delegations"}


def _svc(db: Any, *, voting: bool = True) -> DelegationService:
    return DelegationService(db, load_settings(delegation_voting_enabled=voting))


def _actor(sub: str = "lead", perms: set[str] | None = None) -> Principal:
    return Principal(sub=sub, roles=["member"], permissions=perms or set())


def _lead_roles(gremium_id: UUID = GREMIUM_ID) -> Any:
    """Result of `active_gremium_roles`: a role with `session.manage` in the gremium."""
    return result((gremium_id, SimpleNamespace(permissions=["session.manage"])))


def _meeting(status: str = "live", meeting_date: date | None = FUTURE) -> SimpleNamespace:
    return SimpleNamespace(
        id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        title="Sitzung",
        date=meeting_date,
        start_time=time(18, 0),
        status=status,
    )


def _gremium(*, allow: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=GREMIUM_ID,
        name="StuPa",
        allow_vote_delegation=allow,
        delegation_lead_minutes=0,
        delegation_allow_external=False,
    )


def _person(sub: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), sub=sub)


# ---------------------------------------------------------------- O6 lead entry


def _lead_payload(a: Any, b: Any, *, voting: bool = True) -> DelegationCreate:
    return DelegationCreate(
        meetingId=MEETING_ID, delegateId=b.id, delegatorId=a.id, delegateVoting=voting
    )


def _lead_db(*tail: Any, meeting: Any = None, gremium: Any = None) -> FakeSession:
    """Queue the reads of a lead entry: meeting, gremium, then the locked meeting."""
    db = fake_session(_lead_roles(), *tail)
    meeting = meeting or _meeting()
    db.get_results = [meeting, gremium or _gremium(), meeting]
    return db


class _LockSpySession(FakeSession):
    """Fake session that records the keyword arguments of each `get`."""

    def __init__(self, *results: Any) -> None:
        super().__init__(results)
        self.get_kwargs: list[dict[str, Any]] = []

    async def get(self, model: Any, ident: Any, **kw: Any) -> Any:
        self.get_kwargs.append(kw)
        return await super().get(model, ident, **kw)


async def test_lead_entry_for_missing_member() -> None:
    a, b = _person("a"), _person("b")
    db = _lead_db(
        result(a),
        result(b),
        result(["vote.cast"]),  # A may vote
        result(b.id),  # B is in the pool for A
        result(),  # advisory lock
        result(),  # existing delegations
        result(),  # audit lock
        result(),  # audit prev
        result((a.id, "A", None), (b.id, "B", None)),  # names
    )
    db.scalar_results = ["absent"]
    out = await _svc(db).create(_lead_payload(a, b), _actor())
    assert (out.delegator_id, out.delegate_id, out.via_pool) == (a.id, b.id, True)
    assert out.delegate_voting is True
    assert out.revocable is True  # the lead revokes while live
    assert out.direction is None
    entry = next(x for x in db.added if type(x).__name__ == "AuditEntry")
    assert entry.data["byLead"] is True
    assert entry.data["delegatorId"] == str(a.id)
    row = next(x for x in db.added if type(x).__name__ == "MeetingDelegation")
    assert row.created_by == "lead"


async def test_lead_entry_without_attendance_record() -> None:
    a, b = _person("a"), _person("b")
    db = _lead_db(
        result(a),
        result(b),
        result(["vote.cast"]),
        result(b.id),
        result(),
        result(),
        result(),
        result(),
        result(),
    )
    out = await _svc(db).create(_lead_payload(a, b, voting=False), _actor())
    assert out.delegate_voting is False


async def test_lead_entry_needs_the_lead() -> None:
    db = fake_session(result())  # no session.manage
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="meeting lead"):
        await _svc(db).create(_lead_payload(_person("a"), _person("b")), _actor())


async def test_lead_entry_needs_the_gremium_gate() -> None:
    db = _lead_db(gremium=_gremium(allow=False))
    with pytest.raises(ForbiddenError, match="not enabled"):
        await _svc(db).create(_lead_payload(_person("a"), _person("b")), _actor())


async def test_lead_entry_needs_the_voting_switch() -> None:
    db = _lead_db()
    with pytest.raises(ValidationProblem, match="disabled"):
        await _svc(db, voting=False).create(_lead_payload(_person("a"), _person("b")), _actor())


@pytest.mark.parametrize("status", ["planned", "closed"])
async def test_lead_entry_only_while_live(status: str) -> None:
    db = _lead_db(meeting=_meeting(status))
    with pytest.raises(ValidationProblem, match="live"):
        await _svc(db).create(_lead_payload(_person("a"), _person("b")), _actor())


async def test_lead_entry_unknown_delegator_404() -> None:
    db = _lead_db(result())
    with pytest.raises(NotFoundError):
        await _svc(db).create(_lead_payload(_person("a"), _person("b")), _actor())


async def test_lead_entry_unknown_delegate_404() -> None:
    a = _person("a")
    db = _lead_db(result(a), result())
    with pytest.raises(NotFoundError):
        await _svc(db).create(_lead_payload(a, _person("b")), _actor())


async def test_lead_entry_same_person_422() -> None:
    a = _person("a")
    db = _lead_db(result(a), result(a))
    with pytest.raises(ValidationProblem, match="themselves"):
        await _svc(db).create(_lead_payload(a, a), _actor())


async def test_lead_entry_refuses_the_lead_as_substitute() -> None:
    """The member does not consent, so the lead cannot take the vote."""
    a, lead = _person("a"), _person("lead")
    db = _lead_db(result(a), result(lead))
    with pytest.raises(ForbiddenError, match="themselves as the substitute"):
        await _svc(db).create(_lead_payload(a, lead), _actor("lead"))
    assert not db.added


async def test_lead_entry_locks_the_meeting_row() -> None:
    """The lead entry reads the meeting FOR UPDATE before the attendance read (O23)."""
    a, b = _person("a"), _person("b")
    db = _LockSpySession(
        _lead_roles(),
        result(a),
        result(b),
        result(["vote.cast"]),
        result(b.id),
    )
    db.get_results = [_meeting(), _gremium(), _meeting()]
    db.scalar_results = ["present"]
    with pytest.raises(ValidationProblem, match="present"):
        await _svc(db).create(_lead_payload(a, b), _actor())
    assert db.get_kwargs[2] == {"with_for_update": True, "populate_existing": True}
    assert db.get_kwargs[0] == {}


async def test_lead_entry_rechecks_the_status_under_the_lock() -> None:
    """A meeting that closed before the lock gives 422, though the first read saw it live."""
    db = fake_session(_lead_roles())
    db.get_results = [_meeting("live"), _gremium(), _meeting("closed")]
    with pytest.raises(ValidationProblem, match="live"):
        await _svc(db).create(_lead_payload(_person("a"), _person("b")), _actor())


async def test_lead_entry_needs_a_voting_member() -> None:
    a, b = _person("a"), _person("b")
    db = _lead_db(result(a), result(b), result())
    with pytest.raises(ForbiddenError, match="voting member"):
        await _svc(db).create(_lead_payload(a, b), _actor())


async def test_lead_entry_refuses_a_present_member() -> None:
    a, b = _person("a"), _person("b")
    db = _lead_db(result(a), result(b), result(["vote.cast"]))
    db.scalar_results = ["present"]
    with pytest.raises(ValidationProblem, match="present"):
        await _svc(db).create(_lead_payload(a, b), _actor())


async def test_lead_entry_needs_a_pool_substitute() -> None:
    a, b = _person("a"), _person("b")
    db = _lead_db(result(a), result(b), result(["vote.cast"]), result(uuid4()))
    db.scalar_results = ["excused"]
    with pytest.raises(ForbiddenError, match="pool substitute"):
        await _svc(db).create(_lead_payload(a, b), _actor())


async def test_lead_entry_refuses_a_second_delegation_409() -> None:
    a, b = _person("a"), _person("b")
    db = _lead_db(
        result(a),
        result(b),
        result(["vote.cast"]),
        result(b.id),
        result(),
        result((a.id, uuid4(), False)),  # A already delegated
    )
    with pytest.raises(ConflictError, match="already delegated"):
        await _svc(db).create(_lead_payload(a, b), _actor())


async def test_lead_entry_reads_the_pool_of_the_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O6: the lead entry asks the pool helper for the missing member."""
    a, b = _person("a"), _person("b")
    seen: list[dict[str, Any]] = []

    async def spy(
        _session: Any, gremium_id: UUID, member_id: UUID, *_a: Any, **kw: Any
    ) -> set[UUID]:
        seen.append({"gremium": gremium_id, "member": member_id, **kw})
        return set()

    monkeypatch.setattr(service_mod, "substitutes_for", spy)
    db = _lead_db(result(a), result(b), result(["vote.cast"]))
    with pytest.raises(ForbiddenError, match="pool substitute"):
        await _svc(db).create(_lead_payload(a, b), _actor())
    assert seen == [{"gremium": GREMIUM_ID, "member": a.id}]


def _lead_view_db(*tail: Any) -> FakeSession:
    """Queue the reads of the lead recipient list: view guard, then the lead check."""
    db = fake_session(_lead_roles(), _lead_roles(), *tail)
    db.get_results = [_meeting(), _gremium()]
    return db


async def test_lead_recipients_list_the_pool_of_the_member() -> None:
    """O6: the lead gets the pool substitutes of A, without A and without the lead."""
    lead, a = _person("lead"), _person("a")
    bert, carla = uuid4(), uuid4()
    db = _lead_view_db(
        result(lead),  # the lead
        result(bert, carla, lead.id, a.id),  # pool for A
        result(carla),  # members
        result((bert, "Bert", None), (carla, None, "carla@x.de")),  # names
    )
    out = await _svc(db).recipients(MEETING_ID, "", _actor(), a.id)
    assert [(r.principal_id, r.via_pool, r.is_member) for r in out] == [
        (bert, True, False),
        (carla, True, True),
    ]


async def test_lead_recipients_filter_by_the_needle() -> None:
    a = _person("a")
    bert, carla = uuid4(), uuid4()
    db = _lead_view_db(
        result(),  # no principal row for the lead
        result(bert, carla),
        result(),
        result((bert, "Bert", None), (carla, "Carla", None)),
    )
    out = await _svc(db).recipients(MEETING_ID, " car ", _actor(), a.id)
    assert [r.principal_id for r in out] == [carla]


async def test_lead_recipients_need_the_lead() -> None:
    """A member sees the roster but cannot list the pool of another member (403)."""
    member = result((GREMIUM_ID, SimpleNamespace(permissions=[])))
    db = fake_session(member, result())
    db.get_results = [_meeting(), _gremium()]
    with pytest.raises(ForbiddenError, match="meeting lead"):
        await _svc(db).recipients(MEETING_ID, "", _actor("m"), uuid4())


# ---------------------------------------------------------------- list and revoke


async def test_list_for_the_lead_shows_the_whole_meeting() -> None:
    me = _person("lead")
    other = SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=uuid4(),
        delegate_principal_id=uuid4(),
        delegate_voting=True,
        via_pool=True,
        created_at=datetime.now(UTC),
    )
    db = fake_session(
        result(me),  # me
        _lead_roles(),  # can_manage
        result((other, _meeting(), _gremium())),  # every delegation of the meeting
        result(),  # names
    )
    db.get_results = [_meeting()]
    out = await _svc(db).list(_actor(), MEETING_ID)
    assert [o.id for o in out] == [other.id]
    assert out[0].revocable is True
    where = str(db.statements[2]).split("WHERE", 1)[1]
    assert "delegator_principal_id" not in where


def _row(delegator: UUID, delegate: UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        meeting_id=MEETING_ID,
        gremium_id=GREMIUM_ID,
        delegator_principal_id=delegator,
        delegate_principal_id=delegate,
        delegate_voting=True,
        via_pool=False,
        created_at=datetime.now(UTC),
    )


async def test_list_for_the_lead_before_the_start_marks_only_own_rows() -> None:
    """Before the start the lead revokes only the own delegation, not the others."""
    me = _person("lead")
    planned = _meeting("planned")
    foreign = _row(uuid4(), uuid4())
    own = _row(me.id, uuid4())
    db = fake_session(
        result(me),
        _lead_roles(),
        result((foreign, planned, _gremium()), (own, planned, _gremium())),
        result(),
    )
    db.get_results = [planned]
    out = await _svc(db).list(_actor(), MEETING_ID)
    assert {o.id: o.revocable for o in out} == {foreign.id: False, own.id: True}


async def test_list_for_the_admin_marks_foreign_rows_before_the_start() -> None:
    """The admin may revoke every delegation, so a foreign row stays revocable."""
    me = _person("root")
    planned = _meeting("planned")
    foreign = _row(uuid4(), uuid4())
    db = fake_session(result(me), result((foreign, planned, _gremium())), result())
    out = await _svc(db).list(_actor("root", _ADMIN))
    assert [o.revocable for o in out] == [True]


async def test_list_for_a_member_with_meeting_filter() -> None:
    me = _person("m")
    db = fake_session(result(me), result(), result())
    db.get_results = [_meeting()]
    assert await _svc(db).list(_actor("m"), MEETING_ID) == []


async def test_list_unknown_meeting_is_empty() -> None:
    db = fake_session(result(), result())
    assert await _svc(db).list(_actor("m"), MEETING_ID) == []


async def test_revoke_by_lead_while_live() -> None:
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(_lead_roles(), result(), result())
    db.get_results = [row, _meeting()]
    await _svc(db).revoke(row.id, _actor())
    assert db.deleted == [row]
    entry = next(x for x in db.added if type(x).__name__ == "AuditEntry")
    assert entry.data["byLead"] is True
    assert entry.data["delegatorId"] == str(row.delegator_principal_id)


async def test_revoke_by_lead_of_a_planned_meeting_403() -> None:
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result(_person("lead")))
    db.get_results = [row, _meeting("planned")]
    with pytest.raises(ForbiddenError, match="meeting lead"):
        await _svc(db).revoke(row.id, _actor())


async def test_revoke_unknown_principal_403() -> None:
    row = SimpleNamespace(id=uuid4(), meeting_id=MEETING_ID, delegator_principal_id=uuid4())
    db = fake_session(result())
    db.get_results = [row, _meeting("planned")]
    with pytest.raises(ForbiddenError):
        await _svc(db).revoke(row.id, _actor())


# ---------------------------------------------------------------- router


class _CreateService:
    async def create(self, payload: Any, actor: Any) -> Any:
        self.created = payload
        raise ForbiddenError("stop")


def _client(service: Any, principal: Principal | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_delegation_service] = lambda: service
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app, raise_server_exceptions=False)


_MEMBER = Principal(sub="lead", roles=["member"], permissions=set())


def test_router_passes_the_delegator_id() -> None:
    service = _CreateService()
    a = uuid4()
    r = _client(service, _MEMBER).post(
        "/api/delegations",
        json={"meetingId": str(MEETING_ID), "delegateId": str(uuid4()), "delegatorId": str(a)},
    )
    assert r.status_code == 403
    assert service.created.delegator_id == a


async def test_lead_entry_by_the_admin_role() -> None:
    """The admin role passes the lead check through the bypass, without a gremium role."""
    a, b = _person("a"), _person("b")
    db = fake_session(
        result(a),
        result(b),
        result(["vote.cast"]),
        result(b.id),
        result(),
        result(),
        result(),
        result(),
        result(),
    )
    db.get_results = [_meeting(), _gremium(), _meeting()]
    admin = Principal(sub="root", roles=["admin"])
    out = await _svc(db).create(_lead_payload(a, b), admin)
    assert out.delegator_id == a.id
