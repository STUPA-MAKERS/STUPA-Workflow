"""Team mails about applications: who can act, and the default-off kinds.

A task mail goes only to a person who has the application as a task: the person can
read the application and fire a ``requires_action`` transition, or still cast a ballot
in an open vote. The kinds ``status_update_team``, ``task`` and ``task_reminder`` are
off until the person switches them on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.notifications import recipients as recipients_mod
from app.modules.notifications import service as service_mod
from app.modules.notifications.kinds import DEFAULT_OFF_KINDS, kind_default
from app.modules.notifications.models import NotificationPreference
from app.modules.notifications.service import (
    NotificationService,
    _filter_kind,
    filter_recipients_by_preference,
)
from app.settings import load_settings
from app.shared.errors import ForbiddenError
from tests._support.notifications_fakes import FakeSession

SETTINGS = load_settings()
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def _row(email: str | None = "a@x.de") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), sub=f"sub-{email}", email=email)


def _patch_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(_s: Any, row: Any, _now: Any) -> Principal:
        return Principal(sub=row.sub, email=row.email)

    monkeypatch.setattr("app.modules.auth.rbac.resolve_principal", fake_resolve)


def test_default_off_kinds() -> None:
    """The team mails about applications are off by default, every other kind is on."""
    assert {"status_update_team", "task", "task_reminder"} == DEFAULT_OFF_KINDS
    assert kind_default("task") is False
    assert kind_default("comment") is True
    assert kind_default("status_update") is True


def test_filter_kind_team_send() -> None:
    """A status send without an applicant spec filters on the team kind."""
    assert _filter_kind("status_update", [{"kind": "gremium", "ref": "g"}]) == (
        "status_update_team"
    )
    assert _filter_kind("status_update", [{"kind": "applicant"}]) == "status_update"
    assert _filter_kind("comment", [{"kind": "gremium", "ref": "g"}]) == "comment"


async def test_filter_default_off_keeps_opt_in_and_non_accounts() -> None:
    """A default-off kind keeps an opted-in account and an address without an account."""
    session = FakeSession(
        executes=[[("In@x.de", True), ("out@x.de", None), ("no@x.de", False), (None, None)]]
    )
    out = await filter_recipients_by_preference(
        cast(AsyncSession, session),
        ["in@x.de", "out@x.de", "no@x.de", "list@x.de"],
        "task",
    )
    assert out == ["in@x.de", "list@x.de"]


async def test_set_preferences_stores_opt_in_for_default_off_kind() -> None:
    """Switching a default-off kind on stores an enabled row; switching it off removes it."""
    pid = uuid.uuid4()
    existing = NotificationPreference(principal_id=pid, kind="task_reminder", enabled=True)
    stale = NotificationPreference(principal_id=pid, kind="status_update_team", enabled=False)
    session = FakeSession(scalar=[pid, pid], executes=[[("task", True)]])
    session.store[(pid, "task_reminder")] = existing  # type: ignore[index]
    session.store[(pid, "status_update_team")] = stale  # type: ignore[index]
    deleted: list[Any] = []

    async def delete(obj: Any) -> None:
        deleted.append(obj)

    session.delete = delete  # type: ignore[attr-defined]

    async def get(_model: Any, ident: Any) -> Any:
        return session.store.get(ident)

    session.get = get  # type: ignore[method-assign]
    svc = NotificationService(
        cast(AsyncSession, session), queue=None, settings=SETTINGS
    )
    out = dict(
        await svc.set_preferences(
            "u",
            [("task", True), ("task_reminder", False), ("status_update_team", True)],
        )
    )
    added = {(p.kind, p.enabled) for p in session.added}
    assert ("task", True) in added
    assert existing in deleted
    assert stale.enabled is True
    assert out["task"] is True
    assert out["status_update_team"] is False


async def test_readers_keeps_only_principals_who_can_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A candidate without read access to the application gets no task mail."""
    reader, outsider = _row("r@x.de"), _row("o@x.de")
    _patch_resolve(monkeypatch)

    async def fake_read(_s: Any, _app_id: Any, principal: Principal, _a: Any) -> None:
        if principal.email == "o@x.de":
            raise ForbiddenError("no")

    monkeypatch.setattr("app.modules.applications.access.resolve_app_read", fake_read)
    session = FakeSession(scalars=[[reader, outsider]])
    out = await recipients_mod._readers(
        cast(AsyncSession, session), uuid.uuid4(), [reader.id, outsider.id], NOW
    )
    assert out == {reader.id}


async def test_readers_without_candidates_runs_no_query() -> None:
    """No candidate means no query; the FIFO fake proves it."""
    out = await recipients_mod._readers(
        cast(AsyncSession, FakeSession()), uuid.uuid4(), [], NOW
    )
    assert out == set()


