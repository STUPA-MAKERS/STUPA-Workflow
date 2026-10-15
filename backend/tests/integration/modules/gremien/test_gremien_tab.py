"""The reads of the tab "Gremien" against a real Postgres.

The unit suite checks every branch with fakes. This suite checks that the SQL holds:
the gate (member, ``gremium.view_all``, admin, else 404), the attendance aggregation
(present, excused, vote transfer, pool substitute, member months), the meeting counts
and the decisions with their sums.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.main as main_mod
from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.delegations.models import MeetingDelegation
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.protocol.models import Protocol
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.settings import get_settings, load_settings
from app.shared.config_schemas import VoteConfig

pytestmark = pytest.mark.integration

PLAIN = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "simple"}
).model_dump(by_alias=True)
SECRET = VoteConfig.model_validate(
    {"options": ["yes", "no", "abstain"], "majorityRule": "two_thirds", "secret": True}
).model_dump(by_alias=True)
ELECTION = {
    "seats": 1,
    "candidates": [{"id": "c1", "name": "Jonas Albrecht"}, {"id": "c2", "name": "Mara Keller"}],
    "secret": True,
}


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@dataclass
class World:
    gremium_id: uuid.UUID
    other_id: uuid.UUID
    me: Principal
    ids: dict[str, uuid.UUID] = field(default_factory=dict)


@pytest.fixture
def app_for(migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    settings = load_settings(
        database_url=migrated[1],
        session_secret="session-secret-gremien-tab-000",
        magic_link_secret="magic-link-secret-gremien-tab0",
        cookie_secure=False,
    )
    request_maker = async_sessionmaker(
        create_async_engine(migrated[1], poolclass=NullPool), expire_on_commit=False
    )

    async def _request_session() -> AsyncIterator[AsyncSession]:
        async with request_maker() as db:
            yield db

    monkeypatch.setattr(main_mod, "get_sessionmaker", lambda: request_maker)
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_session] = _request_session
    try:
        yield application
    finally:
        application.dependency_overrides.clear()


def _client(app: FastAPI, principal: Principal) -> TestClient:
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app)


async def _world(maker: async_sessionmaker[AsyncSession]) -> World:
    tag = uuid.uuid4().hex[:8]
    async with maker() as s:
        g = Gremium(name=f"STUPA {tag}", slug=f"stupa-{tag}", quorum_percent=50)
        other = Gremium(name=f"AStA {tag}", slug=f"asta-{tag}")
        s.add_all([g, other])
        await s.flush()
        vorstand = GremiumRole(
            gremium_id=g.id, key="vorstand", name_i18n={"de": "Vorstand"}, permissions=[]
        )
        member = GremiumRole(
            gremium_id=g.id, key="member", name_i18n={"de": "Mitglied"}, permissions=["vote.cast"]
        )
        other_member = GremiumRole(
            gremium_id=other.id, key="member", name_i18n={"de": "Mitglied"}, permissions=[]
        )
        s.add_all([vorstand, member, other_member])
        await s.flush()
        people: dict[str, PrincipalRow] = {}
        for name in ("me", "alice", "bob", "sub", "outsider"):
            row = PrincipalRow(
                sub=f"{name}-{tag}", display_name=name.title(), email=f"{name}-{tag}@x.de"
            )
            s.add(row)
            people[name] = row
        await s.flush()
        s.add_all(
            [
                GremiumMembership(
                    principal_id=people["me"].id, gremium_id=g.id, gremium_role_id=vorstand.id
                ),
                GremiumMembership(
                    principal_id=people["alice"].id, gremium_id=g.id, gremium_role_id=member.id
                ),
                # Bob left at the end of May.
                GremiumMembership(
                    principal_id=people["bob"].id,
                    gremium_id=g.id,
                    gremium_role_id=member.id,
                    valid_until=datetime(2026, 5, 31, 22, 0, tzinfo=UTC),
                ),
                GremiumMembership(
                    principal_id=people["outsider"].id,
                    gremium_id=other.id,
                    gremium_role_id=other_member.id,
                ),
            ]
        )
        meetings: dict[str, Meeting] = {}
        for key, day, status in (
            ("m1", date(2026, 5, 10), "closed"),
            ("m2", date(2026, 5, 20), "closed"),
            ("m3", date(2026, 6, 5), "closed"),
            ("m4", date(2099, 1, 1), "planned"),
            ("m5", date(2099, 2, 1), "planned"),
        ):
            m = Meeting(
                gremium_id=g.id,
                title=f"Sitzung {key}",
                date=day,
                start_time=time(18, 0),
                status=status,
            )
            s.add(m)
            meetings[key] = m
        await s.flush()
        s.add_all(
            [
                MeetingAgendaItem(meeting_id=meetings["m1"].id, title="TOP 1", position=0),
                MeetingAgendaItem(meeting_id=meetings["m1"].id, title="TOP 2", position=1),
                Protocol(meeting_id=meetings["m1"].id, gremium_id=g.id, status="final"),
                Protocol(meeting_id=meetings["m3"].id, gremium_id=g.id, status="draft"),
                MeetingAttendance(
                    meeting_id=meetings["m1"].id,
                    principal_id=people["me"].id,
                    status="present",
                    note="x",
                ),
                MeetingAttendance(
                    meeting_id=meetings["m1"].id,
                    principal_id=people["alice"].id,
                    status="excused",
                    note="krank",
                ),
                MeetingAttendance(
                    meeting_id=meetings["m1"].id, principal_id=people["sub"].id, status="present"
                ),
                MeetingAttendance(
                    meeting_id=meetings["m1"].id, principal_id=people["bob"].id, status="present"
                ),
                MeetingAttendance(
                    meeting_id=meetings["m2"].id, principal_id=people["me"].id, status="present"
                ),
                MeetingAttendance(
                    meeting_id=meetings["m2"].id, principal_id=people["alice"].id, status="present"
                ),
                MeetingAttendance(
                    meeting_id=meetings["m3"].id, principal_id=people["me"].id, status="excused"
                ),
                MeetingDelegation(
                    meeting_id=meetings["m1"].id,
                    gremium_id=g.id,
                    delegator_principal_id=people["alice"].id,
                    delegate_principal_id=people["sub"].id,
                    delegate_voting=True,
                    via_pool=True,
                ),
            ]
        )
        await s.flush()
        closed = datetime(2026, 5, 10, 19, 0, tzinfo=UTC)
        motion = Vote(
            meeting_id=meetings["m1"].id,
            eligible_group=str(g.id),
            question="Lastenrad",
            config=PLAIN,
            status="closed",
            result="passed",
            closed_at=closed,
        )
        secret = Vote(
            meeting_id=meetings["m1"].id,
            eligible_group=str(g.id),
            question="Geschäftsordnung § 7",
            config=SECRET,
            status="closed",
            result="rejected",
            closed_at=datetime(2026, 5, 10, 19, 30, tzinfo=UTC),
        )
        election = Vote(
            meeting_id=meetings["m1"].id,
            eligible_group=str(g.id),
            question="Wahl der Sitzungsleitung",
            config=ELECTION,
            kind="election",
            status="closed",
            result="elected",
            election_result={"counts": {"c1": 2, "c2": 1}, "ballots": 3, "elected": ["c1"]},
            closed_at=datetime(2026, 5, 10, 20, 0, tzinfo=UTC),
        )
        draft = Vote(
            meeting_id=meetings["m1"].id,
            eligible_group=str(g.id),
            question="Entwurf",
            config=PLAIN,
            status="draft",
        )
        foreign = Vote(
            eligible_group=str(other.id),
            question="Fremd",
            config=PLAIN,
            status="closed",
            result="passed",
            closed_at=closed,
        )
        s.add_all([motion, secret, election, draft, foreign])
        await s.flush()
        s.add_all(
            [
                Ballot(vote_id=motion.id, voter_sub="a", choice="yes"),
                Ballot(vote_id=motion.id, voter_sub="b", choice="yes"),
                Ballot(vote_id=motion.id, voter_sub="c", choice="no"),
                Ballot(vote_id=motion.id, voter_sub="d", choice="abstain"),
                VotedMarker(vote_id=secret.id, voter_sub="a"),
                VotedMarker(vote_id=secret.id, voter_sub="b"),
                SecretBallot(vote_id=secret.id, choice="no"),
                SecretBallot(vote_id=secret.id, choice="yes"),
            ]
        )
        await s.commit()
        me = Principal(sub=people["me"].sub, display_name="Me")
        world = World(gremium_id=g.id, other_id=other.id, me=me)
        world.ids = {k: v.id for k, v in people.items()} | {k: v.id for k, v in meetings.items()}
        world.ids |= {"motion": motion.id, "secret": secret.id, "election": election.id}
        return world


async def test_overview_member_and_view_all(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    w = await _world(maker)
    rows = _client(app_for, w.me).get("/api/gremien/overview").json()
    assert [r["id"] for r in rows] == [str(w.gremium_id)]
    row = rows[0]
    assert row["isMember"] is True
    assert row["roleKey"] == "vorstand"
    assert row["roleName"] == {"de": "Vorstand"}
    # me and alice; bob left.
    assert row["memberCount"] == 2
    assert row["nextMeeting"]["id"] == str(w.ids["m4"])
    assert row["live"] is False
    assert row["quorumPercent"] == 50
    assert row["logoUrl"] is None

    viewer = Principal(sub="viewer-x", permissions={"gremium.view_all"})
    ids = {r["id"] for r in _client(app_for, viewer).get("/api/gremien/overview").json()}
    assert {str(w.gremium_id), str(w.other_id)} <= ids


async def test_gate_hides_foreign_gremium(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    w = await _world(maker)
    outsider = Principal(sub=f"outsider-{w.me.sub.split('-', 1)[1]}")
    client = _client(app_for, outsider)
    for path in ("members", "meetings", "attendance", "decisions"):
        resp = client.get(f"/api/gremien/{w.gremium_id}/{path}")
        assert resp.status_code == 404, path
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert resp.json()["code"] == "gremium_not_found"
    assert client.get(f"/api/gremien/{uuid.uuid4()}/members").status_code == 404
    admin = Principal(sub="admin-x", roles=["admin"])
    assert _client(app_for, admin).get(f"/api/gremien/{w.gremium_id}/members").status_code == 200


async def test_members_and_former(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    w = await _world(maker)
    client = _client(app_for, w.me)
    rows = client.get(f"/api/gremien/{w.gremium_id}/members").json()
    assert [r["displayName"] for r in rows] == ["Me", "Alice"]
    assert rows[0]["isSelf"] is True and rows[0]["roleKey"] == "vorstand"
    assert rows[1]["email"].startswith("alice-")
    former = client.get(f"/api/gremien/{w.gremium_id}/members", params={"former": "true"}).json()
    assert [r["displayName"] for r in former] == ["Bob"]


async def test_meetings_counts(maker: async_sessionmaker[AsyncSession], app_for: FastAPI) -> None:
    w = await _world(maker)
    rows = _client(app_for, w.me).get(f"/api/gremien/{w.gremium_id}/meetings").json()
    by_id = {r["id"]: r for r in rows}
    assert [r["id"] for r in rows][:2] == [str(w.ids["m5"]), str(w.ids["m4"])]
    m1 = by_id[str(w.ids["m1"])]
    assert m1["agendaItemCount"] == 2
    assert m1["presentCount"] == 3  # me, sub, bob
    # me, alice, bob (member then), sub (recorded)
    assert m1["memberCount"] == 4
    assert m1["protocolStatus"] == "final"
    assert by_id[str(w.ids["m3"])]["protocolStatus"] == "draft"
    assert by_id[str(w.ids["m4"])]["protocolStatus"] is None


async def test_attendance_matrix(maker: async_sessionmaker[AsyncSession], app_for: FastAPI) -> None:
    w = await _world(maker)
    resp = _client(app_for, w.me).get(
        f"/api/gremien/{w.gremium_id}/attendance", params={"from": "2026-05", "to": "2026-07"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fromMonth"] == "2026-05" and body["toMonth"] == "2026-07"
    assert body["months"] == [
        {"month": "2026-05", "meetings": 2},
        {"month": "2026-06", "meetings": 1},
        {"month": "2026-07", "meetings": 0},
    ]
    rows = {r["displayName"]: r for r in body["rows"]}
    assert set(rows) == {"Me", "Alice", "Bob", "Sub"}
    may = lambda name: rows[name]["cells"][0]  # noqa: E731
    assert may("Me") == {
        "month": "2026-05",
        "member": True,
        "present": 2,
        "excused": 0,
        "delegated": 0,
    }
    # The excuse of m1 is a vote transfer, so it counts as delegated only.
    assert may("Alice") == {
        "month": "2026-05",
        "member": True,
        "present": 1,
        "excused": 0,
        "delegated": 1,
    }
    # The pool substitute is no member: the present record does not count.
    assert may("Sub") == {
        "month": "2026-05",
        "member": False,
        "present": 0,
        "excused": 0,
        "delegated": 0,
    }
    assert rows["Bob"]["cells"][1]["member"] is False
    assert rows["Me"]["cells"][1]["excused"] == 1
    assert rows["Me"]["isSelf"] is True
    assert "note" not in str(body)


async def test_attendance_range_errors(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    w = await _world(maker)
    client = _client(app_for, w.me)
    url = f"/api/gremien/{w.gremium_id}/attendance"
    too_long = client.get(url, params={"from": "2024-01", "to": "2026-01"})
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "invalid_month_range"
    assert client.get(url, params={"from": "2026-07", "to": "2026-05"}).status_code == 422
    assert client.get(url, params={"from": "2026-13"}).status_code == 422
    assert client.get(url).status_code == 200


async def test_member_attendance_detail(
    maker: async_sessionmaker[AsyncSession], app_for: FastAPI
) -> None:
    w = await _world(maker)
    client = _client(app_for, w.me)
    body = client.get(
        f"/api/gremien/{w.gremium_id}/attendance/{w.ids['alice']}", params={"month": "2026-05"}
    ).json()
    assert body["displayName"] == "Alice"
    states = [(m["title"], m["status"], m["delegateName"]) for m in body["meetings"]]
    assert states == [("Sitzung m1", "delegated", "Sub"), ("Sitzung m2", "present", None)]
    assert "krank" not in str(body)
    june = client.get(
        f"/api/gremien/{w.gremium_id}/attendance/{w.ids['alice']}", params={"month": "2026-06"}
    ).json()
    assert [m["status"] for m in june["meetings"]] == ["absent"]
    outsider = client.get(
        f"/api/gremien/{w.gremium_id}/attendance/{w.ids['outsider']}", params={"month": "2026-05"}
    )
    assert outsider.status_code == 404
    assert outsider.json()["code"] == "member_not_found"


async def test_decisions(maker: async_sessionmaker[AsyncSession], app_for: FastAPI) -> None:
    w = await _world(maker)
    client = _client(app_for, w.me)
    url = f"/api/gremien/{w.gremium_id}/decisions"
    page = client.get(url).json()
    assert page["nextCursor"] is None
    items = page["items"]
    assert [i["question"] for i in items] == [
        "Wahl der Sitzungsleitung",
        "Geschäftsordnung § 7",
        "Lastenrad",
    ]
    election, secret, motion = items
    assert election["kind"] == "election" and election["elected"] == ["Jonas Albrecht"]
    assert election["ballots"] == 3 and election["counts"] is None
    assert secret["secret"] is True and secret["counts"] == {"yes": 1, "no": 1, "abstain": 0}
    assert secret["majorityRule"] == "two_thirds"
    assert motion["counts"] == {"yes": 2, "no": 1, "abstain": 1} and motion["ballots"] == 4
    assert motion["kind"] == "motion" and motion["meetingTitle"] == "Sitzung m1"
    assert [
        i["question"] for i in client.get(url, params={"kind": "election"}).json()["items"]
    ] == ["Wahl der Sitzungsleitung"]
    assert [
        i["question"] for i in client.get(url, params={"result": "rejected"}).json()["items"]
    ] == ["Geschäftsordnung § 7"]
    assert [i["question"] for i in client.get(url, params={"q": "lasten"}).json()["items"]] == [
        "Lastenrad"
    ]
    assert client.get(url, params={"kind": "application"}).json()["items"] == []
    assert client.get(url, params={"since": "2026-06-01"}).json()["items"] == []
    assert client.get(url, params={"cursor": "%%%"}).status_code == 400
