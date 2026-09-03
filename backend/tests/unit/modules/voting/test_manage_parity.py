"""The `canManageVotes` flag and the vote lifecycle gate must agree.

The meeting payload advertises `canManageVotes`. The client renders the open, close and
delete buttons from it. `MeetingService.can_manage_votes` computes it for the session
manager, the protokollant, and a gremium role with `vote.manage`. The lifecycle gate of
the voting module used to admit only `vote.manage`, so the protokollant could create,
open and even delete a vote of the meeting, but never close it. The open vote then
stranded until a `vote.manage` holder stepped in.

These tests pin the invariant: the capability the API advertises equals the capability
the gate admits.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.admin import gremium_roles as gremium_roles_mod
from app.modules.auth.principal import Principal
from app.modules.livevote.service import MeetingService
from app.modules.livevote.service import permissions as permissions_mod
from app.modules.voting.service import VotingService
from app.shared.errors import ForbiddenError
from tests._support.flow_fakes import fake_session, result

GID = uuid4()
PID = uuid4()


def _meeting(**over: Any) -> Any:
    base: dict[str, Any] = {
        "id": uuid4(),
        "gremium_id": GID,
        "protokollant_id": PID,
        "status": "live",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _patch_gremium_perms(
    monkeypatch: pytest.MonkeyPatch, mapping: dict[str, set[UUID]]
) -> None:
    """Give both call sites the same per-permission gremium answer."""

    async def _fake(
        _session: object, _sub: str, perm: str, _now: object = None
    ) -> set[UUID]:
        return mapping.get(perm, set())

    monkeypatch.setattr(permissions_mod, "gremium_ids_with_permission", _fake)
    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _fake)


async def _advertised(meeting: Any, principal: Principal) -> bool:
    """Run the rule the meeting payload publishes as `canManageVotes`."""
    db = fake_session(result(PID))  # `_principal_id` for the protokollant check
    return await MeetingService(db).can_manage_votes(meeting, principal)


async def _admitted(meeting: Any, principal: Principal) -> bool:
    """Run the gate that guards close, cancel and open."""
    vote = SimpleNamespace(
        id=uuid4(), eligible_group=str(GID), meeting_id=meeting.id
    )
    db = fake_session(result(vote), result(PID))
    db.get_results = [meeting]
    try:
        await VotingService(db).assert_can_manage_vote(vote.id, principal)
    except ForbiddenError:
        return False
    return True


async def _parity(meeting: Any, principal: Principal) -> bool:
    advertised = await _advertised(meeting, principal)
    assert advertised == await _admitted(meeting, principal)
    return advertised


async def test_protokollant_may_close_the_vote_it_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The person who runs the session finishes the vote they started."""
    _patch_gremium_perms(monkeypatch, {})
    assert await _parity(_meeting(), Principal(sub="protokoll")) is True


async def test_session_manager_may_close_the_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A gremium `session.manage` role manages the votes of its meetings."""
    _patch_gremium_perms(monkeypatch, {"session.manage": {GID}})
    meeting = _meeting(protokollant_id=uuid4())
    assert await _parity(meeting, Principal(sub="manager")) is True


async def test_global_meeting_manage_may_close_the_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The global meeting manager sees the flag, so the gate must admit it too."""
    _patch_gremium_perms(monkeypatch, {})
    meeting = _meeting(protokollant_id=uuid4())
    principal = Principal(sub="ops", permissions={"meeting.manage"})
    assert await _parity(meeting, principal) is True


async def test_gremium_vote_manage_may_close_the_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_gremium_perms(monkeypatch, {"vote.manage": {GID}})
    meeting = _meeting(protokollant_id=uuid4())
    assert await _parity(meeting, Principal(sub="chair")) is True


async def test_plain_member_may_not_close_the_vote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail-closed stays fail-closed: an ordinary member gets no lifecycle right."""
    _patch_gremium_perms(monkeypatch, {})
    meeting = _meeting(protokollant_id=uuid4())
    assert await _parity(meeting, Principal(sub="member")) is False


async def test_vanished_meeting_falls_back_to_the_gremium_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vote whose meeting no longer exists keeps the gremium-scoped `vote.manage`."""
    _patch_gremium_perms(monkeypatch, {})
    vote = SimpleNamespace(id=uuid4(), eligible_group=str(GID), meeting_id=uuid4())
    db = fake_session(result(vote))  # `get` finds no meeting
    with pytest.raises(ForbiddenError, match="manage"):
        await VotingService(db).assert_can_manage_vote(vote.id, Principal(sub="x"))
