"""Unit tests for the faculty substitute groups (Z5) and the lead entry (O6).

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
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.delegations import service as service_mod
from app.modules.delegations.models import SubstituteGroup, SubstituteGroupMember
from app.modules.delegations.router import get_delegation_service
from app.modules.delegations.schemas import (
    DelegationCreate,
    SubstituteGroupCreate,
    SubstituteGroupMemberCreate,
    SubstituteGroupMemberOut,
    SubstituteGroupOut,
    SubstituteGroupUpdate,
)
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


def _group(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "gremium_id": GREMIUM_ID,
        "name_i18n": {"de": "Fakultät Informatik"},
        "position": 0,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _gm(group_id: UUID, kind: str, pid: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(group_id=group_id, principal_id=pid or uuid4(), kind=kind)


# ---------------------------------------------------------------- schemas


def test_group_create_cleans_the_name() -> None:
    body = SubstituteGroupCreate.model_validate(
        {"gremiumId": str(GREMIUM_ID), "nameI18n": {"de": " Informatik ", "en": "CS"}}
    )
    assert body.name_i18n == {"de": "Informatik", "en": "CS"}
    assert body.position == 0


@pytest.mark.parametrize(
    "name",
    [{}, {"fr": "Info"}, {"de": "  "}, {"de": "x" * 201}],
)
def test_group_create_refuses_a_bad_name(name: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SubstituteGroupCreate.model_validate({"gremiumId": str(GREMIUM_ID), "nameI18n": name})


def test_group_update_needs_one_field() -> None:
    with pytest.raises(ValidationError):
        SubstituteGroupUpdate.model_validate({})
    assert SubstituteGroupUpdate.model_validate({"position": 3}).name_i18n is None
    assert SubstituteGroupUpdate.model_validate({"nameI18n": {"en": "CS"}}).name_i18n == {
        "en": "CS"
    }


def test_member_create_refuses_an_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        SubstituteGroupMemberCreate.model_validate({"principalId": str(uuid4()), "kind": "x"})


# ---------------------------------------------------------------- group CRUD


async def test_groups_list_needs_view_rights() -> None:
    db = fake_session(result(), result())  # no membership, no pool
    db.get_results = [_gremium()]
    with pytest.raises(ForbiddenError):
        await _svc(db).substitute_groups_list(GREMIUM_ID, _actor())


async def test_groups_list_empty() -> None:
    db = fake_session(result())  # the groups
    db.get_results = [_gremium()]
    assert await _svc(db).substitute_groups_list(GREMIUM_ID, _actor(perms=_ADMIN)) == []


async def test_groups_list_builds_members_and_warning() -> None:
    g1, g2 = _group(), _group(position=1)
    member = uuid4()
    rows = [
        _gm(g1.id, "member", member),
        _gm(g1.id, "member"),
        _gm(g1.id, "substitute"),
        _gm(g1.id, "substitute"),
        _gm(g1.id, "substitute"),
        _gm(g2.id, "substitute"),
    ]
    db = fake_session(
        result(g1, g2),  # the groups
        result(*rows),  # their people
        result((member, "Mia", None)),  # the names
        result(member),  # active members of the gremium
    )
    db.get_results = [_gremium()]
    out = await _svc(db).substitute_groups_list(GREMIUM_ID, _actor(perms=_ADMIN))
    assert [g.id for g in out] == [g1.id, g2.id]
    first = out[0]
    assert first.too_many_substitutes is True
    assert out[1].too_many_substitutes is False
    actives = [(m.kind, m.active) for m in first.members]
    assert actives == [
        ("member", True),
        ("member", False),
        ("substitute", True),
        ("substitute", True),
        ("substitute", True),
    ]
    assert first.members[0].display_name == "Mia"


async def test_group_create_needs_manage_rights() -> None:
    db = fake_session(result())  # no session.manage role
    payload = SubstituteGroupCreate(gremiumId=GREMIUM_ID, nameI18n={"de": "Info"})
    with pytest.raises(ForbiddenError, match="session.manage"):
        await _svc(db).substitute_group_create(payload, _actor())


async def test_group_create_by_session_manage_persists_and_audits() -> None:
    db = fake_session(_lead_roles(), result(), result(), result(), result())
    db.get_results = [_gremium()]
    payload = SubstituteGroupCreate(gremiumId=GREMIUM_ID, nameI18n={"de": "Info"}, position=2)
    out = await _svc(db).substitute_group_create(payload, _actor())
    group = next(a for a in db.added if isinstance(a, SubstituteGroup))
    assert (group.gremium_id, group.position, group.created_by) == (GREMIUM_ID, 2, "lead")
    assert out.name_i18n == {"de": "Info"}
    assert out.members == []
    entry = next(a for a in db.added if type(a).__name__ == "AuditEntry")
    assert entry.action == "delegation_substitute_add"
    assert entry.target_type == "substitute_group"
    assert db.committed == 1


async def test_group_create_unknown_gremium_404() -> None:
    db = fake_session()
    payload = SubstituteGroupCreate(gremiumId=GREMIUM_ID, nameI18n={"de": "Info"})
    with pytest.raises(NotFoundError):
        await _svc(db).substitute_group_create(payload, _actor(perms=_ADMIN))


async def test_group_update_changes_fields() -> None:
    group = _group()
    db = fake_session(result(), result())  # people, active members
    db.get_results = [group]
    out = await _svc(db).substitute_group_update(
        group.id,
        SubstituteGroupUpdate(nameI18n={"en": "CS"}, position=4),
        _actor(perms=_ADMIN),
    )
    assert (group.name_i18n, group.position) == ({"en": "CS"}, 4)
    assert (out.name_i18n, out.position) == ({"en": "CS"}, 4)
    assert db.committed == 1


async def test_group_update_keeps_the_unset_fields() -> None:
    group = _group(position=7)
    db = fake_session(result(), result())
    db.get_results = [group]
    await _svc(db).substitute_group_update(
        group.id, SubstituteGroupUpdate(position=1), _actor(perms=_ADMIN)
    )
    assert (group.name_i18n, group.position) == ({"de": "Fakultät Informatik"}, 1)


async def test_group_update_name_only() -> None:
    group = _group(position=7)
    db = fake_session(result(), result())
    db.get_results = [group]
    await _svc(db).substitute_group_update(
        group.id, SubstituteGroupUpdate(nameI18n={"de": "Neu"}), _actor(perms=_ADMIN)
    )
    assert (group.name_i18n, group.position) == ({"de": "Neu"}, 7)


async def test_group_update_unknown_404() -> None:
    db = fake_session()
    with pytest.raises(NotFoundError, match="substitute group"):
        await _svc(db).substitute_group_update(
            uuid4(), SubstituteGroupUpdate(position=1), _actor(perms=_ADMIN)
        )


async def test_group_delete_audits_the_people() -> None:
    group = _group()
    member, sub = uuid4(), uuid4()
    db = fake_session(result((member, "member"), (sub, "substitute")), result(), result())
    db.get_results = [group]
    await _svc(db).substitute_group_delete(group.id, _actor(perms=_ADMIN))
    assert db.deleted == [group]
    entry = next(a for a in db.added if type(a).__name__ == "AuditEntry")
    assert entry.action == "delegation_substitute_remove"
    assert entry.data["memberIds"] == [str(member)]
    assert entry.data["substituteIds"] == [str(sub)]


async def test_group_delete_of_another_gremium_403() -> None:
    group = _group()
    db = fake_session(_lead_roles(uuid4()))  # session.manage in another gremium
    db.get_results = [group]
    with pytest.raises(ForbiddenError):
        await _svc(db).substitute_group_delete(group.id, _actor())


# ---------------------------------------------------------------- group people


async def test_member_add_persists_and_audits() -> None:
    group = _group()
    person = _person("p")
    db = fake_session(result(person), result(), result(), result(), result())
    db.get_results = [group, None]  # the group, not yet in the group
    out = await _svc(db).substitute_group_member_add(
        group.id,
        SubstituteGroupMemberCreate(principalId=person.id, kind="member"),
        _actor(perms=_ADMIN),
    )
    row = next(a for a in db.added if isinstance(a, SubstituteGroupMember))
    assert (row.group_id, row.principal_id, row.gremium_id, row.kind) == (
        group.id,
        person.id,
        GREMIUM_ID,
        "member",
    )
    entry = next(a for a in db.added if type(a).__name__ == "AuditEntry")
    assert entry.action == "delegation_substitute_add"
    assert entry.data["kind"] == "member"
    assert isinstance(out, SubstituteGroupOut)


async def test_substitute_add_skips_the_member_probe() -> None:
    group = _group()
    person = _person("p")
    db = fake_session(result(person), result(), result(), result(), result())
    db.get_results = [group, None]
    db.scalar_results = [uuid4()]  # would refuse a member, not a substitute
    await _svc(db).substitute_group_member_add(
        group.id,
        SubstituteGroupMemberCreate(principalId=person.id, kind="substitute"),
        _actor(perms=_ADMIN),
    )
    assert db.scalar_results  # not read


async def test_member_add_unknown_principal_404() -> None:
    db = fake_session(result())
    db.get_results = [_group()]
    with pytest.raises(NotFoundError, match="principal"):
        await _svc(db).substitute_group_member_add(
            uuid4(),
            SubstituteGroupMemberCreate(principalId=uuid4(), kind="member"),
            _actor(perms=_ADMIN),
        )


async def test_member_add_twice_409() -> None:
    person = _person("p")
    db = fake_session(result(person))
    db.get_results = [_group(), SimpleNamespace()]
    with pytest.raises(ConflictError, match="already in this group"):
        await _svc(db).substitute_group_member_add(
            uuid4(),
            SubstituteGroupMemberCreate(principalId=person.id, kind="substitute"),
            _actor(perms=_ADMIN),
        )


async def test_member_in_another_group_409() -> None:
    person = _person("p")
    db = fake_session(result(person))
    db.get_results = [_group(), None]
    db.scalar_results = [uuid4()]
    with pytest.raises(ConflictError, match="another group"):
        await _svc(db).substitute_group_member_add(
            uuid4(),
            SubstituteGroupMemberCreate(principalId=person.id, kind="member"),
            _actor(perms=_ADMIN),
        )


class _RacingSession(FakeSession):
    async def flush(self) -> None:
        raise IntegrityError("insert", {}, Exception("uq"))


async def test_member_add_race_409() -> None:
    person = _person("p")
    db = _RacingSession([result(person)])
    db.get_results = [_group(), None]
    with pytest.raises(ConflictError, match="same time"):
        await _svc(db).substitute_group_member_add(
            uuid4(),
            SubstituteGroupMemberCreate(principalId=person.id, kind="member"),
            _actor(perms=_ADMIN),
        )
    assert db.rolled_back == 1


async def test_member_remove_deletes_and_audits() -> None:
    group = _group()
    row = _gm(group.id, "substitute")
    db = fake_session(result(), result())
    db.get_results = [group, row]
    await _svc(db).substitute_group_member_remove(group.id, row.principal_id, _actor(perms=_ADMIN))
    assert db.deleted == [row]
    entry = next(a for a in db.added if type(a).__name__ == "AuditEntry")
    assert entry.action == "delegation_substitute_remove"
    assert entry.data["kind"] == "substitute"


async def test_member_remove_unknown_404() -> None:
    db = fake_session()
    db.get_results = [_group(), None]
    with pytest.raises(NotFoundError, match="is not in group"):
        await _svc(db).substitute_group_member_remove(uuid4(), uuid4(), _actor(perms=_ADMIN))


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


async def test_lead_entry_reads_the_pool_without_the_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O6: the lead entry asks the pool helper without the faculty groups."""
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
    assert seen == [{"gremium": GREMIUM_ID, "member": a.id, "include_groups": False}]


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
    assert out[0].substitute_group_name is None


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


