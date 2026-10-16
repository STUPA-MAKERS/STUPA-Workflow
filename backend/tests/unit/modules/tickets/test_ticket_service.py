"""Unit tests of ``TicketService`` with a scripted session (no database).

The queues of ``ScriptedSession`` follow the query order of each method. The
integration suite (``tests/integration/modules/tickets``) runs the same paths
against Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.files.schemas import AttachmentOut
from app.modules.livevote.models import Meeting
from app.modules.tickets import service as svc_mod
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from app.modules.tickets.schemas import TicketCreate, TicketPatch
from app.modules.tickets.service import (
    TicketService,
    format_number,
    principal_id_of,
    ticket_managers,
)
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from app.shared.people import DELETED_PERSON, PersonRef
from tests.unit.modules.tickets.fakes import FakeFiles, ScriptedSession

ME = uuid.uuid4()
OTHER = uuid.uuid4()
VIEWER = Principal(sub="me-sub", permissions={"ticket.manage"})
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _svc(session: ScriptedSession, **kw: Any) -> TicketService:
    files = kw.pop("files", FakeFiles())
    return TicketService(session, files=files, **kw)  # type: ignore[arg-type]


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": 7,
        "kind": "bug",
        "title": "Fehler",
        "body": "Text",
        "status": "new",
        "reporter_principal_id": None,
        "reporter_email": "a@example.org",
        "assignee_id": None,
        "duplicate_of_id": None,
        "context": {},
        "closed_at": None,
        "anonymized_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(kw)
    return Ticket(**base)


def _create(**kw: Any) -> TicketCreate:
    return TicketCreate.model_validate({"kind": "idea", "title": "  T  ", "body": "B", **kw})


class _Todos:
    def __init__(self, count: int = 0, readable: set[uuid.UUID] | None = None) -> None:
        self.count = count
        self.completed: list[uuid.UUID] = []
        self.readable = readable or set()
        self.asked: list[set[uuid.UUID]] = []

    async def open_count(self, _ticket_id: uuid.UUID, _principal: Principal) -> int:
        return self.count

    async def complete(self, ticket_id: uuid.UUID, _principal: Principal) -> None:
        self.completed.append(ticket_id)

    async def readable_cards(self, card_ids: Any, _principal: Principal) -> set[uuid.UUID]:
        wanted = set(card_ids)
        self.asked.append(wanted)
        return wanted & self.readable


# -- helpers ------------------------------------------------------------------------


def test_format_number_pads_to_four_digits_and_grows() -> None:
    assert format_number(42) == "T-0042"
    assert format_number(12345) == "T-12345"


async def test_principal_id_of_reads_the_row_id() -> None:
    session = ScriptedSession(scalar=[ME])
    assert await principal_id_of(session, "s") == ME  # type: ignore[arg-type]


async def test_ticket_managers_with_and_without_groups() -> None:
    session = ScriptedSession(scalars=[["grp"]], execute=[[(ME, "Ada", "a@x")]])
    assert await ticket_managers(session, principal_id=ME) == [(ME, "Ada", "a@x")]  # type: ignore[arg-type]
    sql = str(session.statements[-1])
    assert "oidc_groups" in sql
    session = ScriptedSession(scalars=[[]], execute=[[]])
    assert await ticket_managers(session) == []  # type: ignore[arg-type]
    assert "oidc_groups" not in str(session.statements[-1])


# -- create ---------------------------------------------------------------------------


async def test_create_with_an_email_reporter() -> None:
    session = ScriptedSession()
    ticket = await _svc(session).create(
        _create(context={"language": "en"}), reporter_id=None, email="a@x.org", pepper="p"
    )
    assert ticket.title == "T"
    assert ticket.reporter_email == "a@x.org"
    assert ticket.context == {"language": "en"}
    (event,) = [o for o in session.added if isinstance(o, TicketEvent)]
    assert event.payload == {"confirmationSent": True}
    assert session.committed == 1


async def test_create_with_an_account_ignores_the_email_and_notes_a_missing_address() -> None:
    session = ScriptedSession(scalar=[None])
    ticket = await _svc(session).create(
        _create(title="  "), reporter_id=ME, email="ignored@x.org", pepper="p"
    )
    assert ticket.title == "  "
    assert ticket.reporter_principal_id == ME
    assert ticket.reporter_email is None
    (event,) = [o for o in session.added if isinstance(o, TicketEvent)]
    assert event.actor_id == ME
    assert event.payload == {"confirmationSent": False}


async def test_create_needs_the_draft_token_with_attachments() -> None:
    with pytest.raises(ValidationProblem) as exc:
        await _svc(ScriptedSession()).create(
            _create(attachmentIds=[str(uuid.uuid4())]), reporter_id=None, email="a@x", pepper="p"
        )
    assert exc.value.errors is not None
    assert exc.value.errors[0].field == "draftToken"


async def test_create_checks_and_binds_the_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def _check(_s: object, **kw: Any) -> None:
        calls.append(("check", kw))

    async def _bind(_s: object, **kw: Any) -> None:
        calls.append(("bind", kw))

    monkeypatch.setattr(svc_mod, "check_drafts", _check)
    monkeypatch.setattr(svc_mod, "bind_drafts", _bind)
    draft = uuid.uuid4()
    ticket = await _svc(ScriptedSession()).create(
        _create(attachmentIds=[str(draft)], draftToken="tok"),
        reporter_id=None,
        email="a@x",
        pepper="p",
    )
    assert [c[0] for c in calls] == ["check", "bind"]
    assert calls[1][1]["ticket_id"] == ticket.id
    assert calls[1][1]["attachment_ids"] == [draft]


async def test_reporter_address_reads_the_account_email() -> None:
    session = ScriptedSession(scalar=["acc@x"])
    ticket = _ticket(reporter_principal_id=ME, reporter_email=None)
    assert await _svc(session).reporter_address(ticket) == "acc@x"


# -- list, counts, assignees -----------------------------------------------------------


async def test_list_without_filters_maps_reporters_and_assignees() -> None:
    anon = _ticket(anonymized_at=NOW, reporter_email=None)
    account = _ticket(reporter_principal_id=ME, reporter_email=None, assignee_id=OTHER)
    gone = _ticket(reporter_principal_id=uuid.uuid4(), reporter_email=None)
    mail = _ticket()
    session = ScriptedSession(
        scalar=[4],
        scalars=[[anon, account, gone, mail]],
        execute=[[(ME, "Ada", "ada@x"), (OTHER, None, "otto@x")]],
    )
    page = await _svc(session).list()
    assert page.total == 4
    first, second, third, fourth = page.items
    assert first.reporter.anonymized is True
    assert first.reporter.email is None
    assert second.reporter.display_name == "Ada"
    assert second.reporter.email == "ada@x"
    assert second.assignee == PersonRef(principal_id=OTHER, display_name="otto@x")
    assert third.reporter.principal_id is None
    assert third.reporter.email is None
    assert fourth.reporter.email == "a@example.org"
    assert fourth.assignee is None


async def test_list_with_every_filter_builds_the_where_clause() -> None:
    session = ScriptedSession(scalar=[None], scalars=[[]])
    page = await _svc(session).list(
        statuses=["new"], kinds=["bug"], assignee="none", q="T-0040", limit=5, offset=10
    )
    assert page.total == 0
    assert (page.limit, page.offset) == (5, 10)
    sql = str(session.statements[0])
    assert "ticket.assignee_id IS NULL" in sql
    assert "ticket.number =" in sql
    assert "ticket.status IN" in sql
    assert "ticket.kind IN" in sql


async def test_list_assignee_me_and_uuid_and_a_text_query() -> None:
    session = ScriptedSession(scalar=[0, 0], scalars=[[], []])
    await _svc(session).list(assignee="me", me=ME, q="drucker")
    sql = str(session.statements[0])
    assert "ticket.assignee_id =" in sql
    assert "ticket.number =" not in sql
    await _svc(session).list(assignee=OTHER, q="   ")
    assert "ticket.assignee_id =" in str(session.statements[2])


async def test_counts_fill_missing_statuses_with_zero() -> None:
    session = ScriptedSession(execute=[[("new", 3), ("done", 1)]])
    counts = await _svc(session).counts()
    assert (counts.new, counts.in_progress, counts.done, counts.rejected) == (3, 0, 1, 0)


async def test_assignees_drop_nameless_accounts_and_sort_by_name() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session = ScriptedSession(
        scalars=[[]], execute=[[(a, "zora", None), (b, None, None), (c, "Anna", None)]]
    )
    people = await _svc(session).assignees()
    assert [p.display_name for p in people] == ["Anna", "zora"]


# -- detail -------------------------------------------------------------------------


async def test_detail_of_an_unknown_ticket_is_404() -> None:
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).detail(uuid.uuid4(), VIEWER)


async def test_detail_maps_notes_events_attachments_and_duplicate() -> None:
    dup = _ticket(number=3)
    ticket = _ticket(duplicate_of_id=dup.id, context={"url": "u"}, status="rejected")
    note = TicketNote(id=uuid.uuid4(), ticket_id=ticket.id, author_id=ME, body="n", created_at=NOW)
    events = [
        TicketEvent(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            actor_id=ME,
            kind="assignee",
            payload={"from": None, "to": str(OTHER)},
            created_at=NOW,
        ),
        TicketEvent(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            actor_id=None,
            kind="created",
            payload={"confirmationSent": True},
            created_at=NOW,
        ),
    ]
    session = ScriptedSession(
        scalar=[ME],
        scalars=[[note], events],
        execute=[[(ME, "Ada", None), (OTHER, "Otto", None)]],
    )
    session.put(ticket, dup)
    att = AttachmentOut(
        id=uuid.uuid4(),
        filename="a.png",
        mime="image/png",
        size=3,
        scanned=True,
        is_comparison_offer=False,
    )
    detail = await _svc(session, files=FakeFiles([att]), todos=_Todos(2)).detail(ticket.id, VIEWER)
    assert detail.duplicate_of is not None
    assert detail.duplicate_of.number == "T-0003"
    assert detail.notes[0].is_own is True
    assert detail.attachments[0].filename == "a.png"
    assert detail.open_todo_count == 2
    assert detail.context == {"url": "u"}
    assert detail.context_target is None
    assignee, created = detail.events
    assert assignee.payload == {
        "from": None,
        "to": {"principalId": str(OTHER), "displayName": "Otto"},
    }
    assert created.actor is None
    dumped = detail.model_dump(by_alias=True, mode="json")
    assert dumped["events"][0]["payload"]["to"]["displayName"] == "Otto"


async def test_detail_without_an_account_row_marks_no_note_as_own() -> None:
    ticket = _ticket(context=None)
    note = TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, author_id=OTHER, body="n", created_at=NOW
    )
    session = ScriptedSession(scalar=[None], scalars=[[note], []], execute=[[]])
    session.put(ticket)
    detail = await _svc(session).detail(ticket.id, VIEWER)
    assert detail.notes[0].is_own is False
    assert detail.notes[0].author == DELETED_PERSON
    assert detail.open_todo_count == 0
    assert detail.context == {}


def _todo_done(ticket: Ticket, card_id: object) -> TicketEvent:
    return TicketEvent(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        actor_id=None,
        kind="todo_done",
        payload={"cardId": card_id, "cardTitle": "Geheim", "boardId": str(uuid.uuid4())},
        created_at=NOW,
    )


async def test_detail_shows_a_todo_title_only_to_a_reader_of_its_board() -> None:
    ticket = _ticket()
    seen, hidden = uuid.uuid4(), uuid.uuid4()
    events = [_todo_done(ticket, str(seen)), _todo_done(ticket, str(hidden))]
    events.append(_todo_done(ticket, "kein-uuid"))
    events.append(_todo_done(ticket, None))
    session = ScriptedSession(scalar=[None], scalars=[[], events], execute=[[]])
    session.put(ticket)
    todos = _Todos(readable={seen})
    detail = await _svc(session, todos=todos).detail(ticket.id, VIEWER)
    titles = [e.payload["cardTitle"] for e in detail.events]
    assert titles == ["Geheim", None, None, None]
    assert todos.asked == [{seen, hidden}]


async def test_detail_without_todo_hooks_hides_every_todo_title() -> None:
    ticket = _ticket()
    session = ScriptedSession(
        scalar=[None], scalars=[[], [_todo_done(ticket, str(uuid.uuid4()))]], execute=[[]]
    )
    session.put(ticket)
    detail = await _svc(session).detail(ticket.id, VIEWER)
    assert detail.events[0].payload["cardTitle"] is None


async def _detail_with_route(route: object, session: ScriptedSession) -> Any:
    ticket = _ticket(context={"route": route})
    session.scalar_q[:0] = [None]
    session.scalars_q[:0] = [[], []]
    session.put(ticket)
    return (await _svc(session).detail(ticket.id, VIEWER)).context_target


@pytest.mark.parametrize(
    "route",
    [
        None,
        5,
        "/admin",
        "/applications/not-a-uuid",
        "/applications/" + "-" * 36,
        "/meetings/" + "a" * 36,
    ],
)
async def test_a_route_without_a_target_gives_none(route: object) -> None:
    assert await _detail_with_route(route, ScriptedSession()) is None


async def test_the_application_target_needs_a_confirmed_readable_application(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_id = uuid.uuid4()
    route = f"/applications/{app_id}/edit"
    # Missing application.
    assert await _detail_with_route(route, ScriptedSession()) is None
    # Unconfirmed guest application.
    session = ScriptedSession()
    session.put(Application(id=app_id, data={}, email_confirmed_at=None))
    assert await _detail_with_route(route, session) is None

    allowed = {"ok": False}

    async def _read(*_a: object) -> None:
        if not allowed["ok"]:
            raise ForbiddenError("no")

    monkeypatch.setattr(svc_mod, "resolve_app_read", _read)
    session = ScriptedSession()
    session.put(Application(id=app_id, data={"title": "Antrag"}, email_confirmed_at=NOW))
    assert await _detail_with_route(route, session) is None
    allowed["ok"] = True
    session = ScriptedSession()
    session.put(Application(id=app_id, data={"title": "Antrag"}, email_confirmed_at=NOW))
    target = await _detail_with_route(route, session)
    assert target is not None
    assert (target.kind, target.id, target.title) == ("application", app_id, "Antrag")
    session = ScriptedSession()
    session.put(Application(id=app_id, data={}, email_confirmed_at=NOW))
    target = await _detail_with_route(f"/applications/{app_id}", session)
    assert target is not None
    assert target.title == ""


async def test_the_meeting_target_needs_read_access(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.livevote import service as livevote_service

    meeting_id = uuid.uuid4()
    route = f"/meetings/{meeting_id}?item=1"
    assert await _detail_with_route(route, ScriptedSession()) is None

    allowed = {"ok": False}

    async def _assert(_self: object, *_a: object) -> None:
        if not allowed["ok"]:
            raise ForbiddenError("no")

    monkeypatch.setattr(livevote_service.MeetingService, "assert_can_read", _assert)
    session = ScriptedSession()
    session.put(Meeting(id=meeting_id, title="StuPa 3"))
    assert await _detail_with_route(route, session) is None
    allowed["ok"] = True
    session = ScriptedSession()
    session.put(Meeting(id=meeting_id, title="StuPa 3"))
    target = await _detail_with_route(route, session)
    assert target is not None
    assert (target.kind, target.title) == ("meeting", "StuPa 3")


# -- patch ----------------------------------------------------------------------------


@pytest.fixture
def no_detail(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    seen: list[uuid.UUID] = []

    async def _detail(_self: object, ticket_id: uuid.UUID, _p: Principal) -> str:
        seen.append(ticket_id)
        return "detail"

    monkeypatch.setattr(TicketService, "detail", _detail)
    return seen


def _events(session: ScriptedSession) -> list[tuple[str, dict[str, Any]]]:
    return [(e.kind, e.payload) for e in session.added if isinstance(e, TicketEvent)]


async def test_patch_of_an_unknown_ticket_is_404() -> None:
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).patch(uuid.uuid4(), TicketPatch(), VIEWER)


async def test_patch_closes_and_reopens_with_the_retention_clock(
    no_detail: list[uuid.UUID],
) -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, ME, ME])
    session.put(ticket)
    service = _svc(session)
    assert await service.patch(ticket.id, TicketPatch(status="done"), VIEWER) == "detail"
    assert ticket.status == "done"
    first_close = ticket.closed_at
    assert first_close is not None
    # done -> rejected keeps the clock.
    await service.patch(ticket.id, TicketPatch(status="rejected"), VIEWER)
    assert ticket.closed_at == first_close
    await service.patch(ticket.id, TicketPatch(status="in_progress"), VIEWER)
    assert ticket.closed_at is None
    assert [p for _k, p in _events(session)] == [
        {"from": "new", "to": "done"},
        {"from": "done", "to": "rejected"},
        {"from": "rejected", "to": "in_progress"},
    ]
    assert no_detail == [ticket.id] * 3


async def test_patch_without_a_change_writes_no_event(no_detail: list[uuid.UUID]) -> None:
    ticket = _ticket(status="new", kind="bug", assignee_id=OTHER)
    session = ScriptedSession(scalar=[ME])
    session.put(ticket)
    payload = TicketPatch.model_validate({"status": "new", "kind": "bug"})
    await _svc(session).patch(ticket.id, payload, VIEWER)
    assert _events(session) == []
    assert ticket.updated_at == NOW
    assert session.committed == 1


async def test_patch_as_a_duplicate(no_detail: list[uuid.UUID]) -> None:
    original = _ticket(number=1)
    ticket = _ticket(number=2, status="rejected")
    session = ScriptedSession(scalar=[ME])
    session.put(original, ticket)
    payload = TicketPatch.model_validate({"status": "rejected", "duplicateOfId": str(original.id)})
    await _svc(session).patch(ticket.id, payload, VIEWER)
    assert ticket.duplicate_of_id == original.id
    assert _events(session) == [
        ("status", {"from": "rejected", "to": "rejected", "duplicateOf": "T-0001"})
    ]


@pytest.mark.parametrize("case", ["self", "missing", "open"])
async def test_patch_with_a_bad_duplicate_is_422(case: str) -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME])
    session.put(ticket)
    target = {"self": ticket.id, "missing": uuid.uuid4(), "open": ticket.id}[case]
    status = "done" if case == "open" else "rejected"
    payload = TicketPatch.model_validate({"status": status, "duplicateOfId": str(target)})
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).patch(ticket.id, payload, VIEWER)
    assert exc.value.code == "duplicate_invalid"


async def test_patch_complete_todos_needs_a_closing_status() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME])
    session.put(ticket)
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).patch(ticket.id, TicketPatch(completeTodos=True), VIEWER)
    assert exc.value.errors is not None
    assert exc.value.errors[0].field == "completeTodos"


async def test_patch_complete_todos_calls_the_hooks(no_detail: list[uuid.UUID]) -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, ME])
    session.put(ticket)
    todos = _Todos()
    payload = TicketPatch.model_validate({"status": "done", "completeTodos": True})
    await _svc(session, todos=todos).patch(ticket.id, payload, VIEWER)
    assert todos.completed == [ticket.id]
    # Without hooks the flag changes no card.
    payload = TicketPatch.model_validate({"status": "rejected", "completeTodos": True})
    await _svc(session).patch(ticket.id, payload, VIEWER)
    assert ticket.status == "rejected"


async def test_patch_assignee_must_hold_ticket_manage() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME], scalars=[[]], execute=[[]])
    session.put(ticket)
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).patch(ticket.id, TicketPatch(assigneeId=OTHER), VIEWER)
    assert exc.value.code == "assignee_not_allowed"


async def test_patch_assigns_unassigns_and_changes_the_kind(no_detail: list[uuid.UUID]) -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, ME], scalars=[[]], execute=[[(OTHER, "Otto", None)]])
    session.put(ticket)
    service = _svc(session)
    await service.patch(ticket.id, TicketPatch(assigneeId=OTHER, kind="idea"), VIEWER)
    assert (ticket.assignee_id, ticket.kind) == (OTHER, "idea")
    await service.patch(ticket.id, TicketPatch.model_validate({"assigneeId": None}), VIEWER)
    assert ticket.assignee_id is None
    assert ticket.updated_at != NOW
    assert _events(session) == [
        ("assignee", {"from": None, "to": str(OTHER)}),
        ("kind", {"from": "bug", "to": "idea"}),
        ("assignee", {"from": str(OTHER), "to": None}),
    ]


# -- notes --------------------------------------------------------------------------


async def test_add_note() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME], execute=[[(ME, "Ada", None)]])
    session.put(ticket)
    out = await _svc(session).add_note(ticket.id, "hallo", VIEWER)
    assert out.body == "hallo"
    assert out.is_own is True
    assert out.author.display_name == "Ada"
    assert session.committed == 1


async def test_add_note_needs_an_account_row() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[None])
    session.put(ticket)
    with pytest.raises(NotFoundError):
        await _svc(session).add_note(ticket.id, "x", VIEWER)


def _note(ticket: Ticket, author: uuid.UUID, **kw: Any) -> TicketNote:
    return TicketNote(
        id=uuid.uuid4(), ticket_id=ticket.id, author_id=author, body="alt", created_at=NOW, **kw
    )


async def test_edit_and_delete_an_own_note() -> None:
    ticket = _ticket()
    note = _note(ticket, ME)
    session = ScriptedSession(scalar=[ME, ME], execute=[[(ME, "Ada", None)]])
    session.put(ticket, note)
    service = _svc(session)
    out = await service.edit_note(ticket.id, note.id, "neu", VIEWER)
    assert out.body == "neu"
    assert out.edited_at is not None
    await service.delete_note(ticket.id, note.id, VIEWER)
    assert note.deleted_at is not None


async def test_a_foreign_note_is_403() -> None:
    ticket = _ticket()
    note = _note(ticket, OTHER)
    session = ScriptedSession(scalar=[ME, None])
    session.put(ticket, note)
    with pytest.raises(ForbiddenError) as exc:
        await _svc(session).edit_note(ticket.id, note.id, "x", VIEWER)
    assert exc.value.code == "not_note_author"
    with pytest.raises(ForbiddenError):
        await _svc(session).delete_note(ticket.id, note.id, VIEWER)


async def test_a_missing_note_is_404() -> None:
    ticket, other = _ticket(), _ticket()
    elsewhere = _note(other, ME)
    deleted = _note(ticket, ME, deleted_at=NOW)
    session = ScriptedSession()
    session.put(ticket, other, elsewhere, deleted)
    for note_id in (uuid.uuid4(), elsewhere.id, deleted.id):
        with pytest.raises(NotFoundError):
            await _svc(session).edit_note(ticket.id, note_id, "x", VIEWER)


# -- anonymization ----------------------------------------------------------------


async def test_anonymize_clears_the_reporter_the_context_and_the_files() -> None:
    files = FakeFiles()
    ticket = _ticket(reporter_principal_id=ME, reporter_email=None, context={"url": "u"})
    session = ScriptedSession()
    await _svc(session, files=files).anonymize(ticket, actor="sys")
    assert files.deleted == [(ticket.id, "sys")]
    # The created event names the reporter, so its actor goes too.
    (clear,) = session.statements
    sql = str(clear.compile(compile_kwargs={"literal_binds": True}))
    assert sql.startswith("UPDATE ticket_event SET actor_id")
    assert "kind = 'created'" in sql
    assert ticket.reporter_principal_id is None
    assert ticket.reporter_email is None
    assert ticket.context == {}
    assert ticket.anonymized_at is not None


def test_the_service_builds_its_own_files_service() -> None:
    service = TicketService(ScriptedSession())  # type: ignore[arg-type]
    assert service.files is not None
    assert service.todos is None