async def test_actionable_drops_firable_candidate_without_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A firable candidate that cannot read the application gets no mail."""
    from app.modules.flow.models import State
    from app.shared.guards import GuardContext

    keep = recipients_mod.ActionableCandidate(
        principal_id=uuid.uuid4(),
        sub="k",
        email="k@x.de",
        roles=frozenset(),
        committees=frozenset(),
    )
    drop = recipients_mod.ActionableCandidate(
        principal_id=uuid.uuid4(),
        sub="d",
        email="d@x.de",
        roles=frozenset(),
        committees=frozenset(),
    )

    async def fake_base(_s: Any, _app: Any, *, manual: bool) -> GuardContext:
        return GuardContext(manual=manual)

    async def fake_candidates(_s: Any, _now: Any, *, gremium_id: Any) -> list[Any]:
        return [keep, drop]

    async def fake_readers(_s: Any, _app_id: Any, _ids: Any, _now: Any) -> set[uuid.UUID]:
        return {keep.principal_id}

    monkeypatch.setattr(recipients_mod, "build_base_context", fake_base)
    monkeypatch.setattr(recipients_mod, "_candidates_with_transition_permission", fake_candidates)
    monkeypatch.setattr(recipients_mod, "_readers", fake_readers)
    app = SimpleNamespace(
        id=uuid.uuid4(),
        current_state_id=uuid.uuid4(),
        flow_version_id=uuid.uuid4(),
        gremium_id=None,
        created_by=None,
    )
    session = FakeSession(scalar=[app], scalars=[[SimpleNamespace(guard=None)]])
    out = await recipients_mod.actionable_principal_emails(
        cast(AsyncSession, session), application_id=app.id, state=State(kind="normal")
    )
    assert out == ["k@x.de"]


async def test_open_vote_casters_without_open_vote_is_empty() -> None:
    """A vote state without an open vote is no task: nobody gets mail."""
    app = SimpleNamespace(id=uuid.uuid4(), vote_gremium_id=uuid.uuid4())
    out = await recipients_mod._open_vote_casters(
        cast(AsyncSession, FakeSession(scalars=[[]])), app, NOW  # type: ignore[arg-type]
    )
    assert out == []


async def test_open_vote_casters_without_vote_gremium_is_empty() -> None:
    app = SimpleNamespace(id=uuid.uuid4(), vote_gremium_id=None)
    out = await recipients_mod._open_vote_casters(
        cast(AsyncSession, FakeSession(scalars=[[SimpleNamespace()]])),
        app,  # type: ignore[arg-type]
        NOW,
    )
    assert out == []


async def test_open_vote_casters_keeps_members_who_can_still_cast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a member that an open vote still takes a ballot from gets mail."""
    voter, done, guest = _row("v@x.de"), _row("d@x.de"), _row("g@x.de")
    _patch_resolve(monkeypatch)
    votes = [SimpleNamespace(name="v1"), SimpleNamespace(name="v2")]

    class FakeVoting:
        def __init__(self, _s: Any) -> None:
            pass

        async def can_still_cast(self, vote: Any, principal: Principal, *, now: Any) -> bool:
            return principal.email == "v@x.de" and vote.name == "v2"

    monkeypatch.setattr("app.modules.voting.service.VotingService", FakeVoting)
    app = SimpleNamespace(id=uuid.uuid4(), vote_gremium_id=uuid.uuid4())
    session = FakeSession(
        scalars=[votes, [voter.id, done.id, guest.id], [voter, done, guest]]
    )
    out = await recipients_mod._open_vote_casters(
        cast(AsyncSession, session), app, NOW  # type: ignore[arg-type]
    )
    assert out == ["v@x.de"]


async def test_team_status_send_skipped_without_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flow notify to a Gremium sends nothing while no member switched the kind on."""
    seen: list[str] = []

    async def fake_filter(_s: Any, recipients: list[str], kind: str) -> list[str]:
        seen.append(kind)
        return []

    monkeypatch.setattr(service_mod, "filter_recipients_by_preference", fake_filter)

    class Resolver:
        async def resolve(self, _specs: Any, **_kw: Any) -> list[str]:
            return ["m@x.de"]

    svc = NotificationService(
        cast(AsyncSession, FakeSession()), queue=None, settings=SETTINGS
    )
    svc.resolver = Resolver()  # type: ignore[assignment]
    count = await svc.handle_notify_action(
        {"type": "notify", "recipients": [{"kind": "gremium", "ref": "g"}]}
    )
    assert count == 0
    assert seen == ["status_update_team"]
