"""Embedded PDFs of a protocol: the check, the service, the routes and the render input."""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.deps import get_current_applicant, get_current_principal, get_session
from app.main import create_app
from app.modules.auth.principal import Applicant, Principal
from app.modules.files import scanner as scanner_mod
from app.modules.files.scanner import ScanVerdict
from app.modules.media import service as service_mod
from app.modules.media.documents import DocumentRejected, DocumentTooLarge, check_pdf
from app.modules.media.refs import document_ids_in, document_path
from app.modules.media.router import DOCUMENT_PREVIEW_CSP, get_media_service
from app.modules.media.service import MediaService, document_asset_name
from app.modules.protocol.public import PublicProtocolService, PublicSnapshot, PublicTop
from app.modules.protocol.public_images_router import get_public_protocols
from app.modules.protocol.router import get_protocol_service
from app.settings import Settings, get_settings, load_settings
from app.shared.errors import (
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from tests._support.media_fakes import MediaSession, MediaStorage, add_document

PROTOCOL_ID = uuid.uuid4()
MEETING_ID = uuid.uuid4()


def make_pdf(pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if password is not None:
        writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _service(
    session: MediaSession | None = None,
    storage: MediaStorage | None = None,
    **kwargs: Any,
) -> MediaService:
    return MediaService(
        session or MediaSession(),  # pyright: ignore[reportArgumentType]
        storage=storage,
        settings=get_settings(),
        **kwargs,
    )


# -- check (spec 000869) -----------------------------------------------------


def test_check_counts_the_pages_of_a_pdf() -> None:
    assert check_pdf(make_pdf(3)).pages == 3


@pytest.mark.parametrize(
    "data",
    [b"just text", b"\x89PNG\r\n\x1a\n" + b"0" * 64, b"%PDF-1.7\nkaputt", make_pdf(password="x")],
)
def test_check_refuses_no_pdf_a_broken_and_an_encrypted_pdf(data: bytes) -> None:
    """§000869: only a readable, unencrypted PDF by its content."""
    with pytest.raises(DocumentRejected):
        check_pdf(data)


def test_check_refuses_more_than_the_page_limit() -> None:
    """§000869: at most 100 pages."""
    with pytest.raises(DocumentTooLarge):
        check_pdf(make_pdf(4), max_pages=3)


# -- refs --------------------------------------------------------------------


def test_document_ids_come_in_the_order_of_the_first_reference() -> None:
    """§000862: `[name](/api/media/documents/<uuid>)`."""
    a, b = uuid.uuid4(), uuid.uuid4()
    text = f"[B]({document_path(b)}) [A]({document_path(a)}) [B2]({document_path(b)})"
    assert document_ids_in(text, None, f"[x]({document_path(a)}/x)") == [b, a]


# -- service -----------------------------------------------------------------


async def test_upload_stores_the_pdf_with_its_name_and_pages() -> None:
    session, storage = MediaSession(), MediaStorage()
    out = await _service(session, storage).upload_document(make_pdf(2), "../Haushalt\nplan.pdf")
    assert out.url == f"/api/media/documents/{out.id}"
    assert (out.name, out.pages) == ("Haushaltplan.pdf", 2)
    assert storage.objects[f"media/documents/{out.id}"][1] == "application/pdf"
    assert session.committed == 1


async def test_upload_refusals_map_to_415_and_413() -> None:
    """§000869: a non-PDF and an encrypted PDF give 415, a too large PDF gives 413."""
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(storage=MediaStorage()).upload_document(b"no pdf", "x.pdf")
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(storage=MediaStorage()).upload_document(make_pdf(password="x"), "x.pdf")
    with pytest.raises(PayloadTooLargeError):
        await _service(storage=MediaStorage(), max_document_bytes=10).upload_document(
            make_pdf(), "x.pdf"
        )
    with pytest.raises(PayloadTooLargeError):
        await _service(storage=MediaStorage()).upload_document(make_pdf(101), "x.pdf")


class _InfectedScanner:
    async def scan(self, data: bytes) -> ScanVerdict:
        return ScanVerdict(clean=False, signature="Eicar-Test-Signature")


async def test_upload_scans_before_pypdf_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """§000869: the ClamAV scan runs before the server reads the PDF."""

    def _infected(_settings: Settings) -> _InfectedScanner:
        return _InfectedScanner()

    def _never(_data: bytes) -> object:
        raise AssertionError("an infected upload must not reach pypdf")

    monkeypatch.setattr(scanner_mod, "build_scanner", _infected)
    monkeypatch.setattr(service_mod, "check_pdf", _never)
    storage = MediaStorage()
    with pytest.raises(UnsupportedMediaTypeError, match="Eicar"):
        await _service(storage=storage).upload_document(make_pdf(), "x.pdf")
    assert storage.objects == {}


async def test_info_and_open_of_an_unknown_pdf_are_404() -> None:
    with pytest.raises(NotFoundError):
        await _service(storage=MediaStorage()).document_info(uuid.uuid4())
    with pytest.raises(NotFoundError):
        await _service(storage=MediaStorage()).open_document(uuid.uuid4())


def _refs(*ids: uuid.UUID) -> str:
    return " ".join(f"[d]({document_path(i)})" for i in ids)


async def test_render_documents_keep_the_order_and_the_budget() -> None:
    """§000868: the 21st PDF and a PDF past the page sum are left out."""
    session, storage = MediaSession(), MediaStorage()
    ids = [add_document(session, storage, b"%PDF" + bytes([k])) for k in range(21)]
    assets = await _service(session, storage).render_documents(_refs(*reversed(ids)))
    assert list(assets) == [document_asset_name(i) for i in reversed(ids)][:20]

    big = add_document(session, storage, b"%PDFbig", pages=299)
    small = add_document(session, storage, b"%PDFsmall", pages=2)
    last = add_document(session, storage, b"%PDFlast", pages=1)
    assets = await _service(session, storage).render_documents(_refs(big, small, last))
    assert list(assets) == [document_asset_name(big), document_asset_name(last)]


async def test_render_documents_never_fail_for_a_missing_pdf() -> None:
    """§000868: a missing PDF is no asset, and the render goes on."""
    session, storage = MediaSession(), MediaStorage()
    gone = add_document(session, storage, b"%PDFgone")
    storage.objects.clear()
    service = _service(session, storage)
    assert await service.render_documents(_refs(gone, uuid.uuid4())) == {}
    assert await _service(session, None).render_documents(_refs(gone)) == {}
    assert await service.render_documents("no pdf here") == {}


# -- public render input (spec 000867) ----------------------------------------


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _PublicSession:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def execute(self, _stmt: object) -> _Result:
        return _Result(self.row)


async def test_public_document_ids_leave_out_a_non_public_top() -> None:
    """§000867: a PDF of a non-public TOP is not in the public version."""
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    snapshot = PublicSnapshot(
        tops=[
            PublicTop(number=1, title="Offen", markdown=_refs(a)),
            PublicTop(number=2, title="Geheim", nonPublic=True, markdown=_refs(b)),
        ],
        markdown=_refs(c),
    )
    row = (
        SimpleNamespace(
            id=PROTOCOL_ID, sent_at=None, public_content=snapshot.model_dump(by_alias=True)
        ),
        SimpleNamespace(title="Sitzung", date=None),
        SimpleNamespace(id=uuid.uuid4(), name="StuPa", slug="stupa"),
    )
    svc = PublicProtocolService(_PublicSession(row))  # pyright: ignore[reportArgumentType]
    assert await svc.public_document_ids(PROTOCOL_ID) == {a, c}


# -- routes ------------------------------------------------------------------


class _PublicProtocols:
    def __init__(self) -> None:
        self.ids: set[uuid.UUID] = set()

    async def public_document_ids(self, protocol_id: uuid.UUID) -> set[uuid.UUID]:
        if protocol_id != PROTOCOL_ID:
            raise NotFoundError("protocol not found")
        return self.ids


class _Protocols:
    def __init__(self) -> None:
        self.allowed = True

    async def authorize_write_meeting(self, meeting_id: uuid.UUID, _principal: object) -> None:
        if meeting_id != MEETING_ID:
            raise NotFoundError("meeting not found")
        if not self.allowed:
            raise ForbiddenError("not allowed to write this meeting's minutes")


async def _no_session() -> AsyncIterator[object]:
    yield object()


@pytest.fixture
def session() -> MediaSession:
    return MediaSession()


@pytest.fixture
def storage() -> MediaStorage:
    return MediaStorage()


@pytest.fixture
def public() -> _PublicProtocols:
    return _PublicProtocols()


@pytest.fixture
def protocols() -> _Protocols:
    return _Protocols()


@pytest.fixture
def app(
    session: MediaSession, storage: MediaStorage, public: _PublicProtocols, protocols: _Protocols
) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_session] = _no_session
    application.dependency_overrides[get_media_service] = lambda: _service(session, storage)
    application.dependency_overrides[get_public_protocols] = lambda: public
    application.dependency_overrides[get_protocol_service] = lambda: protocols
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_principal(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p", permissions=set())


def _upload(client: TestClient, data: bytes, meeting: uuid.UUID = MEETING_ID) -> Any:
    return client.post(
        f"/api/meetings/{meeting}/documents",
        files={"file": ("Angebot.pdf", data, "application/pdf")},
    )


def test_upload_route_201_for_a_writer(app: FastAPI, client: TestClient) -> None:
    """§000862: a person who can write the protocol uploads a PDF."""
    _as_principal(app)
    r = _upload(client, make_pdf(2))
    assert r.status_code == 201
    body = r.json()
    assert (body["name"], body["pages"]) == ("Angebot.pdf", 2)
    assert body["url"] == f"/api/media/documents/{body['id']}"


def test_upload_route_refuses_who_cannot_write(
    app: FastAPI, client: TestClient, protocols: _Protocols
) -> None:
    """§000862: only a person who can write the text uploads."""
    assert _upload(client, make_pdf()).status_code == 401
    _as_principal(app)
    protocols.allowed = False
    assert _upload(client, make_pdf()).status_code == 403
    assert _upload(client, make_pdf(), uuid.uuid4()).status_code == 404


def test_upload_route_415_and_413(app: FastAPI, client: TestClient) -> None:
    """§000869: a non-PDF and an encrypted PDF give 415, over the limits 413."""
    _as_principal(app)
    assert _upload(client, b"no pdf at all").status_code == 415
    assert _upload(client, make_pdf(password="x")).status_code == 415
    assert _upload(client, make_pdf(101)).status_code == 413
    app.dependency_overrides[get_settings] = lambda: load_settings(markdown_document_max_bytes=1)
    r = _upload(client, b"x" * (128 * 1024))
    assert r.status_code == 413


def test_download_is_an_attachment_and_inline_is_framable(
    app: FastAPI, client: TestClient, session: MediaSession, storage: MediaStorage
) -> None:
    """§000869: the download streams through the API with the attachment PDF headers."""
    doc = add_document(session, storage, b"%PDF-data", name="Haushaltsplan.pdf", pages=4)
    assert client.get(f"/api/media/documents/{doc}").status_code == 401
    _as_principal(app)
    r = client.get(f"/api/media/documents/{doc}")
    assert r.status_code == 200
    assert r.content == b"%PDF-data"
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-content-type-options"] == "nosniff"
    inline = client.get(f"/api/media/documents/{doc}?inline=true")
    assert inline.headers["content-disposition"].startswith("inline;")
    assert inline.headers["content-security-policy"] == DOCUMENT_PREVIEW_CSP
    assert inline.headers["x-frame-options"] == "SAMEORIGIN"
    info = client.get(f"/api/media/documents/{doc}/info").json()
    assert (info["name"], info["pages"]) == ("Haushaltsplan.pdf", 4)


def test_an_applicant_reads_a_pdf(
    app: FastAPI, client: TestClient, session: MediaSession, storage: MediaStorage
) -> None:
    doc = add_document(session, storage, b"%PDF-data")
    app.dependency_overrides[get_current_applicant] = lambda: Applicant(
        application_id=str(uuid.uuid4())
    )
    assert client.get(f"/api/media/documents/{doc}").status_code == 200


def test_public_download_only_for_a_pdf_of_the_public_text(
    client: TestClient, session: MediaSession, storage: MediaStorage, public: _PublicProtocols
) -> None:
    """§000867: the public download of a PDF of a non-public TOP answers 404."""
    shown = add_document(session, storage, b"%PDF-shown", pages=2)
    hidden = add_document(session, storage, b"%PDF-hidden")
    public.ids = {shown}
    base = f"/api/public/protocols/{PROTOCOL_ID}/documents"
    assert client.get(f"{base}/{shown}").content == b"%PDF-shown"
    assert client.get(f"{base}/{shown}/info").json()["pages"] == 2
    assert client.get(f"{base}/{hidden}").status_code == 404
    assert client.get(f"{base}/{hidden}/info").status_code == 404
    other = f"/api/public/protocols/{uuid.uuid4()}/documents/{shown}"
    assert client.get(other).status_code == 404
