"""Public meeting with a QR code (#17) on a real Postgres.

The tests drive the lead routes, the public guest routes and both WebSockets through
the real app wiring: the join with its cookie, the decisions of the lead, the guest
view without non-public content, the guest ballot (open and secret), the rules for the
quorum and the late admission, the switch-off, the close and the protocol finalize
(privacy), the audit entries without names, ALTCHA, CSRF and the rate limits.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from datetime import time as _time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.models import Gremium
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.livevote.broker import InMemoryBroker
from app.modules.livevote.models import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingGuest,
)
from app.modules.livevote.publisher import get_meeting_publisher
from app.modules.livevote.router import get_broker_rest, get_broker_ws, get_ws_principal
from app.modules.livevote.service import BrokerPublisher
from app.modules.protocol.models import Protocol
from app.modules.protocol.service import ProtocolService
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.settings import Settings, get_settings, load_settings
from app.shared.altcha import AltchaVerifier, InMemoryReplayGuard, create_challenge, solve_challenge
from app.shared.antiabuse import get_altcha_verifier, get_rate_limiter
from app.shared.ratelimit import InMemoryRateLimiter

pytestmark = pytest.mark.integration

LEAD_SUB = "lead-pub"
ALTCHA_SECRET = "altcha-secret-public-meeting-000000"


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Any
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@dataclass
class Ctx:
    app: FastAPI
    settings: Settings
    principal: dict[str, Principal | None]


def _make_app(
    migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch, **settings_over: Any
) -> Ctx:
    over: dict[str, Any] = {"csrf_enabled": False, "rate_limit_enabled": False}
    over.update(settings_over)
    settings = load_settings(
        database_url=migrated[1],
        session_secret="session-secret-public-meet-0000",
        magic_link_secret="magic-link-secret-public-meet0",
        cookie_secure=False,
        public_base_url="https://stupa.example",
        **over,
    )
    request_maker = async_sessionmaker(
        create_async_engine(migrated[1], poolclass=NullPool), expire_on_commit=False
    )

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with request_maker() as db:
            yield db

    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: request_maker)
    application = create_app(settings)
    broker = InMemoryBroker()
    holder: dict[str, Principal | None] = {
        "p": Principal(sub=LEAD_SUB, roles=["admin"], permissions={"meeting.view_all"})
    }
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    application.dependency_overrides[get_broker_rest] = lambda: broker
    application.dependency_overrides[get_broker_ws] = lambda: broker
    application.dependency_overrides[get_meeting_publisher] = lambda: BrokerPublisher(broker)
    application.dependency_overrides[get_current_principal] = lambda: holder["p"]
    application.dependency_overrides[get_ws_principal] = lambda: holder["p"]
    return Ctx(application, settings, holder)


@pytest.fixture
def ctx(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[Ctx]:
    c = _make_app(migrated, monkeypatch)
    try:
        yield c
    finally:
        c.app.dependency_overrides.clear()


@dataclass
class Seed:
    gremium_id: uuid.UUID
    meeting_id: uuid.UUID
    public_item: uuid.UUID
    secret_item: uuid.UUID
    np_item: uuid.UUID
    members: list[uuid.UUID]


async def seed(
    maker: async_sessionmaker[AsyncSession],
    *,
    status: str = "live",
    public_join: bool = True,
    guests_mode: str = "vote",
    present: int = 2,
    quorum_percent: int | None = None,
) -> Seed:
    """A live meeting with two public free-text items, one non-public item, members."""
    tag = uuid.uuid4().hex[:8]
    async with maker() as session:
        gremium = Gremium(name=f"Fachschaft {tag}", slug=f"fs-{tag}", quorum_percent=quorum_percent)
        session.add(gremium)
        lead = PrincipalRow(sub=LEAD_SUB, display_name="Lea Lead", email=f"l-{tag}@x.de")
        existing = await session.scalar(select(PrincipalRow).where(PrincipalRow.sub == LEAD_SUB))
        if existing is None:
            session.add(lead)
        await session.flush()
        writer = PrincipalRow(sub=f"w-{tag}", display_name="W", email=f"w-{tag}@x.de")
        session.add(writer)
        await session.flush()
        meeting = Meeting(
            gremium_id=gremium.id,
            title="7. Sitzung",
            date=_date(2026, 10, 6),
            start_time=_time(18, 0),
            status=status,
            protokollant_id=writer.id,
            public_join=public_join,
            guests_mode=guests_mode,
            join_code=("A" + tag[:5])
            .upper()
            .replace("0", "2")
            .replace("1", "3")
            .replace("O", "P")
            .replace("I", "J")
            .replace("L", "M")
            if public_join
            else None,
        )
        session.add(meeting)
        await session.flush()
        items = []
        for n, (title, non_public) in enumerate(
            [("Öffentlich", False), ("Geheim", False), ("Personal", True)]
        ):
            item = MeetingAgendaItem(
                meeting_id=meeting.id,
                title=title,
                position=n,
                non_public=non_public,
                body=f"Text {title}",
            )
            session.add(item)
            await session.flush()
            items.append(item.id)
        members = []
        for n in range(present):
            p = PrincipalRow(sub=f"m{n}-{tag}", display_name=f"M{n}", email=f"m{n}-{tag}@x.de")
            session.add(p)
            await session.flush()
            session.add(
                MeetingAttendance(meeting_id=meeting.id, principal_id=p.id, status="present")
            )
            members.append(p.id)
        await session.commit()
        return Seed(gremium.id, meeting.id, items[0], items[1], items[2], members)


async def code_of(maker: async_sessionmaker[AsyncSession], meeting_id: uuid.UUID) -> str:
    async with maker() as session:
        meeting = await session.get(Meeting, meeting_id)
        assert meeting is not None and meeting.join_code is not None
        return meeting.join_code


def join(client: TestClient, code: str, name: str = "Jana Roth") -> Any:
    return client.post(f"/api/public/meetings/join/{code}", json={"displayName": name})


def guest_client(app: FastAPI) -> TestClient:
    return TestClient(app)


async def guests(
    maker: async_sessionmaker[AsyncSession], meeting_id: uuid.UUID
) -> list[MeetingGuest]:
    async with maker() as session:
        return list(
            (
                await session.scalars(
                    select(MeetingGuest)
                    .where(MeetingGuest.meeting_id == meeting_id)
                    .order_by(MeetingGuest.seq)
                )
            ).all()
        )


async def audits(maker: async_sessionmaker[AsyncSession]) -> list[AuditEntry]:
    async with maker() as session:
        return list((await session.scalars(select(AuditEntry).order_by(AuditEntry.id))).all())


def admit_one(lead: TestClient, s: Seed, guest_id: str) -> None:
    resp = lead.post(f"/api/meetings/{s.meeting_id}/guests/{guest_id}/admit")
    assert resp.status_code == 200, resp.text


def open_vote(lead: TestClient, s: Seed, item: uuid.UUID, **body: Any) -> dict[str, Any]:
    resp = lead.post(
        f"/api/meetings/{s.meeting_id}/votes", json={"agendaItemId": str(item), **body}
    )
    assert resp.status_code == 200, resp.text
    return next(
        v for v in resp.json()["votes"] if v["agendaItemId"] == str(item) and v["status"] == "open"
    )


# -- meeting settings ---------------------------------------------------------------


async def test_create_and_patch_public_settings(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker, status="planned", public_join=False)
    with TestClient(ctx.app) as lead:
        resp = lead.post(
            "/api/meetings",
            json={
                "gremiumId": str(s.gremium_id),
                "title": "Neu",
                "date": "2026-11-01",
                "startTime": "18:00",
                "publicJoin": True,
                "guestsMode": "watch",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["publicJoin"] is True and body["guestsMode"] == "watch"
        assert len(body["joinCode"]) == 6
        assert set(body["joinCode"]) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
        # Off -> on gives a code; the change writes its own audit action.
        resp = lead.patch(f"/api/meetings/{s.meeting_id}", json={"publicJoin": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["joinCode"]
        link = lead.get(f"/api/meetings/{s.meeting_id}/join-link").json()
        assert link["joinUrl"] == f"https://stupa.example/j/{link['joinCode']}"
        assert link["qr"]["size"] == len(link["qr"]["rows"]) >= 21
        assert set("".join(link["qr"]["rows"])) <= {"0", "1"}
        # A plain member sees neither the code nor the open requests.
        ctx.principal["p"] = Principal(sub="plain", permissions={"meeting.view_all"})
        member_view = lead.get(f"/api/meetings/{s.meeting_id}").json()
        assert member_view["publicJoin"] is True and member_view["joinCode"] is None
        assert lead.get(f"/api/meetings/{s.meeting_id}/guests").status_code == 403
        assert lead.get(f"/api/meetings/{s.meeting_id}/join-link").status_code == 403
    entries = [e for e in await audits(maker) if e.action == "meeting_public_join_changed"]
    assert entries[-1].data["publicJoin"] == {"from": False, "to": True}


async def test_join_link_of_a_meeting_without_public_join(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker, public_join=False)
    with TestClient(ctx.app) as lead:
        resp = lead.get(f"/api/meetings/{s.meeting_id}/join-link")
        assert resp.status_code == 409 and resp.json()["code"] == "meeting_not_public"
        assert lead.post(f"/api/meetings/{s.meeting_id}/join-code/rotate").status_code == 409


# -- join, decisions, guest state ------------------------------------------------------


async def test_join_admit_and_guest_view_without_non_public_content(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as phone:
        head = phone.get(f"/api/public/meetings/{code[:3].lower()}-{code[3:].lower()}")
        assert head.status_code == 200, head.text
        assert head.json()["title"] == "7. Sitzung" and head.json()["guestsMode"] == "vote"
        resp = join(phone, code, "  Jana   Roth ")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "pending" and resp.json()["displayName"] == "Jana Roth"
        cookie = resp.headers["set-cookie"]
        assert "mg_token=" in cookie and "HttpOnly" in cookie
        assert "SameSite=strict" in cookie or "samesite=strict" in cookie.lower()
        assert "Path=/api/public/meetings" in cookie
        me = phone.get(f"/api/public/meetings/{code}/me").json()
        assert me["status"] == "pending" and me["view"] is None
        listed = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        assert [g["status"] for g in listed] == ["pending"]
        assert lead.get(f"/api/meetings/{s.meeting_id}").json()["pendingGuests"] == 1
        admit_one(lead, s, listed[0]["id"])
        me = phone.get(f"/api/public/meetings/{code}/me").json()
        assert me["status"] == "admitted"
        view = me["view"]
        assert view["presentMembers"] == 2 and view["admittedGuests"] == 1
        by_id = {a["id"]: a for a in view["agenda"]}
        assert by_id[str(s.public_item)]["body"] == "Text Öffentlich"
        # A non-public item keeps its title but never its text.
        assert by_id[str(s.np_item)] == {
            "id": str(s.np_item),
            "position": 3,
            "title": "Personal",
            "kind": "freetext",
            "nonPublic": True,
            "body": None,
        }
        # A second admit gives 409.
        again = lead.post(f"/api/meetings/{s.meeting_id}/guests/{listed[0]['id']}/admit")
        assert again.status_code == 409 and again.json()["code"] == "guest_not_pending"
        assert lead.get(f"/api/meetings/{s.meeting_id}").json()["admittedGuests"] == 1
        # The admitted device cannot ask again.
        dup = join(phone, code)
        assert dup.status_code == 409 and dup.json()["code"] == "already_admitted"
    [entry] = [e for e in await audits(maker) if e.action == "guest_admitted"]
    assert entry.actor == LEAD_SUB
    assert entry.data == {
        "meetingId": str(s.meeting_id),
        "gremiumId": str(s.gremium_id),
        "guestId": listed[0]["id"],
    }
    assert "Jana" not in str(entry.data)


async def test_public_routes_reject_bad_tokens_and_codes(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    other = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    other_code = await code_of(maker, other.meeting_id)
    with guest_client(ctx.app) as phone:
        assert phone.get("/api/public/meetings/ZZZZZZ").json()["code"] == "join_code_unknown"
        missing = phone.get(f"/api/public/meetings/{code}/me")
        assert missing.status_code == 401 and missing.json()["code"] == "guest_token_missing"
        phone.cookies.set("mg_token", "forged-token", path="/api/public/meetings")
        forged = phone.get(f"/api/public/meetings/{code}/me")
        assert forged.status_code == 404 and forged.json()["code"] == "guest_not_found"
        phone.cookies.clear()
        assert join(phone, code).status_code == 200
        # The token of meeting A does not open meeting B.
        cross = phone.get(f"/api/public/meetings/{other_code}/me")
        assert cross.status_code == 404 and cross.json()["code"] == "guest_not_found"
        bad_name = phone.post(f"/api/public/meetings/join/{code}", json={"displayName": "J"})
        assert bad_name.status_code == 422
        extra = phone.post(
            f"/api/public/meetings/join/{code}", json={"displayName": "Jo Do", "admin": True}
        )
        assert extra.status_code == 422
    async with maker() as session:
        await session.execute(
            update(Meeting).where(Meeting.id == s.meeting_id).values(public_join=False)
        )
        await session.commit()
    with guest_client(ctx.app) as phone:
        resp = phone.get(f"/api/public/meetings/{code}")
        # The same 404 as an unknown code: nobody can probe the codes.
        assert resp.status_code == 404 and resp.json()["code"] == "join_code_unknown"


async def test_reject_and_ask_again_after_three_minutes(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as phone:
        assert join(phone, code).status_code == 200
        [g] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        resp = lead.post(f"/api/meetings/{s.meeting_id}/guests/{g['id']}/reject")
        assert resp.status_code == 200 and resp.json()["status"] == "rejected"
        me = phone.get(f"/api/public/meetings/{code}/me").json()
        assert me["status"] == "rejected" and 170 <= me["retryAfter"] <= 180
        early = join(phone, code, "Jana R.")
        assert early.status_code == 429 and early.json()["code"] == "retry_later"
        assert 1 <= int(early.headers["retry-after"]) <= 180
        async with maker() as session:
            await session.execute(
                update(MeetingGuest)
                .where(MeetingGuest.id == uuid.UUID(g["id"]))
                .values(decided_at=datetime.now(UTC) - timedelta(minutes=4))
            )
            await session.commit()
        later = join(phone, code, "Jana R.")
        assert later.status_code == 200, later.text
        assert later.json()["status"] == "pending"
        # Same device, same row: the request is the old one again.
        assert later.json()["guestId"] == g["id"]
    [row] = await guests(maker, s.meeting_id)
    assert row.display_name == "Jana R." and row.decided_at is None


async def test_second_request_of_a_device_replaces_the_first(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with guest_client(ctx.app) as phone:
        first = join(phone, code, "Jana").json()
        second = join(phone, code, "Jana Roth").json()
        assert first["guestId"] == second["guestId"]
        renamed = phone.patch(f"/api/public/meetings/{code}/me", json={"displayName": "J. Roth"})
        assert renamed.status_code == 200 and renamed.json()["displayName"] == "J. Roth"
    rows = await guests(maker, s.meeting_id)
    assert len(rows) == 1 and rows[0].display_name == "J. Roth"


async def test_remove_rename_admit_all_and_leave(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as a, guest_client(ctx.app) as b:
        assert join(a, code, "Anna A").status_code == 200
        assert join(b, code, "Bert B").status_code == 200
        admitted = lead.post(f"/api/meetings/{s.meeting_id}/guests/admit-all").json()
        assert {g["displayName"] for g in admitted} == {"Anna A", "Bert B"}
        assert all(g["decidedByName"] == "Lea Lead" for g in admitted)
        assert lead.post(f"/api/meetings/{s.meeting_id}/guests/admit-all").json() == []
        anna = next(g for g in admitted if g["displayName"] == "Anna A")
        renamed = lead.post(
            f"/api/meetings/{s.meeting_id}/guests/{anna['id']}/rename",
            json={"displayName": "Anna Ahrens"},
        )
        assert renamed.json()["displayName"] == "Anna Ahrens"
        # The guest can change the name only while waiting.
        late = a.patch(f"/api/public/meetings/{code}/me", json={"displayName": "Nope Nope"})
        assert late.status_code == 409 and late.json()["code"] == "guest_not_pending"
        removed = lead.post(f"/api/meetings/{s.meeting_id}/guests/{anna['id']}/remove")
        assert removed.json()["status"] == "removed"
        again = lead.post(f"/api/meetings/{s.meeting_id}/guests/{anna['id']}/remove")
        assert again.json()["code"] == "guest_not_admitted"
        # Leaving pseudonymizes at once and clears the cookie.
        left = b.delete(f"/api/public/meetings/{code}/me")
        assert left.status_code == 204
        assert "mg_token=" in left.headers["set-cookie"]
        bert = next(g for g in admitted if g["displayName"] == "Bert B")
        rows = {g["id"]: g for g in lead.get(f"/api/meetings/{s.meeting_id}/guests").json()}
        assert rows[bert["id"]]["status"] == "left" and rows[bert["id"]]["displayName"] is None
        gone = lead.post(
            f"/api/meetings/{s.meeting_id}/guests/{bert['id']}/rename",
            json={"displayName": "Bert"},
        )
        assert gone.json()["code"] == "guest_pseudonymized"
        # A removed device asks again only after 3 minutes, then as a new request.
        assert join(a, code).json()["code"] == "retry_later"
    names = " ".join(str(e.data) for e in await audits(maker))
    assert "Anna" not in names and "Bert" not in names
    actions = [e.action for e in await audits(maker)]
    assert {"guest_admit_all", "guest_renamed", "guest_removed"} <= set(actions)


# -- votes with guests ------------------------------------------------------------------


async def test_guest_votes_without_quorum_and_late_admission(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    # A quorum of 100 % of 2 members: a members-only vote without ballots cannot close.
    s = await seed(maker, quorum_percent=100)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as a, guest_client(ctx.app) as b:
        assert join(a, code, "Anna A").status_code == 200
        [ga] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        admit_one(lead, s, ga["id"])
        vote = open_vote(lead, s, s.public_item, question="Zuschuss?")
        assert vote["guestsVote"] is True and vote["quorum"] is None
        # 2 present members + 1 guest.
        assert vote["present"] == 3 and vote["presentGuests"] == 1
        detail = lead.get(f"/api/votes/{vote['id']}").json()
        assert detail["guestsVote"] is True and detail["config"]["guestsVote"] is True
        ok = a.post(
            f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "yes"}
        )
        assert ok.status_code == 200 and ok.json() == {"status": "cast"}
        dup = a.post(
            f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "no"}
        )
        assert dup.status_code == 409 and dup.json()["code"] == "already_voted"
        bad = a.post(f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "x"})
        assert bad.status_code == 422
        # Admitted while the vote runs: votes too.
        assert join(b, code, "Bert B").status_code == 200
        pending = b.post(
            f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "no"}
        )
        assert pending.status_code == 403 and pending.json()["code"] == "guest_not_admitted"
        gb = next(
            g
            for g in lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
            if g["status"] == "pending"
        )
        admit_one(lead, s, gb["id"])
        me = b.get(f"/api/public/meetings/{code}/me").json()
        [gv] = me["view"]["votes"]
        assert gv["canCast"] is True and gv["guestsVote"] is True
        assert (
            b.post(
                f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "yes"}
            ).status_code
            == 200
        )
        me = b.get(f"/api/public/meetings/{code}/me").json()
        assert me["view"]["votes"][0]["myBallot"] == {"cast": True, "choice": "yes", "choices": None}
        assert me["view"]["votes"][0]["canCast"] is False
        # No quorum: the vote closes with 2 guest ballots although no member voted.
        closed = lead.post(f"/api/votes/{vote['id']}/close")
        assert closed.status_code == 200, closed.text
        assert closed.json()["result"] == "passed"
        assert closed.json()["tally"]["presentMembers"] == 2
        assert closed.json()["tally"]["presentGuests"] == 2
        # A members-only vote keeps the quorum and refuses the close without ballots.
        members_only = open_vote(lead, s, s.secret_item, guestsVote=False)
        assert members_only["guestsVote"] is False and members_only["quorum"] is not None
        refused = lead.post(f"/api/votes/{members_only['id']}/close")
        assert refused.status_code == 409
        guest_try = a.post(
            f"/api/public/meetings/{code}/votes/{members_only['id']}/ballot",
            json={"choice": "yes"},
        )
        assert guest_try.status_code == 403 and guest_try.json()["code"] == "vote_members_only"
    async with maker() as session:
        row = await session.get(Vote, uuid.UUID(vote["id"]))
        assert row is not None
        assert (row.present_members, row.present_guests, row.eligible_count) == (2, 2, 4)
        voters = set(
            (await session.scalars(select(Ballot.voter_sub).where(Ballot.vote_id == row.id))).all()
        )
    assert voters == {f"guest:{ga['id']}", f"guest:{gb['id']}"}
    casts = [e for e in await audits(maker) if e.action == "vote_cast"]
    assert {e.actor for e in casts} == voters
    assert all("choice" not in e.data for e in casts)


async def test_secret_guest_ballot_keeps_identity_apart(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as a:
        assert join(a, code).status_code == 200
        [g] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        admit_one(lead, s, g["id"])
        vote = open_vote(lead, s, s.secret_item, secret=True)
        resp = a.post(
            f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "no"}
        )
        assert resp.status_code == 200, resp.text
        me = a.get(f"/api/public/meetings/{code}/me").json()
        mine = next(v for v in me["view"]["votes"] if v["id"] == vote["id"])
        assert mine["myBallot"] == {"cast": True, "choice": None, "choices": None}
        assert mine["tally"]["revealed"] is False and mine["tally"]["counts"] == {}
    async with maker() as session:
        vid = uuid.UUID(vote["id"])
        markers = (
            await session.scalars(select(VotedMarker.voter_sub).where(VotedMarker.vote_id == vid))
        ).all()
        choices = (
            await session.scalars(select(SecretBallot.choice).where(SecretBallot.vote_id == vid))
        ).all()
        ballots = (await session.scalars(select(Ballot.id).where(Ballot.vote_id == vid))).all()
    assert list(markers) == [f"guest:{g['id']}"]
    assert list(choices) == ["no"]
    assert list(ballots) == []


async def test_non_public_item_and_watch_mode(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as a:
        assert join(a, code).status_code == 200
        [g] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        admit_one(lead, s, g["id"])
        refused = lead.post(
            f"/api/meetings/{s.meeting_id}/votes",
            json={"agendaItemId": str(s.np_item), "guestsVote": True},
        )
        assert refused.status_code == 422 and refused.json()["code"] == "guests_vote_non_public"
        np_vote = open_vote(lead, s, s.np_item)
        assert np_vote["guestsVote"] is False
        # The guest never sees the vote of a non-public item and cannot vote in it.
        me = a.get(f"/api/public/meetings/{code}/me").json()
        assert me["view"]["votes"] == []
        hidden = a.post(
            f"/api/public/meetings/{code}/votes/{np_vote['id']}/ballot", json={"choice": "yes"}
        )
        assert hidden.status_code == 404
        assert lead.post(f"/api/votes/{np_vote['id']}/cancel").status_code == 200
        guest_vote = open_vote(lead, s, s.public_item)
        # vote -> watch is blocked while a vote with guests is open.
        blocked = lead.patch(f"/api/meetings/{s.meeting_id}", json={"guestsMode": "watch"})
        assert blocked.status_code == 409 and blocked.json()["code"] == "guest_vote_open"
        # The item of a guest vote cannot become non-public.
        np = lead.patch(
            f"/api/meetings/{s.meeting_id}/agenda/{s.public_item}", json={"nonPublic": True}
        )
        assert np.status_code == 409 and np.json()["code"] == "guests_vote_on_item"
        assert lead.post(f"/api/votes/{guest_vote['id']}/cancel").status_code == 200
        watch = lead.patch(f"/api/meetings/{s.meeting_id}", json={"guestsMode": "watch"})
        assert watch.status_code == 200 and watch.json()["guestsMode"] == "watch"
        unavailable = lead.post(
            f"/api/meetings/{s.meeting_id}/votes",
            json={"agendaItemId": str(s.secret_item), "guestsVote": True},
        )
        assert (
            unavailable.status_code == 422
            and unavailable.json()["code"] == "guests_vote_unavailable"
        )
        watch_vote = open_vote(lead, s, s.secret_item)
        assert watch_vote["guestsVote"] is False and watch_vote["present"] == 2
        refused_ballot = a.post(
            f"/api/public/meetings/{code}/votes/{watch_vote['id']}/ballot", json={"choice": "yes"}
        )
        assert (
            refused_ballot.status_code == 403
            and refused_ballot.json()["code"] == "guests_watch_only"
        )
        me = a.get(f"/api/public/meetings/{code}/me").json()
        assert me["meeting"]["guestsMode"] == "watch"
        assert all(v["canCast"] is False for v in me["view"]["votes"])


async def test_switch_off_voids_requests_and_ends_guests(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as a, guest_client(ctx.app) as b:
        assert join(a, code, "Anna A").status_code == 200
        [ga] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        admit_one(lead, s, ga["id"])
        vote = open_vote(lead, s, s.public_item)
        assert (
            a.post(
                f"/api/public/meetings/{code}/votes/{vote['id']}/ballot", json={"choice": "yes"}
            ).status_code
            == 200
        )
        assert join(b, code, "Bert B").status_code == 200
        off = lead.patch(f"/api/meetings/{s.meeting_id}", json={"publicJoin": False})
        assert off.status_code == 200, off.text
        assert off.json()["admittedGuests"] == 0 and off.json()["pendingGuests"] == 0
        assert a.get(f"/api/public/meetings/{code}/me").json()["code"] == "meeting_not_public"
        # The cast ballot stays counted.
        assert lead.get(f"/api/votes/{vote['id']}").json()["tally"]["voted"] == 1
    rows = await guests(maker, s.meeting_id)
    assert [(r.display_name, r.status) for r in rows] == [("Anna A", "removed")]


async def test_rotate_voids_requests_and_keeps_admitted_guests(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as a, guest_client(ctx.app) as b:
        assert join(a, code, "Anna A").status_code == 200
        [ga] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        admit_one(lead, s, ga["id"])
        assert join(b, code, "Bert B").status_code == 200
        link = lead.post(f"/api/meetings/{s.meeting_id}/join-code/rotate").json()
        assert link["joinCode"] != code
        assert b.get(f"/api/public/meetings/{code}").json()["code"] == "join_code_unknown"
        assert b.get(f"/api/public/meetings/{code}/me").status_code == 404
        # The admitted guest keeps working with the old link.
        assert a.get(f"/api/public/meetings/{code}/me").json()["status"] == "admitted"
    rows = await guests(maker, s.meeting_id)
    assert [r.display_name for r in rows] == ["Anna A"]
    [entry] = [e for e in await audits(maker) if e.action == "meeting_join_code_rotated"]
    assert entry.data["voidedRequests"] == 1
    assert code not in str(entry.data) and link["joinCode"] not in str(entry.data)


async def test_close_purges_requests_and_finalize_pseudonymizes(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with (
        TestClient(ctx.app) as lead,
        guest_client(ctx.app) as a,
        guest_client(ctx.app) as b,
        guest_client(ctx.app) as c,
    ):
        assert join(a, code, "Anna A").status_code == 200
        assert join(b, code, "Bert B").status_code == 200
        assert join(c, code, "Cleo C").status_code == 200
        listed = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        by_name = {g["displayName"]: g for g in listed}
        admit_one(lead, s, by_name["Anna A"]["id"])
        lead.post(f"/api/meetings/{s.meeting_id}/guests/{by_name['Bert B']['id']}/reject")
        assert c.delete(f"/api/public/meetings/{code}/me").status_code == 204
        closed = lead.patch(f"/api/meetings/{s.meeting_id}", json={"status": "closed"})
        assert closed.status_code == 200, closed.text
        # The closed meeting refuses a join and the token no longer works.
        assert join(b, code).json()["code"] == "join_code_unknown"
        assert b.get(f"/api/public/meetings/{code}").status_code == 404
        assert a.get(f"/api/public/meetings/{code}/me").status_code == 404
    rows = await guests(maker, s.meeting_id)
    # The close pseudonymizes at the latest (ruling 2026-10-06); the count stays.
    assert [(r.display_name, r.status) for r in rows] == [(None, "admitted")]
    assert rows[0].token_hash is None
    async with maker() as session:
        protocol = Protocol(meeting_id=s.meeting_id, gremium_id=s.gremium_id, status="draft")
        session.add(protocol)
        await session.commit()
        await ProtocolService(session).start_finalize(protocol.id, actor=LEAD_SUB)
    rows = await guests(maker, s.meeting_id)
    assert [(r.display_name, r.seq) for r in rows] == [(None, 1)]


async def test_lead_websocket_gets_guest_events_and_members_do_not(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with TestClient(ctx.app) as client, guest_client(ctx.app) as phone:
        with client.websocket_connect(f"/api/ws/meetings/{s.meeting_id}") as ws:
            _drain_until(ws, "viewers")
            assert join(phone, code, "Jana Roth").status_code == 200
            event = _drain_until(ws, "guest_requested")
            assert event["guest"]["displayName"] == "Jana Roth"
            counts = _drain_until(ws, "guest_counts")
            assert counts["pendingGuests"] == 1 and counts["joinCode"] == code
        ctx.principal["p"] = Principal(sub="plain", permissions={"meeting.view_all"})
        with client.websocket_connect(f"/api/ws/meetings/{s.meeting_id}") as ws:
            _drain_until(ws, "viewers")
            assert join(phone, code, "Jana R").status_code == 200
            counts = _drain_until(ws, "guest_counts")
            # No name event before the counts, and no code for a plain member.
            assert counts["joinCode"] is None and counts["pendingGuests"] == 0


async def test_guest_websocket_filters_names_and_non_public_votes(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    with (
        TestClient(ctx.app) as lead,
        guest_client(ctx.app) as phone,
        guest_client(ctx.app) as other,
    ):
        assert join(phone, code, "Jana Roth").status_code == 200
        [g] = lead.get(f"/api/meetings/{s.meeting_id}/guests").json()
        with phone.websocket_connect(f"/api/public/meetings/{code}/ws") as ws:
            first = ws.receive_json()
            assert first == {
                "type": "guest_status",
                "status": "pending",
                "displayName": "Jana Roth",
                "number": 1,
                "reason": None,
            }
            # Another request reaches the lead, never this guest.
            assert join(other, code, "Bert Other").status_code == 200
            admit_one(lead, s, g["id"])
            seen: list[dict[str, Any]] = []
            status = _drain_until(ws, "guest_status", seen=seen)
            assert status["status"] == "admitted"
            np_vote = open_vote(lead, s, s.np_item)
            public_vote = open_vote(lead, s, s.public_item)
            opened = _drain_until(ws, "vote_opened", seen=seen)
            # The vote of the non-public item never arrives.
            assert opened["voteId"] == public_vote["id"]
            assert all(m.get("voteId") != np_vote["id"] for m in seen)
            assert all("Bert" not in str(m) for m in seen)
            assert all(m["type"] != "viewers" for m in seen)
        # A missing or unknown token closes the handshake.
        with (
            pytest.raises(WebSocketDisconnect),
            other.websocket_connect("/api/public/meetings/ZZZZZZ/ws") as ws2,
        ):
            ws2.receive_json()


def _drain_until(
    ws: Any, kind: str, limit: int = 20, *, seen: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    for _ in range(limit):
        message = ws.receive_json()
        if seen is not None:
            seen.append(message)
        if message.get("type") == kind:
            return message
    raise AssertionError(f"no {kind} event")


# -- abuse protection -----------------------------------------------------------------


async def test_altcha_csrf_and_rate_limits(
    maker: async_sessionmaker[AsyncSession],
    migrated: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    c = _make_app(
        migrated,
        monkeypatch,
        csrf_enabled=True,
        rate_limit_enabled=True,
        altcha_hmac_secret=ALTCHA_SECRET,
        rl_public_join_ip_per_hour=2,
    )
    limiter = InMemoryRateLimiter()
    verifier = AltchaVerifier(ALTCHA_SECRET, replay=InMemoryReplayGuard())
    c.app.dependency_overrides[get_rate_limiter] = lambda: limiter
    c.app.dependency_overrides[get_altcha_verifier] = lambda: verifier

    def solution() -> str:
        return solve_challenge(create_challenge(ALTCHA_SECRET, max_number=200))

    with guest_client(c.app) as phone:
        no_captcha = phone.post(f"/api/public/meetings/join/{code}", json={"displayName": "Jo Do"})
        assert no_captcha.status_code == 400 and no_captcha.json()["code"] == "altcha_failed"
        ok = phone.post(
            f"/api/public/meetings/join/{code}",
            json={"displayName": "Jo Do", "altcha": solution()},
        )
        assert ok.status_code == 200, ok.text
        # With the device cookie a write needs the CSRF header (double submit).
        no_header = phone.patch(f"/api/public/meetings/{code}/me", json={"displayName": "Jo Doe"})
        assert no_header.status_code == 403 and no_header.json()["code"] == "csrf_failed"
        token = phone.cookies.get("XSRF-TOKEN")
        assert token
        with_header = phone.patch(
            f"/api/public/meetings/{code}/me",
            json={"displayName": "Jo Doe"},
            headers={"X-XSRF-TOKEN": token},
        )
        assert with_header.status_code == 200, with_header.text
        # The join limit per IP (2 per hour in this test).
        limited = phone.post(
            f"/api/public/meetings/join/{code}",
            json={"displayName": "Jo Do", "altcha": solution()},
            headers={"X-XSRF-TOKEN": token},
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"]
    c.app.dependency_overrides.clear()


async def test_public_join_only_without_a_quorum(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    s = await seed(maker, status="planned", public_join=False, quorum_percent=50)
    with TestClient(ctx.app) as lead:
        resp = lead.patch(f"/api/meetings/{s.meeting_id}", json={"publicJoin": True})
        assert resp.status_code == 422 and resp.json()["code"] == "public_join_needs_no_quorum"
        created = lead.post(
            "/api/meetings",
            json={
                "gremiumId": str(s.gremium_id),
                "title": "Neu",
                "date": "2026-11-01",
                "startTime": "18:00",
                "publicJoin": True,
            },
        )
        assert created.status_code == 422
        detail = lead.get(f"/api/meetings/{s.meeting_id}").json()
        assert detail["publicJoinAllowed"] is False
        defaults = lead.get(f"/api/gremien/{s.gremium_id}/meeting-defaults").json()
        assert defaults == {"publicJoinAllowed": False, "quorumPercent": 50}


async def test_admitted_device_joining_another_meeting_leaves_the_first(
    maker: async_sessionmaker[AsyncSession], ctx: Ctx
) -> None:
    a_seed = await seed(maker)
    b_seed = await seed(maker)
    code_a = await code_of(maker, a_seed.meeting_id)
    code_b = await code_of(maker, b_seed.meeting_id)
    with TestClient(ctx.app) as lead, guest_client(ctx.app) as phone:
        assert join(phone, code_a, "Jana Roth").status_code == 200
        [g] = lead.get(f"/api/meetings/{a_seed.meeting_id}/guests").json()
        admit_one(lead, a_seed, g["id"])
        assert join(phone, code_b, "Jana Roth").status_code == 200
        assert lead.get(f"/api/meetings/{a_seed.meeting_id}").json()["admittedGuests"] == 0
    [row] = await guests(maker, a_seed.meeting_id)
    assert (row.status, row.display_name, row.token_hash) == ("left", None, None)


async def test_random_cookies_share_the_ip_budget(
    maker: async_sessionmaker[AsyncSession],
    migrated: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await seed(maker)
    code = await code_of(maker, s.meeting_id)
    c = _make_app(migrated, monkeypatch, rate_limit_enabled=True, rl_public_guest_write_per_hour=2)
    limiter = InMemoryRateLimiter()
    c.app.dependency_overrides[get_rate_limiter] = lambda: limiter
    with guest_client(c.app) as phone:
        codes = []
        for n in range(3):
            phone.cookies.set("mg_token", f"random-{n}", path="/api/public/meetings")
            codes.append(phone.delete(f"/api/public/meetings/{code}/me").status_code)
            phone.cookies.clear()
    assert codes == [404, 404, 429]
    c.app.dependency_overrides.clear()
