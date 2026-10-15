"""Unit tests of the two ticket mails (``ticket_created``, ``ticket_received``)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.admin.branding import Branding, HelpSettings, TicketSettings
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.notifications import tickets as mails
from app.modules.notifications.kinds import NOTIFICATION_KINDS
from app.modules.notifications.layout import _REASONS
from app.modules.notifications.templates_catalogue import CATALOGUE_BY_KEY
from app.modules.tickets.models import Ticket
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
    assert "ticket_created" in NOTIFICATION_KINDS
    assert "ticket_received" not in NOTIFICATION_KINDS
    assert {"ticket_created", "ticket_received"} <= set(_REASONS)
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
    account = PrincipalRow(id=uuid.uuid4(), sub="s", email="acc@x.org", display_name="Ada")
    nameless = PrincipalRow(id=uuid.uuid4(), sub="t", email="n@x.org", display_name=None)
    managers.append((uuid.uuid4(), "M", "m@x.org"))
    for row, expected in ((account, "Ada"), (nameless, "n@x.org")):
        ticket = _ticket(reporter_principal_id=row.id, reporter_email=None)
        session = ScriptedSession(scalar=[row.email])
        session.put(ticket, row)
        assert await _created(session, ticket.id) is True
        assert sent[-1]["context"]["reporter"] == expected
    # An account row that is gone leaves the address, else nothing.
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
    branding["value"] = Branding(help=HelpSettings(wikiUrl="https://wiki.example.org/b"))
    for context, lang in (({"language": "en"}, "en"), ({"language": "fr"}, "de"), (None, "de")):
        ticket = _ticket(context=context)
        session = ScriptedSession()
        session.put(ticket)
        assert await _received(session, ticket.id) is True
        assert sent[-1]["lang"] == lang
        assert sent[-1]["to"] == ["gast@x.org"]
        assert sent[-1]["context"]["wikiUrl"] == "https://wiki.example.org/b"
        assert "link" not in sent[-1]


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
