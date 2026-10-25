"""Router tests of the ticket module with a fake service (no database).

They cover the report (session, anonymous, public switch, missing e-mail, the mail
background task), the filters of the list and the RBAC of the work routes.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.admin.branding import Branding, TicketSettings
from app.modules.auth.principal import Principal
from app.modules.tickets import router as router_mod
from app.modules.tickets.router import (
    _deliver_note_mail,
    _deliver_ticket_mails,
    get_note_mail_sender,
    get_ticket_mail_sender,
    get_ticket_service,
)
from app.modules.tickets.schemas import (
    ReporterTicketDetail,
    ReporterTicketItem,
    TicketBlockedSender,
    TicketCounts,
    TicketDetail,
    TicketListItem,
    TicketNoteOut,
    TicketReporter,
)
from app.modules.tickets.service import SwallowedReport
from app.settings import load_settings
from app.shared.errors import ValidationProblem
from app.shared.paging import Page
from app.shared.people import PersonRef

NOW = datetime(2026, 10, 1, tzinfo=UTC)
NOTE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
TID = uuid.uuid4()
MANAGER = Principal(sub="mgr", permissions={"ticket.manage"})


def _item() -> TicketListItem:
    return TicketListItem(
        id=TID,
        number="T-0001",
        kind="bug",
        title="t",
        status="new",
        reporter=TicketReporter(email="a@x"),
        created_at=NOW,
        updated_at=NOW,
    )


def _detail() -> TicketDetail:
    return TicketDetail(**_item().model_dump(), body="b")


def _note() -> TicketNoteOut:
    return TicketNoteOut(
        id=uuid.uuid4(),
        author=PersonRef(principal_id=uuid.uuid4(), display_name="Ada"),
        body="n",
        at=NOW,
    )


class _Created:
    id = TID
    number = 42


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.swallow = False
        self.added_mentions: list[uuid.UUID] = []

    async def create(self, payload: Any, **kw: Any) -> _Created | SwallowedReport:
        self.calls.append(("create", kw))
        return SwallowedReport(number=43) if self.swallow else _Created()

    async def block_sender(self, ticket_id: uuid.UUID, _p: Principal) -> TicketDetail:
        self.calls.append(("block", ticket_id))
        return _detail().model_copy(update={"sender_blocked": True})

    async def unblock_sender(self, ticket_id: uuid.UUID, _p: Principal) -> TicketDetail:
        self.calls.append(("unblock", ticket_id))
        return _detail()

    async def blocked_senders(self) -> list[TicketBlockedSender]:
        return [TicketBlockedSender(id=TID, kind="email", email="a@x", blocked_at=NOW, hit_count=2)]

    async def delete_block(self, block_id: uuid.UUID) -> None:
        self.calls.append(("delete_block", block_id))

    async def list(self, **kw: Any) -> Page[TicketListItem]:
        self.calls.append(("list", kw))
        return Page[TicketListItem](items=[_item()], total=1, limit=kw["limit"], offset=0)

    async def counts(self) -> TicketCounts:
        return TicketCounts(new=2)

    async def assignees(self) -> list[PersonRef]:
        return [PersonRef(principal_id=uuid.uuid4(), display_name="Ada")]

    async def detail(self, ticket_id: uuid.UUID, _p: Principal) -> TicketDetail:
        self.calls.append(("detail", ticket_id))
        return _detail()

    async def patch(self, ticket_id: uuid.UUID, payload: Any, _p: Principal) -> TicketDetail:
        self.calls.append(("patch", payload))
        return _detail()

    async def add_note(self, *a: Any, **kw: Any) -> TicketNoteOut:
        self.calls.append(("add_note", (a, kw)))
        return _note().model_copy(update={"visibility": a[1].visibility})

    async def edit_note(self, *a: Any, **kw: Any) -> TicketNoteOut:
        self.calls.append(("edit_note", (a, kw)))
        return _note()

    async def delete_note(self, *_a: Any) -> None:
        self.calls.append(("delete_note", None))

    async def reporter_list(self, me: uuid.UUID, **kw: Any) -> Page[ReporterTicketItem]:
        self.calls.append(("reporter_list", (me, kw)))
        item = ReporterTicketItem(
            id=TID,
            number="T-0001",
            kind="bug",
            title="t",
            status="new",
            created_at=NOW,
            updated_at=NOW,
        )
        return Page[ReporterTicketItem](items=[item], total=1, limit=kw["limit"], offset=0)

    async def reporter_detail(self, ticket_id: uuid.UUID, _p: Principal) -> ReporterTicketDetail:
        self.calls.append(("reporter_detail", ticket_id))
        return ReporterTicketDetail(
            id=TID,
            number="T-0001",
            kind="bug",
            title="t",
            status="new",
            created_at=NOW,
            updated_at=NOW,
            body="b",
        )

    async def reporter_add_note(self, *a: Any, **kw: Any) -> TicketNoteOut:
        self.calls.append(("reporter_add_note", (a, kw)))
        return _note().model_copy(update={"visibility": "public", "id": NOTE_ID})

    async def reporter_edit_note(self, *a: Any) -> TicketNoteOut:
        self.calls.append(("reporter_edit_note", a))
        return _note()

    async def reporter_delete_note(self, *a: Any) -> None:
        self.calls.append(("reporter_delete_note", a))


class _Mails:
    def __init__(self) -> None:
        self.sent: list[uuid.UUID] = []

    async def __call__(self, _settings: object, ticket_id: uuid.UUID, _pool: object) -> None:
        self.sent.append(ticket_id)


class _Env:
    def __init__(self, app: FastAPI, service: _FakeService, mails: _Mails) -> None:
        self.app = app
        self.service = service
        self.mails = mails
        self.note_mails = _Mails()
        self.public = True
        self.account: uuid.UUID | None = uuid.uuid4()

    def login(self, principal: Principal | None) -> None:
        self.app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    app = create_app()
    service, mails = _FakeService(), _Mails()
    state = _Env(app, service, mails)

    def _session() -> Iterator[object]:
        yield object()

    async def _branding(_db: object) -> Branding:
        return Branding(tickets=TicketSettings(publicEnabled=state.public))

    async def _pid(_db: object, _sub: str) -> uuid.UUID | None:
        return state.account

    monkeypatch.setattr(router_mod, "active_branding", _branding)
    monkeypatch.setattr(router_mod, "principal_id_of", _pid)
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_ticket_service] = lambda: service
    app.dependency_overrides[get_ticket_mail_sender] = lambda: mails
    app.dependency_overrides[get_note_mail_sender] = lambda: state.note_mails
    state.login(None)
    return state


_REPORT = {"kind": "bug", "title": "t", "body": "b"}


def test_an_anonymous_report_answers_the_number_and_mails(env: _Env) -> None:
    resp = TestClient(env.app).post("/api/tickets", json={**_REPORT, "email": "a@example.org"})
    assert resp.status_code == 201
    assert resp.json() == {"number": "T-0042"}
    kind, kw = env.service.calls[0]
    assert kind == "create"
    assert kw["reporter_id"] is None
    assert kw["email"] == "a@example.org"
    assert env.mails.sent == [TID]


def test_a_swallowed_report_answers_a_number_and_sends_no_mail(env: _Env) -> None:
    env.service.swallow = True
    resp = TestClient(env.app).post("/api/tickets", json={**_REPORT, "email": "a@example.org"})
    assert resp.status_code == 201
    assert resp.json() == {"number": "T-0043"}
    assert env.mails.sent == []


def test_an_anonymous_report_without_an_email_is_422(env: _Env) -> None:
    resp = TestClient(env.app).post("/api/tickets", json=_REPORT)
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "email"


def test_an_anonymous_report_while_public_reports_are_off_is_403(env: _Env) -> None:
    env.public = False
    resp = TestClient(env.app).post("/api/tickets", json={**_REPORT, "email": "a@example.org"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "tickets_public_disabled"


def test_a_session_report_passes_while_public_reports_are_off(env: _Env) -> None:
    env.public = False
    env.login(Principal(sub="u"))
    resp = TestClient(env.app).post("/api/tickets", json={**_REPORT, "email": "x@example.org"})
    assert resp.status_code == 201
    assert env.service.calls[0][1]["reporter_id"] == env.account


def test_a_session_without_an_account_row_falls_back_to_the_email(env: _Env) -> None:
    env.account = None
    env.login(Principal(sub="u"))
    client = TestClient(env.app)
    assert client.post("/api/tickets", json=_REPORT).status_code == 422
    assert (
        client.post("/api/tickets", json={**_REPORT, "email": "x@example.org"}).status_code == 201
    )


def test_a_body_over_the_cap_is_413(env: _Env) -> None:
    big = {**_REPORT, "email": "a@example.org", "body": "x" * 70000}
    assert TestClient(env.app).post("/api/tickets", json=big).status_code == 413


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/tickets"),
        ("get", "/api/tickets/counts"),
        ("get", "/api/tickets/assignees"),
        ("get", f"/api/tickets/{TID}"),
        ("patch", f"/api/tickets/{TID}"),
        ("post", f"/api/tickets/{TID}/notes"),
        ("patch", f"/api/tickets/{TID}/notes/{TID}"),
        ("delete", f"/api/tickets/{TID}/notes/{TID}"),
        ("post", f"/api/tickets/{TID}/block-sender"),
        ("delete", f"/api/tickets/{TID}/block-sender"),
        ("get", "/api/tickets/blocked-senders"),
        ("delete", f"/api/tickets/blocked-senders/{TID}"),
    ],
)
def test_the_work_routes_need_ticket_manage(env: _Env, method: str, path: str) -> None:
    client = TestClient(env.app)
    kwargs: dict[str, Any] = {"json": {"body": "x"}} if method in ("post", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    env.login(Principal(sub="plain"))
    assert getattr(client, method)(path, **kwargs).status_code == 403


def test_the_list_passes_the_filters(env: _Env) -> None:
    env.login(MANAGER)
    client = TestClient(env.app)
    resp = client.get(
        "/api/tickets",
        params=[("status", "new"), ("status", "done"), ("kind", "bug"), ("assignee", "me")],
    )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["number"] == "T-0001"
    _kind, kw = env.service.calls[-1]
    assert kw["statuses"] == ["new", "done"]
    assert kw["kinds"] == ["bug"]
    assert kw["assignee"] == "me"
    assert kw["me"] == env.account
    other = uuid.uuid4()
    client.get("/api/tickets", params={"assignee": str(other), "q": "x"})
    _kind, kw = env.service.calls[-1]
    assert (kw["assignee"], kw["me"], kw["q"]) == (other, None, "x")
    client.get("/api/tickets", params={"assignee": "none"})
    assert env.service.calls[-1][1]["assignee"] == "none"
    client.get("/api/tickets")
    _kind, kw = env.service.calls[-1]
    assert (kw["statuses"], kw["kinds"], kw["assignee"]) == ((), (), None)
    bad = client.get("/api/tickets", params={"assignee": "nobody"})
    assert bad.status_code == 422
    assert bad.json()["errors"][0]["field"] == "assignee"
    assert client.get("/api/tickets", params={"status": "open"}).status_code == 422


def test_the_work_routes_answer(env: _Env) -> None:
    env.login(MANAGER)
    client = TestClient(env.app)
    assert client.get("/api/tickets/counts").json() == {
        "new": 2,
        "inProgress": 0,
        "done": 0,
        "rejected": 0,
    }
    assert client.get("/api/tickets/assignees").json()[0]["displayName"] == "Ada"
    detail = client.get(f"/api/tickets/{TID}").json()
    assert detail["number"] == "T-0001"
    assert detail["duplicateOf"] is None
    assert detail["openTodoCount"] == 0
    patched = client.patch(f"/api/tickets/{TID}", json={"assigneeId": None})
    assert patched.status_code == 200
    assert "assignee_id" in env.service.calls[-1][1].model_fields_set
    assert client.patch(f"/api/tickets/{TID}", json={"unknown": 1}).status_code == 422
    note = client.post(f"/api/tickets/{TID}/notes", json={"body": "n"})
    assert note.status_code == 201
    assert note.json()["isOwn"] is False
    assert client.post(f"/api/tickets/{TID}/notes", json={"body": ""}).status_code == 422
    files = {"body": "", "attachmentIds": [str(TID)], "draftToken": "tok"}
    assert client.post(f"/api/tickets/{TID}/notes", json=files).status_code == 201
    (args, kw) = env.service.calls[-1][1]
    assert args[1].attachment_ids == [TID]
    assert args[1].draft_token == "tok"
    assert kw["pepper"]
    too_many = {"body": "x", "attachmentIds": [str(uuid.uuid4()) for _ in range(6)]}
    assert client.post(f"/api/tickets/{TID}/notes", json=too_many).status_code == 422
    blocked = client.post(f"/api/tickets/{TID}/block-sender")
    assert blocked.status_code == 200
    assert blocked.json()["senderBlocked"] is True
    unblocked = client.delete(f"/api/tickets/{TID}/block-sender")
    assert unblocked.json()["senderBlocked"] is False
    listed = client.get("/api/tickets/blocked-senders").json()
    assert listed[0]["kind"] == "email"
    assert listed[0]["hitCount"] == 2
    assert listed[0]["blockedAt"].startswith("2026-10-01")
    assert client.delete(f"/api/tickets/blocked-senders/{TID}").status_code == 204
    assert env.service.calls[-1] == ("delete_block", TID)
    assert client.patch(f"/api/tickets/{TID}/notes/{TID}", json={"body": "m"}).status_code == 200
    assert client.delete(f"/api/tickets/{TID}/notes/{TID}").status_code == 204


def test_the_default_wiring() -> None:
    assert get_ticket_mail_sender() is _deliver_ticket_mails
    assert get_note_mail_sender() is _deliver_note_mail
    from app.modules.todos.hooks import TicketTodoBridge

    storage = object()

    class _Request:
        class app:
            class state:
                object_storage = storage

    service = get_ticket_service(object(), _Request())  # type: ignore[arg-type]
    assert isinstance(service.todos, TicketTodoBridge)
    assert service.files.storage is storage


async def test_the_mail_sender_sends_both_mails(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []

    async def _received(**kw: Any) -> bool:
        order.append(f"received:{kw['ticket_id']}")
        return True

    async def _created(**kw: Any) -> bool:
        order.append(f"created:{kw['ticket_id']}")
        return True

    monkeypatch.setattr(router_mod, "notify_ticket_received", _received)
    monkeypatch.setattr(router_mod, "notify_ticket_created", _created)
    await _deliver_ticket_mails(load_settings(), TID, None)
    assert order == [f"received:{TID}", f"created:{TID}"]


async def test_the_note_mail_sender_passes_the_note(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[uuid.UUID] = []

    async def _note_mail(**kw: Any) -> bool:
        seen.append(kw["note_id"])
        return True

    monkeypatch.setattr(router_mod, "notify_ticket_note", _note_mail)
    await _deliver_note_mail(load_settings(), NOTE_ID, None)
    assert seen == [NOTE_ID]


def test_only_a_public_note_of_the_team_mails(env: _Env) -> None:
    env.login(MANAGER)
    client = TestClient(env.app)
    assert client.post(f"/api/tickets/{TID}/notes", json={"body": "n"}).status_code == 201
    assert env.note_mails.sent == []
    public = client.post(f"/api/tickets/{TID}/notes", json={"body": "n", "visibility": "public"})
    assert public.status_code == 201
    assert env.note_mails.sent == [uuid.UUID(public.json()["id"])]


def test_a_message_of_the_reporter_mails_the_team(env: _Env) -> None:
    """Mail the team about a message of the reporter; an edit sends nothing."""
    env.login(Principal(sub="plain"))
    client = TestClient(env.app)
    assert client.post(f"/api/tickets/mine/{TID}/notes", json={"body": "n"}).status_code == 201
    assert env.note_mails.sent == [NOTE_ID]
    client.patch(f"/api/tickets/mine/{TID}/notes/{TID}", json={"body": "m"})
    assert env.note_mails.sent == [NOTE_ID]


def test_validation_problem_is_the_shape_of_the_assignee_error() -> None:
    with pytest.raises(ValidationProblem):
        router_mod._assignee_filter("x")
    assert router_mod._assignee_filter(None) is None


_MINE = [
    ("get", "/api/tickets/mine"),
    ("get", f"/api/tickets/mine/{TID}"),
    ("post", f"/api/tickets/mine/{TID}/notes"),
    ("patch", f"/api/tickets/mine/{TID}/notes/{TID}"),
    ("delete", f"/api/tickets/mine/{TID}/notes/{TID}"),
]


@pytest.mark.parametrize(("method", "path"), _MINE)
def test_the_reporter_routes_need_a_session_and_no_permission(
    env: _Env, method: str, path: str
) -> None:
    client = TestClient(env.app)
    kwargs: dict[str, Any] = {"json": {"body": "x"}} if method in ("post", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    env.login(Principal(sub="plain"))
    assert getattr(client, method)(path, **kwargs).status_code in (200, 201, 204)


def test_the_reporter_list_passes_the_filters_and_the_account(env: _Env) -> None:
    env.login(Principal(sub="plain"))
    client = TestClient(env.app)
    resp = client.get(
        "/api/tickets/mine", params=[("status", "done"), ("kind", "idea"), ("q", "x")]
    )
    assert resp.status_code == 200
    assert resp.json()["items"][0]["number"] == "T-0001"
    assert "reporter" not in resp.json()["items"][0]
    me, kw = env.service.calls[-1][1]
    assert me == env.account
    assert (kw["statuses"], kw["kinds"], kw["q"]) == (["done"], ["idea"], "x")
    client.get("/api/tickets/mine")
    _me, kw = env.service.calls[-1][1]
    assert (kw["statuses"], kw["kinds"]) == ((), ())


def test_the_reporter_list_of_a_session_without_an_account_is_empty(env: _Env) -> None:
    env.account = None
    env.login(Principal(sub="plain"))
    body = TestClient(env.app).get("/api/tickets/mine").json()
    assert (body["items"], body["total"]) == ([], 0)
    assert env.service.calls == []


def test_the_reporter_routes_answer(env: _Env) -> None:
    """Answer on the routes of the reporter.

    A reporter has no visibility switch, so the field is refused.
    """
    env.login(Principal(sub="plain"))
    client = TestClient(env.app)
    detail = client.get(f"/api/tickets/mine/{TID}").json()
    assert detail["canReply"] is True
    assert "assignee" not in detail
    assert "context" not in detail
    note = client.post(f"/api/tickets/mine/{TID}/notes", json={"body": "n"})
    assert note.status_code == 201
    (args, kw) = env.service.calls[-1][1]
    assert args[1].body == "n"
    assert kw["pepper"]
    assert (
        client.post(
            f"/api/tickets/mine/{TID}/notes", json={"body": "n", "visibility": "internal"}
        ).status_code
        == 422
    )
    assert (
        client.patch(f"/api/tickets/mine/{TID}/notes/{TID}", json={"body": "m"}).status_code == 200
    )
    assert client.delete(f"/api/tickets/mine/{TID}/notes/{TID}").status_code == 204
    assert env.service.calls[-1][0] == "reporter_delete_note"


@pytest.mark.parametrize(("method", "path"), _MINE[2:])
def test_a_token_without_tickets_write_cannot_write_as_reporter(
    env: _Env, method: str, path: str
) -> None:
    env.login(Principal(sub="plain", scope_permissions=frozenset({"application.read"})))
    client = TestClient(env.app)
    kwargs: dict[str, Any] = {"json": {"body": "x"}} if method in ("post", "patch") else {}
    assert getattr(client, method)(path, **kwargs).status_code == 403
    assert client.get(f"/api/tickets/mine/{TID}").status_code == 200
    env.login(Principal(sub="plain", scope_permissions=frozenset({"ticket.manage"})))
    assert getattr(client, method)(path, **kwargs).status_code in (200, 201, 204)


def test_a_manager_note_takes_a_visibility(env: _Env) -> None:
    env.login(MANAGER)
    client = TestClient(env.app)
    assert (
        client.post(
            f"/api/tickets/{TID}/notes", json={"body": "n", "visibility": "public"}
        ).status_code
        == 201
    )
    (args, _kw) = env.service.calls[-1][1]
    assert args[1].visibility == "public"
    client.post(f"/api/tickets/{TID}/notes", json={"body": "n"})
    (args, _kw) = env.service.calls[-1][1]
    assert args[1].visibility == "internal"
    bad = client.post(f"/api/tickets/{TID}/notes", json={"body": "n", "visibility": "secret"})
    assert bad.status_code == 422


class _MentionMails:
    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, list[uuid.UUID]]] = []

    async def __call__(
        self, _settings: object, note_id: uuid.UUID, ids: list[uuid.UUID], _pool: object
    ) -> None:
        self.sent.append((note_id, ids))


def test_a_note_queues_the_mention_mail_of_the_added_mentions(env: _Env) -> None:
    mentions = _MentionMails()
    env.app.dependency_overrides[router_mod.get_mention_mail_sender] = lambda: mentions
    env.login(MANAGER)
    client = TestClient(env.app)
    ada = uuid.uuid4()
    assert client.post(f"/api/tickets/{TID}/notes", json={"body": "n"}).status_code == 201
    assert mentions.sent == []
    env.service.added_mentions = [ada]
    note = client.post(f"/api/tickets/{TID}/notes", json={"body": "n", "mentions": [str(ada)]})
    assert note.status_code == 201
    _kind, (args, _kw) = env.service.calls[-1]
    assert args[1].mentions == [ada]
    assert mentions.sent == [(uuid.UUID(note.json()["id"]), [ada])]
    env.service.added_mentions = []
    edit = client.patch(f"/api/tickets/{TID}/notes/{TID}", json={"body": "m"})
    assert edit.status_code == 200
    assert env.service.calls[-1][1][1] == {"mentions": None}
    assert len(mentions.sent) == 1
    env.service.added_mentions = [ada]
    client.patch(f"/api/tickets/{TID}/notes/{TID}", json={"body": "m", "mentions": [str(ada)]})
    assert env.service.calls[-1][1][1] == {"mentions": [ada]}
    assert len(mentions.sent) == 2


def test_the_reporter_routes_take_no_mentions(env: _Env) -> None:
    env.login(Principal(sub="u"))
    client = TestClient(env.app)
    body = {"body": "n", "mentions": [str(uuid.uuid4())]}
    assert client.post(f"/api/tickets/mine/{TID}/notes", json=body).status_code == 422
    assert client.patch(f"/api/tickets/mine/{TID}/notes/{TID}", json=body).status_code == 422
