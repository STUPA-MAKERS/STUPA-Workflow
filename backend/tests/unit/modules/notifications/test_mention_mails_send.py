"""``send_comment_mentions`` and ``send_ticket_mentions`` with a fake session (no database).

The fake answers ``get`` by model and id and ``scalar``/``execute`` from queues in the
order of the queries. ``NotificationService`` and ``FilesService`` are fakes that record
the mails and the file reads.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.applications.models import Comment
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications import mentions as mails
from app.modules.tickets.models import Ticket, TicketNote
from app.settings import load_settings

SETTINGS = load_settings()
ME, ADA, BOB, EVE = (uuid.UUID(int=n) for n in (1, 2, 3, 4))
APP = uuid.UUID(int=10)
MSG = uuid.UUID(int=20)
TICKET = uuid.UUID(int=30)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    def __init__(self, *, scalar: list[Any] | None = None, execute: list[Any] | None = None):
        self.objs: dict[tuple[type, uuid.UUID], Any] = {}
        self.scalar_q = list(scalar or [])
        self.execute_q = list(execute or [])

    async def get(self, model: type, ident: uuid.UUID) -> Any:
        return self.objs.get((model, ident))

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalar_q.pop(0)

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self.execute_q.pop(0))


class _Mail:
    sent: list[dict[str, Any]]
    refuse: set[str]

    def __init__(self, _session: Any, *, queue: Any, settings: Any) -> None:
        del queue, settings

    async def send_kind_mail(self, to: list[str], **kw: Any) -> bool:
        _Mail.sent.append({"to": to, **kw})
        return to[0] not in _Mail.refuse


class _Files:
    names: dict[uuid.UUID, list[str]]
    asked: list[tuple[str, list[uuid.UUID]]]

    def __init__(self, _session: Any) -> None:
        pass

    async def message_attachments(self, owner: str, ids: list[uuid.UUID]) -> dict[Any, Any]:
        _Files.asked.append((owner, ids))
        return {
            i: [SimpleNamespace(filename=n) for n in _Files.names[i]]
            for i in ids
            if i in _Files.names
        }


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh mail and files fakes for each test."""
    _Mail.sent = []
    _Mail.refuse = set()
    _Files.names = {}
    _Files.asked = []
    monkeypatch.setattr(mails, "NotificationService", _Mail)
    monkeypatch.setattr(mails, "FilesService", _Files)


def _person(pid: uuid.UUID, name: str | None, email: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=pid, display_name=name, email=email)


def _comment(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": MSG,
        "application_id": APP,
        "mentions": [str(ADA), str(BOB), str(ME), "kein-uuid"],
        "body": "Bitte prüfen",
        "author_kind": "principal",
        "author": "author-sub",
    }
    base.update(kw)
    return SimpleNamespace(**base)


async def test_comment_mentions_skip_a_missing_comment_and_an_empty_list() -> None:
    session = _Session()
    assert (
        await mails.send_comment_mentions(
            session,  # type: ignore[arg-type]
            queue=None,
            settings=SETTINGS,
            comment_id=MSG,
            recipients=[ADA],
            actor_sub="me",
        )
        == 0
    )
    session.objs[(Comment, MSG)] = _comment()
    assert (
        await mails.send_comment_mentions(
            session,  # type: ignore[arg-type]
            queue=None,
            settings=SETTINGS,
            comment_id=MSG,
            recipients=[],
            actor_sub="me",
        )
        == 0
    )
    assert _Mail.sent == []


async def test_comment_mentions_mail_each_mentioned_address_but_the_actor() -> None:
    session = _Session(
        scalar=[
            _person(ME, "Moritz"),
            {"title": "  Sommerfest "},
            _person(EVE, "Eva Lang"),
        ],
        execute=[[(ADA, "ada@example.org"), (BOB, "bob@example.org"), (EVE, None)]],
    )
    session.objs[(Comment, MSG)] = _comment()
    _Mail.refuse = {"bob@example.org"}
    sent = await mails.send_comment_mentions(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        comment_id=MSG,
        recipients=[ADA, BOB, ME, EVE, ADA],
        actor_sub="me",
    )
    assert sent == 1
    assert [m["to"] for m in _Mail.sent] == [["ada@example.org"], ["bob@example.org"]]
    first = _Mail.sent[0]
    assert first["kind"] == "mention" and first["template_key"] == "comment_mentioned"
    assert first["idempotency_parts"] == ("comment_mentioned", str(MSG), str(ADA))
    assert first["context"] == {
        "actor": "Moritz",
        "applicationId": str(APP),
        "applicationTitle": "Sommerfest",
        "comment": "Bitte prüfen",
        "commentAuthor": "Eva Lang",
        "commentAuthorInitials": "EL",
    }
    assert _Files.asked == [("comment", [MSG])]


