"""Unit-Tests Flow-Action-Dispatcher exportPdf + Chain (T-20, flows §9.3)."""

from __future__ import annotations

import uuid

from app.modules.applications.models import Application
from app.modules.flow.dispatch import DispatchedAction
from app.modules.pdf.action_dispatcher import (
    ChainActionDispatcher,
    PdfActionDispatcher,
    build_pdf_dispatcher,
)
from tests.pdf_fakes import FakePdfSession, FakeRenderQueue, FakeSessionmaker


def _action(type_: str, app_id: uuid.UUID, key: str = "k") -> DispatchedAction:
    return DispatchedAction(
        type=type_,
        application_id=app_id,
        transition_id=uuid.uuid4(),
        status_event_id=uuid.uuid4(),
        idempotency_key=key,
    )


def _dispatcher(
    session: FakePdfSession, queue: FakeRenderQueue | None
) -> PdfActionDispatcher:
    return PdfActionDispatcher(FakeSessionmaker(session), queue)  # type: ignore[arg-type]


async def test_export_pdf_creates_job_and_enqueues() -> None:
    session = FakePdfSession()
    app = Application()
    app.id = uuid.uuid4()
    session.store[app.id] = app
    session._scalar = [None]  # kein bestehender Job für den Idempotenz-Key
    queue = FakeRenderQueue()
    await _dispatcher(session, queue).dispatch([_action("exportPdf", app.id)])
    assert len(session.added) == 1
    assert session.committed == 1
    assert len(queue.enqueued) == 1


async def test_non_export_action_ignored() -> None:
    session = FakePdfSession()
    queue = FakeRenderQueue()
    await _dispatcher(session, queue).dispatch([_action("notify", uuid.uuid4())])
    assert session.added == []
    assert queue.enqueued == []


async def test_export_pdf_missing_application_skipped() -> None:
    session = FakePdfSession()  # leerer Store → Antrag fehlt → NotFoundError → skip
    queue = FakeRenderQueue()
    await _dispatcher(session, queue).dispatch([_action("exportPdf", uuid.uuid4())])
    assert queue.enqueued == []


async def test_export_pdf_without_queue_still_creates_job() -> None:
    session = FakePdfSession()
    app = Application()
    app.id = uuid.uuid4()
    session.store[app.id] = app
    session._scalar = [None]
    await _dispatcher(session, None).dispatch([_action("exportPdf", app.id)])
    assert len(session.added) == 1  # Job angelegt; Enqueue entfällt (kein Redis)


async def test_chain_runs_all_dispatchers() -> None:
    calls: list[str] = []

    class _Rec:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        async def dispatch(self, _actions: object) -> None:
            calls.append(self.tag)

    chain = ChainActionDispatcher([_Rec("a"), _Rec("b")])  # type: ignore[list-item]
    await chain.dispatch([_action("notify", uuid.uuid4())])
    assert calls == ["a", "b"]


def test_build_pdf_dispatcher_without_pool() -> None:
    disp = build_pdf_dispatcher(None)
    assert disp.queue is None
