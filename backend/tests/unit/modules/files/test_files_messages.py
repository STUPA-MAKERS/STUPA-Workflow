"""Unit tests of the files of chat messages (no database).

A ticket note, a to-do comment and an application comment can carry files. The
composer uploads them as drafts; the send checks and binds them with the owner
column. The files service lists and removes them per message, and the download
routes apply the read rule of the message (``_assert_owner_reader``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.applications.models import Comment
from app.modules.auth.principal import Applicant, Principal
from app.modules.files import drafts as drafts_mod
from app.modules.files import router as router_mod
from app.modules.files import service as files_service
from app.modules.files.drafts import bind_drafts, check_message_drafts
from app.modules.files.models import Attachment
from app.modules.files.router import _assert_owner_reader
from app.modules.files.schemas import (
    MAX_MESSAGE_ATTACHMENTS,
    MessageFilesIn,
    message_attachment_out,
)
from app.modules.files.service import AttachmentOwner, FilesService
from app.modules.todos.models import TodoBoard
from app.settings import load_settings
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from tests._support.files_fakes import FailingStorage, FakeStorage
from tests.unit.modules.tickets.fakes import ScriptedSession

SETTINGS = load_settings()
NOW = datetime(2026, 10, 1, tzinfo=UTC)
NOTE = uuid.uuid4()


def _att(**kw: Any) -> Attachment:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "ticket_note_id": NOTE,
        "filename": "shot.png",
        "mime": "image/png",
        "size": 3,
        "storage_key": "k1",
        "scanned": True,
        "scan_result": "clean",
        "created_at": NOW,
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


# -- wire forms --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "state"),
    [
        ({"scanned": False, "scan_result": None}, "scanning"),
        ({}, "clean"),
        ({"storage_key": None}, "quarantined"),
        ({"scan_result": "Eicar-Test"}, "quarantined"),
    ],
)
def test_the_scan_state_of_a_message_file(kw: dict[str, Any], state: str) -> None:
    out = message_attachment_out(_att(**kw))
    assert out.scan_state == state
    assert out.model_dump(by_alias=True)["scanState"] == state


class _Message(MessageFilesIn):
    body: str = ""


def test_a_message_needs_a_text_or_a_file() -> None:
    with pytest.raises(ValidationError):
        _Message.model_validate({"body": " \n"})
    assert _Message.model_validate({"body": "hi"}).attachment_ids == []
    files = _Message.model_validate({"body": "", "attachmentIds": [str(uuid.uuid4())]})
    assert len(files.attachment_ids) == 1
    with pytest.raises(ValidationError):
        _Message.model_validate(
            {
                "body": "x",
                "attachmentIds": [str(uuid.uuid4()) for _ in range(MAX_MESSAGE_ATTACHMENTS + 1)],
            }
        )


# -- check and bind ------------------------------------------------------------------


async def test_check_message_drafts_without_files_checks_nothing() -> None:
    session = ScriptedSession()
    assert (
        await check_message_drafts(session, attachment_ids=[], token=None, pepper="p")  # type: ignore[arg-type]
        is None
    )
    assert session.statements == []


async def test_check_message_drafts_needs_the_token() -> None:
    with pytest.raises(ValidationProblem) as exc:
        await check_message_drafts(
            ScriptedSession(),  # type: ignore[arg-type]
            attachment_ids=[uuid.uuid4()],
            token=None,
            pepper="p",
        )
    assert exc.value.errors is not None
    assert exc.value.errors[0].field == "draftToken"


async def test_check_message_drafts_checks_every_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    async def _check(_s: object, **kw: Any) -> None:
        seen.append(kw)

    monkeypatch.setattr(drafts_mod, "check_drafts", _check)
    ids = [uuid.uuid4()]
    token = await check_message_drafts(
        ScriptedSession(),  # type: ignore[arg-type]
        attachment_ids=ids,
        token="tok",
        pepper="p",
    )
    assert token == "tok"
    assert seen == [{"attachment_ids": ids, "token": "tok", "pepper": "p"}]


@pytest.mark.parametrize("owner", ["ticket_note_id", "todo_comment_id", "comment_id"])
async def test_bind_drafts_sets_the_message_owner(owner: str) -> None:
    session = ScriptedSession()
    target = uuid.uuid4()
    await bind_drafts(
        session,  # type: ignore[arg-type]
        attachment_ids=[uuid.uuid4()],
        token="t",
        pepper="p",
        **{owner: target},
    )
    sql = str(session.statements[0])
    assert f"{owner}=" in sql.replace(" ", "")
    for column in ("application_id", "ticket_id", "ticket_note_id", "todo_comment_id"):
        assert f"attachment.{column} IS NULL" in sql


async def test_bind_drafts_without_ids_writes_nothing() -> None:
    session = ScriptedSession()
    await bind_drafts(session, attachment_ids=[], token="t", pepper="p", comment_id=NOTE)  # type: ignore[arg-type]
    assert session.statements == []


# -- list and remove ---------------------------------------------------------------------


async def test_message_attachments_group_by_message_in_one_query() -> None:
    other = uuid.uuid4()
    first, second, third = _att(), _att(ticket_note_id=other), _att()
    session = ScriptedSession(scalars=[[first, second, third]])
    out = await _svc(session).message_attachments("ticket_note", [NOTE, other, NOTE])
    assert [a.id for a in out[NOTE]] == [first.id, third.id]
    assert [a.id for a in out[other]] == [second.id]
    assert len(session.statements) == 1
    assert "attachment.ticket_note_id IN" in str(session.statements[0])


async def test_message_attachments_without_ids_ask_nothing() -> None:
    session = ScriptedSession()
    assert await _svc(session).message_attachments("comment", []) == {}
    assert session.statements == []


@pytest.mark.parametrize("owner", ["todo_comment", "comment"])
async def test_message_attachments_read_the_owner_column(owner: str) -> None:
    session = ScriptedSession(scalars=[[]])
    assert await _svc(session).message_attachments(owner, [NOTE]) == {}  # type: ignore[arg-type]
    assert f"attachment.{owner}_id IN" in str(session.statements[0])


async def test_delete_for_messages_removes_rows_objects_and_audits(
    audits: list[dict[str, Any]],
) -> None:
    keep, gone = _att(storage_key="k1"), _att(storage_key=None)
    storage = FakeStorage()
    session = ScriptedSession(scalars=[[keep, gone]])
    assert await _svc(session, storage).delete_for_messages("ticket_note", [NOTE], actor="a") == 2
    assert session.deleted == [keep, gone]
    assert storage.removed == ["k1"]
    assert [a["data"] for a in audits] == [{"ticket_note_id": str(NOTE)}] * 2
    assert session.committed == 0
    session = ScriptedSession(scalars=[[_att()]])
    assert (
        await _svc(session, FailingStorage()).delete_for_messages("ticket_note", [NOTE], actor="a")
        == 1
    )
    session = ScriptedSession(scalars=[[_att()]])
    assert await _svc(session).delete_for_messages("ticket_note", [NOTE], actor="a") == 1


async def test_drop_for_messages_keeps_the_objects_until_remove_objects(
    audits: list[dict[str, Any]],
) -> None:
    keep, gone = _att(storage_key="k1"), _att(storage_key=None)
    storage = FakeStorage()
    session = ScriptedSession(scalars=[[keep, gone]])
    service = _svc(session, storage)
    assert await service.drop_for_messages("todo_comment", [NOTE, NOTE], actor="a") == ["k1"]
    assert session.deleted == [keep, gone]
    assert len(audits) == 2 and session.committed == 0
    assert storage.removed == []
    await service.remove_objects(["k1"])
    assert storage.removed == ["k1"]
    empty = ScriptedSession()
    assert await _svc(empty, storage).drop_for_messages("todo_comment", [], actor="a") == []
    assert empty.statements == []


async def test_the_removal_locks_and_deletes_every_row_before_its_first_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = _att(storage_key="k1"), _att(storage_key="k2")
    session = ScriptedSession(scalars=[[first, second]])
    seen: list[tuple[int, int]] = []

    async def _record(_session: object, **_kw: Any) -> None:
        seen.append((len(session.deleted), session.flushed))

    monkeypatch.setattr(files_service, "audit_record", _record)
    await _svc(session).drop_for_messages("ticket_note", [NOTE], actor="a")
    sql = str(session.statements[0])
    assert "ORDER BY attachment.id" in sql and sql.endswith("FOR UPDATE")
    # Both rows are deleted and flushed before the first audit entry takes the lock
    # of the audit chain, so no row lock follows that lock.
    assert seen == [(2, 1), (2, 1)]


async def test_lock_for_messages_locks_the_rows_in_id_order() -> None:
    session = ScriptedSession()
    await _svc(session).lock_for_messages("todo_comment", [NOTE, NOTE])
    sql = str(session.statements[0])
    assert sql.startswith("SELECT attachment.id") and "attachment.todo_comment_id IN" in sql
    assert "ORDER BY attachment.id" in sql and sql.endswith("FOR UPDATE")
    empty = ScriptedSession()
    await _svc(empty).lock_for_messages("todo_comment", [])
    assert empty.statements == []


async def test_remove_objects_is_best_effort() -> None:
    await _svc(ScriptedSession(), FailingStorage()).remove_objects(["k1", "k2"])
    await _svc(ScriptedSession()).remove_objects(["k1"])


async def test_delete_for_messages_without_ids_asks_nothing() -> None:
    session = ScriptedSession()
    assert await _svc(session).delete_for_messages("todo_comment", [], actor="a") == 0
    assert session.statements == []


async def test_delete_for_application_also_removes_the_comment_files(
    audits: list[dict[str, Any]],
) -> None:
    app_id, comment_id = uuid.uuid4(), uuid.uuid4()
    own = _att(ticket_note_id=None, application_id=app_id)
    of_comment = _att(ticket_note_id=None, comment_id=comment_id)
    session = ScriptedSession(scalars=[[own, of_comment]])
    assert await _svc(session, FakeStorage()).delete_for_application(app_id, actor="x") == 2
    sql = str(session.statements[0])
    assert "attachment.comment_id IN" in sql
    assert "attachment.application_id IS NOT NULL" in sql
    assert [a["data"] for a in audits] == [
        {"application_id": str(app_id)},
        {"comment_id": str(comment_id)},
    ]


# -- the read rule of the owner ------------------------------------------------------------


class _Files:
    def __init__(self) -> None:
        self.visible: list[tuple[uuid.UUID, bool]] = []

    async def assert_app_visible(
        self, application_id: uuid.UUID, *, allow_unconfirmed: bool
    ) -> None:
        self.visible.append((application_id, allow_unconfirmed))


MANAGER = Principal(sub="m", permissions={"ticket.manage"})
PLAIN = Principal(sub="p")
ATT = uuid.uuid4()


async def _check(
    owner: AttachmentOwner,
    principal: Principal | None,
    db: ScriptedSession | None = None,
    applicant: Applicant | None = None,
    files: _Files | None = None,
) -> None:
    await _assert_owner_reader(
        db or ScriptedSession(),  # type: ignore[arg-type]
        files or _Files(),  # type: ignore[arg-type]
        owner,
        principal,
        applicant,
        ATT,
    )


@pytest.mark.parametrize("kind", ["ticket", "ticket_note"])
async def test_a_ticket_file_needs_ticket_manage(kind: str) -> None:
    owner = AttachmentOwner(kind=kind, id=uuid.uuid4())  # type: ignore[arg-type]
    for principal in (None, PLAIN):
        with pytest.raises(NotFoundError):
            await _check(owner, principal)
    await _check(owner, MANAGER, ScriptedSession(scalar=[None]))


async def test_the_file_of_a_deleted_note_is_404() -> None:
    owner = AttachmentOwner(kind="ticket_note", id=uuid.uuid4())
    with pytest.raises(NotFoundError):
        await _check(owner, MANAGER, ScriptedSession(scalar=[NOW]))


async def test_a_ticket_report_file_asks_no_note() -> None:
    db = ScriptedSession()
    await _check(AttachmentOwner(kind="ticket", id=uuid.uuid4()), MANAGER, db)
    assert db.statements == []


def _board() -> TodoBoard:
    return TodoBoard(id=uuid.uuid4(), name="B", kind="gremium", gremium_id=uuid.uuid4())


async def test_a_todo_comment_file_follows_the_board(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = AttachmentOwner(kind="todo_comment", id=uuid.uuid4())
    readable = {"yes": True}

    async def _can_read(_self: object, _board: object, _p: object) -> bool:
        return readable["yes"]

    monkeypatch.setattr(router_mod.BoardAccess, "can_read", _can_read)
    with pytest.raises(NotFoundError):
        await _check(owner, None)
    with pytest.raises(NotFoundError):
        await _check(owner, PLAIN, ScriptedSession(execute=[[]]))
    with pytest.raises(NotFoundError):
        await _check(owner, PLAIN, ScriptedSession(execute=[[(NOW, _board())]]))
    await _check(owner, PLAIN, ScriptedSession(execute=[[(None, _board())]]))
    readable["yes"] = False
    with pytest.raises(NotFoundError):
        await _check(owner, PLAIN, ScriptedSession(execute=[[(None, _board())]]))


def _comment(visibility: str) -> Comment:
    return Comment(
        id=uuid.uuid4(),
        application_id=uuid.uuid4(),
        author_kind="principal",
        body="b",
        visibility=visibility,
    )


class _Access:
    def __init__(self, *, internal: bool, owning: bool = False) -> None:
        self.can_see_internal = internal
        self.is_owning_applicant = owning


async def test_a_comment_file_follows_the_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    answers: list[object] = []

    async def _resolve(_db: object, _app: object, _p: object, _a: object) -> object:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(router_mod, "resolve_app_read", _resolve)
    public, internal = _comment("public"), _comment("internal")
    db = ScriptedSession()
    db.put(public, internal)
    # Unknown comment.
    with pytest.raises(NotFoundError):
        await _check(AttachmentOwner(kind="comment", id=uuid.uuid4()), PLAIN, db)
    # No read access to the application.
    answers.append(ForbiddenError("no"))
    with pytest.raises(NotFoundError):
        await _check(AttachmentOwner(kind="comment", id=public.id), PLAIN, db)
    # An internal comment needs can_see_internal.
    answers.append(_Access(internal=False, owning=True))
    with pytest.raises(NotFoundError):
        await _check(
            AttachmentOwner(kind="comment", id=internal.id),
            None,
            db,
            Applicant(application_id=str(internal.application_id), scope="view"),
        )
    files = _Files()
    answers.append(_Access(internal=True))
    await _check(AttachmentOwner(kind="comment", id=internal.id), PLAIN, db, files=files)
    # The public comment reaches the magic-link applicant, unconfirmed included.
    answers.append(_Access(internal=False, owning=True))
    await _check(AttachmentOwner(kind="comment", id=public.id), None, db, files=files)
    assert files.visible == [
        (internal.application_id, False),
        (public.application_id, True),
    ]
