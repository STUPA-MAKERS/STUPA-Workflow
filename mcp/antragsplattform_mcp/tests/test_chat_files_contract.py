"""Contract test: chat files and sender blocks against the real routers of the backend.

The test builds the real FastAPI app (`app.main.create_app`) and serves it in process
through `httpx.ASGITransport`. The MCP tools go through the real `ApiClient`. So the
draft upload route `POST /apply/attachments` (multipart part `file`, header
`X-Draft-Token`, no ALTCHA for a principal), the draft delete, the create bodies of the
three message routes (`MessageFilesIn`: `attachmentIds`, `draftToken`, the empty-body
rule), the response models with `attachments`, the four sender-block routes and the
message-file branch of `GET /attachments/{id}/download` all come from the backend code
and cannot drift.

The principal carries the OAuth scope cap of an MCP token: the permission set of the
default scope of this package (`config.DEFAULT_SCOPE`), resolved by the scope catalog
of the backend (`app.modules.auth.oauth`). A token without `tickets:write` gets 403 on
the ticket routes and 404 on the file of a ticket note.

Only the services and the database are fakes. The draft store keeps the real
`validate_upload` and checks the token against the ids like `check_drafts`.

The test needs the backend dependencies. The CI job `mcp` does not install them, so
there the module skips. Run it from the repository root with the backend venv:

    PYTHONPATH=mcp:backend:$(echo mcp/.venv/lib/python3*/site-packages) \\
      backend/.venv/bin/python -m pytest -q \\
      mcp/antragsplattform_mcp/tests/test_chat_files_contract.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

_BACKEND = Path(__file__).resolve().parents[3] / "backend"
if _BACKEND.is_dir() and str(_BACKEND) not in sys.path:
    sys.path.append(str(_BACKEND))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:pw@localhost/antrag_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("MAGIC_LINK_SECRET", "test-magic-link-secret")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

pytest.importorskip("fastapi")
backend_main = pytest.importorskip("app.main")

from app.deps import get_current_applicant, get_current_principal, get_session  # noqa: E402
from app.modules.applications.router import (  # noqa: E402
    get_applications_service,
    get_comment_mail_sender,
)
from app.modules.applications.schemas import CommentOut  # noqa: E402
from app.modules.auth import oauth  # noqa: E402
from app.modules.auth.principal import Principal  # noqa: E402
from app.modules.files import mime as backend_mime  # noqa: E402
from app.modules.files.drafts import DRAFT_ATTACHMENTS_MISSING  # noqa: E402
from app.modules.files.router import (  # noqa: E402
    DRAFT_TOKEN_HEADER,
    get_draft_attachments,
    get_files_service,
)
from app.modules.files.schemas import (  # noqa: E402
    MAX_MESSAGE_ATTACHMENTS,
    DraftAttachmentOut,
    MessageAttachmentOut,
)
from app.modules.files.service import AttachmentOwner  # noqa: E402
from app.modules.tickets.router import get_ticket_service  # noqa: E402
from app.modules.tickets.schemas import (  # noqa: E402
    TicketBlockedSender,
    TicketDetail,
    TicketNoteOut,
    TicketRef,
    TicketReporter,
)
from app.modules.todos.router import get_todo_service  # noqa: E402
from app.modules.todos.schemas import TodoCommentOut  # noqa: E402
from app.shared.errors import (  # noqa: E402
    NotFoundError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from app.shared.filenames import sanitize_display_name  # noqa: E402
from app.shared.people import PersonRef  # noqa: E402

from antragsplattform_mcp.client import ApiClient, ApiError  # noqa: E402
from antragsplattform_mcp.config import DEFAULT_SCOPE, Config  # noqa: E402
from antragsplattform_mcp.tools import (  # noqa: E402
    _chat_files,
    _common,
    applications,
    meetings,
    tickets,
    todos,
)

TICKET_ID = uuid4()
CARD_ID = uuid4()
APP_ID = uuid4()
BLOCK_ID = uuid4()
ME = PersonRef(principal_id=uuid4(), display_name="Agent")
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108000000003a7e9b55"
    "0000000a49444154789c636000000002000148afa4710000000049454e44ae426082"
)


class _Drafts:
    """The draft store of `POST /apply/attachments` with the real MIME check."""

    class files:  # the route reads `drafts.files.max_bytes`
        max_bytes = 10 * 1024 * 1024

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.tokens: set[str] = set()
        self.deleted: list[tuple[UUID, str]] = []

    async def token_is_valid(self, token: str) -> bool:
        return token in self.tokens

    async def upload(
        self,
        *,
        token: str | None,
        filename: str | None,
        data: bytes,
        by: str,
        field_key: str | None,
    ) -> DraftAttachmentOut:
        try:
            sniffed = backend_mime.validate_upload(filename, data)
        except backend_mime.MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        if token is None:
            token = f"dt_{len(self.tokens)}"
            self.tokens.add(token)
        att_id = uuid4()
        safe = sanitize_display_name(filename)
        self.rows[att_id] = {
            "token": token,
            "filename": safe,
            "mime": sniffed,
            "size": len(data),
            "data": data,
            "by": by,
        }
        return DraftAttachmentOut(
            id=att_id,
            filename=safe,
            mime=sniffed,
            size=len(data),
            scanned=False,
            draftToken=token,
            draftExpiresAt=NOW + timedelta(days=7),
        )

    async def delete(self, attachment_id: UUID, *, token: str, actor: str) -> None:
        row = self.rows.get(attachment_id)
        if row is None or row["token"] != token:
            raise NotFoundError(f"draft {attachment_id} not found")
        del self.rows[attachment_id]
        self.deleted.append((attachment_id, token))

    def bind(self, ids: list[UUID], token: str | None) -> list[MessageAttachmentOut]:
        """Check like `check_message_drafts`, then return the message files."""
        if not ids:
            return []
        if not token:
            raise ValidationProblem(
                "Attachments need the draft token of their upload.",
                errors=[{"field": "draftToken", "msg": "required with attachmentIds"}],
            )
        missing = [i for i in ids if self.rows.get(i, {}).get("token") != token]
        if missing:
            raise ValidationProblem(
                "Some attachments are missing, expired or infected. Upload them again.",
                code=DRAFT_ATTACHMENTS_MISSING,
                errors=[{"field": f"attachmentIds.{i}", "msg": "missing"} for i in missing],
            )
        return [
            MessageAttachmentOut(
                id=i,
                filename=self.rows[i]["filename"],
                mime=self.rows[i]["mime"],
                size=self.rows[i]["size"],
                scan_state="scanning",
            )
            for i in ids
        ]


def _detail(blocked: bool) -> TicketDetail:
    return TicketDetail(
        id=TICKET_ID,
        number="T-0040",
        kind="bug",
        title="Absturz",
        status="new",
        reporter=TicketReporter(email="spam@example.org"),
        created_at=NOW,
        updated_at=NOW,
        body="x",
        sender_blocked=blocked,
    )


class _Tickets:
    def __init__(self, drafts: _Drafts) -> None:
        self.drafts = drafts
        self.notes: list[Any] = []
        self.blocked = False
        self.lifted: list[UUID] = []
        self.fail = False

    async def add_note(
        self, ticket_id: UUID, payload: Any, principal: Principal, *, pepper: str
    ) -> TicketNoteOut:
        files = self.drafts.bind(payload.attachment_ids, payload.draft_token)
        if self.fail:
            raise ValidationProblem("ticket is anonymized", code="ticket_anonymized")
        self.notes.append(payload)
        return TicketNoteOut(
            id=uuid4(),
            author=ME,
            body=payload.body,
            at=NOW,
            is_own=True,
            attachments=files,
        )

    async def block_sender(self, ticket_id: UUID, principal: Principal) -> TicketDetail:
        self.blocked = True
        return _detail(True)

    async def unblock_sender(self, ticket_id: UUID, principal: Principal) -> TicketDetail:
        self.blocked = False
        return _detail(False)

    async def blocked_senders(self) -> list[TicketBlockedSender]:
        return [
            TicketBlockedSender(
                id=BLOCK_ID,
                kind="email",
                email="spam@example.org",
                blocked_by=ME,
                blocked_at=NOW,
                source_ticket=TicketRef(id=TICKET_ID, number="T-0040"),
                hit_count=3,
            )
        ]

    async def delete_block(self, block_id: UUID) -> None:
        if block_id != BLOCK_ID:
            raise NotFoundError("block not found")
        self.lifted.append(block_id)


class _Todos:
    outbox: list[object] = []

    def __init__(self, drafts: _Drafts) -> None:
        self.drafts = drafts
        self.calls: list[dict[str, Any]] = []

    async def add_comment(
        self,
        card_id: UUID,
        body: str,
        mentions: list[UUID],
        principal: Principal,
        *,
        attachment_ids: list[UUID],
        draft_token: str | None,
        pepper: str,
    ) -> TodoCommentOut:
        files = self.drafts.bind(attachment_ids, draft_token)
        self.calls.append({"card_id": card_id, "body": body, "mentions": mentions})
        return TodoCommentOut(
            id=uuid4(), author=ME, body=body, at=NOW, is_own=True, attachments=files
        )


class _Applications:
    def __init__(self, drafts: _Drafts) -> None:
        self.drafts = drafts
        self.calls: list[dict[str, Any]] = []

    async def add_comment(
        self,
        application_id: UUID,
        *,
        author: str | None,
        author_kind: str,
        body: str,
        visibility: str,
        allow_unconfirmed: bool,
        attachment_ids: list[UUID],
        draft_token: str | None,
        pepper: str,
    ) -> CommentOut:
        files = self.drafts.bind(attachment_ids, draft_token)
        self.calls.append({"application_id": application_id, "visibility": visibility})
        return CommentOut(
            id=uuid4(),
            author=author,
            authorKind="principal",
            body=body,
            visibility=visibility,  # pyright: ignore[reportArgumentType]
            at=NOW,
            attachments=files,
        )


class _Files:
    """The message-file branch of the download route."""

    def __init__(self) -> None:
        self.note_file = uuid4()

    async def owner_of(self, attachment_id: UUID) -> AttachmentOwner | None:
        if attachment_id == self.note_file:
            return AttachmentOwner(kind="ticket_note", id=uuid4())
        return None

    async def message_download_stream(
        self, attachment_id: UUID
    ) -> tuple[AsyncIterator[bytes], str, str, int]:
        async def _iter() -> AsyncIterator[bytes]:
            yield PDF[:7]
            yield PDF[7:]

        return _iter(), "Protokoll.pdf", "application/pdf", len(PDF)


class _Result:
    def all(self) -> list[object]:
        return []

    def first(self) -> None:
        return None


class _Db:
    """No creator, no Gremium membership, no deleted note."""

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None

    async def execute(self, *_a: object, **_k: object) -> _Result:
        return _Result()


async def _session() -> AsyncIterator[_Db]:
    yield _Db()


async def _no_mails(*_a: object, **_k: object) -> None:
    return None


def _principal(scope: str) -> Principal:
    """A manager of tickets and applications, capped like an MCP token of `scope`."""
    return Principal(
        sub="agent-user",
        permissions={"ticket.manage", "application.read", "application.manage"},
        scope_permissions=oauth.scope_permissions(oauth.parse_scope(scope)),
    )


@pytest.fixture
def drafts() -> _Drafts:
    return _Drafts()


@pytest.fixture
def svc(drafts: _Drafts) -> dict[str, Any]:
    return {
        "tickets": _Tickets(drafts),
        "todos": _Todos(drafts),
        "applications": _Applications(drafts),
        "files": _Files(),
    }


@pytest.fixture
def backend(drafts: _Drafts, svc: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    app = backend_main.create_app()
    app.dependency_overrides[get_draft_attachments] = lambda: drafts
    app.dependency_overrides[get_ticket_service] = lambda: svc["tickets"]
    app.dependency_overrides[get_todo_service] = lambda: svc["todos"]
    app.dependency_overrides[get_applications_service] = lambda: svc["applications"]
    app.dependency_overrides[get_files_service] = lambda: svc["files"]
    app.dependency_overrides[get_comment_mail_sender] = lambda: _no_mails
    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_applicant] = lambda: None
    app.dependency_overrides[get_current_principal] = lambda: _principal(DEFAULT_SCOPE)

    client = ApiClient(Config(base_url="http://testserver", scope=DEFAULT_SCOPE))
    client._client = httpx.AsyncClient(
        base_url="http://testserver/api", transport=httpx.ASGITransport(app=app)
    )

    async def _token(*, force_login: bool = False) -> str:
        return "apat_test"

    monkeypatch.setattr(client, "_token", _token)
    monkeypatch.setattr(_common, "_client", client)
    yield app


@pytest.fixture
def files(tmp_path: Path) -> list[Path]:
    a = tmp_path / "Angebot 1.pdf"
    a.write_bytes(PDF)
    b = tmp_path / "Foto.png"
    b.write_bytes(PNG)
    return [a, b]


def test_default_scope_reaches_every_route() -> None:
    perms = oauth.scope_permissions(oauth.parse_scope(DEFAULT_SCOPE))
    assert {"ticket.manage", "todo.write", "application.read"} <= perms
    assert DEFAULT_SCOPE == oauth.DEFAULT_SCOPE


def test_file_cap_matches_the_backend() -> None:
    assert _chat_files.MAX_MESSAGE_FILES == MAX_MESSAGE_ATTACHMENTS
    assert _chat_files.DRAFT_TOKEN_HEADER == DRAFT_TOKEN_HEADER


def test_ticket_note_with_files(
    backend: Any, drafts: _Drafts, svc: dict[str, Any], files: list[Path]
) -> None:
    out = asyncio.run(tickets.tickets_note(str(TICKET_ID), "", [str(p) for p in files]))
    assert [a["filename"] for a in out["attachments"]] == [
        sanitize_display_name("Angebot 1.pdf"),
        "Foto.png",
    ]
    assert [a["mime"] for a in out["attachments"]] == ["application/pdf", "image/png"]
    assert {a["scanState"] for a in out["attachments"]} == {"scanning"}
    assert "draftToken" not in out
    # One token for the whole message: the second upload sent the header.
    assert drafts.tokens == {"dt_0"}
    assert {row["by"] for row in drafts.rows.values()} == {"agent-user"}
    note = svc["tickets"].notes[0]
    assert note.body == ""
    assert note.draft_token == "dt_0"
    assert [str(i) for i in note.attachment_ids] == [a["id"] for a in out["attachments"]]


def test_ticket_note_without_files_sends_no_upload(
    backend: Any, drafts: _Drafts, svc: dict[str, Any]
) -> None:
    out = asyncio.run(tickets.tickets_note(str(TICKET_ID), "Erledigt."))
    assert out["attachments"] == []
    assert drafts.rows == {}
    assert svc["tickets"].notes[0].attachment_ids == []


def test_empty_note_without_files_is_422(backend: Any) -> None:
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note(str(TICKET_ID), "  "))
    assert err.value.status == 422


def test_failed_post_deletes_the_drafts(
    backend: Any, drafts: _Drafts, svc: dict[str, Any], files: list[Path]
) -> None:
    svc["tickets"].fail = True
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note(str(TICKET_ID), "x", [str(p) for p in files]))
    assert err.value.status == 422
    assert drafts.rows == {}
    assert [token for _, token in drafts.deleted] == ["dt_0", "dt_0"]


def test_mismatched_file_is_415_and_deletes_the_first(
    backend: Any, drafts: _Drafts, files: list[Path], tmp_path: Path
) -> None:
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(PNG)
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note(str(TICKET_ID), "x", [str(files[0]), str(fake)]))
    assert err.value.status == 415
    assert drafts.rows == {}
    assert len(drafts.deleted) == 1


def test_todo_comment_with_files(backend: Any, svc: dict[str, Any], files: list[Path]) -> None:
    mention = str(uuid4())
    out = asyncio.run(todos.todo_comment(str(CARD_ID), "@Agent bitte", [mention], [str(files[1])]))
    assert [a["filename"] for a in out["attachments"]] == ["Foto.png"]
    assert out["attachments"][0]["scanState"] == "scanning"
    assert svc["todos"].calls == [
        {"card_id": CARD_ID, "body": "@Agent bitte", "mentions": [UUID(mention)]}
    ]


def test_application_comment_with_files(
    backend: Any, svc: dict[str, Any], files: list[Path]
) -> None:
    out = asyncio.run(
        applications.comment_application(str(APP_ID), "", "internal", [str(p) for p in files])
    )
    assert out["visibility"] == "internal"
    assert len(out["attachments"]) == 2
    assert svc["applications"].calls == [{"application_id": APP_ID, "visibility": "internal"}]


def test_block_unblock_and_list(backend: Any, svc: dict[str, Any]) -> None:
    blocked = asyncio.run(tickets.tickets_block_sender(str(TICKET_ID)))
    assert blocked["senderBlocked"] is True
    assert svc["tickets"].blocked is True
    listed = asyncio.run(tickets.tickets_blocked_senders())
    assert listed[0]["id"] == str(BLOCK_ID)
    assert listed[0]["hitCount"] == 3
    assert listed[0]["sourceTicket"] == {"id": str(TICKET_ID), "number": "T-0040"}
    unblocked = asyncio.run(tickets.tickets_unblock_sender(str(TICKET_ID)))
    assert unblocked["senderBlocked"] is False
    assert asyncio.run(tickets.tickets_delete_blocked_sender(str(BLOCK_ID))) == {"status": "ok"}
    assert svc["tickets"].lifted == [BLOCK_ID]
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_delete_blocked_sender(str(uuid4())))
    assert err.value.status == 404


def test_download_a_note_file(backend: Any, svc: dict[str, Any], tmp_path: Path) -> None:
    out = asyncio.run(meetings.download_attachment(str(svc["files"].note_file), str(tmp_path)))
    assert (tmp_path / "Protokoll.pdf").read_bytes() == PDF
    assert out["mime"] == "application/pdf"
    assert out["size"] == len(PDF)


def test_without_tickets_write_the_ticket_routes_are_closed(
    backend: Any,
    svc: dict[str, Any],
    drafts: _Drafts,
    files: list[Path],
    tmp_path: Path,
) -> None:
    backend.dependency_overrides[get_current_principal] = lambda: _principal("read")
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_block_sender(str(TICKET_ID)))
    assert err.value.status == 403
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_blocked_senders())
    assert err.value.status == 403
    with pytest.raises(ApiError) as err:
        asyncio.run(tickets.tickets_note(str(TICKET_ID), "x", [str(files[0])]))
    assert err.value.status == 403
    # The draft went up (the upload route takes any principal) and was deleted again.
    assert drafts.rows == {}
    assert len(drafts.deleted) == 1
    with pytest.raises(ApiError) as err:
        asyncio.run(meetings.download_attachment(str(svc["files"].note_file), str(tmp_path)))
    assert err.value.status == 404