async def test_comment_mentions_of_an_applicant_comment_use_the_fallback_author() -> None:
    session = _Session(
        scalar=[None, None],
        execute=[[(ADA, "ada@example.org")]],
    )
    session.objs[(Comment, MSG)] = _comment(author_kind="applicant", author=None, body="")
    _Files.names[MSG] = ["beleg.pdf"]
    sent = await mails.send_comment_mentions(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        comment_id=MSG,
        recipients=[ADA],
        actor_sub="gone",
    )
    assert sent == 1
    context = _Mail.sent[0]["context"]
    assert context["actor"] == ""
    assert context["applicationTitle"] == ""
    assert "beleg.pdf" in context["comment"]
    assert context["commentAuthor"]


async def test_comment_mentions_without_an_address_send_nothing() -> None:
    session = _Session(scalar=[_person(ME, "Moritz")], execute=[[]])
    session.objs[(Comment, MSG)] = _comment()
    sent = await mails.send_comment_mentions(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        comment_id=MSG,
        recipients=[ADA],
        actor_sub="me",
    )
    assert sent == 0 and _Mail.sent == []
    session = _Session(scalar=[_person(ME, "Moritz")])
    session.objs[(Comment, MSG)] = _comment()
    assert (
        await mails.send_comment_mentions(
            session,  # type: ignore[arg-type]
            queue=None,
            settings=SETTINGS,
            comment_id=MSG,
            recipients=[ME],
            actor_sub="me",
        )
        == 0
    )


def _note(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": MSG,
        "ticket_id": TICKET,
        "mentions": [str(ADA), str(BOB)],
        "author_id": ME,
        "body": "Schau mal",
        "deleted_at": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


async def _ticket_send(session: _Session, recipients: list[uuid.UUID]) -> int:
    return await mails.send_ticket_mentions(
        session,  # type: ignore[arg-type]
        queue=None,
        settings=SETTINGS,
        note_id=MSG,
        recipients=recipients,
    )


async def test_ticket_mentions_skip_missing_deleted_or_orphan_notes() -> None:
    session = _Session()
    assert await _ticket_send(session, [ADA]) == 0
    session.objs[(TicketNote, MSG)] = _note(deleted_at=object())
    assert await _ticket_send(session, [ADA]) == 0
    session.objs[(TicketNote, MSG)] = _note()
    assert await _ticket_send(session, []) == 0
    assert await _ticket_send(session, [ADA]) == 0
    session.objs[(Ticket, TICKET)] = SimpleNamespace(id=TICKET, number=42, title="Drucker")
    assert await _ticket_send(session, [EVE]) == 0
    assert _Mail.sent == []


async def test_ticket_mentions_mail_the_mentioned_holders() -> None:
    session = _Session(execute=[[(ADA, "ada@example.org")]])
    session.objs[(TicketNote, MSG)] = _note()
    session.objs[(Ticket, TICKET)] = SimpleNamespace(id=TICKET, number=42, title="Drucker")
    session.objs[(PrincipalRow, ME)] = _person(ME, None, "moritz@example.org")
    assert await _ticket_send(session, [ADA, BOB]) == 1
    (mail,) = _Mail.sent
    assert mail["template_key"] == "ticket_mentioned"
    assert mail["context"] == {
        "actor": "moritz@example.org",
        "number": mails.format_number(42),
        "title": "Drucker",
        "message": "Schau mal",
        "author": "moritz@example.org",
        "authorInitials": mail["context"]["authorInitials"],
    }
    assert _Files.asked == []


async def test_ticket_mentions_of_a_files_only_note_name_the_files() -> None:
    session = _Session(execute=[[(ADA, "ada@example.org")]])
    session.objs[(TicketNote, MSG)] = _note(body="  ", author_id=None)
    session.objs[(Ticket, TICKET)] = SimpleNamespace(id=TICKET, number=7, title="Licht")
    _Files.names[MSG] = ["foto.jpg"]
    assert await _ticket_send(session, [ADA]) == 1
    context = _Mail.sent[0]["context"]
    assert context["actor"] == "" and "foto.jpg" in context["message"]
    assert _Files.asked == [("ticket_note", [MSG])]
