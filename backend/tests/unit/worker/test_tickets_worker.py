"""Unit tests of the ticket retention cron (``worker/tickets.py``)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.admin.branding import Branding, TicketSettings
from app.modules.tickets.models import Ticket
from app.settings import load_settings
from tests.unit.modules.tickets.fakes import ScriptedSession
from worker import tickets as worker

MOMENT = datetime(2026, 10, 1, 3, 45, tzinfo=UTC)


class _Maker:
    """Hand out the queued sessions, one per ``async with``."""

    def __init__(self, *sessions: ScriptedSession) -> None:
        self.sessions = list(sessions)

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> ScriptedSession:
        return self.sessions.pop(0)

    async def __aexit__(self, *_a: object) -> None:
        return None


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": 1,
        "kind": "bug",
        "title": "t",
        "body": "b",
        "status": "done",
        "reporter_principal_id": None,
        "reporter_email": "a@x.org",
        "context": {"url": "u"},
        "anonymized_at": None,
    }
    base.update(kw)
    return Ticket(**base)


@pytest.fixture
def months(monkeypatch: pytest.MonkeyPatch) -> dict[str, int | None]:
    box: dict[str, int | None] = {"value": 12}

    async def _active(_session: object) -> Branding:
        return Branding(tickets=TicketSettings(retentionMonths=box["value"]))

    monkeypatch.setattr(worker, "active_branding", _active)
    return box


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def _record(_session: object, **kw: Any) -> None:
        out.append(kw)

    monkeypatch.setattr(worker, "audit_record", _record)

    class _Files:
        def __init__(self, _session: object, **_kw: object) -> None:
            pass

        async def delete_for_ticket(self, *_a: object, **_kw: object) -> int:
            return 0

    monkeypatch.setattr(worker, "FilesService", _Files)
    return out


async def test_a_null_retention_turns_the_job_off(
    months: dict[str, int | None], audits: list[dict[str, Any]]
) -> None:
    months["value"] = None
    ctx = {"tickets_sessionmaker": _Maker(ScriptedSession()), "object_storage": object()}
    assert await worker.anonymize_tickets(ctx) == 0


async def test_due_tickets_are_anonymized_one_by_one(
    months: dict[str, int | None], audits: list[dict[str, Any]]
) -> None:
    """Anonymize the due tickets one by one.

    The row lock serializes the run with a note that binds files.
    """
    due, gone, done_already, broken = (
        _ticket(),
        uuid.uuid4(),
        _ticket(anonymized_at=MOMENT),
        _ticket(),
    )
    lookup = ScriptedSession(scalars=[[due.id, gone, done_already.id, broken.id]])
    work = ScriptedSession()
    work.put(due)
    skip_gone, skip_done = ScriptedSession(), ScriptedSession()
    skip_done.put(done_already)

    class _Failing(ScriptedSession):
        async def commit(self) -> None:
            raise RuntimeError("constraint")

    failing = _Failing()
    failing.put(broken)
    maker = _Maker(lookup, work, skip_gone, skip_done, failing)
    ctx = {"tickets_sessionmaker": maker, "object_storage": object()}
    assert await worker.anonymize_tickets(ctx, now=MOMENT) == 1
    assert due.anonymized_at == MOMENT
    assert due.reporter_email is None
    assert due.context == {}
    assert work.committed == 1
    assert work.get_kw == [{"with_for_update": True}]
    assert [(a["action"], a["target_id"]) for a in audits[:1]] == [("anonymization", str(due.id))]
    sql = str(lookup.statements[0])
    assert "ticket.closed_at IS NOT NULL" in sql
    assert "make_interval" in sql


async def test_a_run_without_due_tickets_reports_zero(
    months: dict[str, int | None], audits: list[dict[str, Any]]
) -> None:
    ctx = {"tickets_sessionmaker": _Maker(ScriptedSession(scalars=[[]])), "object_storage": 1}
    assert await worker.anonymize_tickets(ctx) == 0


def test_the_defaults_come_from_the_app(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(worker, "get_sessionmaker", lambda: sentinel)
    assert worker._sessionmaker({}) is sentinel
    built: list[object] = []

    def _build(settings: object) -> str:
        built.append(settings)
        return "storage"

    monkeypatch.setattr(worker, "build_object_storage", _build)
    settings = load_settings()
    assert worker._storage({"settings": settings}) == "storage"
    assert built == [settings]
    monkeypatch.setattr(worker, "load_settings", lambda: settings)
    assert worker._storage({}) == "storage"