class _GroupService:
    def _out(self, gremium_id: UUID | None = None) -> SubstituteGroupOut:
        return SubstituteGroupOut(
            id=uuid4(),
            gremium_id=gremium_id or GREMIUM_ID,
            name_i18n={"de": "Info"},
            position=0,
            members=[
                SubstituteGroupMemberOut(
                    principal_id=uuid4(), display_name="Mia", kind="member", active=True
                )
            ],
            too_many_substitutes=False,
        )

    async def substitute_groups_list(self, gremium_id: UUID, actor: Any) -> list[Any]:
        return [self._out(gremium_id)]

    async def substitute_group_create(self, payload: Any, actor: Any) -> Any:
        return self._out(payload.gremium_id)

    async def substitute_group_update(self, group_id: UUID, payload: Any, actor: Any) -> Any:
        if str(group_id).startswith("00000000"):
            raise NotFoundError("nope")
        return self._out()

    async def substitute_group_delete(self, group_id: UUID, actor: Any) -> None:
        if str(group_id).startswith("11111111"):
            raise ForbiddenError("not yours")

    async def substitute_group_member_add(self, group_id: UUID, payload: Any, actor: Any) -> Any:
        if payload.kind == "member" and str(group_id).startswith("22222222"):
            raise ConflictError("dup", code="conflict")
        return self._out()

    async def substitute_group_member_remove(
        self, group_id: UUID, principal_id: UUID, actor: Any
    ) -> None:
        return None

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


