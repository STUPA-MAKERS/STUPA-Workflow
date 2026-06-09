"""Unit-Tests Worker-Task render_pdf (T-20): Erfolg, Retry, erschöpfter Retry → failed."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from arq import Retry

from app.modules.pdf import render as render_mod
from app.modules.pdf.models import RenderJob
from app.modules.pdf.pytex_client import PytexError
from app.settings import load_settings
from tests.files_fakes import FakeStorage
from tests.pdf_fakes import FakePdfSession, FakePytex, FakeSessionmaker
from worker.pdf import render_pdf


class _DocStub:
    variant = "report"


class _SvcStub:
    def __init__(self, _session: object) -> None: ...

    async def load_application_doc(self, _app_id: uuid.UUID) -> _DocStub:
        return _DocStub()


@pytest.fixture(autouse=True)
def _stub_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(render_mod, "PdfService", _SvcStub)
    monkeypatch.setattr(render_mod, "build_application_markdown", lambda _doc: "# md")


def _ctx(
    session: FakePdfSession, *, pytex: FakePytex, storage: object | None, job_try: int = 1
) -> dict[str, Any]:
    return {
        "settings": load_settings(pdf_max_tries=3, pdf_retry_backoff_seconds=10),
        "pytex_client": pytex,
        "object_storage": storage,
        "pdf_sessionmaker": FakeSessionmaker(session),
        "job_try": job_try,
    }


def _job() -> RenderJob:
    job = RenderJob(application_id=uuid.uuid4(), status="pending")
    job.id = uuid.uuid4()
    return job


async def test_render_pdf_success() -> None:
    job = _job()
    ctx = _ctx(FakePdfSession(store={job.id: job}), pytex=FakePytex(), storage=FakeStorage())
    assert await render_pdf(ctx, str(job.id)) == "done"
    assert job.status == "done"


async def test_render_pdf_transient_retries() -> None:
    job = _job()
    pytex = FakePytex(error=PytexError("5xx", status=503, retryable=True))
    ctx = _ctx(FakePdfSession(store={job.id: job}), pytex=pytex, storage=FakeStorage(), job_try=1)
    with pytest.raises(Retry):
        await render_pdf(ctx, str(job.id))


async def test_render_pdf_exhausted_marks_failed_dead() -> None:
    job = _job()
    pytex = FakePytex(error=PytexError("5xx", status=503, retryable=True))
    session = FakePdfSession(store={job.id: job})
    ctx = _ctx(session, pytex=pytex, storage=FakeStorage(), job_try=3)  # == pdf_max_tries
    assert await render_pdf(ctx, str(job.id)) == "dead"
    assert job.status == "failed"
    assert job.error == "render_unavailable"


async def test_render_pdf_skipped_without_storage() -> None:
    job = _job()
    ctx = _ctx(FakePdfSession(store={job.id: job}), pytex=FakePytex(), storage=None)
    assert await render_pdf(ctx, str(job.id)) == "skipped"
