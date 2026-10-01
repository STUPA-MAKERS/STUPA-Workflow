"""Unit tests for the draft uploads of the wizard (Z4) without a database.

A scripted session fake answers the queries of `DraftAttachments`, `check_drafts` and
`bind_drafts`. The integration tests `test_draft_upload` and
`test_create_binds_drafts` run the same code against Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.files import drafts as drafts_mod
from app.modules.files import service as files_service
from app.modules.files.drafts import (
    DRAFT_ATTACHMENTS_MISSING,
    DRAFT_QUOTA_EXCEEDED,
    DRAFT_TOKEN_INVALID,
    DraftAttachments,
    bind_drafts,
    check_drafts,
    hash_draft_token,
)
from app.modules.files.models import Attachment
from app.modules.files.router import get_draft_attachments
from app.modules.files.service import FilesService, application_id_of
from app.settings import load_settings
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from tests._support.files_fakes import FailingStorage, FakeScanQueue, FakeStorage
from tests._support.notifications_fakes import FakeSession

SETTINGS = load_settings()
PDF = b"%PDF-1.4 draft"
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class _Result:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:  # noqa: ANN401
        self._row = row
        self._rows = rows or []

    def one(self) -> Any:  # noqa: ANN401
        return self._row

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """Scripted session: `scalar` and `scalars` answer from queues."""

    def __init__(
        self,
        *,
        scalar: list[Any] | None = None,
        scalars: list[list[Any]] | None = None,
        quota: tuple[int, int] = (0, 0),
    ) -> None:
        self._scalar = list(scalar or [])
        self._scalars = list(scalars or [])
        self.quota = quota
        self.statements: list[str] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.committed = 0

    async def execute(self, stmt: Any, params: Any = None) -> _Result:  # noqa: ANN401
        sql = str(stmt)
        self.statements.append(sql)
        if "count(" in sql:
            return _Result(row=self.quota)
        return _Result()

    async def scalar(self, stmt: Any) -> Any:  # noqa: ANN401
        self.statements.append(str(stmt))
        return self._scalar.pop(0) if self._scalar else None

    async def scalars(self, stmt: Any) -> _Result:  # noqa: ANN401
        self.statements.append(str(stmt))
        return _Result(rows=self._scalars.pop(0) if self._scalars else [])

    def add(self, obj: Any) -> None:  # noqa: ANN401
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def delete(self, obj: Any) -> None:  # noqa: ANN401
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.committed += 1


AUDITS: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _patches(monkeypatch: pytest.MonkeyPatch) -> None:
    AUDITS.clear()

    async def _record(session: object, **kw: Any) -> None:  # noqa: ANN401
        AUDITS.append(kw)

    monkeypatch.setattr(drafts_mod, "audit_record", _record)
    monkeypatch.setattr(
        files_service, "validate_upload", lambda filename, data: "application/pdf"
    )


def _drafts(
    session: _Session, *, storage: object | None = None, queue: object | None = None
) -> DraftAttachments:
    files = FilesService(
        session,  # type: ignore[arg-type]
        storage=storage if storage is not None else FakeStorage(),  # type: ignore[arg-type]
        queue=queue,  # type: ignore[arg-type]
        settings=SETTINGS,
    )
    return DraftAttachments(files)


async def test_first_upload_issues_a_token() -> None:
    session = _Session()
    storage, queue = FakeStorage(), FakeScanQueue()
    out = await _drafts(session, storage=storage, queue=queue).upload(
        token=None, filename="a.pdf", data=PDF, by="applicant", field_key="f"
    )
    assert len(out.draftToken) >= 32
    assert out.draftExpiresAt > datetime.now(UTC) + timedelta(days=6)
    (row,) = session.added
    assert row.application_id is None
    assert row.id == out.id
    assert row.draft_token_hash == hash_draft_token(out.draftToken, SETTINGS.magic_link_secret)
    assert row.storage_key == f"drafts/{out.id}/a.pdf"
    assert storage.put_calls == [row.storage_key]
    assert queue.enqueued == [out.id]
    assert session.committed == 1
    # The new token needs no validity check, but the advisory lock and the quota run.
    assert any("pg_advisory_xact_lock" in s for s in session.statements)
    assert AUDITS[0]["action"] == "attachment_upload"
    assert AUDITS[0]["data"]["draft"] is True


async def test_later_upload_needs_a_valid_token() -> None:
    session = _Session(scalar=[uuid.uuid4()])
    out = await _drafts(session).upload(
        token="known", filename="b.pdf", data=PDF, by="sub-1"
    )
    assert out.draftToken == "known"
    assert AUDITS[0]["actor"] == "sub-1"


async def test_unknown_token_gives_422_and_stores_nothing() -> None:
    session = _Session(scalar=[None])
    storage = FakeStorage()
    with pytest.raises(ValidationProblem) as caught:
        await _drafts(session, storage=storage).upload(
            token="unknown", filename="b.pdf", data=PDF, by="applicant"
        )
    assert caught.value.code == DRAFT_TOKEN_INVALID
    assert storage.put_calls == []
    assert session.added == []


@pytest.mark.parametrize(
    ("quota", "message"),
    [((20, 0), "files"), ((1, 50 * 1024 * 1024 - 1), "bytes")],
)
async def test_quota_gives_413(quota: tuple[int, int], message: str) -> None:
    session = _Session(quota=quota)
    with pytest.raises(PayloadTooLargeError, match=message) as caught:
        await _drafts(session).upload(token=None, filename="c.pdf", data=PDF, by="x")
    assert caught.value.code == DRAFT_QUOTA_EXCEEDED


async def test_token_is_valid_reads_the_database() -> None:
    assert await _drafts(_Session(scalar=[uuid.uuid4()])).token_is_valid("t") is True
    assert await _drafts(_Session(scalar=[None])).token_is_valid("t", now=NOW) is False


def _draft_row(**over: Any) -> Attachment:  # noqa: ANN401
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "application_id": None,
        "filename": "d.pdf",
        "mime": "application/pdf",
        "size": 1,
        "storage_key": "drafts/x/d.pdf",
        "scanned": False,
        "scan_result": None,
        "draft_token_hash": b"h",
        "draft_expires_at": NOW + timedelta(days=1),
    }
    base.update(over)
    return Attachment(**base)


async def test_delete_removes_row_object_and_audits() -> None:
    row = _draft_row()
    session = _Session(scalar=[row])
    storage = FakeStorage()
    await _drafts(session, storage=storage).delete(row.id, token="t", actor="applicant")
    assert session.deleted == [row]
    assert storage.removed == ["drafts/x/d.pdf"]
    assert AUDITS[0]["action"] == "attachment_delete"
    assert AUDITS[0]["data"] == {"draft": True}


async def test_delete_tolerates_a_storage_error_and_a_missing_key() -> None:
    row = _draft_row()
    await _drafts(_Session(scalar=[row]), storage=FailingStorage()).delete(
        row.id, token="t", actor="a"
    )
    quarantined = _draft_row(storage_key=None)
    storage = FakeStorage()
    await _drafts(_Session(scalar=[quarantined]), storage=storage).delete(
        quarantined.id, token="t", actor="a"
    )
    assert storage.removed == []


async def test_delete_of_a_foreign_draft_gives_404() -> None:
    with pytest.raises(NotFoundError):
        await _drafts(_Session(scalar=[None])).delete(uuid.uuid4(), token="t", actor="a")


async def test_check_drafts_names_each_unusable_id() -> None:
    good = _draft_row()
    pending = _draft_row(scanned=False)
    clean = _draft_row(scanned=True, scan_result="clean")
    expired = _draft_row(draft_expires_at=NOW - timedelta(seconds=1))
    no_end = _draft_row(draft_expires_at=None)
    infected = _draft_row(scanned=True, scan_result="EICAR", storage_key="k")
    removed = _draft_row(storage_key=None)
    missing = uuid.uuid4()
    rows = [good, pending, clean, expired, no_end, infected, removed]
    session = _Session(scalars=[rows])
    ids = [r.id for r in rows] + [missing, good.id]
    with pytest.raises(ValidationProblem) as caught:
        await check_drafts(
            session, attachment_ids=ids, token="t", pepper="p", now=NOW  # type: ignore[arg-type]
        )
    assert caught.value.code == DRAFT_ATTACHMENTS_MISSING
    assert caught.value.errors is not None
    assert [e.field for e in caught.value.errors] == [
        f"attachmentIds.{r.id}" for r in (expired, no_end, infected, removed)
    ] + [f"attachmentIds.{missing}"]
    assert "FOR UPDATE" in session.statements[0]


async def test_check_drafts_passes_usable_drafts() -> None:
    rows = [_draft_row(), _draft_row(scanned=True, scan_result="clean")]
    await check_drafts(
        _Session(scalars=[rows]),  # type: ignore[arg-type]
        attachment_ids=[r.id for r in rows],
        token="t",
        pepper="p",
    )


async def test_bind_drafts_updates_and_skips_an_empty_list() -> None:
    session = _Session()
    await bind_drafts(
        session, application_id=uuid.uuid4(), attachment_ids=[], token="t", pepper="p"  # type: ignore[arg-type]
    )
    assert session.statements == []
    await bind_drafts(
        session,  # type: ignore[arg-type]
        application_id=uuid.uuid4(),
        attachment_ids=[uuid.uuid4()],
        token="t",
        pepper="p",
    )
    assert session.statements[0].startswith("UPDATE attachment SET application_id")


def test_validate_rejects_large_empty_and_storage_off() -> None:
    files = FilesService(_Session(), storage=FakeStorage(), settings=SETTINGS)  # type: ignore[arg-type]
    with pytest.raises(PayloadTooLargeError):
        files.validate("a.pdf", b"x" * (files.max_bytes + 1))
    with pytest.raises(UnsupportedMediaTypeError):
        files.validate("a.pdf", b"")
    off = FilesService(_Session(), storage=None, settings=SETTINGS)  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        off.validate("a.pdf", PDF)


async def test_put_object_without_storage_gives_503() -> None:
    off = FilesService(_Session(), storage=None, settings=SETTINGS)  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        await off.put_object("k", PDF, "application/pdf")


def test_application_id_of_a_draft_gives_404() -> None:
    bound = _draft_row(application_id=uuid.uuid4(), draft_token_hash=None)
    assert application_id_of(bound) == bound.application_id
    with pytest.raises(NotFoundError):
        application_id_of(_draft_row())


async def test_get_attachment_hides_a_draft() -> None:
    session = FakeSession()
    draft = _draft_row()
    session.add(draft)
    files = FilesService(session, settings=SETTINGS)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await files.get_attachment(draft.id)


def test_get_draft_attachments_wraps_the_files_service() -> None:
    files = FilesService(_Session(), settings=SETTINGS)  # type: ignore[arg-type]
    assert get_draft_attachments(files).files is files
