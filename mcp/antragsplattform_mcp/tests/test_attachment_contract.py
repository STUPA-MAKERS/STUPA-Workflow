"""Contract test: the attachment tools against the real files router of the backend.

The test builds the real FastAPI app (`app.main.create_app`) and serves it in process
through `httpx.ASGITransport`. The MCP tool goes through the real `ApiClient`. So the
route path, the multipart field `file`, the form fields `field_key` and
`is_comparison_offer`, the libmagic sniff with the extension check, the response shape
and the download headers all come from the backend code and cannot drift.

The principal carries the OAuth scope cap of an MCP token: the permission set of the
default scope of this package (`config.DEFAULT_SCOPE`), resolved by the scope catalog
of the backend (`app.modules.auth.oauth`). A token without `applications:write` gets
403 on the upload, so the scope is the gate.

Only the storage and the database are fakes: the service records the upload after the
real `validate_upload` and `sanitize_filename`, and the session stub knows no creator
and no Gremium.

The test needs the backend dependencies. The CI job `mcp` does not install them, so
there the module skips. Run it from the repository root with the backend venv:

    PYTHONPATH=mcp:backend:$(echo mcp/.venv/lib/python3*/site-packages) \\
      backend/.venv/bin/python -m pytest -q \\
      mcp/antragsplattform_mcp/tests/test_attachment_contract.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import AsyncIterator, Iterator
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
from app.modules.auth import oauth  # noqa: E402
from app.modules.auth.principal import Principal  # noqa: E402
from app.modules.files import mime as backend_mime  # noqa: E402
from app.modules.files.models import MAX_ATTACHMENT_BYTES, Attachment  # noqa: E402
from app.modules.files.router import get_files_service  # noqa: E402
from app.modules.files.schemas import AttachmentOut  # noqa: E402
from app.shared.errors import UnsupportedMediaTypeError  # noqa: E402

from antragsplattform_mcp.client import ApiClient, ApiError  # noqa: E402
from antragsplattform_mcp.config import DEFAULT_SCOPE, Config  # noqa: E402
from antragsplattform_mcp.tools import _common, meetings  # noqa: E402

APP_ID = uuid4()
ATT_ID = uuid4()
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class _Service:
    """The files service with the real validation and no storage or database."""

    max_bytes = MAX_ATTACHMENT_BYTES

    def __init__(self) -> None:
        self.uploads: list[dict[str, Any]] = []

    async def upload(
        self,
        application_id: UUID,
        *,
        filename: str | None,
        data: bytes,
        by: str,
        field_key: str | None = None,
        is_comparison_offer: bool = False,
    ) -> AttachmentOut:
        try:
            sniffed = backend_mime.validate_upload(filename, data)
        except backend_mime.MimeRejected as exc:
            raise UnsupportedMediaTypeError(str(exc)) from exc
        safe = backend_mime.sanitize_filename(filename)
        self.uploads.append(
            {
                "application_id": application_id,
                "filename": filename,
                "data": data,
                "by": by,
                "field_key": field_key,
                "is_comparison_offer": is_comparison_offer,
            }
        )
        return AttachmentOut(
            id=ATT_ID,
            filename=safe,
            mime=sniffed,
            size=len(data),
            scanned=False,
            is_comparison_offer=is_comparison_offer,
        )

    async def owner_of(self, attachment_id: UUID) -> None:
        return None

    async def get_attachment(self, attachment_id: UUID) -> Attachment:
        att = Attachment(
            application_id=APP_ID,
            filename="Angebot_1.pdf",
            mime="application/pdf",
            size=len(PDF),
            storage_key="k",
        )
        att.id = attachment_id
        return att

    async def download_stream(
        self, attachment_id: UUID, *, allow_unconfirmed: bool = True
    ) -> tuple[AsyncIterator[bytes], str, str, int]:
        async def _iter() -> AsyncIterator[bytes]:
            yield PDF[:10]
            yield PDF[10:]

        return _iter(), "Angebot_1.pdf", "application/pdf", len(PDF)


class _Result:
    def all(self) -> list[object]:
        return []


class _Db:
    """No creator, no Gremium membership, no form version."""

    async def scalar(self, *_a: object, **_k: object) -> None:
        return None

    async def execute(self, *_a: object, **_k: object) -> _Result:
        return _Result()


async def _session() -> AsyncIterator[_Db]:
    yield _Db()


def _principal(scope: str) -> Principal:
    """A member with the rights of a manager, capped like an MCP token of `scope`."""
    return Principal(
        sub="agent-user",
        permissions={"application.read", "application.manage"},
        scope_permissions=oauth.scope_permissions(oauth.parse_scope(scope)),
    )


@pytest.fixture
def service() -> _Service:
    return _Service()


@pytest.fixture
def backend(service: _Service, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    app = backend_main.create_app()
    app.dependency_overrides[get_files_service] = lambda: service
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
def pdf(tmp_path: Path) -> Path:
    p = tmp_path / "Angebot 1.pdf"
    p.write_bytes(PDF)
    return p


def test_default_scope_grants_the_upload_right() -> None:
    perms = oauth.scope_permissions(oauth.parse_scope(DEFAULT_SCOPE))
    assert "application.manage" in perms
    assert "application.read" in perms
    assert DEFAULT_SCOPE == oauth.DEFAULT_SCOPE


def test_upload_through_the_real_router(backend: Any, service: _Service, pdf: Path) -> None:
    out = asyncio.run(
        meetings.upload_attachment(
            str(APP_ID), str(pdf), field_key="offer", is_comparison_offer=True
        )
    )
    assert out == {
        "id": str(ATT_ID),
        "filename": backend_mime.sanitize_filename("Angebot 1.pdf"),
        "mime": "application/pdf",
        "size": len(PDF),
        "scanned": False,
        "is_comparison_offer": True,
    }
    assert service.uploads == [
        {
            "application_id": APP_ID,
            "filename": "Angebot 1.pdf",
            "data": PDF,
            "by": "agent-user",
            "field_key": "offer",
            "is_comparison_offer": True,
        }
    ]


def test_upload_defaults_through_the_real_router(
    backend: Any, service: _Service, pdf: Path
) -> None:
    asyncio.run(meetings.upload_attachment(str(APP_ID), str(pdf)))
    assert service.uploads[0]["field_key"] is None
    assert service.uploads[0]["is_comparison_offer"] is False


def test_upload_content_mismatch_is_415(backend: Any, service: _Service, pdf: Path) -> None:
    with pytest.raises(ApiError) as err:
        asyncio.run(meetings.upload_attachment(str(APP_ID), str(pdf), filename="foto.png"))
    assert err.value.status == 415
    assert service.uploads == []


def test_upload_without_applications_write_is_403(
    backend: Any, service: _Service, pdf: Path
) -> None:
    backend.dependency_overrides[get_current_principal] = lambda: _principal("read")
    with pytest.raises(ApiError) as err:
        asyncio.run(meetings.upload_attachment(str(APP_ID), str(pdf)))
    assert err.value.status == 403
    assert service.uploads == []


def test_download_through_the_real_router(backend: Any, tmp_path: Path) -> None:
    out = asyncio.run(meetings.download_attachment(str(ATT_ID), str(tmp_path)))
    target = tmp_path / "Angebot_1.pdf"
    assert target.read_bytes() == PDF
    assert out == {
        "path": str(target.resolve()),
        "filename": "Angebot_1.pdf",
        "mime": "application/pdf",
        "size": len(PDF),
    }


def test_allowlist_matches_the_backend() -> None:
    backend_map = backend_mime._EXT_TO_MIME
    assert set(meetings.ATTACHMENT_TYPES) == set(backend_map)
    for ext, sent in meetings.ATTACHMENT_TYPES.items():
        assert sent in backend_map[ext], ext
        assert sent in backend_mime.ALLOWED_MIME_TYPES, ext
    assert meetings.ATTACHMENT_MAX_BYTES == MAX_ATTACHMENT_BYTES