def test_router_lists_groups_in_camel_case() -> None:
    r = _client(_GroupService(), _MEMBER).get(
        f"/api/delegations/substitute-groups?gremiumId={GREMIUM_ID}"
    )
    assert r.status_code == 200, r.text
    item = r.json()[0]
    assert {"gremiumId", "nameI18n", "position", "members", "tooManySubstitutes"} <= item.keys()
    assert item["members"][0] == {
        "principalId": item["members"][0]["principalId"],
        "displayName": "Mia",
        "kind": "member",
        "active": True,
    }


def test_router_needs_a_session() -> None:
    r = _client(_GroupService()).get(f"/api/delegations/substitute-groups?gremiumId={uuid4()}")
    assert r.status_code == 401


def test_router_creates_updates_and_deletes() -> None:
    client = _client(_GroupService(), _MEMBER)
    created = client.post(
        "/api/delegations/substitute-groups",
        json={"gremiumId": str(GREMIUM_ID), "nameI18n": {"de": "Info"}},
    )
    bad = client.post(
        "/api/delegations/substitute-groups",
        json={"gremiumId": str(GREMIUM_ID), "nameI18n": {}},
    )
    patched = client.patch(f"/api/delegations/substitute-groups/{uuid4()}", json={"position": 1})
    missing = client.patch(
        "/api/delegations/substitute-groups/00000000-0000-0000-0000-000000000000",
        json={"position": 1},
    )
    empty = client.patch(f"/api/delegations/substitute-groups/{uuid4()}", json={})
    deleted = client.delete(f"/api/delegations/substitute-groups/{uuid4()}")
    foreign = client.delete(
        "/api/delegations/substitute-groups/11111111-1111-1111-1111-111111111111"
    )
    assert created.status_code == 201, created.text
    assert bad.status_code == 422
    assert patched.status_code == 200
    assert missing.status_code == 404
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert empty.status_code == 422
    assert deleted.status_code == 204
    assert foreign.status_code == 403


def test_router_adds_and_removes_people() -> None:
    client = _client(_GroupService(), _MEMBER)
    gid = uuid4()
    added = client.post(
        f"/api/delegations/substitute-groups/{gid}/members",
        json={"principalId": str(uuid4()), "kind": "substitute"},
    )
    dup = client.post(
        "/api/delegations/substitute-groups/22222222-2222-2222-2222-222222222222/members",
        json={"principalId": str(uuid4()), "kind": "member"},
    )
    removed = client.delete(f"/api/delegations/substitute-groups/{gid}/members/{uuid4()}")
    assert added.status_code == 201, added.text
    assert dup.status_code == 409
    assert removed.status_code == 204


def test_router_passes_the_delegator_id() -> None:
    service = _GroupService()
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
