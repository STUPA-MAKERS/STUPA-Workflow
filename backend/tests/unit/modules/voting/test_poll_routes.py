"""The poll routes (``POST /votes``, ``PATCH /votes/{id}``) and the start mail.

``dependency_overrides`` replaces the voting service, and a stub replaces
``PollService``. The service tests (``test_poll.py``) cover the rules.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.voting import router as voting_router
from app.modules.voting.schemas import PollCreate, PollPatch, TallyOut, VoteOut
from app.shared.config_schemas import PollConfig
from app.shared.errors import ForbiddenError

GID = UUID("00000000-0000-0000-0000-00000000b0c9")
_MANAGER = "fake:manager"
_POLL = PollConfig.model_validate(
    {"mode": "single", "options": [{"id": "o1", "label": "A"}, {"id": "o2", "label": "B"}]}
)


def _poll_out(status: str = "open", *, meeting_id: UUID | None = None) -> VoteOut:
    return VoteOut(
        id=uuid4(),
        meetingId=meeting_id,
        eligibleGroup=str(GID),
        config=_POLL.as_vote_config(),
        status=status,  # type: ignore[arg-type]
        secret=False,
        tally=TallyOut(counts={}, eligible=3, quorumMet=True),
        kind="poll",
        poll=_POLL,
    )


class _Service:
    def __init__(self) -> None:
        self.opened: VoteOut = _poll_out()

    async def assert_can_manage_vote(self, vote_id: UUID, principal: Principal) -> None:
        if _MANAGER not in principal.groups:
            raise ForbiddenError("not allowed to manage this vote")

    async def assert_can_run_vote(self, vote_id: UUID, principal: Principal) -> None:
        await self.assert_can_manage_vote(vote_id, principal)

    async def meeting_id_of(self, vote_id: UUID) -> None:
        return None

    async def open(self, vote_id: UUID, **_kw: Any) -> VoteOut:
        return self.opened


class _Polls:
    calls: list[tuple[str, Any]] = []
    created: VoteOut = _poll_out()

    def __init__(self, voting: object) -> None:
        self.voting = voting

    async def create(self, payload: PollCreate, principal: Principal, *, now: Any) -> VoteOut:
        _Polls.calls.append(("create", payload.draft))
        return _Polls.created

    async def patch(
        self, vote_id: UUID, payload: PollPatch, principal: Principal, *, now: Any
    ) -> VoteOut:
        _Polls.calls.append(("patch", payload.question))
        return _poll_out("draft")


class _Pub:
    async def vote_opened(self, vote: object) -> None:
        return None


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    sent: list[UUID] = []

    async def _notify(_settings: Any, vote_id: UUID, _pool: Any, **_kw: Any) -> bool:
        sent.append(vote_id)
        return True

    monkeypatch.setattr(voting_router, "notify_poll_started", _notify)
    return sent


@pytest.fixture
def routes(monkeypatch: pytest.MonkeyPatch) -> tuple[FastAPI, _Service]:
    from app.modules.livevote.publisher import get_meeting_publisher

    _Polls.calls = []
    _Polls.created = _poll_out()
    monkeypatch.setattr(voting_router, "PollService", _Polls)
    app = create_app()
    service = _Service()
    app.dependency_overrides[voting_router.get_voting_service] = lambda: service
    app.dependency_overrides[get_meeting_publisher] = lambda: _Pub()
    app.dependency_overrides[get_current_applicant] = lambda: None
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p", groups={_MANAGER})
    return app, service


def _body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "poll",
        "eligibleGroup": str(GID),
        "question": "Wohin?",
        "mode": "single",
        "options": [{"label": "A"}, {"label": "B"}],
        "closesAt": "2026-12-01T12:00:00+01:00",
    }
    body.update(over)
    return body


def test_create_poll_opens_and_mails(routes: tuple[FastAPI, _Service], mails: list[UUID]) -> None:
    app, _ = routes
    r = TestClient(app).post("/api/votes", json=_body())
    assert r.status_code == 200
    assert r.json()["kind"] == "poll"
    assert _Polls.calls == [("create", False)]
    assert mails == [_Polls.created.id]


def test_create_poll_as_draft_sends_no_mail(
    routes: tuple[FastAPI, _Service], mails: list[UUID]
) -> None:
    app, _ = routes
    _Polls.created = _poll_out("draft")
    r = TestClient(app).post("/api/votes", json=_body(draft=True))
    assert r.status_code == 200
    assert _Polls.calls == [("create", True)]
    assert mails == []


def test_create_poll_refuses_another_kind(routes: tuple[FastAPI, _Service]) -> None:
    app, _ = routes
    r = TestClient(app).post("/api/votes", json=_body(kind="motion"))
    assert r.status_code == 422
    assert _Polls.calls == []


def test_patch_poll_needs_the_manage_right(routes: tuple[FastAPI, _Service]) -> None:
    app, _ = routes
    client = TestClient(app)
    r = client.patch(f"/api/votes/{uuid4()}", json={"question": "Neu?"})
    assert r.status_code == 200
    assert _Polls.calls == [("patch", "Neu?")]
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="x")
    r = client.patch(f"/api/votes/{uuid4()}", json={"question": "Neu?"})
    assert r.status_code == 403
    assert r.headers["content-type"] == "application/problem+json"


def test_patch_poll_refuses_an_unknown_field(routes: tuple[FastAPI, _Service]) -> None:
    app, _ = routes
    r = TestClient(app).patch(f"/api/votes/{uuid4()}", json={"mode": "date"})
    assert r.status_code == 422


def test_open_gremium_poll_mails_the_members(
    routes: tuple[FastAPI, _Service], mails: list[UUID]
) -> None:
    app, service = routes
    r = TestClient(app).post(f"/api/votes/{uuid4()}/open")
    assert r.status_code == 200
    assert mails == [service.opened.id]


def test_open_meeting_poll_sends_no_mail(
    routes: tuple[FastAPI, _Service], mails: list[UUID]
) -> None:
    app, service = routes
    service.opened = _poll_out(meeting_id=uuid4())
    assert TestClient(app).post(f"/api/votes/{uuid4()}/open").status_code == 200
    assert mails == []
