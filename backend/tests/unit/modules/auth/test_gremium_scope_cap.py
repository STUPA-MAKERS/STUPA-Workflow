"""F16: the OAuth scope caps the gremium permissions and the admin bypass.

A gremium role grants `session.manage`, `protocol.write`, `vote.manage` and
`protocol.finalize` per gremium. These keys never enter `principal.permissions`, so
`Principal.has` cannot cap them. Before the fix a token with only the `read` scope could
still manage a meeting, write the minutes and run the votes of its owner's gremien.
The minute-taker path had the same gap.

These tests pin the cap on every path: the gremium lookup, the minute-taker path, the
admin bypass and the batched flags of the meeting list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.admin import gremium_roles as gremium_roles_mod
from app.modules.admin.gremium_roles import admin_bypass, gremium_ids_for
from app.modules.auth import oauth
from app.modules.auth.principal import Principal
from app.modules.livevote.models import Meeting
from app.modules.livevote.service import MeetingService
from app.modules.livevote.service import permissions as permissions_mod
from tests._support.flow_fakes import fake_session, result

GID = uuid4()
PID = uuid4()
ALL_GREMIUM = ("session.manage", "protocol.write", "vote.manage", "protocol.finalize")


def _scoped(*scopes: str, sub: str = "chair", roles: list[str] | None = None) -> Principal:
    return Principal(
        sub=sub,
        roles=roles or [],
        scope_permissions=oauth.scope_permissions(list(scopes)),
    )


def _meeting(*, protokollant_id: UUID | None = None) -> Any:
    return SimpleNamespace(
        id=uuid4(), gremium_id=GID, protokollant_id=protokollant_id, status="live"
    )


@pytest.fixture
def chair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every principal holds every gremium permission in GID (a chair)."""

    async def _all(_s: object, _sub: str, perm: str, _now: object = None) -> set[UUID]:
        return {GID} if perm in ALL_GREMIUM else set()

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _all)
    monkeypatch.setattr(permissions_mod, "gremium_ids_with_permission", _all)


@pytest.fixture
def nobody(monkeypatch: pytest.MonkeyPatch) -> None:
    """No principal holds a gremium permission anywhere."""

    async def _none(_s: object, _sub: str, _perm: str, _now: object = None) -> set[UUID]:
        return set()

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _none)
    monkeypatch.setattr(permissions_mod, "gremium_ids_with_permission", _none)


def test_principal_scope_allows_and_is_admin() -> None:
    assert Principal(sub="x").scope_allows("session.manage") is True
    capped = Principal(sub="x", scope_permissions=frozenset({"application.read"}))
    assert capped.scope_allows("session.manage") is False
    assert capped.scope_allows("application.read") is True
    assert Principal(sub="x", roles=["admin"]).is_admin is True
    assert Principal(sub="x").is_admin is False


def test_admin_bypass_respects_the_scope() -> None:
    assert admin_bypass(Principal(sub="a", roles=["admin"]), "session.manage") is True
    assert admin_bypass(_scoped("read", roles=["admin"]), "session.manage") is False
    assert admin_bypass(_scoped("meetings:write", roles=["admin"]), "session.manage") is True
    assert admin_bypass(Principal(sub="m"), "session.manage") is False


async def test_gremium_ids_for_caps_by_scope(chair: None) -> None:
    db = fake_session()
    assert await gremium_ids_for(db, Principal(sub="c"), "session.manage") == {GID}
    assert await gremium_ids_for(db, _scoped("read"), "session.manage") == set()
    assert await gremium_ids_for(db, _scoped("meetings:write"), "session.manage") == {GID}
    assert await gremium_ids_for(db, _scoped("meetings:write"), "vote.manage") == set()
    assert await gremium_ids_for(db, _scoped("votes:write"), "vote.manage") == {GID}


async def test_read_token_of_a_chair_cannot_run_the_meeting(chair: None) -> None:
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    token = _scoped("read")
    meeting = _meeting()
    assert await svc.can_manage(GID, token) is False
    assert await svc.can_write(meeting, token) is False
    assert await svc.can_manage_votes(meeting, token) is False
    assert await svc.can_finalize(meeting, token) is False


