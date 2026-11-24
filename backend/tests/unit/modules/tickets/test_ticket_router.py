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
from app.modules.auth.people import PersonRef
from app.modules.auth.principal import Principal
from app.modules.site_config.branding import Branding, TicketSettings
from app.modules.tickets import router as router_mod
from app.modules.tickets.router import (
    _deliver_note_mail,
    _deliver_ticket_mails,
    get_area_service,
    get_note_mail_sender,
    get_ticket_mail_sender,
    get_ticket_service,
)
from app.modules.tickets.schemas import (
    ReporterTicketDetail,
    ReporterTicketItem,
    TicketAreaChoice,
    TicketAreaOut,
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

NOW = datetime(2026, 10, 1, tzinfo=UTC)
NOTE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
TID = uuid.uuid4()
MANAGER = Principal(sub="mgr", permissions={"ticket.manage"})
WORKER = Principal(sub="worker")
AREA = uuid.uuid4()
NO_AREA: frozenset[uuid.UUID] = frozenset()


def _item() -> TicketListItem:
    return TicketListItem(
        id=TID,
        number="T-AAAA0001",
        area_id=AREA,
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
    number = "AAAA0042"


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.swallow = False
        self.added_mentions: list[uuid.UUID] = []
        self.scopes: list[Any] = []
        self.follow_up: Any = None
        self.manual_note: Any = None

    async def reporter_follow_up(self, *a: Any, **kw: Any) -> Any:
        self.calls.append(("reporter_follow_up", (a, kw)))
        return self.follow_up

    async def create_manual(self, payload: Any, _p: Principal, **kw: Any) -> tuple[Any, Any]:
        self.calls.append(("create_manual", payload))
        self.scopes.append(kw["areas"])
        return _Created(), self.manual_note

    async def create(self, payload: Any, **kw: Any) -> _Created | SwallowedReport:
        self.calls.append(("create", kw))
        return SwallowedReport(number="AAAA0043") if self.swallow else _Created()

    async def block_sender(self, ticket_id: uuid.UUID, _p: Principal, **_kw: Any) -> TicketDetail:
        self.calls.append(("block", ticket_id))
        return _detail().model_copy(update={"sender_blocked": True})

    async def unblock_sender(self, ticket_id: uuid.UUID, _p: Principal, **_kw: Any) -> TicketDetail:
        self.calls.append(("unblock", ticket_id))
        return _detail()

    async def blocked_senders(self) -> list[TicketBlockedSender]:
        return [TicketBlockedSender(id=TID, kind="email", email="a@x", blocked_at=NOW, hit_count=2)]

    async def delete_block(self, block_id: uuid.UUID) -> None:
        self.calls.append(("delete_block", block_id))

    async def list(self, **kw: Any) -> Page[TicketListItem]:
        self.calls.append(("list", kw))
        return Page[TicketListItem](items=[_item()], total=1, limit=kw["limit"], offset=0)

    async def counts(self, **kw: Any) -> TicketCounts:
        self.scopes.append(kw["areas"])
        return TicketCounts(new=2)

    async def assignees(self, areas: Any = None) -> list[PersonRef]:
        self.scopes.append(areas)
        return [PersonRef(principal_id=uuid.uuid4(), display_name="Ada")]

    async def detail(self, ticket_id: uuid.UUID, _p: Principal, **kw: Any) -> TicketDetail:
        self.calls.append(("detail", ticket_id))
        self.scopes.append(kw["areas"])
        return _detail()

    async def patch(
        self, ticket_id: uuid.UUID, payload: Any, _p: Principal, **kw: Any
    ) -> TicketDetail:
        self.calls.append(("patch", payload))
        self.scopes.append(kw["areas"])
        return _detail()

    async def add_note(self, *a: Any, **kw: Any) -> TicketNoteOut:
        self.calls.append(("add_note", (a, kw)))
        return _note().model_copy(update={"visibility": a[1].visibility})

    async def edit_note(self, *a: Any, **kw: Any) -> TicketNoteOut:
        self.calls.append(("edit_note", (a, kw)))
        return _note()

    async def delete_note(self, *_a: Any, **_kw: Any) -> None:
        self.calls.append(("delete_note", None))

    async def reporter_list(self, me: uuid.UUID, **kw: Any) -> Page[ReporterTicketItem]:
        self.calls.append(("reporter_list", (me, kw)))
        item = ReporterTicketItem(
            id=TID,
            number="T-AAAA0001",
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
            number="T-AAAA0001",
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


class _Db:
    """The session double: the routes that commit count here."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _Env:
    def __init__(self, app: FastAPI, service: _FakeService, mails: _Mails) -> None:
        self.app = app
        self.service = service
        self.mails = mails
        self.note_mails = _Mails()
        self.assigned_mails = _Mails()
        self.db = _Db()
        self.public = True
        self.areas: dict[str, frozenset[uuid.UUID]] = {}
        self.account: uuid.UUID | None = uuid.uuid4()

    def login(self, principal: Principal | None) -> None:
        self.app.dependency_overrides[get_current_principal] = lambda: principal


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> _Env:
    app = create_app()
    service, mails = _FakeService(), _Mails()
    state = _Env(app, service, mails)

    def _session() -> Iterator[object]:
        yield state.db

    async def _branding(_db: object) -> Branding:
        return Branding(tickets=TicketSettings(publicEnabled=state.public))

    async def _pid(_db: object, _sub: str) -> uuid.UUID | None:
        return state.account

    async def _scope(_db: object, principal: Principal) -> frozenset[uuid.UUID] | None:
        return None if principal.has("ticket.manage") else state.areas.get(principal.sub, NO_AREA)

    monkeypatch.setattr(router_mod, "area_scope", _scope)
    monkeypatch.setattr(router_mod, "active_branding", _branding)
    monkeypatch.setattr(router_mod, "principal_id_of", _pid)
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_ticket_service] = lambda: service
    app.dependency_overrides[get_ticket_mail_sender] = lambda: mails
    app.dependency_overrides[get_note_mail_sender] = lambda: state.note_mails
    app.dependency_overrides[router_mod.get_assigned_mail_sender] = lambda: state.assigned_mails
    state.login(None)
    return state


_REPORT = {"kind": "bug", "title": "t", "body": "b"}


def test_an_anonymous_report_answers_the_number_and_mails(env: _Env) -> None:
    resp = TestClient(env.app).post("/api/tickets", json={**_REPORT, "email": "a@example.org"})
    assert resp.status_code == 201
    assert resp.json() == {"number": "T-AAAA0042"}
    kind, kw = env.service.calls[0]
    assert kind == "create"
    assert kw["reporter_id"] is None
    assert kw["email"] == "a@example.org"
    assert env.mails.sent == [TID]


def test_a_swallowed_report_answers_a_number_and_sends_no_mail(env: _Env) -> None:
    env.service.swallow = True
    resp = TestClient(env.app).post("/api/tickets", json={**_REPORT, "email": "a@example.org"})
    assert resp.status_code == 201
    assert resp.json() == {"number": "T-AAAA0043"}
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


def test_an_anonymous_barrier_report_passes_while_public_reports_are_off(env: _Env) -> None:
    """The feedback route of the accessibility statement needs no login (spec 000497)."""
    env.public = False
    report = {**_REPORT, "kind": "barrier", "email": "a@example.org"}
    resp = TestClient(env.app).post("/api/tickets", json=report)
    assert resp.status_code == 201
    assert env.service.calls[0][1]["reporter_id"] is None


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
    assert resp.json()["items"][0]["number"] == "T-AAAA0001"
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
        "waiting": 0,
        "done": 0,
        "rejected": 0,
    }
    assert client.get("/api/tickets/assignees").json()[0]["displayName"] == "Ada"
    detail = client.get(f"/api/tickets/{TID}").json()
    assert detail["number"] == "T-AAAA0001"
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


def test_a_worker_reaches_the_work_routes_with_the_own_bereiche(env: _Env) -> None:
    """Spec 002703: ``ticket.work`` in a Gremium opens the routes for its Bereiche only."""
    env.areas[WORKER.sub] = frozenset({AREA})
    env.login(WORKER)
    client = TestClient(env.app)
    assert client.get("/api/tickets", params={"area": str(AREA)}).status_code == 200
    _kind, kw = env.service.calls[-1]
    assert (kw["areas"], kw["area_ids"]) == (frozenset({AREA}), [AREA])
    assert client.get("/api/tickets/counts").status_code == 200
    assert client.get(f"/api/tickets/{TID}").status_code == 200
    moved = client.patch(f"/api/tickets/{TID}", json={"areaId": str(uuid.uuid4())})
    assert moved.status_code == 200
    assert env.service.scopes == [frozenset({AREA})] * 3
    assert client.get("/api/tickets/assignees", params={"area": str(AREA)}).status_code == 200
    assert client.get("/api/tickets/assignees").status_code == 200
    assert env.service.scopes[-2:] == [frozenset({AREA}), frozenset({AREA})]
    foreign = client.get("/api/tickets/assignees", params={"area": str(uuid.uuid4())})
    assert foreign.status_code == 404
    assert client.get("/api/tickets/blocked-senders").status_code == 403
    assert client.post(f"/api/tickets/{TID}/block-sender").status_code == 403


def test_a_manager_works_in_every_bereich(env: _Env) -> None:
    env.login(MANAGER)
    client = TestClient(env.app)
    other = uuid.uuid4()
    assert client.get("/api/tickets/assignees", params={"area": str(other)}).status_code == 200
    assert env.service.scopes[-1] == frozenset({other})
    assert client.get("/api/tickets/counts").status_code == 200
    assert env.service.scopes[-1] is None


class _FakeAreas:
    """The Bereich service double of the area routes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.session = self
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    def _out(self, **kw: Any) -> TicketAreaOut:
        return TicketAreaOut(id=AREA, name="Finanzen", **kw)

    async def choices(self) -> list[TicketAreaChoice]:
        return [TicketAreaChoice(id=AREA, name="Finanzen")]

    async def listing(self, scope: Any = None) -> list[TicketAreaOut]:
        self.calls.append(("listing", scope))
        return [self._out(mine=scope is None or AREA in scope)]

    async def create(self, payload: Any, actor: str) -> TicketAreaOut:
        self.calls.append(("create", (payload, actor)))
        return self._out()

    async def patch(self, area_id: uuid.UUID, payload: Any, actor: str) -> TicketAreaOut:
        self.calls.append(("patch", (area_id, payload, actor)))
        return self._out()

    async def delete(self, area_id: uuid.UUID, actor: str) -> None:
        self.calls.append(("delete", (area_id, actor)))


def test_the_area_routes(env: _Env) -> None:
    """Specs 002702 and 002705: the list for the team, the changes behind ``admin.site``."""
    areas = _FakeAreas()
    env.app.dependency_overrides[get_area_service] = lambda: areas
    client = TestClient(env.app)
    assert client.get("/api/tickets/areas").status_code == 401
    assert client.get("/api/admin/ticket-areas").status_code == 401
    env.areas[WORKER.sub] = frozenset({AREA})
    env.login(WORKER)
    listed = client.get("/api/tickets/areas")
    assert listed.status_code == 200
    assert listed.json()[0] == {
        "id": str(AREA),
        "name": "Finanzen",
        "gremiumId": None,
        "platform": False,
        "notifyNew": True,
        "inApp": False,
        "categories": [],
        "mine": True,
    }
    assert client.get("/api/admin/ticket-areas").status_code == 403
    assert client.post("/api/admin/ticket-areas", json={"name": "X"}).status_code == 403
    env.login(Principal(sub="adm", permissions={"admin.site"}))
    assert client.get("/api/tickets/areas").status_code == 403
    assert client.get("/api/admin/ticket-areas").status_code == 200
    body = {"name": "Finanzen", "gremiumId": str(uuid.uuid4()), "categories": [{"name": "A"}]}
    assert client.post("/api/admin/ticket-areas", json=body).status_code == 201
    assert areas.calls[-1][1][1] == "adm"
    two = {"name": "X", "gremiumId": [str(uuid.uuid4()), str(uuid.uuid4())]}
    assert client.post("/api/admin/ticket-areas", json=two).status_code == 422
    assert client.post("/api/admin/ticket-areas", json={"name": ""}).status_code == 422
    patched = client.patch(f"/api/admin/ticket-areas/{AREA}", json={"notifyNew": False})
    assert patched.status_code == 200
    assert areas.calls[-1][1][1].model_fields_set == {"notify_new"}
    assert client.delete(f"/api/admin/ticket-areas/{AREA}").status_code == 204
    assert areas.calls[-1] == ("delete", (AREA, "adm"))
    assert areas.commits == 3


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


def test_a_late_message_of_the_reporter_becomes_a_new_ticket(env: _Env) -> None:
    """Spec 002710: the answer names the new ticket, and its mails are those of a report."""
    env.login(Principal(sub="plain"))
    env.service.follow_up = _Created()
    resp = TestClient(env.app).post(f"/api/tickets/mine/{TID}/notes", json={"body": "n"})
    assert resp.status_code == 201
    assert resp.json() == {"followUp": {"id": str(TID), "number": "T-AAAA0042"}}
    assert env.db.commits == 1
    assert env.mails.sent == [TID]
    assert env.note_mails.sent == []
    assert "reporter_add_note" not in [kind for kind, _ in env.service.calls]


def test_a_new_assignee_queues_the_assigned_mail(env: _Env) -> None:
    """Spec 002718: only a patch that names an assignee asks for the mail."""
    env.login(MANAGER)
    client = TestClient(env.app)
    assert client.patch(f"/api/tickets/{TID}", json={"status": "waiting"}).status_code == 200
    assert client.patch(f"/api/tickets/{TID}", json={"assigneeId": None}).status_code == 200
    assert env.assigned_mails.sent == []
    assigned = client.patch(f"/api/tickets/{TID}", json={"assigneeId": str(uuid.uuid4())})
    assert assigned.status_code == 200
    assert env.assigned_mails.sent == [TID]


def test_the_team_creates_a_ticket_by_hand(env: _Env) -> None:
    """Spec 002712: the work right opens the route; a first message mails the person."""
    client = TestClient(env.app)
    body = {"areaId": str(AREA), "title": "Anruf", "reporterId": str(uuid.uuid4())}
    assert client.post("/api/tickets/manual", json=body).status_code == 401
    env.login(Principal(sub="plain"))
    assert client.post("/api/tickets/manual", json=body).status_code == 403
    env.areas[WORKER.sub] = frozenset({AREA})
    env.login(WORKER)
    created = client.post("/api/tickets/manual", json=body)
    assert created.status_code == 201
    assert created.json()["id"] == str(TID)
    assert env.service.scopes[0] == frozenset({AREA})
    assert env.db.commits == 1
    assert env.note_mails.sent == []
    env.service.manual_note = _note().model_copy(update={"id": NOTE_ID})
    assert client.post("/api/tickets/manual", json={**body, "message": "Hallo"}).status_code == 201
    assert env.note_mails.sent == [NOTE_ID]
    assert client.post("/api/tickets/manual", json={**body, "title": ""}).status_code == 422


def test_a_signed_in_person_reads_the_bereiche_of_the_ticket_dialog(env: _Env) -> None:
    """Spec 002713: any session reads the list, a person without one does not."""
    env.app.dependency_overrides[get_area_service] = _FakeAreas
    client = TestClient(env.app)
    assert client.get("/api/tickets/report-areas").status_code == 401
    env.login(Principal(sub="plain"))
    listed = client.get("/api/tickets/report-areas")
    assert listed.status_code == 200
    assert listed.json() == [
        {"id": str(AREA), "name": "Finanzen", "platform": False, "categories": []}
    ]


def test_a_report_names_a_bereich_and_its_kategorie(env: _Env) -> None:
    """Spec 002713: the body takes ``areaId`` and ``categoryId`` in place of a kind."""
    env.login(Principal(sub="plain"))
    body = {"title": "t", "body": "b", "areaId": str(AREA), "categoryId": str(uuid.uuid4())}
    assert TestClient(env.app).post("/api/tickets", json=body).status_code == 201


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
    assert resp.json()["items"][0]["number"] == "T-AAAA0001"
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
    assert env.service.calls[-1][1][1]["mentions"] is None
    assert len(mentions.sent) == 1
    env.service.added_mentions = [ada]
    client.patch(f"/api/tickets/{TID}/notes/{TID}", json={"body": "m", "mentions": [str(ada)]})
    assert env.service.calls[-1][1][1]["mentions"] == [ada]
    assert len(mentions.sent) == 2


def test_the_reporter_routes_take_no_mentions(env: _Env) -> None:
    env.login(Principal(sub="u"))
    client = TestClient(env.app)
    body = {"body": "n", "mentions": [str(uuid.uuid4())]}
    assert client.post(f"/api/tickets/mine/{TID}/notes", json=body).status_code == 422
    assert client.patch(f"/api/tickets/mine/{TID}/notes/{TID}", json=body).status_code == 422


class _FakeMailboxes:
    """The Postfach service double: it keeps the calls and counts the commits."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.commits = 0
        self.session = self

    async def commit(self) -> None:
        self.commits += 1

    def _out(self) -> Any:
        from app.modules.tickets.mailbox_schemas import MailboxOut

        return MailboxOut(
            area_id=AREA,
            address="buero@example.org",
            imap_host="mail.example.org",
            imap_port=993,
            imap_user="buero",
            smtp_host="mail.example.org",
            smtp_port=465,
            smtp_user="buero",
            done_folder="Erledigt",
            enabled=False,
        )

    async def listing(self) -> Any:
        from app.modules.tickets.mailbox_schemas import MailboxList

        return MailboxList(items=(self._out(),), allowed_hosts=("mail.example.org",))

    async def create(self, area_id: uuid.UUID, payload: Any, actor: str) -> Any:
        self.calls.append(("create", (area_id, payload, actor)))
        return self._out()

    async def patch(self, area_id: uuid.UUID, payload: Any, actor: str) -> Any:
        self.calls.append(("patch", (area_id, payload, actor)))
        return self._out()

    async def delete(self, area_id: uuid.UUID, actor: str) -> None:
        self.calls.append(("delete", (area_id, actor)))

    async def test(self, area_id: uuid.UUID) -> dict[str, Any]:
        self.calls.append(("test", area_id))
        return {"imap": {"ok": True}, "smtp": {"ok": False, "error": "timeout"}}


def test_the_postfach_routes_need_admin_ticket_mail(env: _Env) -> None:
    """Spec 002721: a save without ``admin.ticket_mail`` is 403, also with ``admin.site``."""
    boxes = _FakeMailboxes()
    env.app.dependency_overrides[router_mod.get_mailbox_service] = lambda: boxes
    client = TestClient(env.app)
    url = f"/api/admin/ticket-areas/{AREA}/mailbox"
    body = {
        "address": "buero@example.org",
        "imapHost": "mail.example.org",
        "imapPort": 993,
        "imapUser": "buero",
        "imapPassword": "geheim",
        "smtpHost": "mail.example.org",
        "smtpPort": 465,
        "smtpUser": "buero",
        "smtpPassword": "geheim",
    }
    assert client.get("/api/admin/ticket-mailboxes").status_code == 401
    env.login(Principal(sub="site", permissions={"admin.site", "ticket.manage"}))
    assert client.get("/api/admin/ticket-mailboxes").status_code == 403
    assert client.post(url, json=body).status_code == 403
    assert client.patch(url, json={"enabled": True}).status_code == 403
    assert client.delete(url).status_code == 403
    assert client.post(f"{url}/test").status_code == 403
    assert boxes.calls == []
    env.login(Principal(sub="adm", permissions={"admin.ticket_mail"}))
    listed = client.get("/api/admin/ticket-mailboxes")
    assert listed.status_code == 200
    assert listed.json()["allowedHosts"] == ["mail.example.org"]
    assert "geheim" not in listed.text
    assert client.post(url, json=body).status_code == 201
    assert boxes.calls[-1][1][2] == "adm"
    assert client.post(url, json={**body, "address": "kein"}).status_code == 422
    assert client.post(url, json={**body, "imapHost": "http://x/"}).status_code == 422
    assert client.post(url, json={**body, "imapPort": 0}).status_code == 422
    patched = client.patch(url, json={"enabled": True})
    assert patched.status_code == 200
    assert boxes.calls[-1][1][1].model_fields_set == {"enabled"}
    assert client.post(f"{url}/test").json() == {
        "imap": {"ok": True, "error": None},
        "smtp": {"ok": False, "error": "timeout"},
    }
    assert client.delete(url).status_code == 204
    assert boxes.commits == 3
    assert isinstance(
        router_mod.get_mailbox_service(object(), object()),  # type: ignore[arg-type]
        router_mod.TicketMailboxService,
    )
