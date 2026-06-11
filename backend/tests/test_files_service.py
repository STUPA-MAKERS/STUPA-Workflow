"""Service-Tests files (T-13): Upload, Quarantäne, signierte URLs, Scan-Abschluss.

DB via `FakeSession`, Storage/Queue/Scan via Fakes (kein echtes MinIO/ClamAV/Redis).
MIME-Sniffing wird gemockt (kein libmagic nötig) — die Sniff-Logik testet
`test_files_mime`.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.applications.models import Application
from app.modules.files import service as files_service
from app.modules.files.mime import MimeRejected
from app.modules.files.models import Attachment
from app.modules.files.scanner import ScanVerdict
from app.modules.files.service import SCAN_RESULT_CLEAN, FilesService
from app.modules.flow.models import State
from app.settings import load_settings
from app.shared.errors import (
    ConflictError,
    GoneError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
)
from tests.files_fakes import FailingStorage, FakeScanQueue, FakeStorage
from tests.notifications_fakes import FakeSession

SETTINGS = load_settings()
PDF = b"%PDF-1.4 fake pdf bytes"


@pytest.fixture(autouse=True)
def _mock_mime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sniff/Validate auf »PDF ok« mocken (libmagic-frei)."""
    monkeypatch.setattr(
        files_service, "validate_upload", lambda filename, data: "application/pdf"
    )


def _app(session: FakeSession) -> uuid.UUID:
    app = Application()
    app.id = uuid.uuid4()
    session.add(app)
    return app.id


def _service(
    session: FakeSession,
    *,
    storage: object | None = None,
    queue: object | None = None,
) -> FilesService:
    return FilesService(session, storage=storage, queue=queue, settings=SETTINGS)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- upload
async def test_upload_clean_path_stores_and_enqueues() -> None:
    session = FakeSession()
    app_id = _app(session)
    storage, queue = FakeStorage(), FakeScanQueue()
    out = await _service(session, storage=storage, queue=queue).upload(
        app_id, filename="doc.pdf", data=PDF, by="applicant"
    )
    assert out.scanned is False
    assert out.mime == "application/pdf"
    assert out.size == len(PDF)
    assert len(storage.put_calls) == 1
    assert len(queue.enqueued) == 1
    assert session.committed == 1


async def test_upload_allowed_in_locked_state() -> None:
    """#attachments-when-locked: Anhänge sind auch in gesperrten States nachreichbar
    (Belege/Rechnungen nach der Entscheidung) — nur die Formular-Daten bleiben
    über den PATCH-Lock geschützt."""
    session = FakeSession()
    state = State()
    state.id = uuid.uuid4()
    state.edit_allowed = False
    app = Application()
    app.id = uuid.uuid4()
    app.current_state_id = state.id
    session.add(state)
    session.add(app)
    out = await _service(session, storage=FakeStorage()).upload(
        app.id, filename="doc.pdf", data=PDF, by="p"
    )
    assert out.scanned is False and out.mime == "application/pdf"


async def test_upload_state_row_missing_proceeds() -> None:
    # current_state_id gesetzt, aber kein State-Datensatz → kein Lock, Upload geht durch.
    session = FakeSession()
    app = Application()
    app.id = uuid.uuid4()
    app.current_state_id = uuid.uuid4()
    session.add(app)
    out = await _service(session, storage=FakeStorage()).upload(
        app.id, filename="doc.pdf", data=PDF, by="p"
    )
    assert out.scanned is False


async def test_upload_sanitizes_filename_and_key() -> None:
    session = FakeSession()
    app_id = _app(session)
    storage = FakeStorage()
    out = await _service(session, storage=storage).upload(
        app_id, filename="../../etc/passwd.pdf", data=PDF, by="p"
    )
    assert out.filename == "passwd.pdf"
    assert ".." not in storage.put_calls[0]
    assert storage.put_calls[0].endswith("/passwd.pdf")


async def test_upload_too_large_413() -> None:
    session = FakeSession()
    app_id = _app(session)
    big = b"x" * (SETTINGS.attachment_max_bytes + 1)
    with pytest.raises(PayloadTooLargeError):
        await _service(session, storage=FakeStorage()).upload(
            app_id, filename="doc.pdf", data=big, by="p"
        )


async def test_upload_empty_415() -> None:
    session = FakeSession()
    app_id = _app(session)
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(session, storage=FakeStorage()).upload(
            app_id, filename="doc.pdf", data=b"", by="p"
        )


async def test_upload_unknown_application_404() -> None:
    session = FakeSession()
    with pytest.raises(NotFoundError):
        await _service(session, storage=FakeStorage()).upload(
            uuid.uuid4(), filename="doc.pdf", data=PDF, by="p"
        )


async def test_upload_mime_rejected_415(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    app_id = _app(session)

    def _reject(filename: str | None, data: bytes) -> str:
        raise MimeRejected("nope")

    monkeypatch.setattr(files_service, "validate_upload", _reject)
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(session, storage=FakeStorage()).upload(
            app_id, filename="evil.exe", data=PDF, by="p"
        )


async def test_upload_without_storage_503() -> None:
    session = FakeSession()
    app_id = _app(session)
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=None).upload(
            app_id, filename="doc.pdf", data=PDF, by="p"
        )


