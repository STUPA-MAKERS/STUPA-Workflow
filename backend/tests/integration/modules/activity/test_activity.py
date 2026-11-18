"""Integration: the activity page (specs 001270-001277) on a real Postgres.

Each test writes the rows of one history directly, with fixed times, so the order of the
page is known. The read rules are the real ones of the modules.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.activity.service import ActivityService, Cursor
from app.modules.applications.models import Comment, StatusEvent, SubmissionVersion
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from app.modules.todos.models import TodoAssignee, TodoCard, TodoColumn, TodoComment, TodoEvent
from app.shared.errors import ValidationProblem
from tests.integration.modules.flow.agenda_support import make_application, seed_agenda_flow
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def _card(
    maker: async_sessionmaker[AsyncSession], board_id: uuid.UUID, creator: uuid.UUID
) -> uuid.UUID:
    async with maker() as session:
        column = TodoColumn(board_id=board_id, name="Offen", position=99)
        session.add(column)
        await session.flush()
        card = TodoCard(
            board_id=board_id, column_id=column.id, rank="a", title="Karte", created_by=creator
        )
        session.add(card)
        await session.commit()
        return card.id


async def test_a_card_shows_what_others_did(maker: async_sessionmaker[AsyncSession]) -> None:
    """Spec 001271/001273: an assignee sees the events of others, own ones on request."""
    alice, alice_id = await add_person(maker, "Alice")
    _, bob_id = await add_person(maker, "Bob")
    gremium_id, board_id = await add_gremium(maker)
    await add_member(maker, gremium_id, alice_id, "todo.write")
    card_id = await _card(maker, board_id, bob_id)
    async with maker() as session:
        session.add(TodoAssignee(card_id=card_id, principal_id=alice_id))
        session.add_all(
            [
                TodoEvent(
                    card_id=card_id,
                    actor_id=bob_id,
                    kind="assigned",
                    payload={"principalId": str(alice_id), "added": True},
                    created_at=_at(1),
                ),
                TodoEvent(
                    card_id=card_id,
                    actor_id=bob_id,
                    kind="moved",
                    payload={"toColumnName": "Erledigt"},
                    created_at=_at(2),
                ),
                TodoEvent(
                    card_id=card_id,
                    actor_id=alice_id,
                    kind="renamed",
                    payload={"to": "Neu"},
                    created_at=_at(3),
                ),
                TodoComment(
                    card_id=card_id,
                    author_id=bob_id,
                    body="\nHallo\nzweite Zeile",
                    created_at=_at(4),
                ),
            ]
        )
        await session.commit()

    async with maker() as session:
        page = await ActivityService(session).page(alice)
        assert [e.change for e in page.entries] == ["comment", "todo.moved", "todo.assigned"]
        assert page.entries[0].detail == "Hallo"
        assert page.entries[0].actor.name == "Bob"
        assert page.entries[1].detail == "Erledigt"
        assert page.entries[0].url.endswith(str(card_id))
        assert page.next_cursor is None

        own = await ActivityService(session).page(alice, own=True)
        assert [e.change for e in own.entries][1] == "todo.renamed"
        assert own.entries[1].own is True

        only_tickets = await ActivityService(session).page(alice, kinds=["ticket"])
        assert only_tickets.entries == []


async def test_a_card_on_an_unreadable_board_leaves_the_page(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec 001272: without the read right the events go, even for the creator."""
    alice, alice_id = await add_person(maker, "Alice")
    _, board_id = await add_gremium(maker)
    card_id = await _card(maker, board_id, alice_id)
    async with maker() as session:
        session.add(TodoEvent(card_id=card_id, actor_id=None, kind="due", created_at=_at(1)))
        await session.commit()
    async with maker() as session:
        assert (await ActivityService(session).page(alice)).entries == []


