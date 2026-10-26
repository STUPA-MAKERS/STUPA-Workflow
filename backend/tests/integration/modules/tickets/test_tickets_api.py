"""Integration: the ticket routes end to end (real Postgres).

Covers the report (session, anonymous, public switch, e-mail, draft attachments),
the list with every filter, the counts, the assignees, the detail with notes, events
and links, the changes of status, assignee and kind, the notes, and the RBAC of every
route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.admin.schemas import HelpTicketsSettings
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.auth.principal import Principal
from app.modules.files.drafts import hash_draft_token
from app.modules.files.models import Attachment
from app.modules.livevote.models import Meeting
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from app.settings import Settings
from tests._support.guest_apps import create_guest_application, seed_guest_flow
from tests.integration.modules.tickets.conftest import (
    ADMIN,
    MANAGER,
    PLAIN,
    Api,
    add_group_role,
    add_principal,
)

pytestmark = pytest.mark.integration

_REPORT = {"kind": "bug", "title": "Knopf geht nicht", "body": "Beim Klick passiert nichts."}


def _report(client: TestClient, **over: object) -> dict[str, str]:
    resp = client.post("/api/tickets", json={**_REPORT, **over})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _ticket(maker: async_sessionmaker[AsyncSession], number: str) -> Ticket:
    async with maker() as session:
        row = await session.scalar(select(Ticket).where(Ticket.number == int(number[2:])))
        assert row is not None
        return row


async def _set_public(maker: async_sessionmaker[AsyncSession], enabled: bool) -> None:
    async with maker() as session:
        await SiteConfigService(session).put_help_tickets(
            HelpTicketsSettings(publicEnabled=enabled), "test"
        )


async def test_an_anonymous_report_answers_the_number_only(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    with TestClient(api.app) as client:
        body = _report(
            client,
            email="Gast@Example.org",
            context={"route": "/x", "language": "en", "viewport": "1440x900"},
        )
    assert set(body) == {"number"}
    assert body["number"].startswith("T-")
    ticket = await _ticket(maker, body["number"])
    assert ticket.reporter_principal_id is None
    assert ticket.reporter_email == "Gast@example.org"
    assert ticket.context == {"route": "/x", "language": "en", "viewport": "1440x900"}
    assert ticket.status == "new"
    assert api.mails.calls == [ticket.id]
    async with maker() as session:
        events = (
            await session.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id))
        ).all()
    assert [(e.kind, e.payload) for e in events] == [("created", {"confirmationSent": True})]


async def test_an_anonymous_report_needs_an_email(api: Api) -> None:
    with TestClient(api.app) as client:
        resp = client.post("/api/tickets", json=_REPORT)
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "email"


async def test_an_anonymous_report_is_refused_while_public_reports_are_off(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Refuse an anonymous report while public reports are off.

    A session still reports.
    """
    await _set_public(maker, False)
    with TestClient(api.app) as client:
        resp = client.post("/api/tickets", json={**_REPORT, "email": "a@example.org"})
        assert resp.status_code == 403
        assert resp.json()["code"] == "tickets_public_disabled"
        await add_principal(maker, sub=PLAIN.sub, email=PLAIN.email)
        api.login(PLAIN)
        assert client.post("/api/tickets", json=_REPORT).status_code == 201


