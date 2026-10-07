"""Gremium-only votes: no global vote right, a gremium UUID as the eligible group.

The global permissions `vote.manage` and `vote.cast` are gone. These tests pin the rules
that replace them:

- `POST /applications/{id}/votes` takes a gremium UUID as `eligibleGroup` and no
  `eligibleCount`. The server counts the roster (F14).
- The gremium must exist (`eligible_group_invalid`) and must be the gremium of the
  application (`eligible_group_mismatch`, NEW-1).
- The gremium permission `vote.manage` or `session.manage` manages a standalone vote.
- An eligible voter reads the vote without `application.read`.
- `GET /votes/{id}` carries the `canManage` and `canCast` flags of the caller.

The suite runs without a database, like the other voting unit tests.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.modules.admin import gremium_roles as gremium_roles_mod
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.voting.schemas import VoteCreate
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ForbiddenError, ValidationProblem
from tests._support.flow_fakes import fake_session, result

GID = UUID("00000000-0000-0000-0000-0000000c0de1")
OTHER = UUID("00000000-0000-0000-0000-0000000c0de2")
# `create` takes the caller. The router checks the manage right before the call.
MANAGER = Principal(sub="m")
ADMIN = Principal(sub="a", roles=["admin"])


def _config(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"options": ["yes", "no"], "majorityRule": "simple"}
    base.update(over)
    return VoteConfig.model_validate(base).model_dump(by_alias=True)


def _body(**over: Any) -> VoteCreate:
    body: dict[str, Any] = {"config": _config(), "eligibleGroup": str(GID)}
    body.update(over)
    return VoteCreate.model_validate(body)


def _application(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(), "current_state_id": None, "gremium_id": GID, "vote_gremium_id": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _roster(casters: int, others: int = 0) -> list[tuple[UUID, list[str]]]:
    rows = [(uuid4(), ["vote.cast"]) for _ in range(casters)]
    rows += [(uuid4(), ["protocol.write"]) for _ in range(others)]
    return rows


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "application_id": uuid4(),
        "meeting_id": None,
        "eligible_group": str(GID),
        "config": _config(),
        "eligible_count": 3,
        "opens_at": None,
        "closes_at": None,
        "closed_at": None,
        "status": "open",
        "result": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _patch_gremium_perms(
    monkeypatch: pytest.MonkeyPatch, grants: dict[str, set[UUID]]
) -> None:
    """Let `gremium_ids_with_permission` answer from `grants` (perm -> gremium ids)."""

    async def _fake(
        _session: object, _sub: str, perm: str, _now: object = None
    ) -> set[UUID]:
        return set(grants.get(perm, set()))

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _fake)


# The request body.


def test_body_refuses_a_free_group_key() -> None:
    with pytest.raises(ValidationError):
        _body(eligibleGroup="stupa")


def test_body_refuses_a_client_eligible_count() -> None:
    """F14: the client cannot send the quorum denominator."""
    with pytest.raises(ValidationError):
        _body(eligibleCount=3)


# create(): gremium check, NEW-1 and the server-side roster count.


async def test_create_stores_the_roster_count() -> None:
    """F14: `eligible_count` is the number of members with `vote.cast` in the gremium."""
    app = _application()
    db = fake_session(result(app), result(*_roster(3, others=2)))
    db.scalar_results = [GID]
    out = await VotingService(db).create(app.id, _body(), MANAGER)
    assert out.tally.eligible == 3
    stored = [o for o in db.added if hasattr(o, "eligible_count")]
    assert stored[0].eligible_count == 3
    assert stored[0].eligible_group == str(GID)


async def test_create_percent_quorum_needs_no_client_count() -> None:
    """A percent quorum works: the server supplies the count from the roster."""
    app = _application()
    db = fake_session(result(app), result(*_roster(4)))
    db.scalar_results = [GID]
    body = _body(config=_config(quorum={"type": "percent", "value": 50}))
    out = await VotingService(db).create(app.id, body, MANAGER)
    assert out.tally.eligible == 4
    assert out.config.quorum is not None


async def test_create_unknown_gremium_422() -> None:
    db = fake_session()
    db.scalar_results = [None]  # no gremium with this id
    with pytest.raises(ValidationProblem) as err:
        await VotingService(db).create(uuid4(), _body(), MANAGER)
    assert err.value.code == "eligible_group_invalid"


async def test_create_other_gremium_than_the_application_422() -> None:
    """NEW-1: a vote of gremium B cannot decide an application of gremium A."""
    app = _application(gremium_id=OTHER)
    db = fake_session(result(app))
    db.scalar_results = [GID]
    with pytest.raises(ValidationProblem) as err:
        await VotingService(db).create(app.id, _body(), MANAGER)
    assert err.value.code == "eligible_group_mismatch"


async def test_create_state_gremium_wins_over_the_application_gremium() -> None:
    """The `gremiumId` of the current vote state decides when it is set."""
    app = _application(current_state_id=uuid4(), gremium_id=OTHER)
    db = fake_session(result(app), result(*_roster(1)))
    db.scalar_results = [GID, {"gremiumId": str(GID)}]
    out = await VotingService(db).create(app.id, _body(), MANAGER)
    assert out.eligible_group == str(GID)


async def test_create_state_gremium_mismatch_422() -> None:
    app = _application(current_state_id=uuid4(), gremium_id=GID)
    db = fake_session(result(app))
    db.scalar_results = [GID, {"gremiumId": str(OTHER)}]
    with pytest.raises(ValidationProblem) as err:
        await VotingService(db).create(app.id, _body(), MANAGER)
    assert err.value.code == "eligible_group_mismatch"


@pytest.mark.parametrize(
    "state_config",
    [None, {}, {"gremiumId": ""}, {"gremiumId": 7}, {"gremiumId": "not-a-uuid"}],
)
async def test_create_state_without_usable_gremium_falls_back(state_config: Any) -> None:
    """A state config without a valid `gremiumId` falls back to the application."""
    app = _application(current_state_id=uuid4(), gremium_id=GID)
    db = fake_session(result(app), result(*_roster(2)))
    db.scalar_results = [GID, state_config]
    out = await VotingService(db).create(app.id, _body(), MANAGER)
    assert out.tally.eligible == 2


async def test_create_application_without_gremium_only_the_admin() -> None:
    """With no gremium on the application or the state, only the admin role creates.

    Else a vote manager of any gremium could run the vote and fire the branch.
    """
    app = _application(gremium_id=None)
    db = fake_session(result(app))
    db.scalar_results = [GID]
    with pytest.raises(ForbiddenError):
        await VotingService(db).create(app.id, _body(), MANAGER)

    db = fake_session(result(app), result(*_roster(1)))
    db.scalar_results = [GID]
    out = await VotingService(db).create(app.id, _body(), ADMIN)
    assert out.eligible_group == str(GID)


async def test_create_application_without_gremium_scoped_admin_token_403() -> None:
    """The scope cap applies: an admin token without `vote.manage` cannot create."""
    app = _application(gremium_id=None)
    db = fake_session(result(app))
    db.scalar_results = [GID]
    token = Principal(
        sub="a", roles=["admin"], scope_permissions=frozenset({"application.read"})
    )
    with pytest.raises(ForbiddenError):
        await VotingService(db).create(app.id, _body(), token)


# Manage right of a standalone vote.


async def test_session_manage_manages_a_standalone_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gremium_perms(monkeypatch, {"session.manage": {GID}})
    svc = VotingService(fake_session())
    lead = Principal(sub="lead")
    await svc.assert_can_manage_group(str(GID), None, lead)
    with pytest.raises(ForbiddenError):
        await svc.assert_can_manage_group(str(OTHER), None, lead)


async def test_vote_manage_manages_a_standalone_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gremium_perms(monkeypatch, {"vote.manage": {GID}})
    await VotingService(fake_session()).assert_can_manage_group(
        str(GID), None, Principal(sub="m")
    )


async def test_free_key_vote_only_the_admin_manages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gremium_perms(monkeypatch, {"vote.manage": {GID}, "session.manage": {GID}})
    svc = VotingService(fake_session())
    with pytest.raises(ForbiddenError):
        await svc.assert_can_manage_group("stupa", None, Principal(sub="m"))
    await svc.assert_can_manage_group("stupa", None, Principal(sub="a", roles=["admin"]))


# Read access to a standalone vote.


async def test_eligible_voter_reads_without_application_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gremium_perms(monkeypatch, {})
    voter = Principal(sub="v", groups={vote_group_key(GID)})
    await VotingService(fake_session()).assert_can_read(_vote(), voter)  # pyright: ignore[reportArgumentType]


async def test_gremium_manager_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gremium_perms(monkeypatch, {"session.manage": {GID}})
    await VotingService(fake_session()).assert_can_read(_vote(), Principal(sub="lead"))  # pyright: ignore[reportArgumentType]


async def test_outsider_cannot_read(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gremium_perms(monkeypatch, {"vote.manage": {OTHER}})
    outsider = Principal(sub="o", groups={vote_group_key(OTHER)})
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_read(_vote(), outsider)  # pyright: ignore[reportArgumentType]


async def test_free_key_vote_needs_application_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gremium_perms(monkeypatch, {"vote.manage": {GID}})
    vote = _vote(eligible_group="stupa")
    svc = VotingService(fake_session())
    with pytest.raises(ForbiddenError):
        await svc.assert_can_read(vote, Principal(sub="m", groups={"stupa"}))  # pyright: ignore[reportArgumentType]
    await svc.assert_can_read(vote, Principal(sub="r", permissions={"application.read_all"}))  # pyright: ignore[reportArgumentType]


# The capability flags of GET /votes/{id}.


async def test_get_scoped_flags_for_a_voter(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gremium_perms(monkeypatch, {})
    vote = _vote()
    db = fake_session(result(vote), result(vote))
    voter = Principal(sub="v", groups={vote_group_key(GID)})
    out = await VotingService(db).get_scoped(vote.id, voter)
    assert out.can_cast is True
    assert out.can_manage is False
    dumped = out.model_dump(by_alias=True)
    assert dumped["canCast"] is True and dumped["canManage"] is False


async def test_get_scoped_flags_for_a_manager(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_gremium_perms(monkeypatch, {"vote.manage": {GID}})
    vote = _vote()
    db = fake_session(result(vote), result(vote))
    out = await VotingService(db).get_scoped(vote.id, Principal(sub="m"))
    assert out.can_manage is True
    assert out.can_cast is False


async def test_get_scoped_token_never_casts(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scoped OAuth token reads the vote, but `canCast` stays False: voting is human."""
    _patch_gremium_perms(monkeypatch, {})
    vote = _vote()
    db = fake_session(result(vote), result(vote))
    agent = Principal(
        sub="v",
        groups={vote_group_key(GID)},
        scope_permissions=frozenset({"application.read"}),
    )
    out = await VotingService(db).get_scoped(vote.id, agent)
    assert out.can_cast is False


async def test_create_follows_the_vote_gremium_snapshot() -> None:
    """Flow variant B: the snapshot of the vote state decides, before the type Gremium."""
    app = _application(vote_gremium_id=OTHER, current_state_id=uuid4())
    db = fake_session(result(app))
    db.scalar_results = [GID]  # the gremium exists
    with pytest.raises(ValidationProblem) as err:
        await VotingService(db).create(app.id, _body(), MANAGER)
    assert err.value.code == "eligible_group_mismatch"
    app = _application(vote_gremium_id=GID, gremium_id=OTHER, current_state_id=uuid4())
    db = fake_session(result(app), result(*_roster(2)))
    db.scalar_results = [GID]
    out = await VotingService(db).create(app.id, _body(), MANAGER)
    assert out.tally.eligible == 2
