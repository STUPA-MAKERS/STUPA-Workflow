"""Unit tests of the status ``waiting``, the late answer, the source and the manual ticket.

They cover the specs 002708 to 002713 and 002718 with the scripted session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.tickets import mails
from app.modules.tickets.areas import TicketAreaService
from app.modules.tickets.models import (
    PLATFORM_AREA_ID,
    REOPEN_DAYS,
    Ticket,
    TicketArea,
    TicketCategory,
    TicketEvent,
    TicketNote,
)
from app.modules.tickets.schemas import (
    ReporterNoteCreate,
    TicketCreate,
    TicketManualCreate,
    TicketPatch,
)
from app.modules.tickets.service import TicketService
from app.settings import load_settings
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from tests.unit.modules.tickets.fakes import FakeFiles, ScriptedSession

ME = uuid.uuid4()
STAFF = uuid.uuid4()
REPORTER = Principal(sub="reporter-sub")
WORKER = Principal(sub="worker", permissions={"ticket.manage"})
NOW = datetime(2026, 10, 1, tzinfo=UTC)
SETTINGS = load_settings()


def _svc(session: ScriptedSession) -> TicketService:
    return TicketService(session, files=FakeFiles())  # type: ignore[arg-type]


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": "AAAA0007",
        "area_id": PLATFORM_AREA_ID,
        "category_id": None,
        "kind": "bug",
        "source": "help",
        "title": "Fehler",
        "body": "Text",
        "status": "in_progress",
        "reporter_principal_id": ME,
        "reporter_email": None,
        "assignee_id": None,
        "duplicate_of_id": None,
        "follow_up_of_id": None,
        "context": {"language": "en"},
        "closed_at": None,
        "anonymized_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Ticket(**{**base, **kw})


def _area(**kw: Any) -> TicketArea:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Finanzen",
        "gremium_id": None,
        "platform": False,
        "notify_new": True,
        "in_app": False,
    }
    return TicketArea(**{**base, **kw})


def _person(**kw: Any) -> PrincipalRow:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "sub": "p",
        "email": "p@x.org",
        "display_name": "Pia",
        "active": True,
        "merged_into": None,
    }
    return PrincipalRow(**{**base, **kw})


def _message(body: str = "noch da") -> ReporterNoteCreate:
    return ReporterNoteCreate.model_validate({"body": body})


def _status_events(session: ScriptedSession) -> list[TicketEvent]:
    return [o for o in session.added if isinstance(o, TicketEvent) and o.kind == "status"]


# ------------------------------------------------------------------ 002708 / 002709


async def test_waiting_is_an_open_status_without_a_close_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _detail(_self: object, _ticket_id: uuid.UUID, _p: Principal) -> str:
        return "detail"

    monkeypatch.setattr(TicketService, "detail", _detail)
    ticket = _ticket(status="in_progress")
    session = ScriptedSession(scalar=[STAFF])
    session.put(ticket)
    await _svc(session).patch(ticket.id, TicketPatch.model_validate({"status": "waiting"}), WORKER)
    assert ticket.status == "waiting"
    assert ticket.closed_at is None
    (event,) = _status_events(session)
    assert event.payload == {"from": "in_progress", "to": "waiting"}
    assert event.actor_id == STAFF


@pytest.mark.parametrize("status", ["waiting", "done", "rejected"])
async def test_a_message_of_the_sender_sets_in_progress_without_an_actor(status: str) -> None:
    closed = None if status == "waiting" else datetime.now(UTC) - timedelta(days=REOPEN_DAYS - 1)
    ticket = _ticket(status=status, closed_at=closed)
    session = ScriptedSession(scalar=[ME, None], execute=[[(ME, "Me", None)]])
    session.put(ticket)
    await _svc(session).reporter_add_note(ticket.id, _message(), REPORTER, pepper="p")
    assert ticket.status == "in_progress"
    assert ticket.closed_at is None
    (event,) = _status_events(session)
    assert event.actor_id is None
    assert event.payload == {"from": status, "to": "in_progress"}


async def test_a_message_on_a_ticket_in_work_writes_no_status_event() -> None:
    ticket = _ticket(status="new")
    session = ScriptedSession(scalar=[ME, None], execute=[[(ME, "Me", None)]])
    session.put(ticket)
    await _svc(session).reporter_add_note(ticket.id, _message(), REPORTER, pepper="p")
    assert ticket.status == "new"
    assert _status_events(session) == []


# ------------------------------------------------------------------ 002710


@pytest.mark.parametrize(
    ("status", "days"),
    [("done", REOPEN_DAYS - 1), ("waiting", REOPEN_DAYS + 30), ("in_progress", 0)],
)
async def test_an_answer_in_time_or_on_an_open_ticket_is_no_follow_up(
    status: str, days: int
) -> None:
    closed = datetime.now(UTC) - timedelta(days=days) if status == "done" else None
    ticket = _ticket(status=status, closed_at=closed)
    session = ScriptedSession(scalar=[ME])
    session.put(ticket)
    out = await _svc(session).reporter_follow_up(ticket.id, _message(), REPORTER, pepper="p")
    assert out is None
    assert session.added == []


async def test_a_late_answer_opens_a_follow_up_ticket_in_the_same_bereich() -> None:
    area, category = uuid.uuid4(), uuid.uuid4()
    old = _ticket(
        status="done",
        kind=None,
        area_id=area,
        category_id=category,
        closed_at=datetime.now(UTC) - timedelta(days=REOPEN_DAYS + 1),
    )
    session = ScriptedSession(scalar=[ME, None, None, "me@x.org"])
    session.put(old)
    new = await _svc(session).reporter_follow_up(
        ticket_id=old.id, payload=_message("wieder"), principal=REPORTER, pepper="p"
    )
    assert new is not None
    assert new.id != old.id
    assert new.follow_up_of_id == old.id
    assert (new.area_id, new.category_id, new.kind) == (area, category, None)
    assert (new.title, new.body, new.status, new.source) == ("Fehler", "wieder", "new", "help")
    assert new.reporter_principal_id == ME
    assert new.context == {"language": "en"}
    assert old.status == "done"
    (event,) = [o for o in session.added if isinstance(o, TicketEvent)]
    assert event.ticket_id == new.id
    assert event.payload == {"confirmationSent": True, "followUpOf": "T-AAAA0007"}
    assert session.committed == 0


async def test_a_late_answer_binds_its_files_to_the_new_ticket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.tickets import service as svc_mod

    bound: list[dict[str, Any]] = []

    async def _check(_s: object, **_kw: Any) -> str:
        return "tok"

    async def _bind(_s: object, **kw: Any) -> None:
        bound.append(kw)

    monkeypatch.setattr(svc_mod, "check_message_drafts", _check)
    monkeypatch.setattr(svc_mod, "bind_drafts", _bind)
    old = _ticket(status="rejected", context={}, closed_at=datetime.now(UTC) - timedelta(days=40))
    session = ScriptedSession(scalar=[ME, None, None, None])
    session.put(old)
    draft = uuid.uuid4()
    payload = ReporterNoteCreate.model_validate(
        {"body": "", "attachmentIds": [str(draft)], "draftToken": "tok"}
    )
    new = await _svc(session).reporter_follow_up(old.id, payload, REPORTER, pepper="p")
    assert new is not None
    assert new.context == {}
    assert bound[0]["ticket_id"] == new.id
    assert bound[0]["attachment_ids"] == [draft]
    (event,) = [o for o in session.added if isinstance(o, TicketEvent)]
    assert event.payload["confirmationSent"] is False


async def test_a_blocked_sender_opens_no_follow_up() -> None:
    old = _ticket(status="done", closed_at=datetime.now(UTC) - timedelta(days=40))
    session = ScriptedSession(scalar=[ME, uuid.uuid4()])
    session.put(old)
    with pytest.raises(ForbiddenError) as exc:
        await _svc(session).reporter_follow_up(old.id, _message(), REPORTER, pepper="p")
    assert exc.value.code == "sender_blocked"
    assert session.added == []


async def test_the_view_of_the_sender_tells_that_an_answer_opens_a_new_ticket() -> None:
    late = _ticket(status="done", closed_at=datetime.now(UTC) - timedelta(days=40))
    session = ScriptedSession(scalar=[ME], scalars=[[], []])
    session.put(late)
    assert (await _svc(session).reporter_detail(late.id, REPORTER)).reply_opens_new is True
    fresh = _ticket(status="done", closed_at=datetime.now(UTC) - timedelta(days=1))
    session = ScriptedSession(scalar=[ME], scalars=[[], []])
    session.put(fresh)
    assert (await _svc(session).reporter_detail(fresh.id, REPORTER)).reply_opens_new is False


# ------------------------------------------------------------------ 002711 / 002712


def _manual(area: uuid.UUID = PLATFORM_AREA_ID, **kw: Any) -> TicketManualCreate:
    base: dict[str, Any] = {
        "areaId": str(area),
        "title": " Karte ",
        "body": "intern",
        "kind": "bug",
    }
    return TicketManualCreate.model_validate({**base, **kw})


async def test_a_report_of_the_help_menu_has_the_source_help() -> None:
    session = ScriptedSession()
    ticket = await _svc(session).create(
        TicketCreate.model_validate({"kind": "bug", "title": "T", "body": "b"}),
        reporter_id=None,
        email="a@x.org",
        pepper="p",
    )
    assert isinstance(ticket, Ticket)
    assert ticket.source == "help"


async def test_a_ticket_by_hand_has_the_source_team_and_a_first_message() -> None:
    person = _person()
    session = ScriptedSession(scalar=[STAFF])
    session.put(_area(id=PLATFORM_AREA_ID, platform=True), person)
    ticket, note = await _svc(session).create_manual(
        _manual(reporterId=str(person.id), message="Hallo"), WORKER
    )
    assert (ticket.source, ticket.status, ticket.title) == ("team", "new", "Karte")
    assert ticket.reporter_principal_id == person.id
    assert ticket.body == "intern"
    assert isinstance(note, TicketNote)
    assert (note.visibility, note.author_id, note.body) == ("public", STAFF, "Hallo")
    (event,) = [o for o in session.added if isinstance(o, TicketEvent)]
    assert (event.kind, event.actor_id) == ("created", STAFF)
    assert event.payload == {"confirmationSent": False}
    assert session.committed == 0


async def test_a_ticket_by_hand_without_a_message_has_no_note() -> None:
    person = _person()
    area = _area()
    category = TicketCategory(id=uuid.uuid4(), area_id=area.id, name="Erstattung", position=0)
    session = ScriptedSession(scalar=[STAFF])
    session.put(area, person, category)
    ticket, note = await _svc(session).create_manual(
        _manual(area.id, reporterId=str(person.id), kind=None, categoryId=str(category.id)),
        WORKER,
        areas=frozenset({area.id}),
    )
    assert note is None
    assert (ticket.area_id, ticket.category_id, ticket.kind) == (area.id, category.id, None)


async def test_the_sender_does_not_read_the_team_note_of_a_ticket_by_hand() -> None:
    ticket = _ticket(source="team", body="intern")
    session = ScriptedSession(scalar=[ME], scalars=[[], []])
    session.put(ticket)
    assert (await _svc(session).reporter_detail(ticket.id, REPORTER)).body == ""


async def test_a_ticket_by_hand_outside_the_own_bereiche_is_403() -> None:
    with pytest.raises(ForbiddenError):
        await _svc(ScriptedSession()).create_manual(
            _manual(reporterId=str(uuid.uuid4())), WORKER, areas=frozenset({uuid.uuid4()})
        )


async def test_a_ticket_by_hand_needs_an_account_of_the_caller() -> None:
    with pytest.raises(NotFoundError):
        await _svc(ScriptedSession()).create_manual(_manual(reporterId=str(uuid.uuid4())), WORKER)


async def test_a_ticket_by_hand_in_an_unknown_bereich_is_422() -> None:
    with pytest.raises(ValidationProblem) as exc:
        await _svc(ScriptedSession(scalar=[STAFF])).create_manual(
            _manual(uuid.uuid4(), reporterId=str(uuid.uuid4())), WORKER
        )
    assert exc.value.code == "area_invalid"


@pytest.mark.parametrize(
    ("extra", "code"),
    [
        ({}, "ticket_reporter_invalid"),
        ({"reporterId": str(uuid.uuid4()), "email": "a@x.org"}, "ticket_reporter_invalid"),
        ({"email": "a@x.org"}, "ticket_area_without_mailbox"),
        ({"reporterId": str(uuid.uuid4())}, "ticket_reporter_invalid"),
    ],
)
async def test_a_ticket_by_hand_names_one_known_account(extra: dict[str, Any], code: str) -> None:
    session = ScriptedSession(scalar=[STAFF])
    session.put(_area(id=PLATFORM_AREA_ID, platform=True))
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).create_manual(_manual(**extra), WORKER)
    assert exc.value.code == code
    assert session.added == []


@pytest.mark.parametrize("kw", [{"active": False}, {"merged_into": uuid.uuid4()}])
async def test_a_ticket_by_hand_for_an_inactive_or_merged_account_is_422(
    kw: dict[str, Any],
) -> None:
    person = _person(**kw)
    session = ScriptedSession(scalar=[STAFF])
    session.put(_area(id=PLATFORM_AREA_ID, platform=True), person)
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).create_manual(_manual(reporterId=str(person.id)), WORKER)
    assert exc.value.code == "ticket_reporter_invalid"


# ------------------------------------------------------------------ 002713


def _report(**kw: Any) -> TicketCreate:
    return TicketCreate.model_validate({"title": "T", "body": "b", **kw})


async def test_a_report_without_a_session_reaches_plattform_only() -> None:
    area = _area(in_app=True)
    session = ScriptedSession()
    session.put(area)
    with pytest.raises(ForbiddenError) as exc:
        await _svc(session).create(
            _report(areaId=str(area.id)), reporter_id=None, email="a@x.org", pepper="p"
        )
    assert exc.value.code == "ticket_area_needs_session"
    assert session.added == []


async def test_a_report_reaches_a_bereich_with_the_switch_only() -> None:
    closed, shown = _area(), _area(in_app=True)
    category = TicketCategory(id=uuid.uuid4(), area_id=shown.id, name="K", position=0)
    session = ScriptedSession()
    session.put(closed, shown, category)
    service = _svc(session)
    with pytest.raises(ForbiddenError) as exc:
        await service.create(_report(areaId=str(closed.id)), reporter_id=ME, email=None, pepper="p")
    assert exc.value.code == "ticket_area_not_reachable"
    with pytest.raises(ValidationProblem) as bad:
        await service.create(
            _report(areaId=str(uuid.uuid4())), reporter_id=ME, email=None, pepper="p"
        )
    assert bad.value.code == "area_invalid"
    ticket = await service.create(
        _report(areaId=str(shown.id), categoryId=str(category.id)),
        reporter_id=ME,
        email=None,
        pepper="p",
    )
    assert isinstance(ticket, Ticket)
    assert (ticket.area_id, ticket.category_id, ticket.kind) == (shown.id, category.id, None)
    assert ticket.source == "help"


async def test_a_report_checks_the_kind_and_the_kategorie_of_the_bereich() -> None:
    shown, other = _area(in_app=True), _area(name="Kultur")
    foreign = TicketCategory(id=uuid.uuid4(), area_id=other.id, name="K", position=0)
    session = ScriptedSession()
    session.put(shown, foreign)
    service = _svc(session)
    with pytest.raises(ValidationProblem) as no_kind:
        await service.create(_report(), reporter_id=ME, email=None, pepper="p")
    assert no_kind.value.errors is not None
    assert no_kind.value.errors[0].field == "kind"
    for bad in (
        {"areaId": str(shown.id), "kind": "bug"},
        {"areaId": str(shown.id), "categoryId": str(foreign.id)},
        {"areaId": str(shown.id), "categoryId": str(uuid.uuid4())},
    ):
        with pytest.raises(ValidationProblem) as exc:
            await service.create(_report(**bad), reporter_id=ME, email=None, pepper="p")
        assert exc.value.code == "category_invalid"
    assert session.added == []


async def test_the_choices_are_plattform_and_the_bereiche_with_the_switch() -> None:
    platform = _area(id=PLATFORM_AREA_ID, name="Plattform", platform=True)
    shown = _area(in_app=True)
    category = TicketCategory(id=uuid.uuid4(), area_id=shown.id, name="K", position=0)
    session = ScriptedSession(scalars=[[platform, shown], [category]])
    choices = await TicketAreaService(session).choices()  # type: ignore[arg-type]
    assert [(c.name, c.platform) for c in choices] == [("Plattform", True), ("Finanzen", False)]
    assert [c.name for c in choices[1].categories] == ["K"]
    assert "in_app" in str(session.statements[0])


# ------------------------------------------------------------------ 002718


class _Maker:
    def __init__(self, session: ScriptedSession) -> None:
        self.session = session

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> ScriptedSession:
        return self.session

    async def __aexit__(self, *_a: object) -> None:
        return None


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    class _Service:
        def __init__(self, _session: object, **_kw: object) -> None:
            pass

        async def send_kind_mail(self, recipients: list[str], **kw: Any) -> bool:
            out.append({"to": recipients, **kw})
            return True

    async def _workers(
        _session: object, _areas: object = None, **kw: Any
    ) -> list[tuple[uuid.UUID, str | None, str | None]]:
        return [(kw["principal_id"], "Mia", WORKER_MAIL["value"])]

    monkeypatch.setattr(mails, "NotificationService", _Service)
    monkeypatch.setattr(mails, "area_workers", _workers)
    return out


WORKER_MAIL: dict[str, str | None] = {"value": "mia@x.org"}


def _assigned(ticket: Ticket, actor: uuid.UUID | None, to: uuid.UUID | None) -> TicketEvent:
    return TicketEvent(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        kind="assignee",
        actor_id=actor,
        payload={"from": None, "to": str(to) if to else None},
        created_at=NOW,
    )


async def _assigned_mail(session: ScriptedSession, ticket_id: uuid.UUID) -> bool:
    return await mails.notify_ticket_assigned(
        queue=None,
        settings=SETTINGS,
        ticket_id=ticket_id,
        sessionmaker=_Maker(session),  # type: ignore[arg-type]
    )


async def test_an_assignment_by_another_person_mails_the_new_assignee(
    sent: list[dict[str, Any]],
) -> None:
    actor = _person(display_name="Bo")
    ticket = _ticket(assignee_id=STAFF)
    event = _assigned(ticket, actor.id, STAFF)
    session = ScriptedSession(scalar=[event])
    session.put(ticket, actor)
    assert await _assigned_mail(session, ticket.id) is True
    (mail,) = sent
    assert mail["to"] == ["mia@x.org"]
    assert mail["kind"] == "ticket_assigned"
    assert mail["context"] == {"number": "T-AAAA0007", "title": "Fehler", "actor": "Bo"}
    assert mail["idempotency_parts"] == ("ticket_assigned", str(event.id))
    assert mail["link"].url.endswith(f"/tickets/{ticket.id}")


async def test_an_assignment_without_a_known_actor_has_no_name(
    sent: list[dict[str, Any]],
) -> None:
    ticket = _ticket(assignee_id=STAFF)
    for actor in (None, uuid.uuid4()):
        session = ScriptedSession(scalar=[_assigned(ticket, actor, STAFF)])
        session.put(ticket)
        assert await _assigned_mail(session, ticket.id) is True
    assert [m["context"]["actor"] for m in sent] == ["", ""]


async def test_no_assigned_mail_for_the_own_take_over_or_a_stale_event(
    sent: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    ticket = _ticket(assignee_id=STAFF)
    free = _ticket(assignee_id=None)
    cases: list[tuple[Ticket | None, TicketEvent | None]] = [
        (ticket, _assigned(ticket, STAFF, STAFF)),
        (ticket, _assigned(ticket, ME, uuid.uuid4())),
        (ticket, None),
        (free, _assigned(free, ME, None)),
        (None, _assigned(ticket, ME, STAFF)),
    ]
    for row, event in cases:
        session = ScriptedSession(scalar=[event])
        if row is not None:
            session.put(row)
        assert await _assigned_mail(session, ticket.id if row is None else row.id) is False
    monkeypatch.setitem(WORKER_MAIL, "value", None)
    session = ScriptedSession(scalar=[_assigned(ticket, ME, STAFF)])
    session.put(ticket)
    assert await _assigned_mail(session, ticket.id) is False
    assert sent == []


async def test_the_assigned_mail_never_raises() -> None:
    assert await _assigned_mail(None, uuid.uuid4()) is False  # type: ignore[arg-type]