async def test_a_session_report_names_the_account_and_ignores_the_email(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    pid = await add_principal(maker, sub=PLAIN.sub, email=PLAIN.email, name="Pia")
    api.login(PLAIN)
    with TestClient(api.app) as client:
        body = _report(client, email="other@example.org", kind="idea")
    ticket = await _ticket(maker, body["number"])
    assert ticket.reporter_principal_id == pid
    assert ticket.reporter_email is None
    assert ticket.kind == "idea"


async def test_a_session_without_an_account_row_needs_an_email(api: Api) -> None:
    api.login(Principal(sub="ghost"))
    with TestClient(api.app) as client:
        assert client.post("/api/tickets", json=_REPORT).status_code == 422
        assert (
            client.post("/api/tickets", json={**_REPORT, "email": "g@example.org"}).status_code
            == 201
        )


async def test_a_report_rejects_unknown_fields_and_long_titles(api: Api) -> None:
    with TestClient(api.app) as client:
        assert (
            client.post(
                "/api/tickets", json={**_REPORT, "email": "a@example.org", "x": 1}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/tickets", json={**_REPORT, "email": "a@example.org", "title": "t" * 201}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/tickets",
                json={**_REPORT, "email": "a@example.org", "context": {"language": "fr_FR"}},
            ).status_code
            == 422
        )


async def _draft(
    maker: async_sessionmaker[AsyncSession], settings: Settings, token: str
) -> uuid.UUID:
    draft_id = uuid.uuid4()
    async with maker() as session:
        session.add(
            Attachment(
                id=draft_id,
                filename="shot.png",
                mime="image/png",
                size=4,
                storage_key=f"drafts/{draft_id}/shot.png",
                scanned=True,
                scan_result="clean",
                draft_token_hash=hash_draft_token(token, settings.magic_link_secret),
                draft_expires_at=datetime.now(UTC) + timedelta(days=7),
            )
        )
        await session.commit()
    return draft_id


async def test_a_report_binds_its_draft_attachments(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    draft_id = await _draft(maker, settings, "tok-1")
    with TestClient(api.app) as client:
        body = _report(
            client, email="a@example.org", attachmentIds=[str(draft_id)], draftToken="tok-1"
        )
    ticket = await _ticket(maker, body["number"])
    async with maker() as session:
        row = await session.get(Attachment, draft_id)
        assert row is not None
        assert row.ticket_id == ticket.id
        assert row.application_id is None
        assert row.draft_token_hash is None
        assert row.draft_expires_at is None


async def test_a_report_with_attachments_needs_the_token_and_own_drafts(
    api: Api, maker: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    draft_id = await _draft(maker, settings, "tok-2")
    with TestClient(api.app) as client:
        no_token = client.post(
            "/api/tickets",
            json={**_REPORT, "email": "a@example.org", "attachmentIds": [str(draft_id)]},
        )
        assert no_token.status_code == 422
        assert no_token.json()["errors"][0]["field"] == "draftToken"
        foreign = client.post(
            "/api/tickets",
            json={
                **_REPORT,
                "email": "a@example.org",
                "attachmentIds": [str(draft_id)],
                "draftToken": "other",
            },
        )
        assert foreign.status_code == 422
        assert foreign.json()["code"] == "draft_attachments_missing"
        too_many = client.post(
            "/api/tickets",
            json={
                **_REPORT,
                "email": "a@example.org",
                "attachmentIds": [str(uuid.uuid4()) for _ in range(6)],
                "draftToken": "tok-2",
            },
        )
        assert too_many.status_code == 422
    async with maker() as session:
        assert (await session.scalars(select(Ticket))).all() == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/tickets"),
        ("get", "/api/tickets/counts"),
        ("get", "/api/tickets/assignees"),
        ("get", f"/api/tickets/{uuid.uuid4()}"),
        ("patch", f"/api/tickets/{uuid.uuid4()}"),
        ("post", f"/api/tickets/{uuid.uuid4()}/notes"),
        ("patch", f"/api/tickets/{uuid.uuid4()}/notes/{uuid.uuid4()}"),
        ("delete", f"/api/tickets/{uuid.uuid4()}/notes/{uuid.uuid4()}"),
    ],
)
async def test_every_work_route_needs_ticket_manage(api: Api, method: str, path: str) -> None:
    with TestClient(api.app) as client:
        call = getattr(client, method)
        kwargs = {"json": {"body": "x"}} if method in ("post", "patch") else {}
        assert call(path, **kwargs).status_code == 401
        api.login(PLAIN)
        resp = call(path, **kwargs)
        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")


async def test_a_token_without_the_tickets_scope_gets_403(api: Api) -> None:
    api.login(Principal(sub="agent", roles=["admin"], scope_permissions=frozenset({"mcp.use"})))
    with TestClient(api.app) as client:
        assert client.get("/api/tickets").status_code == 403


async def test_the_list_filters_and_pages(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    me = await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, role="admin")
    reporter = await add_principal(maker, email="reporter@example.org", name="Rita Reporter")
    async with maker() as session:
        tickets = [
            Ticket(kind="bug", title="Login kaputt", body="a", reporter_email="x@example.org"),
            Ticket(
                kind="question",
                title="Frage zum Budget",
                body="b",
                reporter_principal_id=reporter,
                status="in_progress",
                assignee_id=me,
            ),
            Ticket(
                kind="idea",
                title="Dunkles Design",
                body="100%_sicher",
                status="done",
                reporter_email="y@example.org",
            ),
        ]
        for i, t in enumerate(tickets):
            t.created_at = datetime(2026, 10, 1 + i, tzinfo=UTC)
            session.add(t)
        await session.commit()
        numbers = [t.number for t in tickets]
    api.login(MANAGER)
    with TestClient(api.app) as client:

        def titles(**params: object) -> list[str]:
            resp = client.get("/api/tickets", params=params)
            assert resp.status_code == 200, resp.text
            return [i["title"] for i in resp.json()["items"]]

        assert titles() == ["Dunkles Design", "Frage zum Budget", "Login kaputt"]
        assert titles(status=["new", "done"]) == ["Dunkles Design", "Login kaputt"]
        assert titles(kind="question") == ["Frage zum Budget"]
        assert titles(assignee="me") == ["Frage zum Budget"]
        assert titles(assignee=str(me)) == ["Frage zum Budget"]
        assert titles(assignee="none") == ["Dunkles Design", "Login kaputt"]
        assert titles(q="login") == ["Login kaputt"]
        assert titles(q=f"T-{numbers[0]:04d}") == ["Login kaputt"]
        assert titles(q=str(numbers[1])) == ["Frage zum Budget"]
        assert titles(q="rita") == ["Frage zum Budget"]
        assert titles(q="reporter@example") == ["Frage zum Budget"]
        assert titles(q="y@example.org") == ["Dunkles Design"]
        assert titles(q="%_") == ["Dunkles Design"]
        assert titles(q="   ") == ["Dunkles Design", "Frage zum Budget", "Login kaputt"]
        page = client.get("/api/tickets", params={"limit": 1, "offset": 1}).json()
        assert page["total"] == 3
        assert [i["title"] for i in page["items"]] == ["Frage zum Budget"]
        item = page["items"][0]
        assert item["reporter"] == {
            "principalId": str(reporter),
            "displayName": "Rita Reporter",
            "email": "reporter@example.org",
            "anonymized": False,
        }
        assert item["assignee"] == {"principalId": str(me), "displayName": MANAGER.email}
        bad = client.get("/api/tickets", params={"assignee": "someone"})
        assert bad.status_code == 422
        assert client.get("/api/tickets", params={"status": "open"}).status_code == 422
        counts = client.get("/api/tickets/counts").json()
        assert counts == {"new": 1, "inProgress": 1, "done": 1, "rejected": 0}


async def test_the_assignees_are_the_active_holders_by_name(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_group_role(maker, "tickets-support", "ticket.manage")
    await add_group_role(maker, "tickets-other", "budget.view")
    admin = await add_principal(maker, sub=MANAGER.sub, name="Zora", role="admin")
    grouped = await add_principal(maker, name="anna", groups=["tickets-support"])
    await add_principal(maker, name="Inactive", role="admin", active=False)
    await add_principal(maker, name="Member", role="member", groups=["tickets-other"])
    nameless = await add_principal(maker, email="", name=None, role="admin")
    api.login(MANAGER)
    with TestClient(api.app) as client:
        body = client.get("/api/tickets/assignees").json()
    assert body == [
        {"principalId": str(grouped), "displayName": "anna"},
        {"principalId": str(admin), "displayName": "Zora"},
    ]
    assert str(nameless) not in {p["principalId"] for p in body}


async def test_the_detail_holds_notes_events_attachments_and_links(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Return the notes, events, attachments and links in the detail.

    One transaction gives every server default the same now(), so explicit times keep the
    order of the two notes independent of their random ids.
    """
    me = await add_principal(maker, sub=ADMIN.sub, email=ADMIN.email, name="Ada", role="admin")
    other = await add_principal(maker, name="Otto", role="admin")
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    async with maker() as session:
        await session.execute(
            Attachment.__table__.update()  # pyright: ignore[reportAttributeAccessIssue]
            .where(Attachment.application_id == app_id)
            .values(scanned=True)
        )
        from app.modules.applications.models import Application

        app = await session.get(Application, app_id)
        assert app is not None
        app.email_confirmed_at = datetime.now(UTC)
        ticket = Ticket(
            kind="bug",
            title="Fehler",
            body="**fett**",
            reporter_email="x@example.org",
            context={"route": f"/applications/{app_id}/edit", "url": "https://h/x"},
        )
        session.add(ticket)
        await session.flush()
        noted = datetime.now(UTC)
        session.add_all(
            [
                TicketNote(ticket_id=ticket.id, author_id=me, body="mine", created_at=noted),
                TicketNote(
                    ticket_id=ticket.id,
                    author_id=other,
                    body="theirs",
                    created_at=noted + timedelta(seconds=1),
                ),
                TicketNote(
                    ticket_id=ticket.id,
                    author_id=me,
                    body="gone",
                    deleted_at=datetime.now(UTC),
                ),
                Attachment(
                    ticket_id=ticket.id,
                    filename="a.png",
                    mime="image/png",
                    size=3,
                    storage_key="k",
                ),
            ]
        )
        await session.commit()
        ticket_id = ticket.id
    api.login(ADMIN)
    with TestClient(api.app) as client:
        resp = client.patch(f"/api/tickets/{ticket_id}", json={"assigneeId": str(other)})
        assert resp.status_code == 200, resp.text
        detail = client.get(f"/api/tickets/{ticket_id}").json()
    assert detail["body"] == "**fett**"
    assert detail["context"]["url"] == "https://h/x"
    assert [n["body"] for n in detail["notes"]] == ["mine", "theirs"]
    assert [n["isOwn"] for n in detail["notes"]] == [True, False]
    assert detail["notes"][0]["author"] == {"principalId": str(me), "displayName": "Ada"}
    assert [a["filename"] for a in detail["attachments"]] == ["a.png"]
    assert set(detail["attachments"][0]) == {"id", "filename", "mime", "size", "scanned"}
    assert detail["contextTarget"] == {
        "kind": "application",
        "id": str(app_id),
        "title": "Gastantrag",
    }
    assert detail["openTodoCount"] == 0
    assert detail["duplicateOf"] is None
    (event,) = detail["events"]
    assert event["kind"] == "assignee"
    assert event["actor"] == {"principalId": str(me), "displayName": "Ada"}
    assert event["payload"] == {
        "from": None,
        "to": {"principalId": str(other), "displayName": "Otto"},
    }
    assert detail["assignee"] == {"principalId": str(other), "displayName": "Otto"}


async def test_the_context_target_needs_read_access(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email)
    seed = await seed_guest_flow(maker)
    app_id = await create_guest_application(maker, seed)
    async with maker() as session:
        meeting = Meeting(gremium_id=seed.gremium_id, title="StuPa-Sitzung")
        session.add(meeting)
        await session.flush()
        routes = {
            "unconfirmed": f"/applications/{app_id}",
            "missing_app": f"/applications/{uuid.uuid4()}",
            "meeting": f"/meetings/{meeting.id}",
            "missing_meeting": f"/meetings/{uuid.uuid4()}",
            "other": "/budget",
            "none": None,
        }
        ids: dict[str, uuid.UUID] = {}
        for key, route in routes.items():
            t = Ticket(
                kind="bug",
                title=key,
                body="b",
                reporter_email="x@example.org",
                context={"route": route} if route is not None else {},
            )
            session.add(t)
            await session.flush()
            ids[key] = t.id
        await session.commit()
        meeting_id = meeting.id
    with TestClient(api.app) as client:
        api.login(MANAGER)
        for key in ids:
            assert client.get(f"/api/tickets/{ids[key]}").json()["contextTarget"] is None, key
        api.login(ADMIN)
        assert client.get(f"/api/tickets/{ids['meeting']}").json()["contextTarget"] == {
            "kind": "meeting",
            "id": str(meeting_id),
            "title": "StuPa-Sitzung",
        }
        assert client.get(f"/api/tickets/{ids['unconfirmed']}").json()["contextTarget"] is None
        assert client.get(f"/api/tickets/{uuid.uuid4()}").status_code == 404


async def test_status_changes_set_the_retention_clock_and_write_events(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, role="admin")
    async with maker() as session:
        first = Ticket(kind="bug", title="first", body="b", reporter_email="x@example.org")
        second = Ticket(kind="bug", title="second", body="b", reporter_email="x@example.org")
        session.add_all([first, second])
        await session.commit()
        first_id, second_id, first_number = first.id, second.id, first.number
    api.login(MANAGER)
    with TestClient(api.app) as client:
        url = f"/api/tickets/{second_id}"
        done = client.patch(url, json={"status": "done"}).json()
        assert done["status"] == "done"
        closed_at = done["closedAt"]
        assert closed_at is not None
        rejected = client.patch(
            url, json={"status": "rejected", "duplicateOfId": str(first_id)}
        ).json()
        assert rejected["closedAt"] == closed_at
        assert rejected["duplicateOf"] == {"id": str(first_id), "number": f"T-{first_number:04d}"}
        again = client.patch(url, json={"status": "rejected", "duplicateOfId": str(first_id)})
        assert again.status_code == 200
        reopened = client.patch(url, json={"status": "in_progress", "kind": "idea"}).json()
        assert reopened["closedAt"] is None
        assert reopened["duplicateOf"] is None
        assert reopened["kind"] == "idea"
        unchanged = client.patch(url, json={"status": "in_progress", "kind": "idea"}).json()
        payloads = [(e["kind"], e["payload"]) for e in unchanged["events"]]
    dup = f"T-{first_number:04d}"
    assert payloads == [
        ("status", {"from": "new", "to": "done"}),
        ("status", {"from": "done", "to": "rejected", "duplicateOf": dup}),
        ("status", {"from": "rejected", "to": "rejected", "duplicateOf": dup}),
        ("status", {"from": "rejected", "to": "in_progress"}),
        ("kind", {"from": "bug", "to": "idea"}),
    ]


async def test_invalid_changes_give_422(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, role="admin")
    outsider = await add_principal(maker, name="Out")
    async with maker() as session:
        ticket = Ticket(kind="bug", title="t", body="b", reporter_email="x@example.org")
        session.add(ticket)
        await session.commit()
        ticket_id = ticket.id
    api.login(MANAGER)
    url = f"/api/tickets/{ticket_id}"
    with TestClient(api.app) as client:
        for body, code in (
            ({"status": "done", "duplicateOfId": str(uuid.uuid4())}, "duplicate_invalid"),
            ({"status": "rejected", "duplicateOfId": str(ticket_id)}, "duplicate_invalid"),
            ({"status": "rejected", "duplicateOfId": str(uuid.uuid4())}, "duplicate_invalid"),
            ({"assigneeId": str(outsider)}, "assignee_not_allowed"),
            ({"assigneeId": str(uuid.uuid4())}, "assignee_not_allowed"),
            ({"status": "in_progress", "completeTodos": True}, None),
            ({"completeTodos": True}, None),
            ({"status": "closed"}, None),
        ):
            resp = client.patch(url, json=body)
            assert resp.status_code == 422, body
            if code is not None:
                assert resp.json()["code"] == code
        assert client.patch(f"/api/tickets/{uuid.uuid4()}", json={}).status_code == 404
        ok = client.patch(url, json={"status": "done", "completeTodos": True})
        assert ok.status_code == 200
        unassigned = client.patch(url, json={"assigneeId": None})
        assert unassigned.json()["events"][-1]["kind"] == "status"


async def test_assign_and_unassign(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    me = await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, role="admin")
    async with maker() as session:
        ticket = Ticket(kind="bug", title="t", body="b", reporter_email="x@example.org")
        session.add(ticket)
        await session.commit()
        ticket_id = ticket.id
    api.login(MANAGER)
    url = f"/api/tickets/{ticket_id}"
    with TestClient(api.app) as client:
        assert client.patch(url, json={"assigneeId": str(me)}).json()["assignee"][
            "principalId"
        ] == str(me)
        detail = client.patch(url, json={"assigneeId": None}).json()
    assert detail["assignee"] is None
    assert detail["events"][-1]["payload"] == {
        "from": {"principalId": str(me), "displayName": MANAGER.email},
        "to": None,
    }


async def test_notes_belong_to_their_author(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    await add_principal(maker, sub=ADMIN.sub, email=ADMIN.email)
    async with maker() as session:
        ticket = Ticket(kind="bug", title="t", body="b", reporter_email="x@example.org")
        other = Ticket(kind="bug", title="o", body="b", reporter_email="x@example.org")
        session.add_all([ticket, other])
        await session.commit()
        ticket_id, other_id = ticket.id, other.id
    base = f"/api/tickets/{ticket_id}/notes"
    with TestClient(api.app) as client:
        api.login(MANAGER)
        created = client.post(base, json={"body": "Erste Notiz"})
        assert created.status_code == 201, created.text
        note = created.json()
        assert note["isOwn"] is True
        assert note["author"]["displayName"] == "Mia"
        assert note["editedAt"] is None
        edited = client.patch(f"{base}/{note['id']}", json={"body": "Geändert"}).json()
        assert edited["body"] == "Geändert"
        assert edited["editedAt"] is not None
        assert client.post(base, json={"body": ""}).status_code == 422
        assert (
            client.post(f"/api/tickets/{uuid.uuid4()}/notes", json={"body": "x"}).status_code == 404
        )
        assert (
            client.patch(
                f"/api/tickets/{other_id}/notes/{note['id']}", json={"body": "x"}
            ).status_code
            == 404
        )
        api.login(ADMIN)
        foreign = client.patch(f"{base}/{note['id']}", json={"body": "x"})
        assert foreign.status_code == 403
        assert foreign.json()["code"] == "not_note_author"
        assert client.delete(f"{base}/{note['id']}").status_code == 403
        api.login(MANAGER)
        assert client.delete(f"{base}/{note['id']}").status_code == 204
        assert client.delete(f"{base}/{note['id']}").status_code == 404
        api.login(Principal(sub="no-row", roles=["admin"]))
        assert client.post(base, json={"body": "x"}).status_code == 404
        assert client.get(f"/api/tickets/{ticket_id}").json()["notes"] == []
