"""Unit-Tests RenderPipeline (T-20): Markdown→pytex→MinIO→Nextcloud + Fehlerpfade.

``PdfService.load_application_doc`` + ``build_application_markdown`` werden gestubbt
(DB-frei); getestet wird die Orchestrierung: Statuswechsel, Ablage, optionaler
Nextcloud-Export, transiente vs. dauerhafte Fehler.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.pdf import render as render_mod
from app.modules.pdf.models import RenderJob
from app.modules.pdf.nextcloud import NextcloudError
from app.modules.pdf.pytex_client import PytexError
from app.modules.pdf.render import RenderPipeline, RenderRetry
from tests.files_fakes import FakeStorage
from tests.pdf_fakes import FakeNextcloud, FakePdfSession, FakePytex, FakeSessionmaker


class _DocStub:
    variant = "report"


class _SvcStub:
    def __init__(self, _session: object) -> None: ...

    async def load_application_doc(self, _app_id: uuid.UUID) -> _DocStub:
        return _DocStub()


@pytest.fixture(autouse=True)
def _stub_doc(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB-Laden + Markdown-Bau stubben (Pipeline-Orchestrierung isoliert testen)."""
    monkeypatch.setattr(render_mod, "PdfService", _SvcStub)
    monkeypatch.setattr(render_mod, "build_application_markdown", lambda _doc: "# md")


def _job(**over: object) -> RenderJob:
    job = RenderJob(application_id=uuid.uuid4(), status="pending")
    job.id = uuid.uuid4()
    for k, v in over.items():
        setattr(job, k, v)
    return job


def _pipeline(
    job: RenderJob | None,
    *,
    storage: object | None = None,
    pytex: FakePytex | None = None,
    nextcloud: object | None = None,
) -> tuple[RenderPipeline, FakePdfSession]:
    store = {job.id: job} if job is not None else {}
    session = FakePdfSession(store=store)
    pipe = RenderPipeline(
        sessionmaker=FakeSessionmaker(session),  # type: ignore[arg-type]
        pytex=pytex or FakePytex(),  # type: ignore[arg-type]
        storage=storage,  # type: ignore[arg-type]
        nextcloud=nextcloud,  # type: ignore[arg-type]
    )
    return pipe, session


async def test_run_success_stores_pdf_and_marks_done() -> None:
    job = _job()
    storage = FakeStorage()
    pipe, _ = _pipeline(job, storage=storage)
    result = await pipe.run(job.id)
    assert result == "done"
    assert job.status == "done"
    expected_key = f"pdf/{job.application_id}/{job.id}.pdf"
    assert job.storage_key == expected_key
    assert job.finished_at is not None
    assert storage.put_calls == [expected_key]
    assert storage.objects[expected_key][1] == "application/pdf"


async def test_run_success_with_nextcloud_records_path() -> None:
    job = _job()
    nc = FakeNextcloud()
    pipe, _ = _pipeline(job, storage=FakeStorage(), nextcloud=nc)
    await pipe.run(job.id)
    assert job.nextcloud_path is not None
    assert len(nc.uploads) == 1


async def test_run_skipped_when_no_storage() -> None:
    job = _job()
    pipe, _ = _pipeline(job, storage=None)
    assert await pipe.run(job.id) == "skipped"
    assert job.status == "pending"  # unverändert


async def test_run_gone_when_job_missing() -> None:
    pipe, _ = _pipeline(None, storage=FakeStorage())
    assert await pipe.run(uuid.uuid4()) == "gone"


async def test_run_idempotent_for_done_job() -> None:
    job = _job(status="done")
    pipe, _ = _pipeline(job, storage=FakeStorage())
    assert await pipe.run(job.id) == "done"


async def test_run_failed_when_no_application() -> None:
    job = _job(application_id=None)
    pipe, _ = _pipeline(job, storage=FakeStorage())
    assert await pipe.run(job.id) == "failed"
    assert job.error == "no_application"


async def test_run_pytex_permanent_marks_failed() -> None:
    job = _job()
    pytex = FakePytex(error=PytexError("bad", status=400, retryable=False))
    pipe, _ = _pipeline(job, storage=FakeStorage(), pytex=pytex)
    assert await pipe.run(job.id) == "failed"
    assert job.status == "failed"
    assert job.error == "render_error"


async def test_run_pytex_transient_raises_retry() -> None:
    job = _job()
    pytex = FakePytex(error=PytexError("5xx", status=503, retryable=True))
    pipe, _ = _pipeline(job, storage=FakeStorage(), pytex=pytex)
    with pytest.raises(RenderRetry):
        await pipe.run(job.id)


async def test_run_storage_error_raises_retry() -> None:
    from tests.files_fakes import FailingStorage

    job = _job()
    pipe, _ = _pipeline(job, storage=FailingStorage())
    with pytest.raises(RenderRetry):
        await pipe.run(job.id)


async def test_run_nextcloud_error_raises_retry() -> None:
    job = _job()
    nc = FakeNextcloud(error=NextcloudError("down"))
    pipe, _ = _pipeline(job, storage=FakeStorage(), nextcloud=nc)
    with pytest.raises(RenderRetry):
        await pipe.run(job.id)


async def test_mark_failed_sets_status() -> None:
    job = _job(status="running")
    pipe, _ = _pipeline(job, storage=FakeStorage())
    await pipe.mark_failed(job.id, "render_unavailable")
    assert job.status == "failed"
    assert job.error == "render_unavailable"


async def test_mark_failed_missing_job_noop() -> None:
    pipe, _ = _pipeline(None, storage=FakeStorage())
    await pipe.mark_failed(uuid.uuid4(), "x")  # kein Fehler
