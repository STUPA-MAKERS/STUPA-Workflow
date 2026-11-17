"""Unit tests of the row helpers of the activity page (specs 001272, 001277)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.activity.service import (
    DETAIL_LENGTH,
    Gate,
    Me,
    Raw,
    _actor,
    _is_own,
    _shows,
    _status_to,
    _ticket_raw,
    _todo_raw,
    _uuid,
    first_line,
)
from app.modules.auth.principal import Principal
from app.modules.tickets.models import TicketEvent
from app.modules.todos.models import TodoEvent

AT = datetime(2026, 11, 1, tzinfo=UTC)
ME_ID = uuid.uuid4()
ME = Me(Principal(sub="me"), ME_ID, "me@example.org")
GATE = Gate(title="T", url="/x")


def _raw(**kw: object) -> Raw:
    base: dict[str, object] = {
        "at": AT,
        "key": "k",
        "kind": "application",
        "item_id": uuid.uuid4(),
        "change": "comment",
    }
    base.update(kw)
    return Raw(**base)  # type: ignore[arg-type]


def test_first_line_skips_blank_lines_and_cuts_long_ones() -> None:
    assert first_line(None) is None
    assert first_line("\n  \n") is None
    assert first_line("\n eins \nzwei") == "eins"
    long = first_line("x" * (DETAIL_LENGTH + 10))
    assert long is not None
    assert len(long) == DETAIL_LENGTH
    assert long.endswith("…")


def test_status_to_reads_only_a_status_change() -> None:
    assert _status_to(None) is None
    assert _status_to({"changes": "x"}) is None
    assert _status_to({"changes": {"date": {}}}) is None
    assert _status_to({"changes": {"status": {"to": 1}}}) is None
    assert _status_to({"changes": {"status": {"to": "closed"}}}) == "closed"


def test_uuid_parses_ids_of_the_audit_log() -> None:
    value = uuid.uuid4()
    assert _uuid(str(value)) == value
    assert _uuid("nope") is None
    assert _uuid(None) is None


def test_todo_rows_name_the_change() -> None:
    card = uuid.uuid4()

    def ev(kind: str, payload: dict[str, object]) -> TodoEvent:
        return TodoEvent(card_id=card, actor_id=None, kind=kind, payload=payload, created_at=AT)

    assert _todo_raw(ev("assigned", {"added": False}), "k").change == "todo.unassigned"
    assert _todo_raw(ev("assigned", {}), "k").change == "todo.assigned"
    assert _todo_raw(ev("checklist", {"text": "Punkt"}), "k").detail == "Punkt"
    assert _todo_raw(ev("renamed", {"to": "Neu"}), "k").detail == "Neu"
    assert _todo_raw(ev("moved", {"toColumnName": 3}), "k").detail is None
    assert _todo_raw(ev("unknown", {}), "k").change == "todo.created"


def test_ticket_rows_show_the_status_to_the_reporter_only() -> None:
    ticket = uuid.uuid4()
    status = TicketEvent(
        ticket_id=ticket, kind="status", payload={"to": "done"}, created_at=AT, actor_id=None
    )
    other = TicketEvent(ticket_id=ticket, kind="assignee", payload={}, created_at=AT)
    assert _ticket_raw(status, "k").status == "done"
    assert _ticket_raw(status, "k").reporter_reads is True
    assert _ticket_raw(other, "k").reporter_reads is False
    reporter = Gate(title=None, url="/t", internal=False, reporter=True)
    assert not _shows(_ticket_raw(other, "k"), reporter)
    assert _shows(_ticket_raw(status, "k"), reporter)
    assert not _shows(_raw(visibility="internal"), reporter)
    assert _shows(_raw(visibility="internal"), GATE)


def test_own_rows_match_by_id_or_sub() -> None:
    assert _is_own(_raw(actor_id=ME_ID), ME)
    assert not _is_own(_raw(actor_id=uuid.uuid4(), actor_sub="me"), ME)
    assert _is_own(_raw(actor_sub="me"), ME)
    assert not _is_own(_raw(), ME)


def test_the_actor_follows_the_view_of_the_item() -> None:
    names: dict[str | uuid.UUID, str | None] = {"bob": "Bob"}
    applicant = Gate(title=None, url="/x", applicant_view=True)
    assert _actor(_raw(applicant_author=True), GATE, names, own=False).kind == "applicant"
    assert _actor(_raw(), GATE, names, own=False).kind == "system"
    assert _actor(_raw(actor_sub="system:cron"), GATE, names, own=False).kind == "system"
    assert _actor(_raw(actor_sub="applicant"), GATE, names, own=False).kind == "applicant"
    assert _actor(_raw(actor_sub="bob"), applicant, names, own=False).kind == "committee"
    mine = _actor(_raw(actor_sub="bob"), applicant, names, own=True)
    assert (mine.kind, mine.name) == ("person", "Bob")
    unknown = _actor(_raw(actor_sub="ghost"), GATE, names, own=False)
    assert (unknown.kind, unknown.name) == ("person", None)
