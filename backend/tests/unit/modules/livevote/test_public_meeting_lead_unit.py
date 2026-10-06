"""The lead side of a public meeting (#17) without a database.

Covers the lead routes, the `guestsVote` rules of the vote open, the WebSocket filter of
the member channel, the guest events of the publisher, the public settings of a patch,
the rate-limit dependencies, the protocol line of a guest vote and the name rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.connection import LiveVoteConnection
from app.modules.livevote.router import (
    get_agenda_service,
    get_attendance_service,
    get_guest_service,
    get_meeting_service,
    get_voting_service,
)
from app.modules.livevote.schemas import (
    GuestNameBody,
    MeetingGuestOut,
    MeetingPatch,
    clean_guest_name,
)
from app.modules.livevote.service import BrokerPublisher, MeetingService
from app.modules.livevote.service.lifecycle import LifecycleOps
from app.modules.protocol.markdown import build_vote_snippet, guest_vote_note
from app.modules.protocol.service import _guest_note
from app.modules.voting.schemas import TallyOut, VoteOut
from app.settings import get_settings
from app.shared import antiabuse
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, RateLimitedError
from app.shared.ratelimit import InMemoryRateLimiter
from tests._support.flow_fakes import FakeSession, result
from tests.unit.modules.livevote.test_livevote_cov import (
    _FakeAgendaService,
    _FakeAttendanceService,
    _FakeMeetingService,
    _FakeVotingService,
    _meeting_out,
)

NOW = datetime(2026, 10, 6, 18, 0, tzinfo=UTC)


def _guest_out(**over: Any) -> MeetingGuestOut:
    base: dict[str, Any] = {
        "id": uuid4(),
        "number": 1,
        "displayName": "Jana",
        "status": "pending",
        "requestedAt": NOW,
    }
    base.update(over)
    return MeetingGuestOut.model_validate(base)


class Meetings(_FakeMeetingService):
    async def meeting_gremium_id(self, meeting_id: UUID) -> UUID:
        return uuid4()

    async def present_member_count(self, meeting_id: UUID) -> int:
        return 19

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        return 23


class Guests:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list(self, meeting_id: UUID) -> list[MeetingGuestOut]:
        self.calls.append("list")
        return [_guest_out()]

    async def admit_all(self, meeting_id: UUID, *, actor_sub: str) -> list[MeetingGuestOut]:
        self.calls.append("admit_all")
        return []

    async def _one(self, name: str) -> MeetingGuestOut:
        self.calls.append(name)
        return _guest_out()

    async def admit(self, m: UUID, g: UUID, *, actor_sub: str) -> MeetingGuestOut:
        return await self._one("admit")

    async def reject(self, m: UUID, g: UUID, *, actor_sub: str) -> MeetingGuestOut:
        return await self._one("reject")

    async def remove(self, m: UUID, g: UUID, *, actor_sub: str) -> MeetingGuestOut:
        return await self._one("remove")

    async def rename(self, m: UUID, g: UUID, name: str, *, actor_sub: str) -> MeetingGuestOut:
        return await self._one(f"rename:{name}")

    async def join_link(self, m: UUID) -> Any:
        self.calls.append("link")
        return {
            "joinCode": "7KQ4MP",
            "joinUrl": "https://x/j/7KQ4MP",
            "qr": {"size": 1, "rows": ["1"]},
        }

    async def rotate(self, m: UUID, *, actor_sub: str) -> Any:
        self.calls.append("rotate")
        return await self.join_link(m)


@pytest.fixture
def setup() -> Any:
    meetings = Meetings()
    agenda = _FakeAgendaService()
    voting = _FakeVotingService()
    guests = Guests()
    app: FastAPI = create_app()
    app.dependency_overrides[get_meeting_service] = lambda: meetings
    app.dependency_overrides[get_attendance_service] = lambda: _FakeAttendanceService()
    app.dependency_overrides[get_agenda_service] = lambda: agenda
    app.dependency_overrides[get_voting_service] = lambda: voting
    app.dependency_overrides[get_guest_service] = lambda: guests
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="lead")
    return TestClient(app), meetings, agenda, voting, guests


def test_lead_routes(setup: Any) -> None:
    client, meetings, _, _, guests = setup
    base = f"/api/meetings/{uuid4()}"
    gid = uuid4()
    assert client.get(f"{base}/guests").status_code == 200
    for action in ("admit", "reject", "remove"):
        assert client.post(f"{base}/guests/{gid}/{action}").status_code == 200
    assert (
        client.post(f"{base}/guests/{gid}/rename", json={"displayName": " Jana  R "}).status_code
        == 200
    )
    assert client.post(f"{base}/guests/admit-all").json() == []
    assert client.get(f"{base}/join-link").json()["joinCode"] == "7KQ4MP"
    assert client.post(f"{base}/join-code/rotate").status_code == 200
    assert guests.calls == [
        "list",
        "admit",
        "reject",
        "remove",
        "rename:Jana R",
        "admit_all",
        "link",
        "rotate",
        "link",
    ]
    meetings._can_manage = False
    assert client.get(f"{base}/guests").status_code == 403


def _meeting(public: bool, mode: str = "vote") -> Any:
    out = _meeting_out(status="live", can_manage_votes=True)
    return out.model_copy(update={"public_join": public, "guests_mode": mode, "admitted_guests": 7})


@pytest.mark.parametrize(
    ("public", "mode", "non_public", "body", "status", "guests_vote"),
    [
        (True, "vote", False, {}, 200, True),
        (True, "vote", True, {}, 200, False),
        (True, "watch", False, {}, 200, False),
        (False, "vote", False, {"guestsVote": True}, 422, None),
        (True, "vote", True, {"guestsVote": True}, 422, None),
        (True, "vote", False, {"guestsVote": False}, 200, False),
    ],
)
def test_open_vote_guest_rules(
    setup: Any,
    public: bool,
    mode: str,
    non_public: bool,
    body: dict[str, Any],
    status: int,
    guests_vote: bool | None,
) -> None:
    client, meetings, agenda, voting, _ = setup
    meetings._meeting_out = _meeting(public, mode)
    agenda.item_row = SimpleNamespace(id=uuid4(), application_id=None, non_public=non_public)
    resp = client.post(
        f"/api/meetings/{uuid4()}/votes", json={"agendaItemId": str(uuid4()), **body}
    )
    assert resp.status_code == status, resp.text
    if guests_vote is None:
        return
    payload = voting.last_payload
    assert payload.config.guests_vote is guests_vote
    if guests_vote:
        assert payload.config.quorum is None and payload.eligible_count == 26
    else:
        assert payload.eligible_count == 23


async def test_member_channel_filter() -> None:
    def conn(*, beamer: bool, can_manage: bool) -> LiveVoteConnection:
        return LiveVoteConnection(
            SimpleNamespace(),  # type: ignore[arg-type]
            uuid4(),
            beamer=beamer,
            principal=Principal(sub="p"),
            meetings=SimpleNamespace(),  # type: ignore[arg-type]
            voting=SimpleNamespace(),  # type: ignore[arg-type]
            broker=InMemoryBroker(),
            locker=SimpleNamespace(),  # type: ignore[arg-type]
            can_manage=can_manage,
        )

    counts = {"type": "guest_counts", "joinCode": "7KQ4MP", "pendingGuests": 3, "admittedGuests": 7}
    named = {"type": "guest_requested", "guest": {"displayName": "Jana"}}
    lead = conn(beamer=False, can_manage=True)
    member = conn(beamer=False, can_manage=False)
    beamer = conn(beamer=True, can_manage=True)
    assert lead._filter(named) == named and lead._filter(counts) == counts
    assert member._filter(named) is None
    assert member._filter(counts) == {**counts, "joinCode": None, "pendingGuests": 0}
    assert member._filter({"type": "vote_tally"}) == {"type": "vote_tally"}
    assert beamer._filter(counts) == counts and beamer._filter(named) is None


async def test_publisher_guest_events() -> None:
    broker = InMemoryBroker()
    mid = uuid4()
    async with broker.subscribe(f"meeting:{mid}") as sub:
        publisher = BrokerPublisher(broker)
        await publisher.guest_requested(mid, _guest_out())
        await publisher.guest_updated(mid, _guest_out(status="expired"), "rotated")
        await publisher.guest_counts(
            mid, public_join=True, guests_mode="vote", join_code="X", admitted=1, pending=2
        )
        it = sub.__aiter__()
        got = [await it.__anext__() for _ in range(3)]
    assert [g["type"] for g in got] == ["guest_requested", "guest_updated", "guest_counts"]
    assert got[1]["reason"] == "rotated" and got[2]["pendingGuests"] == 2


class _Lifecycle(LifecycleOps):
    def __init__(self, session: Any, open_vote: bool = False) -> None:
        super().__init__(session)
        self.open_vote_flag = open_vote

    async def _guest_vote_open(self, meeting_id: UUID) -> bool:
        return self.open_vote_flag


def _m(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "gremium_id": uuid4(),
        "public_join": False,
        "guests_mode": "vote",
        "join_code": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


async def test_apply_public_rules() -> None:
    lead = Principal(sub="lead")
    m = _m()
    # No change: no audit.
    assert (
        await _Lifecycle(FakeSession())._apply_public(m, MeetingPatch(publicJoin=False), lead, NOW)  # type: ignore[arg-type]
        is None
    )
    # Switch on: a code, the audit entry, a counts event.
    session = FakeSession()
    events = await _Lifecycle(session)._apply_public(m, MeetingPatch(publicJoin=True), lead, NOW)  # type: ignore[arg-type]
    assert m.public_join is True and m.join_code is not None and events is not None
    [entry] = [a for a in session.added if type(a).__name__ == "AuditEntry"]
    assert entry.action == "meeting_public_join_changed"
    assert entry.data["publicJoin"] == {"from": False, "to": True}
    # vote -> watch with an open guest vote: 409.
    with pytest.raises(ConflictError) as err:
        await _Lifecycle(FakeSession(), open_vote=True)._apply_public(
            m,  # type: ignore[arg-type]
            MeetingPatch(guestsMode="watch"),
            lead,
            NOW,  # type: ignore[arg-type]
        )
    assert err.value.code == "guest_vote_open"
    # Switch off removes the guests.
    off = await _Lifecycle(FakeSession())._apply_public(
        m,  # type: ignore[arg-type]
        MeetingPatch(publicJoin=False),
        lead,
        NOW,  # type: ignore[arg-type]
    )
    assert m.public_join is False and off is not None and off.counts is True
    # Watch while off: only the mode changes.
    watch = await _Lifecycle(FakeSession())._apply_public(
        m,  # type: ignore[arg-type]
        MeetingPatch(guestsMode="watch"),
        lead,
        NOW,  # type: ignore[arg-type]
    )
    assert m.guests_mode == "watch" and watch is not None


async def test_guest_vote_open_query() -> None:
    session = FakeSession()
    session.scalar_results = [uuid4()]
    assert await MeetingService(session)._guest_vote_open(uuid4()) is True  # type: ignore[arg-type]
    assert await MeetingService(FakeSession())._guest_vote_open(uuid4()) is False  # type: ignore[arg-type]


async def test_meeting_reads_for_guests() -> None:
    session = FakeSession([result((uuid4(), "admitted", 2), (uuid4(), "pending", 1))])
    svc = MeetingService(session)  # type: ignore[arg-type]
    counts = await svc._guest_counts([uuid4()])
    assert sorted(counts.values()) == [(0, 1), (2, 0)]
    assert await svc._guest_counts([]) == {}
    assert await svc.admitted_guests_by_meeting([]) == {}
    mid = uuid4()
    session = FakeSession([result((mid, 3))])
    assert await MeetingService(session).present_member_count(mid) == 3  # type: ignore[arg-type]
    session = FakeSession([result(SimpleNamespace(gremium_id=mid))])
    assert await MeetingService(session).meeting_gremium_id(uuid4()) == mid  # type: ignore[arg-type]


def test_patch_body_accepts_public_fields_only() -> None:
    assert MeetingPatch(guestsMode="watch").guests_mode == "watch"
    with pytest.raises(ValueError):
        MeetingPatch()


def test_guest_names() -> None:
    assert clean_guest_name("  Jana   Roth ") == "Jana Roth"
    for bad in ("J", "x" * 81, "   "):
        with pytest.raises(ValueError):
            clean_guest_name(bad)
    assert GuestNameBody(displayName=" Al ").display_name == "Al"


def test_protocol_line_of_a_guest_vote() -> None:
    assert guest_vote_note(19, 7, 24) == (
        "19 Mitglieder + 7 Gäste anwesend · Abgegeben 24 · Mehrheit der abgegebenen Stimmen"
    )
    assert guest_vote_note(None, None, 3) == "Abgegeben 3 · Mehrheit der abgegebenen Stimmen"
    snippet = build_vote_snippet("Q", {"yes": 2}, note="Abgegeben 2")
    assert snippet.splitlines()[-1] == "> Abgegeben 2"
    config = VoteConfig.model_validate({"options": ["yes", "no"], "majorityRule": "simple"})

    def view(guests: bool) -> VoteOut:
        return VoteOut(
            id=uuid4(),
            eligibleGroup="g",
            config=config,
            status="closed",
            secret=False,
            guestsVote=guests,
            tally=TallyOut(
                counts={"yes": 2, "no": 1},
                eligible=3,
                quorumMet=True,
                presentMembers=2,
                presentGuests=1,
            ),
        )

    assert _guest_note(view(False)) is None
    assert (
        _guest_note(view(True))
        == "2 Mitglieder + 1 Gäste anwesend · Abgegeben 3 · Mehrheit der abgegebenen Stimmen"
    )


def _request(path: str = "/api/public/meetings/join/7kq-4mp", cookie: str | None = None) -> Request:
    headers = [(b"cookie", f"mg_token={cookie}".encode())] if cookie else []
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": headers,
            "client": ("10.0.0.1", 1),
            "path_params": {"code": "7kq-4mp"},
        }
    )


async def test_public_rate_limits() -> None:
    settings = get_settings().model_copy(
        update={
            "rl_public_join_ip_per_hour": 1,
            "rl_public_join_code_per_hour": 1,
            "rl_public_meeting_read_ip_per_hour": 1,
            "rl_public_guest_write_per_hour": 1,
        }
    )
    limiter = InMemoryRateLimiter()
    await antiabuse.rate_limit_public_join(_request(), settings, limiter)
    with pytest.raises(RateLimitedError):
        await antiabuse.rate_limit_public_join(_request(), settings, limiter)
    await antiabuse.rate_limit_public_read(_request(), settings, limiter)
    with pytest.raises(RateLimitedError):
        await antiabuse.rate_limit_public_read(_request(), settings, limiter)
    from app.modules.livevote.public_router import rate_limit_public_guest_write

    # A cookie that resolves to a guest counts against that guest.
    known = FakeSession()
    known.scalar_results = [uuid4()]
    await rate_limit_public_guest_write(_request(cookie="tok"), settings, limiter, known)  # type: ignore[arg-type]
    # Unknown cookies and no cookie count against the IP: random cookies get no budget.
    await rate_limit_public_guest_write(_request(cookie="r1"), settings, limiter, FakeSession())  # type: ignore[arg-type]
    with pytest.raises(RateLimitedError):
        await rate_limit_public_guest_write(_request(cookie="r2"), settings, limiter, FakeSession())  # type: ignore[arg-type]
    with pytest.raises(RateLimitedError):
        await rate_limit_public_guest_write(_request(), settings, limiter, FakeSession())  # type: ignore[arg-type]


def test_cookie_lifetime_follows_the_meeting_day() -> None:
    from datetime import date as _date

    from app.modules.livevote.public_router import cookie_ttl_seconds

    settings = get_settings()
    now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    assert cookie_ttl_seconds(None, settings, now) == 24 * 3600
    assert cookie_ttl_seconds(_date(2026, 10, 6), settings, now) == 36 * 3600
    assert cookie_ttl_seconds(_date(2026, 10, 20), settings, now) == (14 * 24 + 36) * 3600
    assert cookie_ttl_seconds(_date(2026, 9, 1), settings, now) == 24 * 3600


def test_guest_name_drops_hidden_characters() -> None:
    assert clean_guest_name("Ja\u200bna\u202e Roth\x07") == "Jana Roth"
    with pytest.raises(ValueError):
        clean_guest_name("\u200b\u200bA")


def test_meeting_defaults_route(setup: Any) -> None:
    client, meetings, *_ = setup
    resp = client.get(f"/api/gremien/{uuid4()}/meeting-defaults")
    assert resp.json() == {"publicJoinAllowed": True, "quorumPercent": None}
    meetings._can_manage = False
    assert client.get(f"/api/gremien/{uuid4()}/meeting-defaults").status_code == 403


async def test_public_join_needs_a_gremium_without_quorum() -> None:
    from app.shared.errors import ValidationProblem

    lead = Principal(sub="lead")
    session = FakeSession()
    session.scalar_results = [50]  # the gremium quorum
    with pytest.raises(ValidationProblem) as err:
        await _Lifecycle(session)._apply_public(_m(), MeetingPatch(publicJoin=True), lead, NOW)  # type: ignore[arg-type]
    assert err.value.code == "public_join_needs_no_quorum"
    no_quorum = FakeSession()
    assert await MeetingService(no_quorum).gremium_has_quorum(uuid4()) is False  # type: ignore[arg-type]
    assert await MeetingService(no_quorum)._gremium_quorum_set(uuid4()) is False  # type: ignore[arg-type]
    with_quorum = FakeSession()
    with_quorum.get_results = [SimpleNamespace(quorum_percent=50)]
    assert await MeetingService(with_quorum)._gremium_quorum_set(uuid4()) is True  # type: ignore[arg-type]


async def test_votes_for_counts_guests_of_a_guest_vote() -> None:
    from app.modules.voting.models import Vote

    mid = uuid4()
    config = VoteConfig.model_validate(
        {"options": ["yes", "no"], "majorityRule": "simple", "guestsVote": True}
    ).model_dump(by_alias=True)
    vote = Vote(
        id=uuid4(),
        meeting_id=mid,
        agenda_item_id=None,
        application_id=None,
        eligible_group=str(uuid4()),
        config=config,
        status="open",
        eligible_count=3,
    )
    session = FakeSession([result(vote), result(), result(), result((mid, 2)), result((mid, 1))])
    out = await MeetingService(session)._votes_for([mid])  # type: ignore[arg-type]
    [item] = out[mid]
    assert item.guests_vote is True and item.present == 3
    assert (item.present_members, item.present_guests) == (2, 1)


async def test_agenda_refuses_non_public_on_a_guest_vote_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.livevote.agenda_service import AgendaService

    service = AgendaService(FakeSession())  # type: ignore[arg-type]
    row = SimpleNamespace(id=uuid4(), application_id=None, body=None, title="T", non_public=False)

    async def _meeting(meeting_id: UUID) -> Any:
        return SimpleNamespace(status="live")

    async def _item(meeting_id: UUID, item_id: UUID) -> Any:
        return row

    async def _open(meeting: Any, *, planned_ok: bool) -> None:
        return None

    async def _has(item_id: UUID) -> bool:
        return True

    monkeypatch.setattr(service, "_meeting", _meeting)
    monkeypatch.setattr(service, "item", _item)
    monkeypatch.setattr(service, "_assert_minutes_open", _open)
    monkeypatch.setattr(service, "_has_guest_vote", _has)
    with pytest.raises(ConflictError) as err:
        await service.set_body(uuid4(), row.id, non_public=True)
    assert err.value.code == "guests_vote_on_item"
    session = FakeSession()
    session.scalar_results = [uuid4()]
    assert await AgendaService(session)._has_guest_vote(uuid4()) is True  # type: ignore[arg-type]