async def test_upload_storage_failure_503() -> None:
    session = FakeSession()
    app_id = _app(session)
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=FailingStorage()).upload(
            app_id, filename="doc.pdf", data=PDF, by="p"
        )


async def test_upload_without_queue_stays_quarantined() -> None:
    session = FakeSession()
    app_id = _app(session)
    storage = FakeStorage()
    out = await _service(session, storage=storage, queue=None).upload(
        app_id, filename="doc.pdf", data=PDF, by="p"
    )
    # Datei liegt, aber kein Scan-Job (kein Redis) → bleibt scanned=false.
    assert out.scanned is False
    assert len(storage.put_calls) == 1


# ----------------------------------------------------------------- signed_url
def _attachment(session: FakeSession, **kw: object) -> Attachment:
    att = Attachment(
        application_id=uuid.uuid4(),
        filename="doc.pdf",
        mime="application/pdf",
        size=10,
        storage_key="k/doc.pdf",
        scanned=False,
        scan_result=None,
        is_comparison_offer=False,
    )
    att.id = uuid.uuid4()
    for key, value in kw.items():
        setattr(att, key, value)
    session.add(att)
    return att


async def test_signed_url_clean_returns_url() -> None:
    session = FakeSession()
    att = _attachment(session, scanned=True, scan_result=SCAN_RESULT_CLEAN)
    storage = FakeStorage()
    out = await _service(session, storage=storage).signed_url(att.id)
    assert out.url.startswith("https://minio.local/")
    assert out.expiresIn == SETTINGS.attachment_url_ttl_seconds
    assert storage.signed == ["k/doc.pdf"]


async def test_signed_url_still_scanning_409() -> None:
    session = FakeSession()
    att = _attachment(session, scanned=False)
    with pytest.raises(ConflictError):
        await _service(session, storage=FakeStorage()).signed_url(att.id)


async def test_signed_url_infected_410() -> None:
    session = FakeSession()
    att = _attachment(session, scanned=True, scan_result="Eicar-Test", storage_key=None)
    with pytest.raises(GoneError):
        await _service(session, storage=FakeStorage()).signed_url(att.id)


async def test_signed_url_unknown_404() -> None:
    session = FakeSession()
    with pytest.raises(NotFoundError):
        await _service(session, storage=FakeStorage()).signed_url(uuid.uuid4())


async def test_signed_url_without_storage_503() -> None:
    session = FakeSession()
    att = _attachment(session, scanned=True, scan_result=SCAN_RESULT_CLEAN)
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=None).signed_url(att.id)


async def test_signed_url_presign_failure_503() -> None:
    session = FakeSession()
    att = _attachment(session, scanned=True, scan_result=SCAN_RESULT_CLEAN)
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage=FailingStorage()).signed_url(att.id)


# ---------------------------------------------------------------- finalize_scan
async def test_finalize_scan_clean_marks_scanned() -> None:
    session = FakeSession()
    att = _attachment(session)
    await _service(session, storage=FakeStorage()).finalize_scan(
        att.id, ScanVerdict(clean=True)
    )
    assert att.scanned is True
    assert att.scan_result == SCAN_RESULT_CLEAN
    assert session.committed == 1


async def test_finalize_scan_infected_quarantines_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def _record(session: object, **kw: object) -> None:
        calls.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = FakeSession()
    att = _attachment(session)
    storage = FakeStorage()
    storage.objects["k/doc.pdf"] = (b"x", "application/pdf")
    await _service(session, storage=storage).finalize_scan(
        att.id, ScanVerdict(clean=False, signature="Eicar-Test-Signature")
    )
    assert att.scanned is True
    assert att.scan_result == "Eicar-Test-Signature"
    assert att.storage_key is None
    assert storage.removed == ["k/doc.pdf"]
    assert calls and calls[0]["target_type"] == "attachment"


async def test_finalize_scan_infected_tolerates_remove_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = FakeSession()
    att = _attachment(session)
    await _service(session, storage=FailingStorage()).finalize_scan(
        att.id, ScanVerdict(clean=False, signature="x")
    )
    # Quarantäne gilt trotz Remove-Fehler (storage_key genullt).
    assert att.storage_key is None
    assert att.scanned is True


async def test_finalize_scan_infected_without_storage_still_quarantines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = FakeSession()
    att = _attachment(session)
    # storage=None → kein remove-Aufruf, Quarantäne (storage_key=None) gilt trotzdem.
    await _service(session, storage=None).finalize_scan(
        att.id, ScanVerdict(clean=False, signature="x")
    )
    assert att.storage_key is None
    assert att.scan_result == "x"


async def test_finalize_scan_unknown_attachment_skips() -> None:
    session = FakeSession()
    # kein Commit, kein Fehler
    await _service(session, storage=FakeStorage()).finalize_scan(
        uuid.uuid4(), ScanVerdict(clean=True)
    )
    assert session.committed == 0
