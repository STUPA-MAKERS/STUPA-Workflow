"""Router tests of the media API: auth, status codes and the image headers.

The routes run through `create_app` with the full middleware stack, so the tests
also prove that the image headers win over the default API headers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_applicant, get_current_principal, get_session
from app.main import create_app
from app.modules.auth import oauth
from app.modules.auth.principal import Applicant, Principal
from app.modules.media.router import (
    IMAGE_CSP,
    UPLOAD_SCOPES,
    get_media_service,
    get_public_protocols,
)
from app.modules.media.service import MediaService
from app.settings import get_settings, load_settings
from app.shared.errors import NotFoundError
from tests._support.media_fakes import MediaSession, MediaStorage, add_image

from ._images import SVG, animation, encode, jpeg_with_gps, opened

PROTOCOL_ID = uuid.uuid4()


class _PublicProtocols:
    """Fake of the visibility read: one visible protocol with a set of image ids."""

    def __init__(self) -> None:
        self.ids: set[uuid.UUID] = set()

    async def public_image_ids(self, protocol_id: uuid.UUID) -> set[uuid.UUID]:
        if protocol_id != PROTOCOL_ID:
            raise NotFoundError("protocol not found")
        return self.ids


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
def app(session: MediaSession, storage: MediaStorage, public: _PublicProtocols) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_session] = _no_session
    application.dependency_overrides[get_media_service] = lambda: MediaService(
        session,  # pyright: ignore[reportArgumentType]
        storage=storage,
        max_bytes=10 * 1024 * 1024,
    )
    application.dependency_overrides[get_public_protocols] = lambda: public
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as_principal(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="p", permissions=set())


def _as_applicant(app: FastAPI) -> None:
    app.dependency_overrides[get_current_applicant] = lambda: Applicant(
        application_id=str(uuid.uuid4()), scope="view"
    )


def _upload(client: TestClient, data: bytes, name: str = "bild.png") -> object:
    return client.post("/api/media/images", files={"file": (name, data, "image/png")})


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (encode("PNG"), "image/png"),
        (encode("JPEG"), "image/jpeg"),
        (encode("GIF"), "image/gif"),
        (encode("WEBP"), "image/webp"),
        (animation("GIF"), "image/gif"),
    ],
)
def test_upload_each_format_201(app: FastAPI, client: TestClient, data: bytes, mime: str) -> None:
    _as_principal(app)
    r = client.post("/api/media/images", files={"file": ("x.bin", data, "text/plain")})
    assert r.status_code == 201
    body = r.json()
    assert set(body) == {"id", "url", "mime", "width", "height", "size"}
    assert body["url"] == f"/api/media/images/{body['id']}"
    assert (body["mime"], body["width"], body["height"]) == (mime, 40, 20)


def test_upload_strips_the_gps_block(
    app: FastAPI, client: TestClient, storage: MediaStorage
) -> None:
    _as_principal(app)
    r = client.post("/api/media/images", files={"file": ("p.jpg", jpeg_with_gps(), "image/jpeg")})
    assert r.status_code == 201
    data, _ = storage.objects[f"media/images/{r.json()['id']}"]
    assert b"SecretCam" not in data
    assert not opened(data).getexif()


def test_upload_scales_down(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)
    r = client.post(
        "/api/media/images",
        files={"file": ("w.png", encode("PNG", size=(5000, 100)), "image/png")},
    )
    assert r.status_code == 201
    assert (r.json()["width"], r.json()["height"]) == (2400, 48)


@pytest.mark.parametrize("data", [SVG, b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n", b"just text"])
def test_upload_of_no_image_is_415(app: FastAPI, client: TestClient, data: bytes) -> None:
    _as_principal(app)
    r = client.post("/api/media/images", files={"file": ("x.png", data, "image/png")})
    assert r.status_code == 415
    assert r.headers["content-type"].startswith("application/problem+json")


def test_upload_too_large_is_413(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)
    app.dependency_overrides[get_media_service] = lambda: MediaService(
        MediaSession(),  # pyright: ignore[reportArgumentType]
        storage=MediaStorage(),
        max_bytes=50,
    )
    r = client.post(
        "/api/media/images", files={"file": ("x.png", encode("PNG", size=(200, 200)), "image/png")}
    )
    assert r.status_code == 413
    assert r.headers["content-type"].startswith("application/problem+json")


def test_upload_body_cap_is_413(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)
    app.dependency_overrides[get_settings] = lambda: load_settings(markdown_image_max_bytes=1)
    r = client.post(
        "/api/media/images",
        files={"file": ("x.png", b"x" * (128 * 1024), "image/png")},
    )
    assert r.status_code == 413


def test_upload_anonymous_is_401(client: TestClient) -> None:
    r = _upload(client, encode("PNG"))
    assert r.status_code == 401  # pyright: ignore[reportAttributeAccessIssue]


def test_upload_applicant_is_401(app: FastAPI, client: TestClient) -> None:
    _as_applicant(app)
    r = _upload(client, encode("PNG"))
    assert r.status_code == 401  # pyright: ignore[reportAttributeAccessIssue]


def _as_token(app: FastAPI, *scopes: str) -> None:
    perms = oauth.scope_permissions(list(scopes))
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set(), scope_permissions=perms
    )


def test_upload_with_a_read_token_is_403(app: FastAPI, client: TestClient) -> None:
    _as_token(app, "read", "budget:write")
    r = client.post("/api/media/images", files={"file": ("a.png", encode("PNG"), "image/png")})
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("scope", list(UPLOAD_SCOPES))
def test_upload_with_a_write_token_is_201(app: FastAPI, client: TestClient, scope: str) -> None:
    _as_token(app, "read", scope)
    r = client.post("/api/media/images", files={"file": ("a.png", encode("PNG"), "image/png")})
    assert r.status_code == 201


def test_upload_without_storage_is_503(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)
    app.dependency_overrides[get_media_service] = lambda: MediaService(
        MediaSession(),  # pyright: ignore[reportArgumentType]
        storage=None,
    )
    r = _upload(client, encode("PNG"))
    assert r.status_code == 503  # pyright: ignore[reportAttributeAccessIssue]


def test_default_wiring_reads_the_settings_and_the_app_storage() -> None:
    """Answer 503 with the default wiring when the app state has no object storage."""
    application = create_app()
    application.dependency_overrides[get_session] = _no_session
    application.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="p", permissions=set()
    )
    r = TestClient(application).post(
        "/api/media/images", files={"file": ("x.png", encode("PNG"), "image/png")}
    )
    assert r.status_code == 503


def _assert_image_headers(headers: object, cache: str) -> None:
    """Assert the inline, nosniff and sandbox headers of an image answer."""
    h = headers
    assert h["content-type"] == "image/png"  # pyright: ignore[reportIndexIssue]
    assert h["content-disposition"] == "inline"  # pyright: ignore[reportIndexIssue]
    assert h["x-content-type-options"] == "nosniff"  # pyright: ignore[reportIndexIssue]
    assert h.get_list("content-security-policy") == [IMAGE_CSP]  # pyright: ignore[reportAttributeAccessIssue]
    assert h["cache-control"] == cache  # pyright: ignore[reportIndexIssue]


def test_get_as_principal(
    app: FastAPI, client: TestClient, session: MediaSession, storage: MediaStorage
) -> None:
    image_id = add_image(session, storage, b"PNGBYTES")
    _as_principal(app)
    r = client.get(f"/api/media/images/{image_id}")
    assert r.status_code == 200
    assert r.content == b"PNGBYTES"
    assert r.headers["content-length"] == "8"
    _assert_image_headers(r.headers, "private, max-age=31536000, immutable")


def test_get_as_applicant(
    app: FastAPI, client: TestClient, session: MediaSession, storage: MediaStorage
) -> None:
    image_id = add_image(session, storage, b"PNGBYTES")
    _as_applicant(app)
    assert client.get(f"/api/media/images/{image_id}").status_code == 200


def test_get_anonymous_is_401(
    client: TestClient, session: MediaSession, storage: MediaStorage
) -> None:
    image_id = add_image(session, storage, b"PNGBYTES")
    r = client.get(f"/api/media/images/{image_id}")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")


def test_get_unknown_is_404(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)
    r = client.get(f"/api/media/images/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_get_bad_id_is_422(app: FastAPI, client: TestClient) -> None:
    _as_principal(app)
    assert client.get("/api/media/images/not-a-uuid").status_code == 422


def test_public_image_of_a_visible_protocol(
    client: TestClient, session: MediaSession, storage: MediaStorage, public: _PublicProtocols
) -> None:
    image_id = add_image(session, storage, b"PNGBYTES")
    public.ids = {image_id}
    r = client.get(f"/api/public/protocols/{PROTOCOL_ID}/images/{image_id}")
    assert r.status_code == 200
    assert r.content == b"PNGBYTES"
    _assert_image_headers(r.headers, "public, max-age=300")
    assert r.headers["x-robots-tag"] == "noindex"


def test_public_image_not_referenced_is_404(
    client: TestClient, session: MediaSession, storage: MediaStorage, public: _PublicProtocols
) -> None:
    image_id = add_image(session, storage, b"PNGBYTES")
    public.ids = {uuid.uuid4()}
    r = client.get(f"/api/public/protocols/{PROTOCOL_ID}/images/{image_id}")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")


def test_public_image_of_a_hidden_protocol_is_404(
    client: TestClient, session: MediaSession, storage: MediaStorage
) -> None:
    image_id = add_image(session, storage, b"PNGBYTES")
    r = client.get(f"/api/public/protocols/{uuid.uuid4()}/images/{image_id}")
    assert r.status_code == 404


def test_public_image_referenced_but_not_stored_is_404(
    client: TestClient, public: _PublicProtocols
) -> None:
    image_id = uuid.uuid4()
    public.ids = {image_id}
    r = client.get(f"/api/public/protocols/{PROTOCOL_ID}/images/{image_id}")
    assert r.status_code == 404


def test_public_wiring_uses_the_public_protocol_service() -> None:
    service = get_public_protocols(object())  # pyright: ignore[reportArgumentType]
    assert service.storage is None
