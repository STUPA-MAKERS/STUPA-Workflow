"""Unit: VotingService Schreib-/Lifecycle-Autorisierung (AUD-027) ohne DB.

Deckt alle Zweige von ``_vote_gremium_id`` / ``assert_can_manage_group`` /
``assert_can_manage`` / ``assert_can_manage_vote`` ab (kritisches Modul → 100 %
Branch): Admin, globale ``vote.manage``, per-Gremium-Rolle (erlaubt/verweigert),
nicht auflösbares Gremium, Sitzungs-gebundene Auflösung über ``meeting_id``.
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
    async def _fake(_session: object, _sub: str, _perm: str) -> set[object]:
        return permitted

    monkeypatch.setattr(gremium_roles_mod, "gremium_ids_with_permission", _fake)


async def test_manage_admin_ok() -> None:
    """``admin``-Rolle darf jede Abstimmung verwalten (erster Zweig)."""
    principal = Principal(sub="a", roles=["admin"])
    await VotingService(fake_session()).assert_can_manage_group("stupa", None, principal)


async def test_manage_global_vote_manage_ok() -> None:
    """Globale ``vote.manage``-Permission genügt (zweiter Zweig)."""
    principal = Principal(sub="m", permissions={"vote.manage"})
    await VotingService(fake_session()).assert_can_manage_group("stupa", None, principal)


async def test_manage_gremium_role_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-Gremium-Rolle mit ``vote.manage`` für DAS Gremium des Votes → erlaubt.

    Gremium aus ``eligible_group`` (UUID-als-Text) aufgelöst, ohne ``meeting_id``."""
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    principal = Principal(sub="g")
    await VotingService(fake_session()).assert_can_manage_group(str(gid), None, principal)


async def test_manage_gremium_role_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auflösbares Gremium, aber der Principal hält dort kein ``vote.manage`` → 403."""
    gid = uuid4()
    _patch_permitted(monkeypatch, set())
    principal = Principal(sub="g")
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            str(gid), None, principal
        )


async def test_manage_unresolvable_group_denied() -> None:
    """Freier Gruppen-Key (keine UUID, keine Sitzung) → kein Gremium → 403."""
    principal = Principal(sub="x")
    with pytest.raises(ForbiddenError):
        await VotingService(fake_session()).assert_can_manage_group(
            "freikey", None, principal
        )


async def test_manage_resolves_gremium_via_meeting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sitzungs-gebundener Vote erbt das Gremium der Sitzung (``meeting_id``-Zweig)."""
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    db = fake_session()
    db.scalar_results = [gid]  # Meeting.gremium_id
    principal = Principal(sub="g")
    await VotingService(db).assert_can_manage_group("ignored", uuid4(), principal)


async def test_manage_meeting_without_gremium_falls_back_to_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``meeting_id`` ohne auflösbares Gremium → Fallback auf ``eligible_group``-UUID."""
    gid = uuid4()
    _patch_permitted(monkeypatch, {gid})
    db = fake_session()
    db.scalar_results = [None]  # Meeting-Lookup liefert nichts
    principal = Principal(sub="g")
    await VotingService(db).assert_can_manage_group(str(gid), uuid4(), principal)


async def test_assert_can_manage_loaded_vote_delegates() -> None:
    """``assert_can_manage`` delegiert an die Group-Variante (Admin-Kurzschluss)."""
    vote = SimpleNamespace(eligible_group="stupa", meeting_id=None)
    principal = Principal(sub="a", roles=["admin"])
    await VotingService(fake_session()).assert_can_manage(
        vote,  # pyright: ignore[reportArgumentType]
        principal,
    )


async def test_assert_can_manage_vote_loads_then_checks() -> None:
    """``assert_can_manage_vote`` lädt den Vote (404 sonst) und prüft dann."""
    vote = SimpleNamespace(id=uuid4(), eligible_group="stupa", meeting_id=None)
    principal = Principal(sub="a", roles=["admin"])
    await VotingService(fake_session(result(vote))).assert_can_manage_vote(
        vote.id, principal
    )
