"""``LinkViewer``: the read sheet of a link target (spec 000487)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.applications.models import Application
from app.modules.budget.tree_models import Invoice
from app.modules.meetings.models import MeetingAgendaItem
from app.modules.todos.link_view import LinkViewer
from app.modules.todos.links import Resolved
from app.modules.todos.schemas import TodoLinkDetail
from app.modules.voting.models import Vote
from app.shared.errors import NotFoundError
from tests.unit.modules.todos.fakes import USER, FakeLinks, ScriptedSession

TID = uuid.UUID(int=77)


def _viewer(session: ScriptedSession, kind: str, title: str | None = "Titel") -> LinkViewer:
    found = Resolved(accessible=True, title=title)
    return LinkViewer(session, FakeLinks(resolved={(kind, TID): found}))  # type: ignore[arg-type]


def _facts(view: Any) -> dict[str, tuple[str, str]]:
    return {f.key: (f.value, f.format) for f in view.facts}


async def test_a_kind_without_a_sheet_is_not_found() -> None:
    viewer = _viewer(ScriptedSession(), "ticket")
    for kind in ("ticket", "gremium"):
        with pytest.raises(NotFoundError):
            await viewer.view(kind, TID, USER)


async def test_a_hidden_target_is_not_found() -> None:
    viewer = LinkViewer(ScriptedSession(), FakeLinks())  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await viewer.view("vote", TID, USER)


def _field(key: str, type_: str, *, pii: bool = False) -> SimpleNamespace:
    return SimpleNamespace(key=key, type=type_, is_pii=pii, label_i18n={"de": key.upper()})


async def test_application_shows_plain_answers_without_pii() -> None:
    app = Application(
        id=TID,
        type_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(),
        amount=Decimal("120.00"),
        approved_amount=None,
        data={
            "title": "Sommerfest",
            "purpose": "Feier",
            "mail": "a@b.de",
            "secret": "x",
            "hidden": "y",
            "tags": ["a", "b"],
            "sum": 12.5,
            "nested": {"a": 1},
            "empty": "",
            "none": [],
            "when": "2026-07-01",
            "story": "**fett**",
        },
    )
    session = ScriptedSession(
        scalars=[
            ["hidden"],
            [
                _field("title", "text"),
                _field("purpose", "text"),
                _field("mail", "email"),
                _field("secret", "text", pii=True),
                _field("hidden", "text"),
                _field("tags", "multiselect"),
                _field("sum", "currency"),
                _field("nested", "select"),
                _field("empty", "text"),
                _field("none", "multiselect"),
                _field("when", "date"),
                _field("story", "textarea"),
                _field("missing", "number"),
            ],
        ]
    )
    session.put(app)
    view = await _viewer(session, "application").view("application", TID, USER)
    assert view.kind == "application"
    assert view.title == "Titel"
    assert view.detail == TodoLinkDetail()
    assert view.rows == []
    assert [f.key for f in view.facts] == ["amount", "purpose", "tags", "sum", "when", "story"]
    assert _facts(view) == {
        "amount": ("120.00", "money"),
        "purpose": ("Feier", "text"),
        "tags": ("a, b", "text"),
        "sum": ("12.5", "money"),
        "when": ("2026-07-01", "date"),
        "story": ("**fett**", "markdown"),
    }
    assert view.facts[1].label == {"de": "PURPOSE"}


async def test_application_with_an_approved_amount_and_no_data() -> None:
    app = Application(
        id=TID,
        type_id=uuid.uuid4(),
        form_version_id=uuid.uuid4(),
        amount=Decimal("50.00"),
        approved_amount=Decimal("40.00"),
        data=None,
    )
    session = ScriptedSession(scalars=[[], [SimpleNamespace(key="x", type="text", is_pii=False)]])
    session.put(app)
    view = await _viewer(session, "application", title=None).view("application", TID, USER)
    assert view.title == ""
    assert _facts(view) == {"amount": ("50.00", "money"), "approvedAmount": ("40.00", "money")}


async def test_meeting_shows_date_time_status_and_agenda() -> None:
    meeting = SimpleNamespace(
        id=uuid.uuid4(), date=date(2026, 7, 1), start_time=time(18, 30), status="planned"
    )
    items = [
        (SimpleNamespace(title="Begrüßung", done_at=datetime(2026, 7, 1, tzinfo=UTC)), None),
        (SimpleNamespace(title=None, done_at=None), {"title": "Antrag Fest"}),
        (SimpleNamespace(title="", done_at=None), None),
    ]
    session = ScriptedSession(execute=[[(meeting, "StuPa")], items])
    view = await _viewer(session, "meeting").view("meeting", TID, USER)
    assert _facts(view) == {
        "gremium": ("StuPa", "text"),
        "date": ("2026-07-01", "date"),
        "startTime": ("18:30", "text"),
        "meetingStatus": ("planned", "text"),
    }
    assert [(r.title, r.done) for r in view.rows] == [
        ("Begrüßung", True),
        ("Antrag Fest", False),
        ("", False),
    ]


async def test_meeting_without_start_time() -> None:
    meeting = SimpleNamespace(id=uuid.uuid4(), date=None, start_time=None, status="draft")
    session = ScriptedSession(execute=[[(meeting, "AStA")], []])
    view = await _viewer(session, "meeting").view("meeting", TID, USER)
    assert _facts(view) == {"gremium": ("AStA", "text"), "meetingStatus": ("draft", "text")}
    assert view.rows == []


async def test_agenda_item_shows_body_and_votes() -> None:
    session = ScriptedSession(
        scalars=[
            [
                SimpleNamespace(question="Annahme?", result="passed", status="closed"),
                SimpleNamespace(question=None, result=None, status="open"),
            ]
        ]
    )
    session.put(MeetingAgendaItem(id=TID, body="Text **fett**"))
    view = await _viewer(session, "agenda_item").view("agenda_item", TID, USER)
    assert _facts(view) == {"body": ("Text **fett**", "markdown")}
    assert [(r.title, r.meta, r.done) for r in view.rows] == [
        ("Annahme?", "passed", True),
        ("", "open", False),
    ]


async def test_vote_shows_status_result_and_eligible() -> None:
    session = ScriptedSession()
    session.put(Vote(id=TID, status="closed", result="rejected", eligible_count=0))
    view = await _viewer(session, "vote").view("vote", TID, USER)
    assert _facts(view) == {
        "voteStatus": ("closed", "text"),
        "voteResult": ("rejected", "text"),
        "eligible": ("0", "text"),
    }


async def test_invoice_shows_the_invoice_fields() -> None:
    session = ScriptedSession()
    session.put(
        Invoice(
            id=TID,
            number="R-1",
            supplier="Druckerei",
            issue_date=date(2026, 6, 1),
            due_date=None,
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("19.00"),
            gross_amount=Decimal("119.00"),
            status="open",
            note="",
        )
    )
    view = await _viewer(session, "invoice").view("invoice", TID, USER)
    assert _facts(view) == {
        "number": ("R-1", "text"),
        "supplier": ("Druckerei", "text"),
        "issueDate": ("2026-06-01", "date"),
        "netAmount": ("100.00", "money"),
        "taxAmount": ("19.00", "money"),
        "grossAmount": ("119.00", "money"),
        "invoiceStatus": ("open", "text"),
    }


async def test_expense_shows_the_booking_and_its_cost_centre() -> None:
    exp = SimpleNamespace(
        amount=Decimal("-5.50"),
        kind="expense",
        correspondent="Getränke GmbH",
        invoice_date=date(2026, 6, 2),
        payment_date=None,
        reference_number="B-7",
        payment_method=None,
        category="Feste",
        note="Beleg folgt",
    )
    session = ScriptedSession(execute=[[(exp, "", "Kultur")]])
    view = await _viewer(session, "expense").view("expense", TID, USER)
    assert _facts(view) == {
        "amount": ("-5.50", "money"),
        "bookingKind": ("expense", "text"),
        "costCentre": ("Kultur", "text"),
        "counterparty": ("Getränke GmbH", "text"),
        "invoiceDate": ("2026-06-02", "date"),
        "referenceNumber": ("B-7", "text"),
        "category": ("Feste", "text"),
        "note": ("Beleg folgt", "markdown"),
    }


async def test_todo_shows_due_date_description_and_checklist() -> None:
    card = SimpleNamespace(id=TID, due_date=date(2026, 8, 1), description_md="Plan")
    session = ScriptedSession(
        execute=[[(card, "Board", "Offen")]],
        scalars=[
            [SimpleNamespace(text="Raum", done=True), SimpleNamespace(text="Flyer", done=False)]
        ],
    )
    view = await _viewer(session, "todo").view("todo", TID, USER)
    assert _facts(view) == {
        "dueDate": ("2026-08-01", "date"),
        "description": ("Plan", "markdown"),
    }
    assert [(r.title, r.done) for r in view.rows] == [("Raum", True), ("Flyer", False)]
