"""Unit tests of the ticket mails.

The mails are ``ticket_created``, ``ticket_received``, ``ticket_message`` and ``ticket_answer``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.admin.branding import Branding, HelpSettings, TicketSettings
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.notifications import tickets as mails
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.layout import _REASONS
from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY
from app.modules.tickets.models import Ticket, TicketNote
from app.settings import load_settings
from tests.unit.modules.tickets.fakes import ScriptedSession

SETTINGS = load_settings()
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": 5,
        "kind": "question",
        "title": "Wie?",
        "body": "b",
        "status": "new",
        "reporter_principal_id": None,
        "reporter_email": "gast@x.org",
        "context": {},
    }
    base.update(kw)
    return Ticket(**base)


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

    monkeypatch.setattr(mails, "NotificationService", _Service)
    return out


@pytest.fixture
def branding(monkeypatch: pytest.MonkeyPatch) -> dict[str, Branding]:
    box = {"value": Branding()}

    async def _active(_session: object) -> Branding:
        return box["value"]

    monkeypatch.setattr(mails, "active_branding", _active)
    return box


@pytest.fixture
def managers(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, str | None, str | None]]:
    rows: list[tuple[uuid.UUID, str | None, str | None]] = []

    async def _managers(_session: object) -> list[tuple[uuid.UUID, str | None, str | None]]:
        return rows

    monkeypatch.setattr(mails, "ticket_managers", _managers)
    return rows


async def _created(session: ScriptedSession, ticket_id: uuid.UUID) -> bool:
    return await mails.notify_ticket_created(
        queue=None,
        settings=SETTINGS,
        ticket_id=ticket_id,
        sessionmaker=_Maker(session),  # type: ignore[arg-type]
    )


async def _received(session: ScriptedSession, ticket_id: uuid.UUID) -> bool:
    return await mails.notify_ticket_received(
        queue=None,
        settings=SETTINGS,
        ticket_id=ticket_id,
        sessionmaker=_Maker(session),  # type: ignore[arg-type]
    )


def test_the_kinds_and_templates_are_registered() -> None:
    assert {"ticket_created", "ticket_message", "ticket_answer"} <= set(NOTIFICATION_KINDS)
    assert "ticket_received" not in NOTIFICATION_KINDS
    keys = {"ticket_created", "ticket_received", "ticket_message", "ticket_answer"}
    assert keys <= set(_REASONS)
    for key in keys:
        assert set(CATALOGUE_BY_KEY[key].body_i18n) == {"de", "en"}
    assert CATALOGUE_BY_KEY["ticket_created"].subject_i18n["en"].startswith("New ticket")
    assert set(CATALOGUE_BY_KEY["ticket_received"].body_i18n) == {"de", "en"}


async def test_created_goes_to_the_managers_without_the_reporter(
    sent: list[dict[str, Any]],
    branding: dict[str, Branding],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    ticket = _ticket()
    managers.extend(
        [
            (uuid.uuid4(), "B", "b@x.org"),
            (uuid.uuid4(), "A", "a@x.org"),
            (uuid.uuid4(), "R", "GAST@x.org"),
            (uuid.uuid4(), "N", None),
        ]
    )
    session = ScriptedSession()
    session.put(ticket)
    assert await _created(session, ticket.id) is True
    (mail,) = sent
    assert mail["to"] == ["a@x.org", "b@x.org"]
    assert mail["kind"] == "ticket_created"
    assert mail["context"]["number"] == "T-0005"
    assert mail["context"]["reporter"] == "gast@x.org"
    assert mail["link"].url.endswith(f"/tickets/{ticket.id}")


async def test_created_names_the_account_of_the_reporter(
    sent: list[dict[str, Any]],
    branding: dict[str, Branding],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    """Name the account of the reporter in the mail to the team.

    An account row that is gone leaves the address, else nothing.
    """
    account = PrincipalRow(id=uuid.uuid4(), sub="s", email="acc@x.org", display_name="Ada")
    nameless = PrincipalRow(id=uuid.uuid4(), sub="t", email="n@x.org", display_name=None)
    managers.append((uuid.uuid4(), "M", "m@x.org"))
    for row, expected in ((account, "Ada"), (nameless, "n@x.org")):
        ticket = _ticket(reporter_principal_id=row.id, reporter_email=None)
        session = ScriptedSession(scalar=[row.email])
        session.put(ticket, row)
        assert await _created(session, ticket.id) is True
        assert sent[-1]["context"]["reporter"] == expected
    ticket = _ticket(reporter_principal_id=uuid.uuid4(), reporter_email=None)
    session = ScriptedSession(scalar=[None])
    session.put(ticket)
    assert await _created(session, ticket.id) is True
    assert sent[-1]["context"]["reporter"] == ""


async def test_created_skips_without_ticket_switch_or_recipients(
    sent: list[dict[str, Any]],
    branding: dict[str, Branding],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    assert await _created(ScriptedSession(), uuid.uuid4()) is False
    ticket = _ticket()
    session = ScriptedSession()
    session.put(ticket)
    assert await _created(session, ticket.id) is False
    branding["value"] = Branding(tickets=TicketSettings(notifyNew=False))
    managers.append((uuid.uuid4(), "M", "m@x.org"))
    assert await _created(session, ticket.id) is False
    assert sent == []


async def test_created_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(_session: object) -> Branding:
        raise RuntimeError("db down")

    monkeypatch.setattr(mails, "active_branding", _boom)
    assert await _created(ScriptedSession(), uuid.uuid4()) is False


async def test_received_confirms_in_the_language_of_the_report(
    sent: list[dict[str, Any]], branding: dict[str, Branding]
) -> None:
    """Confirm the report in its own language.

    A report without a session stays one-way, so the mail has no link.
    """
    branding["value"] = Branding(help=HelpSettings(wikiUrl="https://wiki.example.org/b"))
    for context, lang in (({"language": "en"}, "en"), ({"language": "fr"}, "de"), (None, "de")):
        ticket = _ticket(context=context)
        session = ScriptedSession()
        session.put(ticket)
        assert await _received(session, ticket.id) is True
        assert sent[-1]["lang"] == lang
        assert sent[-1]["to"] == ["gast@x.org"]
        assert sent[-1]["context"]["wikiUrl"] == "https://wiki.example.org/b"
        assert sent[-1]["link"] is None


async def test_received_leaves_out_the_title_of_a_report_without_a_session(
    sent: list[dict[str, Any]], branding: dict[str, Branding]
) -> None:
    """Leave out the title of a report without a session.

    An account reads the ticket again in the tab, so its mail links the ticket.
    """
    from jinja2.sandbox import SandboxedEnvironment

    guest = _ticket(title="Klick hier: https://evil.example")
    session = ScriptedSession()
    session.put(guest)
    assert await _received(session, guest.id) is True
    assert sent[-1]["context"]["title"] == ""
    member = _ticket(reporter_principal_id=uuid.uuid4(), reporter_email=None)
    session = ScriptedSession(scalar=["m@x.org"])
    session.put(member)
    assert await _received(session, member.id) is True
    assert sent[-1]["to"] == ["m@x.org"]
    assert sent[-1]["context"]["title"] == "Wie?"
    assert sent[-1]["link"].url.endswith(f"/tickets/{member.id}")
    env = SandboxedEnvironment()
    for lang, quoted, tab in (("de", "„Wie?“", "„Tickets“"), ("en", '"Wie?"', '"Tickets"')):
        body = env.from_string(mails.TICKET_RECEIVED_BODY[lang])
        linked = body.render(title="Wie?", number="T-0005", wikiUrl="w", link="L")
        assert quoted in linked
        assert tab in linked
        bare = body.render(title="", number="T-0005", wikiUrl="w", link="")
        assert "„" not in bare
        assert '"' not in bare
        assert "T-0005" in bare


async def test_received_skips_without_ticket_or_address(
    sent: list[dict[str, Any]], branding: dict[str, Branding]
) -> None:
    assert await _received(ScriptedSession(), uuid.uuid4()) is False
    ticket = _ticket(reporter_principal_id=uuid.uuid4(), reporter_email=None)
    session = ScriptedSession(scalar=[None])
    session.put(ticket)
    assert await _received(session, ticket.id) is False
    assert sent == []


async def test_received_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken(ScriptedSession):
        async def get(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("db down")

    assert await _received(_Broken(), uuid.uuid4()) is False


def test_the_default_sessionmaker_is_the_app_one(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(mails, "get_sessionmaker", lambda: sentinel)
    assert mails._maker(None) is sentinel


REPORTER = uuid.uuid4()
STAFF = uuid.uuid4()


def _note(ticket: Ticket, author: uuid.UUID | None, **kw: Any) -> TicketNote:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ticket_id": ticket.id,
        "author_id": author,
        "body": "Danke!",
        "visibility": "public",
        "deleted_at": None,
        "created_at": NOW,
    }
    base.update(kw)
    return TicketNote(**base)


def _account_ticket(**kw: Any) -> Ticket:
    return _ticket(reporter_principal_id=REPORTER, reporter_email=None, anonymized_at=None, **kw)


def _reporter(**kw: Any) -> PrincipalRow:
    base: dict[str, Any] = {
        "id": REPORTER,
        "sub": "r",
        "email": "rex@x.org",
        "display_name": "Rex",
        "active": True,
        "merged_into": None,
    }
    base.update(kw)
    return PrincipalRow(**base)


async def _note_mail(session: ScriptedSession, note_id: uuid.UUID) -> bool:
    return await mails.notify_ticket_note(
        queue=None,
        settings=SETTINGS,
        note_id=note_id,
        sessionmaker=_Maker(session),  # type: ignore[arg-type]
    )


async def test_a_message_of_the_reporter_goes_to_the_assignee(
    sent: list[dict[str, Any]],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    ticket = _account_ticket(assignee_id=STAFF)
    note = _note(ticket, REPORTER)
    reporter = PrincipalRow(id=REPORTER, sub="r", email="rex@x.org", display_name="Rex")
    managers.extend([(STAFF, "Mia", "mia@x.org"), (uuid.uuid4(), "Bo", "bo@x.org")])
    session = ScriptedSession()
    session.put(ticket, note, reporter)
    assert await _note_mail(session, note.id) is True
    (mail,) = sent
    assert mail["to"] == ["mia@x.org"]
    assert mail["kind"] == "ticket_message"
    assert mail["context"] == {
        "number": "T-0005",
        "title": "Wie?",
        "reporter": "Rex",
        "message": "Danke!",
    }
    assert mail["idempotency_parts"] == ("ticket_message", str(note.id))
    assert mail["link"].url.endswith(f"/tickets/{ticket.id}")


async def test_a_message_without_an_assignee_goes_to_every_holder(
    sent: list[dict[str, Any]],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Send a message to every holder of ``ticket.manage`` when no assignee can read it.

    The assignee lost ``ticket.manage``, so the whole team gets the mail. The reporter never
    gets the own message, even as a holder. A message of files only names its files.
    """
    ticket = _account_ticket(assignee_id=uuid.uuid4())
    note = _note(ticket, REPORTER, body="  ")
    reporter = PrincipalRow(id=REPORTER, sub="r", email="REX@x.org", display_name=None)
    managers.extend(
        [(STAFF, "Mia", "mia@x.org"), (REPORTER, "Rex", "rex@x.org"), (uuid.uuid4(), "N", None)]
    )
    shot = MessageAttachmentOut(
        id=uuid.uuid4(), filename="screen.png", mime="image/png", size=3, scan_state="clean"
    )
    session = ScriptedSession()
    session.put(ticket, note, reporter)

    class _Files:
        def __init__(self, _session: object) -> None:
            pass

        async def message_attachments(
            self, owner: str, ids: list[uuid.UUID]
        ) -> dict[uuid.UUID, list[MessageAttachmentOut]]:
            assert owner == "ticket_note"
            return {ids[0]: [shot, shot]}

    monkeypatch.setattr(mails, "FilesService", _Files)
    assert await _note_mail(session, note.id) is True
    (mail,) = sent
    assert mail["to"] == ["mia@x.org"]
    assert mail["context"]["reporter"] == "REX@x.org"
    assert mail["context"]["message"] == "screen.png, screen.png"