async def test_a_reporter_reads_status_and_public_notes_only(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec 001272: the reporter sees what the own ticket view shows."""
    alice, alice_id = await add_person(maker, "Alice")
    team, team_id = await add_person(maker, "Team")
    team = Principal(sub=team.sub, email=team.email, permissions={"ticket.manage"})
    async with maker() as session:
        ticket = Ticket(kind="bug", title="Fehler", body="x", reporter_principal_id=alice_id)
        session.add(ticket)
        await session.flush()
        session.add_all(
            [
                TicketEvent(
                    ticket_id=ticket.id, actor_id=team_id, kind="assignee", created_at=_at(1)
                ),
                TicketEvent(
                    ticket_id=ticket.id,
                    actor_id=team_id,
                    kind="status",
                    payload={"from": "new", "to": "in_progress"},
                    created_at=_at(2),
                ),
                TicketNote(
                    ticket_id=ticket.id,
                    author_id=team_id,
                    body="intern",
                    visibility="internal",
                    created_at=_at(3),
                    mentions=[],
                ),
                TicketNote(
                    ticket_id=ticket.id,
                    author_id=team_id,
                    body="Antwort",
                    visibility="public",
                    created_at=_at(4),
                    mentions=[],
                ),
                TicketNote(
                    ticket_id=ticket.id,
                    author_id=alice_id,
                    body="Danke",
                    visibility="public",
                    created_at=_at(5),
                    mentions=[],
                ),
            ]
        )
        await session.commit()
        ticket_id = ticket.id

    async with maker() as session:
        page = await ActivityService(session).page(alice)
        assert [(e.change, e.detail, e.status) for e in page.entries] == [
            ("comment", "Antwort", None),
            ("ticket.status", None, "in_progress"),
        ]
        assert page.entries[0].item_title is not None
        assert page.entries[0].item_title.startswith("T-")

        # The team member wrote a note, so the ticket is theirs too, with every row.
        team_page = await ActivityService(session).page(team)
        assert [e.change for e in team_page.entries] == ["comment"]
        assert team_page.entries[0].actor.name == "Alice"
        assert str(ticket_id) == team_page.entries[0].item_id


async def test_the_applicant_view_hides_internal_rows_and_names(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec 001272/001277: the creator without member rights reads as the applicant."""
    alice, _ = await add_person(maker, "Alice")
    _, _ = await add_person(maker, "Bob", sub="bob-sub")
    async with maker() as session:
        flow = await seed_agenda_flow(session)
        app = await make_application(session, flow)
        app.created_by = alice.sub
        state_id = flow.states["review"].id
        session.add_all(
            [
                StatusEvent(
                    application_id=app.id, to_state_id=state_id, actor="bob-sub", at=_at(1)
                ),
                Comment(
                    application_id=app.id,
                    author="bob-sub",
                    author_kind="principal",
                    body="geheim",
                    visibility="internal",
                    at=_at(2),
                    mentions=[],
                ),
                Comment(
                    application_id=app.id,
                    author="bob-sub",
                    author_kind="principal",
                    body="öffentlich",
                    visibility="public",
                    at=_at(3),
                    mentions=[],
                ),
                SubmissionVersion(
                    application_id=app.id, version=2, changed_by="system:x", at=_at(4), data={}
                ),
            ]
        )
        await session.commit()
        app_id = app.id

    async with maker() as session:
        page = await ActivityService(session).page(alice, lang="de")
        rows = [(e.change, e.actor.kind) for e in page.entries]
        assert rows == [
            ("application.status", "applicant"),
            ("application.edited", "system"),
            ("comment", "committee"),
            ("application.status", "committee"),
        ]
        assert page.entries[3].detail == "Prüfung"
        assert page.entries[0].url == f"/my-applications/{app_id}"
        assert page.entries[0].item_title == "Antrag"


async def test_a_meeting_shows_its_audit_entries(maker: async_sessionmaker[AsyncSession]) -> None:
    """Spec 001270/001271: the meetings of my Gremien show up, not those of another."""
    alice, alice_id = await add_person(maker, "Alice")
    async with maker() as session:
        gremium = Gremium(name="StuPa", slug=f"todo-{uuid.uuid4().hex[:8]}")
        foreign = Gremium(name="AStA", slug=f"todo-{uuid.uuid4().hex[:8]}")
        session.add_all([gremium, foreign])
        await session.flush()
        meeting = Meeting(gremium_id=gremium.id, title="Sitzung 1")
        other = Meeting(gremium_id=foreign.id, title="Sitzung 2")
        mine = Meeting(gremium_id=gremium.id, title="Sitzung 3")
        session.add_all([meeting, other, mine])
        await session.flush()
        session.add(
            MeetingAttendance(
                meeting_id=meeting.id, principal_id=alice_id, status="present", source="lead"
            )
        )
        await audit_record(
            session,
            actor="lead",
            action=AuditAction.MEETING_UPDATE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={"changes": {"status": {"from": "planned", "to": "live"}}},
        )
        await audit_record(
            session,
            actor="lead",
            action=AuditAction.MEETING_UPDATE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={"changes": {"date": {"from": None, "to": "2026-11-02"}}},
        )
        await audit_record(
            session,
            actor="lead",
            action=AuditAction.PROTOCOL_FINALIZE,
            target_type="protocol",
            target_id=str(uuid.uuid4()),
            data={"meetingId": str(meeting.id)},
        )
        await audit_record(
            session,
            actor="lead",
            action=AuditAction.MEETING_UPDATE,
            target_type="meeting",
            target_id=str(other.id),
            data={"changes": {"status": {"from": "planned", "to": "live"}}},
        )
        await audit_record(
            session,
            actor="lead",
            action=AuditAction.MEETING_UPDATE,
            target_type="meeting",
            target_id=str(mine.id),
            data={"changes": {"status": {"from": "planned", "to": "closed"}}},
        )
        await session.commit()
        gremium_id = gremium.id
    await add_member(maker, gremium_id, alice_id)

    async with maker() as session:
        page = await ActivityService(session).page(alice, kinds=["meeting"])
        assert [(e.item_title, e.change, e.status) for e in page.entries] == [
            ("Sitzung 3", "meeting.status", "closed"),
            ("Sitzung 1", "protocol.finalized", None),
            ("Sitzung 1", "meeting.updated", None),
            ("Sitzung 1", "meeting.status", "live"),
        ]


async def test_the_cursor_pages_and_the_mark_counts(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Spec 001275/001276: steps without gaps, then the mark ends the dot."""
    alice, alice_id = await add_person(maker, "Alice")
    _, bob_id = await add_person(maker, "Bob")
    gremium_id, board_id = await add_gremium(maker)
    await add_member(maker, gremium_id, alice_id, "todo.write")
    card_id = await _card(maker, board_id, alice_id)
    async with maker() as session:
        session.add_all(
            [
                TodoComment(card_id=card_id, author_id=bob_id, body=f"c{i}", created_at=_at(i))
                for i in range(5)
            ]
        )
        await session.commit()

    async with maker() as session:
        svc = ActivityService(session)
        first = await svc.page(alice, limit=2)
        assert [e.detail for e in first.entries] == ["c4", "c3"]
        assert first.next_cursor is not None
        second = await svc.page(alice, limit=2, cursor=first.next_cursor)
        assert [e.detail for e in second.entries] == ["c2", "c1"]
        third = await svc.page(alice, limit=2, cursor=second.next_cursor)
        assert [e.detail for e in third.entries] == ["c0"]
        assert third.next_cursor is None
        assert first.seen_at is None
        assert not any(e.is_new for e in first.entries)

    api.login(alice)
    client = TestClient(api.app)
    assert client.get("/api/activity/status").json() == {"hasNew": True}
    body = client.get("/api/activity", params={"kind": "todo"}).json()
    assert len(body["entries"]) == 5
    resp = client.post("/api/activity/seen", json={"at": _at(2).isoformat()})
    assert resp.status_code == 204, resp.text
    assert client.get("/api/activity/status").json() == {"hasNew": True}
    marked = client.get("/api/activity").json()
    assert [e["isNew"] for e in marked["entries"]] == [True, True, False, False, False]
    # The mark never moves back.
    client.post("/api/activity/seen", json={"at": _at(0).isoformat()})
    client.post("/api/activity/seen", json={"at": _at(9).isoformat()})
    assert client.get("/api/activity/status").json() == {"hasNew": False}
    assert client.get("/api/activity", params={"cursor": "%%%"}).status_code == 422


def test_a_broken_cursor_is_a_validation_problem() -> None:
    with pytest.raises(ValidationProblem):
        Cursor.decode("bm8tc2VwYXJhdG9y")
    with pytest.raises(ValidationProblem):
        Cursor.decode(Cursor(datetime(2026, 1, 1), "k").encode())
    cur = Cursor(_at(0), "comment:x")
    assert Cursor.decode(cur.encode()) == cur


async def test_lost_rights_features_and_rounds(
    maker: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 001272: lost rights hide the item; a feature off hides its kind.

    An assignee without ``ticket.manage`` and the creator of a meeting without membership
    see nothing. A page that ends its rounds hands out the cursor.
    """
    alice, alice_id = await add_person(maker, "Alice")
    async with maker() as session:
        ticket = Ticket(
            kind="bug",
            title="Fehler",
            body="x",
            reporter_email="x@example.org",
            assignee_id=alice_id,
        )
        gremium = Gremium(name="StuPa", slug=f"todo-{uuid.uuid4().hex[:8]}")
        session.add_all([ticket, gremium])
        await session.flush()
        session.add_all(
            [
                TicketEvent(
                    ticket_id=ticket.id,
                    actor_id=None,
                    kind="status",
                    payload={"to": "done"},
                    created_at=_at(i),
                )
                for i in range(3)
            ]
        )
        meeting = Meeting(gremium_id=gremium.id, title="Fremd", created_by=alice.sub)
        session.add(meeting)
        await session.flush()
        await audit_record(
            session,
            actor="lead",
            action=AuditAction.MEETING_UPDATE,
            target_type="meeting",
            target_id=str(meeting.id),
            data={"changes": {"status": {"from": "planned", "to": "live"}}},
        )
        await session.commit()

    async with maker() as session:
        svc = ActivityService(session)
        assert (await svc.page(alice)).entries == []
        assert await svc.has_new(alice) is False

        import app.modules.activity.service as activity_service

        monkeypatch.setattr(activity_service, "MAX_ROUNDS", 1)
        cut = await svc.page(alice, kinds=["ticket"], limit=1)
        assert cut.entries == []
        assert cut.next_cursor is not None

        async def _off(_session: object) -> frozenset[object]:
            return frozenset()

        monkeypatch.setattr(activity_service, "active_features", _off)
        assert await svc._kinds(["todo", "application"]) == ["application"]


async def test_a_token_without_a_row_reads_nothing(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    ghost = Principal(sub="ghost", scope_permissions=frozenset())
    async with maker() as session:
        svc = ActivityService(session)
        page = await svc.page(ghost)
        assert page.entries == []
        assert page.seen_at is None
        await svc.mark_seen(ghost, _at(0))
        assert await svc.has_new(ghost) is False
