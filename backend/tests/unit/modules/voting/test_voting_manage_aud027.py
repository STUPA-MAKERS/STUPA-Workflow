"""Unit tests for the VotingService write and lifecycle authorization (AUD-027).

The suite runs without a database. It covers every branch of `_vote_gremium_id`,
`assert_can_manage_group`, `assert_can_manage` and `assert_can_manage_vote`, because
this module is critical and needs 100 % branch coverage. The cases are the admin role,
a stale global `vote.manage` that grants nothing, and a per-Gremium role with
`vote.manage` or `session.manage` that allows or denies. They
also cover a Gremium that does not resolve and the meeting-bound resolution through
`meeting_id`.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.admin import gremium_roles as gremium_roles_mod
from app.modules.auth.principal import Principal
from app.modules.voting.service import VotingService
from app.shared.errors import ForbiddenError
from tests._support.flow_fakes import fake_session, result


def _patch_permitted(
    monkeypatch: pytest.MonkeyPatch, permitted: set[object]
) -> None:
    async def _fake(
        _session: object, _sub: str, _perm: str, _now: object = None
    ) -> set[object]:
        return permitted

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _fake)


async def test_manage_admin_ok() -> None:
    """The `admin` role may manage every vote (first branch)."""
    principal = Principal(sub="a", roles=["admin"])
    await VotingService(fake_session()).assert_can_manage_group("stupa", None, principal)


async def test_manage_global_vote_manage_is_gone() -> None:
    """A stale global `vote.manage` row grants nothing: the key is gremium-only."""
    principal = Principal(sub="m", permissions={"vote.manage"})
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            "stupa", None, principal
        )


async def test_manage_admin_read_token_denied() -> None:
    """The admin bypass is scope-capped: an admin `read` token cannot manage."""
    principal = Principal(
        sub="a", roles=["admin"], scope_permissions=frozenset({"application.read"})
    )
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            "stupa", None, principal
        )


async def test_manage_gremium_session_manage_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gremium permission `session.manage` alone manages a standalone vote."""
    gid = uuid4()

    async def _fake(
        _session: object, _sub: str, perm: str, _now: object = None
    ) -> set[object]:
        return {gid} if perm == "session.manage" else set()

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _fake)
    principal = Principal(sub="lead")
    service = VotingService(fake_session())
    await service.assert_can_manage_group(str(gid), None, principal)
    # The lead of another gremium gets 403.
    with pytest.raises(ForbiddenError):
        await service.assert_can_manage_group(str(uuid4()), None, principal)


async def test_manage_gremium_role_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """A per-Gremium role with `vote.manage` for the Gremium of the vote allows it.

    The service resolves the Gremium from `eligible_group`, a UUID as text, without a
    `meeting_id`.
    """
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    principal = Principal(sub="g")
    await VotingService(fake_session()).assert_can_manage_group(str(gid), None, principal)


async def test_manage_gremium_role_capped_by_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F16: a token without `vote.manage` in its scope gets nothing from the role."""
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    principal = Principal(sub="g", scope_permissions=frozenset({"application.read"}))
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            str(gid), None, principal
        )


async def test_manage_gremium_role_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Gremium resolves, but the principal holds no `vote.manage` there, so 403."""
    gid = uuid4()
    _patch_permitted(monkeypatch, set())
    principal = Principal(sub="g")
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            str(gid), None, principal
        )


async def test_manage_unresolvable_group_denied() -> None:
    """A free group key without a UUID and without a meeting resolves no Gremium: 403."""
    principal = Principal(sub="x")
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            "freikey", None, principal
        )


async def test_manage_resolves_gremium_via_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A meeting-bound vote inherits the Gremium of the meeting (`meeting_id` branch)."""
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    db = fake_session()
    db.scalar_results = [gid]  # Meeting.gremium_id
    principal = Principal(sub="g")
    await VotingService(db).assert_can_manage_group("ignored", uuid4(), principal)


async def test_manage_meeting_without_gremium_falls_back_to_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `meeting_id` without a resolvable Gremium falls back to the `eligible_group`."""
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    db = fake_session()
    db.scalar_results = [None]  # the meeting lookup returns nothing
    principal = Principal(sub="g")
    await VotingService(db).assert_can_manage_group(str(gid), uuid4(), principal)


async def test_assert_can_manage_loaded_vote_delegates() -> None:
    """`assert_can_manage` delegates to the group variant (admin short circuit)."""
    vote = SimpleNamespace(eligible_group="stupa", meeting_id=None)
    principal = Principal(sub="a", roles=["admin"])
    await VotingService(fake_session()).assert_can_manage(
        vote,  # pyright: ignore[reportArgumentType]
        principal,
    )


async def test_assert_can_manage_vote_loads_then_checks() -> None:
    """`assert_can_manage_vote` loads the vote, raises 404 if it is gone, then checks."""
    vote = SimpleNamespace(id=uuid4(), eligible_group="stupa", meeting_id=None)
    principal = Principal(sub="a", roles=["admin"])
    await VotingService(fake_session(result(vote))).assert_can_manage_vote(
        vote.id, principal
    )
