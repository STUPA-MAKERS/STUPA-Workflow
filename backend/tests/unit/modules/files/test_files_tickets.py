"""Unit tests of the ticket half of the files module (no database).

A ticket report binds the drafts of the wizard upload with ``ticket_id``. The files
service lists, streams and, for the anonymization, deletes them. The download gates
are those of an application attachment.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.files import service as files_service
from app.modules.files.drafts import bind_drafts
from app.modules.files.models import Attachment
from app.modules.files.service import (
    SCAN_RESULT_CLEAN,
    FilesService,
    _owner_data,
    upload_audit_data,
)
from app.settings import load_settings
from app.shared.errors import (
    ConflictError,
    GoneError,
    NotFoundError,
    ServiceUnavailableError,
)
from tests._support.files_fakes import FailingStorage, FakeStorage
from tests.unit.modules.tickets.fakes import ScriptedSession

SETTINGS = load_settings()
TICKET = uuid.uuid4()


def _att(**kw: Any) -> Attachment:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ticket_id": TICKET,
        "filename": "shot.png",
        "mime": "image/png",
        "size": 3,
        "storage_key": "k1",
        "scanned": True,
        "scan_result": SCAN_RESULT_CLEAN,
        "is_comparison_offer": False,
    }
    base.update(kw)
    return Attachment(**base)


def _svc(session: ScriptedSession, storage: object | None = None) -> FilesService:
    return FilesService(session, storage=storage, settings=SETTINGS)  # type: ignore[arg-type]


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def _record(_session: object, **kw: Any) -> None:
        out.append(kw)

    monkeypatch.setattr(files_service, "audit_record", _record)
    return out


async def test_bind_drafts_needs_exactly_one_target() -> None:
    session = ScriptedSession()
    for kw in ({}, {"application_id": uuid.uuid4(), "ticket_id": uuid.uuid4()}):
        with pytest.raises(ValueError, match="exactly one"):
            await bind_drafts(session, attachment_ids=[], token="t", pepper="p", **kw)  # type: ignore[arg-type]
    await bind_drafts(
        session,  # type: ignore[arg-type]
        attachment_ids=[uuid.uuid4()],
        token="t",
        pepper="p",
        ticket_id=TICKET,
    )
    sql = str(session.statements[0])
    assert "ticket_id" in sql
    assert "attachment.ticket_id IS NULL" in sql


async def test_is_ticket_attachment() -> None:
    session = ScriptedSession(scalar=[TICKET, None])
    assert await _svc(session).is_ticket_attachment(uuid.uuid4()) is True
    assert await _svc(session).is_ticket_attachment(uuid.uuid4()) is False


async def test_a_ticket_attachment_loads_only_with_a_ticket() -> None:
    bound = _att()
    other = _att(ticket_id=None, application_id=uuid.uuid4())
    session = ScriptedSession()
    session.put(bound, other)
    assert await _svc(session).get_ticket_attachment(bound.id) is bound
    for missing in (other.id, uuid.uuid4()):
        with pytest.raises(NotFoundError):
            await _svc(session).get_ticket_attachment(missing)


async def test_ticket_url_and_stream_after_a_clean_scan() -> None:
    att = _att()
    storage = FakeStorage()
    storage.objects["k1"] = (b"PNG", "image/png")
    session = ScriptedSession()
    session.put(att)
    url = await _svc(session, storage).ticket_url(att.id)
    assert url.url == f"/api/attachments/{att.id}/download"
    stream, filename, mime, size = await _svc(session, storage).ticket_download_stream(att.id)
    assert (filename, mime, size) == ("shot.png", "image/png", 3)
    assert b"".join([chunk async for chunk in stream]) == b"PNG"


@pytest.mark.parametrize(
    ("kw", "storage", "error"),
    [
        ({"scan_result": "Eicar"}, FakeStorage(), GoneError),
        ({"storage_key": None}, FakeStorage(), GoneError),
        ({"scanned": False, "scan_result": None}, FakeStorage(), ConflictError),
        ({}, None, ServiceUnavailableError),
        ({}, FailingStorage(), ServiceUnavailableError),
    ],
)
async def test_ticket_download_gates(
    kw: dict[str, Any], storage: object | None, error: type[Exception]
) -> None:
    att = _att(**kw)
    session = ScriptedSession()
    session.put(att)
    with pytest.raises(error):
        await _svc(session, storage).ticket_download_stream(att.id)


async def test_list_for_ticket() -> None:
    att = _att()
    session = ScriptedSession(scalars=[[att]])
    (out,) = await _svc(session).list_for_ticket(TICKET)
    assert (out.id, out.filename, out.scanned) == (att.id, "shot.png", True)


async def test_delete_for_ticket_removes_rows_objects_and_audits(
    audits: list[dict[str, Any]],
) -> None:
    keep, gone = _att(storage_key="k1"), _att(storage_key=None)
    storage = FakeStorage()
    session = ScriptedSession(scalars=[[keep, gone]])
    assert await _svc(session, storage).delete_for_ticket(TICKET, actor="sys") == 2
    assert session.deleted == [keep, gone]
    assert storage.removed == ["k1"]
    assert [a["data"] for a in audits] == [{"ticket_id": str(TICKET)}] * 2
    # A storage outage keeps the delete of the rows; without storage no object goes.
    session = ScriptedSession(scalars=[[_att()]])
    assert await _svc(session, FailingStorage()).delete_for_ticket(TICKET, actor="sys") == 1
    session = ScriptedSession(scalars=[[_att()]])
    assert await _svc(session, None).delete_for_ticket(TICKET, actor="sys") == 1


def test_the_owner_of_an_audit_entry() -> None:
    app_id = uuid.uuid4()
    assert _owner_data(_att(ticket_id=None, application_id=app_id)) == {
        "application_id": str(app_id)
    }
    assert _owner_data(_att()) == {"ticket_id": str(TICKET)}
    assert _owner_data(_att(ticket_id=None)) == {"draft": True}
    assert upload_audit_data(_att())["ticket_id"] == str(TICKET)
