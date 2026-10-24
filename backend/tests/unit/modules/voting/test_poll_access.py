"""Who reads and who manages a poll of a Gremium (no meeting).

A poll is no application vote: ``application.read`` does not open it. Only an
eligible voter, a manager in its Gremium and the admin role read it. The edit and
the lifecycle take the right that creates it (``vote.manage`` or the admin role),
so ``session.manage`` alone does not manage it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.admin import gremium_roles
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.voting.service import VotingService
from app.shared.errors import ForbiddenError
from tests._support.flow_fakes import fake_session

GID = UUID("00000000-0000-0000-0000-00000000a11c")


def _poll(**over: Any) -> SimpleNamespace:
    data: dict[str, Any] = {
        "id": uuid4(),
        "kind": "poll",
        "meeting_id": None,
        "eligible_group": str(GID),
    }
    data.update(over)
    return SimpleNamespace(**data)


@pytest.fixture
def rights(monkeypatch: pytest.MonkeyPatch) -> dict[str, set[UUID]]:
    """Stub the gremium rights per permission."""
    state: dict[str, set[UUID]] = {}

    async def _ids_for(_s: Any, _p: Principal, perm: str) -> set[UUID]:
        return set(state.get(perm, set()))

    monkeypatch.setattr(gremium_roles, "gremium_ids_for", _ids_for)
    return state


# ------------------------------------------------------------------ read
async def test_application_reader_cannot_read_a_gremium_poll(
    rights: dict[str, set[UUID]],
) -> None:
    svc = VotingService(fake_session())
    for perm in ("application.read", "application.read_all"):
        with pytest.raises(ForbiddenError):
            await svc.assert_can_read(_poll(), Principal(sub="r", permissions={perm}))  # pyright: ignore[reportArgumentType]


async def test_application_reader_still_reads_an_application_vote(
    rights: dict[str, set[UUID]],
) -> None:
    svc = VotingService(fake_session())
    vote = _poll(kind="motion")
    await svc.assert_can_read(vote, Principal(sub="r", permissions={"application.read"}))  # pyright: ignore[reportArgumentType]


async def test_voter_manager_and_admin_read_a_gremium_poll(
    rights: dict[str, set[UUID]],
) -> None:
    svc = VotingService(fake_session())
    await svc.assert_can_read(_poll(), Principal(sub="v", groups={vote_group_key(GID)}))  # pyright: ignore[reportArgumentType]
    await svc.assert_can_read(_poll(), Principal(sub="a", roles=["admin"]))  # pyright: ignore[reportArgumentType]
    rights["session.manage"] = {GID}
    await svc.assert_can_read(_poll(), Principal(sub="m"))  # pyright: ignore[reportArgumentType]


async def test_scope_capped_admin_token_cannot_read_a_gremium_poll(
    rights: dict[str, set[UUID]],
) -> None:
    capped = Principal(sub="a", roles=["admin"], scope_permissions=frozenset({"vote.cast"}))
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_read(_poll(), capped)  # pyright: ignore[reportArgumentType]


# ------------------------------------------------------------------ manage
async def test_session_manage_alone_does_not_manage_a_gremium_poll(
    rights: dict[str, set[UUID]],
) -> None:
    rights["session.manage"] = {GID}
    svc = VotingService(fake_session())
    principal = Principal(sub="s")
    assert await svc.can_manage(_poll(), principal) is False  # pyright: ignore[reportArgumentType]
    with pytest.raises(ForbiddenError):
        await svc.assert_can_manage(_poll(), principal)  # pyright: ignore[reportArgumentType]
    # The same right still manages an application vote of the Gremium.
    assert await svc.can_manage(_poll(kind="motion"), principal) is True  # pyright: ignore[reportArgumentType]


async def test_vote_manage_and_admin_manage_a_gremium_poll(
    rights: dict[str, set[UUID]],
) -> None:
    svc = VotingService(fake_session())
    await svc.assert_can_manage(_poll(), Principal(sub="a", roles=["admin"]))  # pyright: ignore[reportArgumentType]
    rights["vote.manage"] = {GID}
    await svc.assert_can_manage(_poll(), Principal(sub="m"))  # pyright: ignore[reportArgumentType]


async def test_poll_with_a_free_group_key_is_managed_only_by_the_admin(
    rights: dict[str, set[UUID]],
) -> None:
    svc = VotingService(fake_session())
    vote = _poll(eligible_group="free-key")
    rights["vote.manage"] = {GID}
    assert await svc.can_manage(vote, Principal(sub="m")) is False  # pyright: ignore[reportArgumentType]
    assert await svc.can_manage(vote, Principal(sub="a", roles=["admin"])) is True  # pyright: ignore[reportArgumentType]


async def test_meeting_poll_keeps_the_meeting_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[UUID | None] = []

    async def _group(_self: Any, _group: str, meeting_id: UUID | None, _p: Any) -> bool:
        seen.append(meeting_id)
        return True

    monkeypatch.setattr(VotingService, "can_manage_group", _group)
    mid = uuid4()
    assert await VotingService(fake_session()).can_manage(_poll(meeting_id=mid), Principal(sub="x"))  # pyright: ignore[reportArgumentType]
    assert seen == [mid]
