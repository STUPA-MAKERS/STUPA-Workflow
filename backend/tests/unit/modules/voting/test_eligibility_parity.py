"""The quorum roster and the cast gate must admit the same people.

`MeetingService.vote_eligible_count` builds the quorum denominator from the gremium
roster: every active member whose gremium role carries `vote.cast`. `VotingService.cast`
gates the ballot. If the two use different rules, a vote counts a member who cannot
cast, and a percent quorum can become unreachable. A 75 % quorum over four counted
members needs three ballots, so two structurally blocked members make it impossible.

These tests pin the invariant: the set the quorum counts equals the set the gate admits.
They also pin the two rules that keep the gate trustworthy. Only an active `vote.cast`
membership writes the namespaced `vote:<gremium_id>` key, and only a human session can
cast a ballot.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.auth import rbac
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.service import MeetingService
from app.modules.voting.service import VotingService
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ForbiddenError
from tests._support import auth_fakes
from tests._support.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
GID = uuid.UUID("00000000-0000-0000-0000-0000000060e1")
OPTIONS = ["yes", "no"]

# The roster of the measured gremium: the sub, the permissions of the gremium role, and
# the permissions of the global role. `manager` and `protokoll` are ordinary roles of
# people who also sit in the committee. They carry no global `vote.cast`.
_ALL_GREMIUM_PERMS = ["session.manage", "vote.manage", "vote.cast", "protocol.write"]
_ROSTER: tuple[tuple[str, list[str] | None, set[str]], ...] = (
    ("admin", _ALL_GREMIUM_PERMS, {"vote.cast"}),
    ("member", ["vote.cast"], {"vote.cast"}),
    ("manager", _ALL_GREMIUM_PERMS, set()),
    ("protokoll", ["vote.cast"], set()),
    # A member without the voting role, plus a non-member who holds the global right.
    ("guest", ["protocol.write"], set()),
    ("outsider", None, {"vote.cast"}),
)


def _config(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"options": OPTIONS, "majorityRule": "simple"}
    base.update(over)
    return VoteConfig.model_validate(base).model_dump(by_alias=True)


def _vote(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "application_id": uuid.uuid4(),
        "meeting_id": None,
        "eligible_group": str(GID),
        "config": _config(),
        "eligible_count": 4,
        "opens_at": None,
        "closes_at": None,
        "status": "open",
        "result": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


async def _resolve(
    sub: str, gremium_perms: list[str] | None, global_perms: set[str]
) -> Principal:
    """Resolve a principal through the real RBAC resolver against a fake session.

    The queue mirrors the query order of `resolve_principal`: role assignments, then
    the permissions and the role keys of those assignments, then the memberships. A
    principal without a global role skips the two middle queries.
    """
    row = PrincipalRow(sub=sub, email=None, display_name=None, oidc_groups=None)
    row.id = sub  # type: ignore[assignment]
    queue = []
    if global_perms:
        queue.append(
            auth_fakes.result(
                SimpleNamespace(
                    role_id="role", valid_from=None, valid_until=None, gremium_id=None
                )
            )
        )
        queue.append(auth_fakes.result(*sorted(global_perms)))
        queue.append(auth_fakes.result("global-role"))
    else:
        queue.append(auth_fakes.result())
    queue.append(
        auth_fakes.result((str(GID), gremium_perms))
        if gremium_perms is not None
        else auth_fakes.result()
    )
    return await rbac.resolve_principal(auth_fakes.fake_session(*queue), row, NOW)


async def _casts(principal: Principal) -> bool:
    """Run the real cast path and report whether the ballot is accepted."""
    vote = _vote()
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    try:
        await VotingService(db).cast(vote.id, principal, "yes", now=NOW)
    except ForbiddenError:
        return False
    return True


async def test_gremium_role_without_global_permission_may_cast() -> None:
    """The bug: a `Sachbearbeitung` or `Protokoll` member counts, so the member votes."""
    assert await _casts(await _resolve("manager", _ALL_GREMIUM_PERMS, set())) is True
    assert await _casts(await _resolve("protokoll", ["vote.cast"], set())) is True


async def test_gremium_role_with_global_permission_may_cast() -> None:
    assert await _casts(await _resolve("member", ["vote.cast"], {"vote.cast"})) is True


async def test_neither_gremium_role_nor_global_permission_is_refused() -> None:
    assert await _casts(await _resolve("guest", ["protocol.write"], set())) is False


async def test_global_permission_without_membership_is_refused() -> None:
    """The global right alone never reaches the roster of a gremium vote."""
    assert await _casts(await _resolve("outsider", None, {"vote.cast"})) is False


async def test_quorum_roster_equals_cast_gate() -> None:
    """The invariant: the set the quorum counts equals the set the gate admits."""
    rows = [(sub, perms) for sub, perms, _ in _ROSTER if perms is not None]
    counted = await MeetingService(fake_session(result(*rows))).vote_eligible_count(GID)
    admitted = [
        sub for sub, gp, glob in _ROSTER if await _casts(await _resolve(sub, gp, glob))
    ]
    assert admitted == ["admin", "member", "manager", "protokoll"]
    assert len(admitted) == counted == 4


async def test_forged_oidc_group_claim_never_reaches_the_roster() -> None:
    """A raw IdP group named `vote:<gremium_id>` must not grant the cast right.

    The gate now trusts the namespaced key on its own, so the resolver must keep the
    reserved namespace for real memberships.
    """
    row = PrincipalRow(
        sub="forger",
        email=None,
        display_name=None,
        oidc_groups=[rbac.vote_group_key(GID)],
    )
    row.id = "forger"  # type: ignore[assignment]
    # No assignments, no mapping hit, no membership.
    db = auth_fakes.fake_session(
        auth_fakes.result(), auth_fakes.result(), auth_fakes.result()
    )
    principal = await rbac.resolve_principal(db, row, NOW)
    assert rbac.vote_group_key(GID) not in principal.groups
    assert await _casts(principal) is False


async def test_free_group_key_still_needs_the_global_permission() -> None:
    """A non-UUID group key proves no membership, so the global right stays required."""
    vote = _vote(eligible_group="stupa")
    with_perm = Principal(sub="a", permissions={"vote.cast"}, groups={"stupa"})
    without = Principal(sub="b", permissions=set(), groups={"stupa"})
    db = fake_session(result(vote), result(SimpleNamespace(inserted=True)))
    assert (await VotingService(db).cast(vote.id, with_perm, "yes", now=NOW)).status == "cast"
    db = fake_session(result(vote))
    with pytest.raises(ForbiddenError, match="Not eligible"):
        await VotingService(db).cast(vote.id, without, "yes", now=NOW)


async def test_agent_token_cannot_cast_an_own_ballot() -> None:
    """Voting stays human: a scoped OAuth token never casts, whatever group it holds."""
    vote = _vote()
    agent = Principal(
        sub="agent",
        permissions={"vote.cast"},
        groups={rbac.vote_group_key(GID)},
        scope_permissions=frozenset({"vote.manage"}),
    )
    db = fake_session(result(vote))
    with pytest.raises(ForbiddenError, match="human"):
        await VotingService(db).cast(vote.id, agent, "yes", now=NOW)


async def test_agent_token_cannot_cast_a_delegated_ballot() -> None:
    """The human rule also covers the represented ballot of a delegation."""
    vote = _vote(meeting_id=uuid.uuid4())
    agent = Principal(
        sub="agent",
        permissions=set(),
        groups=set(),
        scope_permissions=frozenset({"vote.manage"}),
    )
    db = fake_session(result(vote), result((False, True, "delegator-1")))
    with pytest.raises(ForbiddenError, match="human"):
        await VotingService(db).cast(
            vote.id, agent, "yes", now=NOW, as_delegation=True
        )