async def test_read_token_of_the_minute_taker_cannot_write(nobody: None) -> None:
    # The scope check runs before the minute-taker lookup, so no query is queued.
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    token = _scoped("read", sub="protokoll")
    meeting = _meeting(protokollant_id=PID)
    assert await svc.can_write(meeting, token) is False
    assert await svc.can_manage_votes(meeting, token) is False


async def test_minute_taker_session_still_writes(nobody: None) -> None:
    svc = MeetingService(fake_session(result(PID), result(PID)))  # type: ignore[arg-type]
    meeting = _meeting(protokollant_id=PID)
    assert await svc.can_write(meeting, Principal(sub="protokoll")) is True
    assert await svc.can_manage_votes(meeting, Principal(sub="protokoll")) is True


async def test_meetings_write_token_of_a_chair_manages(chair: None) -> None:
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    token = _scoped("meetings:write")
    meeting = _meeting()
    assert await svc.can_manage(GID, token) is True
    assert await svc.can_write(meeting, token) is True
    assert await svc.can_finalize(meeting, token) is True
    # `vote.manage` needs `votes:write`; the manager path still grants it.
    assert await svc.can_manage_votes(meeting, token) is True


async def test_finalize_needs_the_gremium_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _write_only(_s: object, _sub: str, perm: str, _now: object = None) -> set[UUID]:
        return {GID} if perm == "protocol.write" else set()

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _write_only)
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    meeting = _meeting()
    assert await svc.can_write(meeting, Principal(sub="w")) is True
    assert await svc.can_finalize(meeting, Principal(sub="w")) is False


async def test_finalize_needs_the_write_access(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _finalize_only(_s: object, _sub: str, perm: str, _now: object = None) -> set[UUID]:
        return {GID} if perm == "protocol.finalize" else set()

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _finalize_only)
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    assert await svc.can_finalize(_meeting(), Principal(sub="f")) is False


async def test_admin_read_token_sees_all_but_cannot_manage(nobody: None) -> None:
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    token = _scoped("read", roles=["admin"])
    meeting = _meeting()
    assert await svc.can_manage(GID, token) is False
    assert await svc.can_write(meeting, token) is False
    assert await svc.can_finalize(meeting, token) is False
    # `read` holds `meeting.view_all`, so the admin keeps the cross-gremium view.
    assert await svc._visible_gremium_ids(token) is None


async def test_admin_session_manages_and_finalizes(nobody: None) -> None:
    svc = MeetingService(fake_session())  # type: ignore[arg-type]
    admin = Principal(sub="a", roles=["admin"])
    meeting = _meeting()
    assert await svc.can_manage(GID, admin) is True
    assert await svc.can_finalize(meeting, admin) is True


def _row() -> Meeting:
    m = Meeting(gremium_id=GID, title="GV")
    m.id = uuid4()
    m.status = "closed"
    m.created_at = datetime(2026, 6, 8, tzinfo=UTC)
    m.protokollant_id = PID
    return m


async def test_listing_flags_follow_the_scope_cap(chair: None) -> None:
    """The batched list flags apply the same cap as the detail flags."""
    m = _row()
    # proto rows, gremium names, prot names, principal id, votes. The gremium
    # lookups are patched, `vote.cast` is empty for a scoped token.
    db = fake_session(result(), result(), result(), result(PID), result())
    out = await MeetingService(db)._decorate([m], _scoped("read", sub="protokoll"))  # type: ignore[arg-type]
    flags = out[0]
    assert flags.is_protokollant is True
    assert (flags.can_manage, flags.can_write, flags.can_manage_votes) == (False, False, False)
    assert flags.can_finalize is False


async def test_listing_flags_of_a_chair_session(chair: None) -> None:
    m = _row()
    db = fake_session(result(), result(), result(), result(uuid4()), result())
    out = await MeetingService(db)._decorate([m], Principal(sub="chair"))  # type: ignore[arg-type]
    flags = out[0]
    assert (flags.can_manage, flags.can_write, flags.can_manage_votes) == (True, True, True)
    assert flags.can_finalize is True


async def test_listing_flags_of_an_admin_session(nobody: None) -> None:
    m = _row()
    db = fake_session(result(), result(), result(), result(PID), result())
    out = await MeetingService(db)._decorate([m], Principal(sub="a", roles=["admin"]))  # type: ignore[arg-type]
    flags = out[0]
    assert flags.is_protokollant is True
    assert (flags.can_manage, flags.can_write, flags.can_finalize) == (True, True, True)
