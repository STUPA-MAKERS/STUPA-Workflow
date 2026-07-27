"""Recipient resolver tests (T-18). `FakeSession` answers every database query."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.flow.models import State, Transition
from app.modules.notifications import recipients as recipients_mod
from app.modules.notifications.recipients import (
    ADMIN_ROLE_KEY,
    ActionableCandidate,
    RecipientResolver,
    _candidates_with_transition_permission,
    actionable_principal_emails,
    firable_candidates,
    principal_rows_with_permission_stmt,
    principals_with_permission_stmt,
)
from app.shared.guards import GuardContext
from tests._support.notifications_fakes import FakeSession


def _sql(perm: str, **kw: object) -> str:
    stmt = principals_with_permission_stmt(perm, datetime.now(UTC), **kw)  # type: ignore[arg-type]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _resolver(session: FakeSession) -> RecipientResolver:
    return RecipientResolver(cast(AsyncSession, session))


async def test_resolve_group_filters_none_and_sorts() -> None:
    session = FakeSession(scalars=[["b@y.de", None, "a@x.de"]])
    out = await _resolver(session).resolve([{"kind": "group", "ref": "stupa"}])
    assert out == ["a@x.de", "b@y.de"]


async def test_resolve_role() -> None:
    session = FakeSession(scalars=[["c@x.de"]])
    out = await _resolver(session).resolve([{"kind": "role", "ref": "manager"}])
    assert out == ["c@x.de"]


async def test_resolve_applicant() -> None:
    session = FakeSession(scalar=["d@x.de"])
    out = await _resolver(session).resolve(
        [{"kind": "applicant"}], application_id=uuid.uuid4()
    )
    assert out == ["d@x.de"]


async def test_resolve_applicant_no_email_skipped() -> None:
    session = FakeSession(scalar=[None])
    out = await _resolver(session).resolve(
        [{"kind": "applicant"}], application_id=uuid.uuid4()
    )
    assert out == []


async def test_resolve_applicant_without_application_id_ignored() -> None:
    out = await _resolver(FakeSession()).resolve([{"kind": "applicant"}])
    assert out == []


async def test_resolve_unknown_and_incomplete_specs_ignored() -> None:
    out = await _resolver(FakeSession()).resolve(
        [{"kind": "group"}, {"kind": "weird", "ref": "x"}, {}]
    )
    assert out == []


async def test_resolve_dedup_across_specs() -> None:
    session = FakeSession(scalars=[["a@x.de"], ["a@x.de", "b@y.de"]])
    out = await _resolver(session).resolve(
        [{"kind": "group", "ref": "g"}, {"kind": "role", "ref": "r"}]
    )
    assert out == ["a@x.de", "b@y.de"]


# AUD-057: the admin bypass of the recipient lookup is ONE central query with ONE admin
# key. No duplicate `Role.key == "admin"` literal is left.


def test_admin_role_key_matches_principal_has_bypass() -> None:
    # `Principal.has` bypasses through `ADMIN_ROLE_KEY in roles`. The set query MUST use
    # the same key, otherwise the notification diverges.
    admin = Principal(sub="s", roles=[ADMIN_ROLE_KEY], permissions=set())
    assert admin.has("any.perm") is True
    non_admin = Principal(sub="s", roles=["editor"], permissions=set())
    assert non_admin.has("any.perm") is False


def test_permission_stmt_includes_admin_bypass_via_constant() -> None:
    sql = _sql("application.transition")
    # The admin bypass uses the central constant, not a literal per resolver.
    assert f"key = '{ADMIN_ROLE_KEY}'" in sql
    assert "permission = 'application.transition'" in sql
    # The active flag and the validity window of the assignment apply too.
    assert "active" in sql
    assert "valid_from" in sql and "valid_until" in sql


def test_permission_stmt_gremium_scope_optional() -> None:
    gid = uuid.uuid4()
    scoped = _sql("application.transition", gremium_id=gid)
    unscoped = _sql("application.transition")
    assert "gremium_id" in scoped
    # Without gremium_id there is NO Gremium filter, so the recipient set is global.
    assert "gremium_id" not in unscoped


def test_both_resolvers_share_one_query_builder() -> None:
    # Both actionable_principal_emails (task mail) and _emails_for_permission (rule
    # recipient) build the same admin bypass. The identical core clause for the same
    # permission proves it.
    rule_sql = _sql("application.transition")
    assert rule_sql.count(f"key = '{ADMIN_ROLE_KEY}'") == 1


# #task-recipients: identity row seed statement
def _rows_sql(perm: str, **kw: object) -> str:
    stmt = principal_rows_with_permission_stmt(perm, datetime.now(UTC), **kw)  # type: ignore[arg-type]
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_rows_stmt_projects_identity_columns() -> None:
    sql = _rows_sql("application.transition")
    for col in (
        "principal.id",
        "principal.sub",
        "principal.email",
        "principal.oidc_groups",
    ):
        assert col in sql
    assert "DISTINCT" in sql


def test_rows_stmt_shares_permission_conds_with_email_stmt() -> None:
    # Same seed clauses as the email projection: admin arm, permission arm,
    # active flag and the assignment validity window.
    sql = _rows_sql("application.transition")
    assert f"key = '{ADMIN_ROLE_KEY}'" in sql
    assert "permission = 'application.transition'" in sql
    assert "active" in sql
    assert "valid_from" in sql and "valid_until" in sql


def test_rows_stmt_gremium_scope_optional() -> None:
    gid = uuid.uuid4()
    assert "gremium_id" in _rows_sql("application.transition", gremium_id=gid)
    assert "gremium_id" not in _rows_sql("application.transition")


# firable_candidates: pure guard matrix (task-list parity, #64)
BASE_CTX = GuardContext(manual=True)


def _candidate(
    *,
    sub: str = "sub-1",
    email: str = "one@x.de",
    roles: frozenset[str] = frozenset(),
    committees: frozenset[str] = frozenset(),
) -> ActionableCandidate:
    return ActionableCandidate(
        principal_id=uuid.uuid4(),
        sub=sub,
        email=email,
        roles=roles,
        committees=committees,
    )


def _transitions(*guards: object) -> list[Transition]:
    return cast("list[Transition]", [SimpleNamespace(guard=g) for g in guards])


def test_firable_open_transition_includes_every_candidate() -> None:
    candidates = [
        _candidate(sub="a", email="a@x.de", roles=frozenset({"chair"})),
        _candidate(sub="b", email="b@x.de"),
    ]
    out = firable_candidates(candidates, _transitions(None), BASE_CTX, created_by=None)
    assert out == candidates


def test_firable_role_gate_pass_and_fail() -> None:
    chair = _candidate(sub="a", email="a@x.de", roles=frozenset({"chair"}))
    other = _candidate(sub="b", email="b@x.de", roles=frozenset({"member"}))
    out = firable_candidates(
        [chair, other], _transitions({"roleIs": "chair"}), BASE_CTX, created_by=None
    )
    assert out == [chair]


def test_firable_committee_gate_pass_and_fail() -> None:
    gid = str(uuid.uuid4())
    member = _candidate(sub="a", email="a@x.de", committees=frozenset({gid}))
    outsider = _candidate(sub="b", email="b@x.de")
    out = firable_candidates(
        [member, outsider],
        _transitions({"isInCommittee": gid}),
        BASE_CTX,
        created_by=None,
    )
    assert out == [member]


def test_firable_actor_is_applicant_via_created_by() -> None:
    creator = _candidate(sub="creator", email="c@x.de")
    other = _candidate(sub="other", email="o@x.de")
    guard = {"actorIsApplicant": True}
    out = firable_candidates(
        [creator, other], _transitions(guard), BASE_CTX, created_by="creator"
    )
    assert out == [creator]
    # created_by None -> nobody counts as applicant.
    assert (
        firable_candidates([creator], _transitions(guard), BASE_CTX, created_by=None)
        == []
    )


def test_firable_admin_with_only_unsatisfied_guards_excluded() -> None:
    # THE bug (#task-recipients): admins got task mail even without a firable
    # transition. The code now drops an admin without a matching guard gate.
    admin = _candidate(sub="adm", email="admin@x.de", roles=frozenset({ADMIN_ROLE_KEY}))
    out = firable_candidates(
        [admin], _transitions({"roleIs": "chair"}), BASE_CTX, created_by=None
    )
    assert out == []


def test_firable_admin_with_open_transition_included() -> None:
    admin = _candidate(sub="adm", email="admin@x.de", roles=frozenset({ADMIN_ROLE_KEY}))
    out = firable_candidates([admin], _transitions(None), BASE_CTX, created_by=None)
    assert out == [admin]


def test_firable_guard_error_counts_as_not_firable() -> None:
    # Two operators in one guard -> GuardError -> fail-closed, no exception.
    broken = {"roleIs": "chair", "isInCommittee": "g"}
    chair = _candidate(sub="a", email="a@x.de", roles=frozenset({"chair"}))
    assert (
        firable_candidates([chair], _transitions(broken), BASE_CTX, created_by=None)
        == []
    )


def test_firable_guard_error_then_open_transition_still_counts() -> None:
    broken = {"roleIs": "chair", "isInCommittee": "g"}
    candidate = _candidate(sub="a", email="a@x.de")
    out = firable_candidates(
        [candidate], _transitions(broken, None), BASE_CTX, created_by=None
    )
    assert out == [candidate]


def test_firable_second_transition_can_fire() -> None:
    chair = _candidate(sub="a", email="a@x.de", roles=frozenset({"chair"}))
    out = firable_candidates(
        [chair],
        _transitions({"roleIs": "other"}, {"roleIs": "chair"}),
        BASE_CTX,
        created_by=None,
    )
    assert out == [chair]


def test_firable_empty_transitions_empty() -> None:
    assert firable_candidates([_candidate()], [], BASE_CTX, created_by=None) == []


async def test_candidates_batch_resolution_roles_groups_committees() -> None:
    pid1, pid2 = uuid.uuid4(), uuid.uuid4()
    g_scope, g_member = uuid.uuid4(), uuid.uuid4()
    session = FakeSession(
        executes=[
            # Seed: (id, sub, email, oidc_groups)
            [
                (pid1, "s1", "one@x.de", ["idp-group"]),
                (pid2, "s2", "two@x.de", None),
            ],
            # Active RoleAssignments: (principal_id, Role.key, gremium_id)
            [
                (pid1, "chair", None),
                (pid2, "admin", g_scope),
            ],
            # GroupMappings: (oidc_group, Role.key)
            [
                ("idp-group", "mapped-role"),
                (str(g_scope), "scope-role"),
            ],
            # Active GremiumMemberships: (principal_id, gremium_id)
            [(pid1, g_member)],
        ]
    )
    out = await _candidates_with_transition_permission(
        cast(AsyncSession, session), datetime.now(UTC), gremium_id=None
    )
    by_sub = {c.sub: c for c in out}
    assert by_sub["s1"].email == "one@x.de"
    assert by_sub["s1"].roles == frozenset({"chair", "mapped-role"})
    assert by_sub["s1"].committees == frozenset({str(g_member)})
    # Assignment gremium scope counts as a group key (parity with resolve_principal).
    assert by_sub["s2"].roles == frozenset({"admin", "scope-role"})
    assert by_sub["s2"].committees == frozenset()


async def test_candidates_empty_seed_returns_early() -> None:
    session = FakeSession(executes=[[]])
    out = await _candidates_with_transition_permission(
        cast(AsyncSession, session), datetime.now(UTC), gremium_id=uuid.uuid4()
    )
    assert out == []


async def test_candidates_rows_without_email_skipped() -> None:
    session = FakeSession(executes=[[(uuid.uuid4(), "s1", None, None)]])
    out = await _candidates_with_transition_permission(
        cast(AsyncSession, session), datetime.now(UTC), gremium_id=None
    )
    assert out == []


async def test_candidates_no_groups_skips_mapping_query() -> None:
    # Without any group (no OIDC group and no assignment scope) the membership query
    # comes next. The FIFO queue proves that the code issues no mapping query.
    pid, gid = uuid.uuid4(), uuid.uuid4()
    session = FakeSession(
        executes=[
            [(pid, "s1", "one@x.de", None)],
            [(pid, "chair", None)],
            [(pid, gid)],
        ]
    )
    out = await _candidates_with_transition_permission(
        cast(AsyncSession, session), datetime.now(UTC), gremium_id=None
    )
    assert out[0].roles == frozenset({"chair"})
    assert out[0].committees == frozenset({str(gid)})


# actionable_principal_emails end to end (#task-recipients)
def _app_ns(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "current_state_id": uuid.uuid4(),
        "flow_version_id": uuid.uuid4(),
        "gremium_id": None,
        "created_by": None,
        "data": {},
        "amount": None,
        "budget_id": None,
        "fiscal_year_id": None,
        "form_version_id": uuid.uuid4(),
    }
    base.update(over)
    return SimpleNamespace(**base)


async def test_actionable_vote_state_unchanged() -> None:
    gid = str(uuid.uuid4())
    session = FakeSession(scalars=[["v@x.de"]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session),
        application_id=uuid.uuid4(),
        state=State(kind="vote", config={"gremiumId": gid}),
    )
    assert out == ["v@x.de"]


async def test_actionable_missing_application_empty() -> None:
    session = FakeSession(scalar=[None])
    out = await actionable_principal_emails(
        cast(AsyncSession, session),
        application_id=uuid.uuid4(),
        state=State(kind="normal", config={}),
    )
    assert out == []


async def test_actionable_application_without_state_empty() -> None:
    app = _app_ns(current_state_id=None)
    session = FakeSession(scalar=[app])
    out = await actionable_principal_emails(
        cast(AsyncSession, session), application_id=app.id, state=None
    )
    assert out == []


async def test_actionable_no_requires_action_transitions_empty() -> None:
    app = _app_ns()
    session = FakeSession(scalar=[app], scalars=[[]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session),
        application_id=app.id,
        state=State(kind="normal", config={}),
    )
    assert out == []


async def test_actionable_excludes_admin_without_firable_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # THE bug (#task-recipients) end to end: only a principal whose guard fires gets
    # mail. The admin with an unsatisfied guard drops out.
    captured: dict[str, Any] = {}

    async def fake_base(
        _s: Any, app: Any, *, manual: bool, deadline_passed: bool = False
    ) -> GuardContext:
        captured["base"] = (app, manual, deadline_passed)
        return GuardContext(manual=True)

    async def fake_deadline(_s: Any, application_id: Any) -> bool:
        captured["deadline_app"] = application_id
        return True

    monkeypatch.setattr(recipients_mod, "build_base_context", fake_base)
    monkeypatch.setattr(recipients_mod, "flow_deadline_passed", fake_deadline)

    app = _app_ns(gremium_id=uuid.uuid4())
    pid1, pid2 = uuid.uuid4(), uuid.uuid4()
    session = FakeSession(
        scalar=[app],
        scalars=[[SimpleNamespace(guard={"roleIs": "chair"})]],
        executes=[
            [(pid1, "s1", "chair@x.de", None), (pid2, "s2", "admin@x.de", None)],
            [(pid1, "chair", None), (pid2, ADMIN_ROLE_KEY, None)],
            [],  # no groups -> memberships next (mapping query skipped)
        ],
    )
    out = await actionable_principal_emails(
        cast(AsyncSession, session),
        application_id=app.id,
        state=State(kind="normal", config={}),
    )
    assert out == ["chair@x.de"]
    assert captured["base"] == (app, True, True)
    assert captured["deadline_app"] == app.id


async def test_actionable_seeds_with_app_gremium_and_dedups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake_base(
        _s: Any, _app: Any, *, manual: bool, deadline_passed: bool = False
    ) -> GuardContext:
        return GuardContext(manual=True)

    async def fake_deadline(_s: Any, _application_id: Any) -> bool:
        return False

    async def fake_candidates(
        _s: Any, _now: Any, *, gremium_id: Any
    ) -> list[ActionableCandidate]:
        seen["gremium_id"] = gremium_id
        return [
            _candidate(sub="a", email="dup@x.de"),
            _candidate(sub="b", email="dup@x.de"),
            _candidate(sub="c", email="a@x.de"),
        ]

    monkeypatch.setattr(recipients_mod, "build_base_context", fake_base)
    monkeypatch.setattr(recipients_mod, "flow_deadline_passed", fake_deadline)
    monkeypatch.setattr(
        recipients_mod, "_candidates_with_transition_permission", fake_candidates
    )

    gid = uuid.uuid4()
    app = _app_ns(gremium_id=gid)
    session = FakeSession(scalar=[app], scalars=[[SimpleNamespace(guard=None)]])
    out = await actionable_principal_emails(
        cast(AsyncSession, session), application_id=app.id, state=None
    )
    assert out == ["a@x.de", "dup@x.de"]  # sorted + deduplicated
    assert seen["gremium_id"] == gid
