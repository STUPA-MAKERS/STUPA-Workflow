"""The scan handles draft uploads and rows that disappear during the scan (Z4).

* A draft with a finding is quarantined like a bound file. Its audit entry carries
  `draft: true` instead of an application id.
* A row that a delete, the draft purge or an anonymization removed during the scan is
  no error: `finalize_scan` returns False and the task returns `"gone"`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm.exc import StaleDataError

import worker.scan as wscan
from app.modules.files import service as files_service
from app.modules.files.models import Attachment
from app.modules.files.scanner import ScanVerdict
from app.modules.files.service import FilesService
from app.settings import load_settings
from tests._support.files_fakes import FakeStorage
from tests._support.notifications_fakes import FakeSession

SETTINGS = load_settings()


class _StaleSession(FakeSession):
    """The UPDATE of the commit finds no row: another transaction deleted it."""

    def __init__(self) -> None:
        super().__init__()
        self.rolled_back = 0

    async def commit(self) -> None:
        raise StaleDataError("row is gone")

    async def rollback(self) -> None:
        self.rolled_back += 1


AUDITS: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _audit(monkeypatch: pytest.MonkeyPatch) -> None:
    AUDITS.clear()

    async def _record(session: object, **kw: Any) -> None:  # noqa: ANN401
        AUDITS.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)


def _draft(session: FakeSession) -> Attachment:
    att = Attachment(
        application_id=None,
        filename="d.pdf",
        mime="application/pdf",
        size=3,
        storage_key="drafts/x/d.pdf",
        scanned=False,
        scan_result=None,
        is_comparison_offer=False,
        draft_token_hash=b"h",
        draft_expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    att.id = uuid.uuid4()
    session.add(att)
    return att


async def test_infected_draft_is_quarantined_with_draft_flag() -> None:
    session = FakeSession()
    att = _draft(session)
    storage = FakeStorage()
    stored = await FilesService(session, storage=storage, settings=SETTINGS).finalize_scan(  # type: ignore[arg-type]
        att.id, ScanVerdict(clean=False, signature="Eicar")
    )
    assert stored is True
    assert att.scanned is True
    assert att.storage_key is None
    assert storage.removed == ["drafts/x/d.pdf"]
    assert AUDITS[0]["action"] == "attachment_quarantine"
    assert AUDITS[0]["data"] == {"draft": True, "signature": "Eicar"}


async def test_clean_draft_is_stored() -> None:
    session = FakeSession()
    att = _draft(session)
    stored = await FilesService(session, settings=SETTINGS).finalize_scan(  # type: ignore[arg-type]
        att.id, ScanVerdict(clean=True)
    )
    assert stored is True
    assert att.scan_result == "clean"
    assert AUDITS == []


@pytest.mark.parametrize("clean", [True, False])
async def test_row_removed_during_the_scan_is_skipped(clean: bool) -> None:
    session = _StaleSession()
    att = _draft(session)
    storage = FakeStorage()
    stored = await FilesService(session, storage=storage, settings=SETTINGS).finalize_scan(  # type: ignore[arg-type]
        att.id, ScanVerdict(clean=clean, signature=None if clean else "x")
    )
    assert stored is False
    assert session.rolled_back == 1
    # The deleter owns the object. The scan removes nothing.
    assert storage.removed == []


async def test_row_removed_before_the_audit_flush_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quarantine audit flushes the UPDATE first. A gone row fails there."""

    class _RollbackSession(FakeSession):
        def __init__(self) -> None:
            super().__init__()
            self.rolled_back = 0
            self.committed = 0

        async def commit(self) -> None:
            self.committed += 1

        async def rollback(self) -> None:
            self.rolled_back += 1

    async def _stale(session: object, **kw: Any) -> None:  # noqa: ANN401
        raise StaleDataError("row is gone")

    monkeypatch.setattr(files_service, "audit_record", _stale)
    session = _RollbackSession()
    att = _draft(session)
    storage = FakeStorage()
    stored = await FilesService(session, storage=storage, settings=SETTINGS).finalize_scan(  # type: ignore[arg-type]
        att.id, ScanVerdict(clean=False, signature="Eicar")
    )
    assert stored is False
    assert session.rolled_back == 1
    assert session.committed == 0
    assert storage.removed == []


async def test_unknown_row_returns_false() -> None:
    stored = await FilesService(FakeSession(), settings=SETTINGS).finalize_scan(  # type: ignore[arg-type]
        uuid.uuid4(), ScanVerdict(clean=True)
    )
    assert stored is False


class _GoneFiles:
    def __init__(self, *_a: object, **_k: object) -> None: ...

    async def finalize_scan(self, *_a: object, **_k: object) -> bool:
        return False


class _CM:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_exc: object) -> bool:
        return False


async def test_scan_task_returns_gone_when_the_row_vanishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wscan, "FilesService", _GoneFiles)
    session = FakeSession()
    att = _draft(session)

    class _Storage:
        async def get(self, key: str) -> bytes:
            return b"data"

    class _Scanner:
        async def scan(self, data: bytes) -> ScanVerdict:
            return ScanVerdict(clean=True)

    ctx = {
        "settings": SETTINGS,
        "scanner": _Scanner(),
        "object_storage": _Storage(),
        "files_sessionmaker": lambda: _CM(session),
    }
    assert await wscan.scan_attachment(ctx, str(att.id)) == "gone"
