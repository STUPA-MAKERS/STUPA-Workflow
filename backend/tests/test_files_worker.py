"""Worker-Tests files (T-13): `scan_attachment` Clean/Infected/Retry — alles gefaked."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from arq import Retry

from app.modules.files import service as files_service
from app.modules.files.models import Attachment
from app.modules.files.scanner import ScannerError, ScanVerdict
from app.settings import load_settings
from tests.files_fakes import FailingStorage, FakeStorage, StubScanner
from tests.notifications_fakes import FakeSession
from worker import scan as scan_mod
from worker.scan import on_startup, scan_attachment

SETTINGS = load_settings()


class _SessionCM:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_a: Any) -> bool:
        return False


def _ctx(session: FakeSession, **kw: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "settings": SETTINGS,
        "scanner": kw.get("scanner"),
        "object_storage": kw.get("storage"),
        "files_sessionmaker": lambda: _SessionCM(session),
        "job_try": kw.get("job_try", 1),
    }
    return ctx


def _attachment(session: FakeSession, storage_key: str | None = "k/doc.pdf") -> Attachment:
    att = Attachment(
        application_id=uuid.uuid4(),
        filename="doc.pdf",
        mime="application/pdf",
        size=3,
        storage_key=storage_key,
        scanned=False,
    )
    att.id = uuid.uuid4()
    session.add(att)
    return att


async def test_scan_clean() -> None:
    session = FakeSession()
    att = _attachment(session)
    storage = FakeStorage()
    storage.objects["k/doc.pdf"] = (b"data", "application/pdf")
    scanner = StubScanner(ScanVerdict(clean=True))
    result = await scan_attachment(
        _ctx(session, scanner=scanner, storage=storage), str(att.id)
    )
    assert result == "clean"
    assert att.scanned is True


async def test_scan_infected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _record(session: object, **kw: object) -> None:
        return None

    monkeypatch.setattr(files_service, "audit_record", _record)
    session = FakeSession()
    att = _attachment(session)
    storage = FakeStorage()
    storage.objects["k/doc.pdf"] = (b"x", "application/pdf")
    scanner = StubScanner(ScanVerdict(clean=False, signature="Eicar-Test"))
    result = await scan_attachment(
        _ctx(session, scanner=scanner, storage=storage), str(att.id)
    )
    assert result == "infected"
    assert att.storage_key is None
    assert storage.removed == ["k/doc.pdf"]


async def test_scan_skipped_without_scanner() -> None:
    session = FakeSession()
    result = await scan_attachment(
        _ctx(session, scanner=None, storage=FakeStorage()), str(uuid.uuid4())
    )
    assert result == "skipped"


async def test_scan_gone_when_attachment_missing() -> None:
    session = FakeSession()
    result = await scan_attachment(
        _ctx(session, scanner=StubScanner(ScanVerdict(clean=True)), storage=FakeStorage()),
        str(uuid.uuid4()),
    )
    assert result == "gone"


async def test_scan_retry_on_storage_error() -> None:
    session = FakeSession()
    att = _attachment(session)
    ctx = _ctx(
        session,
        scanner=StubScanner(ScanVerdict(clean=True)),
        storage=FailingStorage(),
        job_try=1,
    )
    with pytest.raises(Retry):
        await scan_attachment(ctx, str(att.id))


async def test_scan_dead_after_max_tries() -> None:
    session = FakeSession()
    att = _attachment(session)
    ctx = _ctx(
        session,
        scanner=StubScanner(ScanVerdict(clean=True)),
        storage=FailingStorage(),
        job_try=99,
    )
    result = await scan_attachment(ctx, str(att.id))
    assert result == "dead"


async def test_scan_retry_on_scanner_error() -> None:
    session = FakeSession()
    att = _attachment(session)
    storage = FakeStorage()
    storage.objects["k/doc.pdf"] = (b"x", "application/pdf")

    class _Boom:
        async def scan(self, data: bytes) -> ScanVerdict:
            raise ScannerError("down")

    ctx = _ctx(session, scanner=_Boom(), storage=storage, job_try=1)
    with pytest.raises(Retry):
        await scan_attachment(ctx, str(att.id))


async def test_on_startup_populates_ctx_disabled() -> None:
    ctx: dict[str, Any] = {}
    await on_startup(ctx)
    # ClamAV/MinIO ohne Config → Scanner/Storage None, aber Keys gesetzt.
    assert "settings" in ctx
    assert ctx["scanner"] is None
    assert ctx["object_storage"] is None
    assert scan_mod.build_scanner is not None


async def test_worker_combined_on_startup() -> None:
    """`worker.main._on_startup` verdrahtet Mail- (T-18) + Scan-Deps (T-13)."""
    from worker.main import _on_startup

    ctx: dict[str, Any] = {}
    await _on_startup(ctx)
    assert "mail_sender" in ctx  # aus mail_on_startup
    assert "object_storage" in ctx  # aus scan_on_startup
