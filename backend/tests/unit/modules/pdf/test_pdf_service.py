"""Unit-Tests PdfService (T-20): Job-Lebenszyklus + ``to_out``-Ergebnis-URL.

DB via ``FakePdfSession``; das Antrags-Dokument-Laden (``load_application_doc``) braucht
echte Joins → integration/test_pdf_service.py.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.applications.models import Application
from app.modules.pdf.models import RenderJob
from app.modules.pdf.service import PdfService
from app.settings import load_settings
from app.shared.errors import NotFoundError
from tests._support.files_fakes import FakeStorage
from tests._support.pdf_fakes import FakePdfSession

SETTINGS = load_settings()


def _svc(session: FakePdfSession) -> PdfService:
    return PdfService(session)  # type: ignore[arg-type]


def _app(session: FakePdfSession) -> uuid.UUID:
    app = Application()
    app.id = uuid.uuid4()
    session.store[app.id] = app
    return app.id


async def test_create_job_pending_for_existing_application() -> None:
    session = FakePdfSession()
    app_id = _app(session)
    job = await _svc(session).create_application_job(app_id)
    assert job.status == "pending"
    assert job.application_id == app_id
    assert session.flushed == 1
    assert job in session.added


async def test_create_job_missing_application_404() -> None:
    session = FakePdfSession()
    with pytest.raises(NotFoundError):
        await _svc(session).create_application_job(uuid.uuid4())


async def test_create_job_idempotency_key_reuses_existing() -> None:
    session = FakePdfSession()
    app_id = _app(session)
    existing = RenderJob(application_id=app_id, status="done", idempotency_key="k1")
    existing.id = uuid.uuid4()
    session._scalar = [existing]
    job = await _svc(session).create_application_job(app_id, idempotency_key="k1")
    assert job is existing
    assert session.added == []  # kein zweiter Job


async def test_create_job_idempotency_key_new_when_none_existing() -> None:
    session = FakePdfSession()
    app_id = _app(session)
    session._scalar = [None]
    job = await _svc(session).create_application_job(app_id, idempotency_key="k2")
    assert job.idempotency_key == "k2"
    assert job in session.added


async def test_get_job_found_and_missing() -> None:
    session = FakePdfSession()
    job = RenderJob(status="pending")
    job.id = uuid.uuid4()
    session.store[job.id] = job
    assert await _svc(session).get_job(job.id) is job
    with pytest.raises(NotFoundError):
        await _svc(session).get_job(uuid.uuid4())


def test_to_out_done_with_storage_yields_signed_url() -> None:
    storage = FakeStorage()
    job = RenderJob(
        application_id=uuid.uuid4(), status="done", storage_key="pdf/a/b.pdf"
    )
    job.id = uuid.uuid4()
    out = _svc(FakePdfSession()).to_out(job, storage=storage, settings=SETTINGS)
    assert out.status == "done"
    assert out.resultUrl is not None and "pdf/a/b.pdf" in out.resultUrl
    assert storage.signed == ["pdf/a/b.pdf"]


def test_to_out_pending_has_no_url() -> None:
    job = RenderJob(application_id=uuid.uuid4(), status="pending")
    job.id = uuid.uuid4()
    out = _svc(FakePdfSession()).to_out(job, storage=FakeStorage(), settings=SETTINGS)
    assert out.resultUrl is None


def test_to_out_done_without_storage_has_no_url() -> None:
    job = RenderJob(application_id=uuid.uuid4(), status="done", storage_key="k")
    job.id = uuid.uuid4()
    out = _svc(FakePdfSession()).to_out(job)
    assert out.resultUrl is None
    assert out.status == "done"


def test_to_out_failed_carries_error() -> None:
    job = RenderJob(application_id=uuid.uuid4(), status="failed", error="render_error")
    job.id = uuid.uuid4()
    out = _svc(FakePdfSession()).to_out(job)
    assert out.error == "render_error"
    assert out.resultUrl is None