async def test_a_message_of_the_reporter_without_recipients_sends_nothing(
    sent: list[dict[str, Any]],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    ticket = _account_ticket()
    note = _note(ticket, REPORTER)
    session = ScriptedSession()
    session.put(ticket, note)
    assert await _note_mail(session, note.id) is False
    managers.append((uuid.uuid4(), "Rex", None))
    assert await _note_mail(session, note.id) is False
    assert sent == []


async def test_a_public_answer_of_the_team_goes_to_the_reporter(
    sent: list[dict[str, Any]],
) -> None:
    """Send a public answer of the team to the reporter.

    The mail holds the name of the team member only, because the e-mail of a team member
    must never reach the reporter.
    """
    ticket = _account_ticket(context={"language": "en"})
    note = _note(ticket, STAFF, body="Oben rechts.")
    staff = PrincipalRow(id=STAFF, sub="s", email="mia@x.org", display_name="Mia")
    session = ScriptedSession()
    session.put(ticket, note, staff, _reporter())
    assert await _note_mail(session, note.id) is True
    (mail,) = sent
    assert mail["to"] == ["rex@x.org"]
    assert mail["kind"] == "ticket_answer"
    assert mail["lang"] == "en"
    assert mail["context"] == {
        "number": "T-0005",
        "title": "Wie?",
        "author": "Mia",
        "message": "Oben rechts.",
    }
    assert mail["idempotency_parts"] == ("ticket_answer", str(note.id))
    assert mail["link"].url.endswith(f"/tickets/{ticket.id}")


async def test_an_answer_of_a_nameless_or_gone_author_has_no_name(
    sent: list[dict[str, Any]],
) -> None:
    ticket = _account_ticket(context={"language": "fr"})
    nameless = PrincipalRow(id=STAFF, sub="s", email="mia@x.org", display_name=None)
    for author, row in ((STAFF, nameless), (None, None), (uuid.uuid4(), None)):
        note = _note(ticket, author)
        session = ScriptedSession()
        session.put(ticket, note, _reporter(), *([row] if row is not None else []))
        assert await _note_mail(session, note.id) is True
        assert sent[-1]["context"]["author"] == ""
        assert sent[-1]["lang"] == "de"


@pytest.mark.parametrize(
    "reporter",
    [
        None,
        {"email": None},
        {"active": False},
        {"merged_into": uuid.uuid4()},
    ],
)
async def test_an_answer_without_a_live_reporter_account_sends_nothing(
    sent: list[dict[str, Any]], reporter: dict[str, Any] | None
) -> None:
    """Send nothing when the reporter account is not live.

    A deactivated or merged account cannot open the link, so it gets no mail.
    """
    ticket = _account_ticket()
    note = _note(ticket, STAFF)
    session = ScriptedSession()
    session.put(ticket, note, *([_reporter(**reporter)] if reporter is not None else []))
    assert await _note_mail(session, note.id) is False
    assert sent == []


async def test_a_message_without_text_or_files_sends_nothing(
    sent: list[dict[str, Any]],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    managers.append((STAFF, "Mia", "mia@x.org"))
    ticket = _account_ticket()
    note = _note(ticket, REPORTER, body=" ")
    session = ScriptedSession(scalars=[[]])
    session.put(ticket, note, _reporter())
    assert await _note_mail(session, note.id) is False
    assert sent == []


async def test_an_assignee_without_an_address_falls_back_to_the_team(
    sent: list[dict[str, Any]],
    managers: list[tuple[uuid.UUID, str | None, str | None]],
) -> None:
    ticket = _account_ticket(assignee_id=STAFF)
    note = _note(ticket, REPORTER)
    managers.extend([(STAFF, "Mia", None), (uuid.uuid4(), "Bo", "bo@x.org")])
    session = ScriptedSession()
    session.put(ticket, note, _reporter())
    assert await _note_mail(session, note.id) is True
    assert sent[-1]["to"] == ["bo@x.org"]


@pytest.mark.parametrize(
    ("note_kw", "ticket_kw"),
    [
        ({"visibility": "internal"}, {}),
        ({"deleted_at": NOW}, {}),
        ({}, {"anonymized_at": NOW}),
        ({}, {"reporter_principal_id": None, "reporter_email": "gast@x.org"}),
    ],
)
async def test_no_mail_for_an_internal_deleted_anonymized_or_guest_note(
    sent: list[dict[str, Any]], note_kw: dict[str, Any], ticket_kw: dict[str, Any]
) -> None:
    ticket = _ticket(**{"reporter_principal_id": REPORTER, "reporter_email": None, **ticket_kw})
    note = _note(ticket, STAFF, **note_kw)
    session = ScriptedSession(scalar=["rex@x.org"])
    session.put(ticket, note)
    assert await _note_mail(session, note.id) is False
    assert sent == []


async def test_no_mail_without_the_note_or_the_ticket(sent: list[dict[str, Any]]) -> None:
    assert await _note_mail(ScriptedSession(), uuid.uuid4()) is False
    orphan = _note(_ticket(), STAFF)
    session = ScriptedSession()
    session.put(orphan)
    assert await _note_mail(session, orphan.id) is False
    assert sent == []


async def test_the_note_mail_never_raises() -> None:
    class _Broken(ScriptedSession):
        async def get(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("db down")

    assert await _note_mail(_Broken(), uuid.uuid4()) is False
