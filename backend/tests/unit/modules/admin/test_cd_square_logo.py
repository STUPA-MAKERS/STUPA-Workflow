"""The square CD logo: header parser, upload policy, service, resolver and routes.

The tests cover six areas.

1. `raster_dimensions` reads the pixel size of PNG, JPEG and WebP (VP8, VP8L,
   VP8X) from the header and gives ``None`` for every truncated header.
2. `check_square_logo`: raster only, square within 1 %, at least 256 px, 2 MB.
3. `CdVariantService.upload_logo` in the square slot: the first upload, the
   replacement of the old row and object, and the refusals.
4. The inline lookups: `admin_square_logo`, `gremium_square_logo`,
   `square_logo_bytes`, and the resolver that never hands the square slot to
   the render service.
5. `can_view_gremium`: member, `gremium.view_all`, admin, a scoped token.
6. The routes `GET /api/gremien/{id}/logo` and
   `GET /api/admin/cd-variant-logos/{id}/square`: headers, ETag and 304, and the
   404 for a caller who may not see the Gremium.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin import gremium_roles
from app.modules.admin import router as admin_router
from app.modules.admin.cd_logos import (
    MAX_CD_LOGO_BYTES,
    SQUARE_LOGO_MAX_PX,
    SQUARE_LOGO_MIN_PX,
    check_square_logo,
)
from app.modules.admin.cd_resolver import resolve_cd_variant_by_key
from app.modules.admin.gremium_roles import GREMIUM_VIEW_ALL, can_view_gremium
from app.modules.admin.image_size import raster_dimensions
from app.modules.admin.models import CdVariantLogo
from app.modules.admin.router import get_cd_variant_service
from app.modules.admin.service.cd_variants import SquareLogoRef
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
    ValidationProblem,
)
from tests._support.files_fakes import FailingStorage, FakeStorage
from tests.unit.modules.admin.test_cd_variants import (
    FakeSession,
    audit_results,
    logo_row,
    res,
    svc,
    variant_row,
)

# --- image builders ---------------------------------------------------------


def png(width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )


def jpeg(width: int, height: int, *, sof: int = 0xC0) -> bytes:
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00" + b"\x00" * 9
    frame = (
        bytes([0xFF, sof])
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03"
        + b"\x00" * 9
    )
    return b"\xff\xd8" + app0 + frame


def _riff(chunk: bytes, body: bytes) -> bytes:
    payload = b"WEBP" + chunk + len(body).to_bytes(4, "little") + body
    return b"RIFF" + len(payload).to_bytes(4, "little") + payload


def webp_vp8(width: int, height: int) -> bytes:
    body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + width.to_bytes(2, "little")
    return _riff(b"VP8 ", body + height.to_bytes(2, "little"))


def webp_vp8l(width: int, height: int) -> bytes:
    bits = (width - 1) | ((height - 1) << 14)
    return _riff(b"VP8L", b"\x2f" + bits.to_bytes(4, "little"))


def webp_vp8x(width: int, height: int) -> bytes:
    body = b"\x00" * 4 + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return _riff(b"VP8X", body)


# --- 1. header parser -------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "size"),
    [
        (png(512, 300), (512, 300)),
        (jpeg(640, 480), (640, 480)),
        (jpeg(256, 256, sof=0xC2), (256, 256)),  # progressive
        (webp_vp8(300, 299), (300, 299)),
        (webp_vp8l(1024, 1024), (1024, 1024)),
        (webp_vp8x(4000, 4000), (4000, 4000)),
    ],
)
def test_raster_dimensions_reads_the_header(data: bytes, size: tuple[int, int]) -> None:
    assert raster_dimensions(data) == size


def test_jpeg_skips_fill_bytes_and_standalone_markers() -> None:
    data = jpeg(300, 300)
    # A fill byte and an RST marker in front of the APP0 segment.
    data = data[:2] + b"\xff" + b"\xff\xd0" + data[2:]
    assert raster_dimensions(data) == (300, 300)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a" + b"\x00" * 30,
        png(1, 1)[:20],  # truncated IHDR
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IDAT" + b"\x00" * 16,  # no IHDR first
        b"\xff\xd8",  # SOI only
        b"\xff\xd8\x00\x00",  # not a marker
        b"\xff\xd8\xff\xda\x00\x02",  # scan before any frame
        b"\xff\xd8\xff\xd9",  # end of image before any frame
        b"\xff\xd8\xff\xe0\x00",  # truncated length
        b"\xff\xd8\xff\xe0\x00\x01",  # length below 2
        b"\xff\xd8\xff\xc0\x00\x11\x08\x01",  # truncated frame header
        b"\xff\xd8\xff\xe0\x00\x02",  # segment that ends the data
        _riff(b"VP8 ", b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),  # no start code
        _riff(b"VP8 ", b"\x00"),  # truncated VP8
        _riff(b"VP8L", b"\x00\x00\x00\x00\x00"),  # wrong signature
        _riff(b"VP8L", b"\x2f"),  # truncated VP8L
        _riff(b"VP8X", b"\x00"),  # truncated VP8X
        _riff(b"ALPH", b"\x00" * 16),  # unknown first chunk
    ],
)
def test_raster_dimensions_refuses_a_broken_header(data: bytes) -> None:
    assert raster_dimensions(data) is None


# --- 2. upload policy -------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (png(512, 512), "image/png"),
        (jpeg(256, 256), "image/jpeg"),
        (webp_vp8l(1000, 1009), "image/webp"),  # 0.9 % off still counts as square
    ],
)
def test_check_square_logo_accepts_a_raster_square(data: bytes, mime: str) -> None:
    assert check_square_logo(data) == mime


def _code(exc: pytest.ExceptionInfo[Any]) -> str:
    return exc.value.code


def test_check_square_logo_refuses_svg() -> None:
    with pytest.raises(UnsupportedMediaTypeError) as exc:
        check_square_logo(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    assert _code(exc) == "logo_type_not_allowed"


def test_check_square_logo_refuses_ico() -> None:
    with pytest.raises(UnsupportedMediaTypeError) as exc:
        check_square_logo(b"\x00\x00\x01\x00" + b"\x00" * 32)
    assert _code(exc) == "logo_type_not_allowed"


def test_check_square_logo_refuses_an_oversized_file() -> None:
    with pytest.raises(PayloadTooLargeError) as exc:
        check_square_logo(png(512, 512) + b"\x00" * MAX_CD_LOGO_BYTES)
    assert _code(exc) == "logo_too_large"


def test_check_square_logo_refuses_an_unreadable_header() -> None:
    with pytest.raises(ValidationProblem) as exc:
        check_square_logo(png(512, 512)[:18])
    assert _code(exc) == "logo_unreadable"


def test_check_square_logo_refuses_a_wide_image() -> None:
    with pytest.raises(ValidationProblem) as exc:
        check_square_logo(png(1000, 980))
    assert _code(exc) == "logo_not_square"


def test_check_square_logo_refuses_a_small_square() -> None:
    edge = SQUARE_LOGO_MIN_PX - 1
    with pytest.raises(ValidationProblem) as exc:
        check_square_logo(png(edge, edge))
    assert _code(exc) == "logo_too_small"


def test_check_square_logo_refuses_a_huge_square() -> None:
    edge = SQUARE_LOGO_MAX_PX + 1
    with pytest.raises(ValidationProblem) as exc:
        check_square_logo(png(edge, edge))
    assert _code(exc) == "logo_too_many_px"


# --- 3. service: upload -----------------------------------------------------


async def test_first_square_upload_takes_position_zero() -> None:
    variant = variant_row()
    storage = FakeStorage()
    # The lock, the logo list (no square row), then the audit write.
    s, sess = svc([res(), res(), *audit_results()], gets=[variant], storage=storage)
    out = await s.upload_logo(
        variant.id, png(512, 512), slot="square", filename="quadrat.png", actor="a"
    )
    assert out.slot == "square" and out.position == 0 and out.mime == "image/png"
    assert sess.deleted == [] and sess.committed == 1
    assert storage.removed == []
    assert len(storage.put_calls) == 1


async def test_square_upload_replaces_the_old_row_and_object() -> None:
    variant = variant_row()
    old = logo_row(
        variant_id=variant.id,
        slot="square",
        object_key="cd-logos/old/q.png",
        file_name="q.png",
        mime="image/png",
    )
    title = logo_row(variant_id=variant.id, slot="title", vendored_name="STUPA")
    storage = FakeStorage()
    storage.objects["cd-logos/old/q.png"] = (png(512, 512), "image/png")
    s, sess = svc([res(), res(title, old), *audit_results()], gets=[variant], storage=storage)
    flushes: list[tuple[int, int]] = []
    plain_flush = sess.flush

    async def tracking_flush() -> None:
        flushes.append((len(sess.deleted), len(sess.added)))
        await plain_flush()

    sess.flush = tracking_flush  # type: ignore[method-assign]
    out = await s.upload_logo(
        variant.id, jpeg(400, 400), slot="square", filename="neu.jpg", actor="a"
    )
    assert out.slot == "square" and out.mime == "image/jpeg"
    assert sess.deleted == [old]
    # The delete is flushed before the new row is added, so the partial unique
    # index never sees two square rows.
    assert flushes[0] == (1, 0)
    assert storage.removed == ["cd-logos/old/q.png"]


async def test_square_upload_keeps_a_vendored_old_row_without_object() -> None:
    """A row without an object (impossible in practice) needs no bucket delete."""
    variant = variant_row()
    old = logo_row(variant_id=variant.id, slot="square", vendored_name="STUPA")
    storage = FakeStorage()
    s, sess = svc([res(), res(old), *audit_results()], gets=[variant], storage=storage)
    await s.upload_logo(variant.id, png(300, 300), slot="square", filename=None, actor="a")
    assert sess.deleted == [old] and storage.removed == []


async def test_square_upload_refuses_a_non_square_before_the_storage() -> None:
    variant = variant_row()
    storage = FakeStorage()
    s, sess = svc(gets=[variant], storage=storage)
    with pytest.raises(ValidationProblem):
        await s.upload_logo(variant.id, png(600, 300), slot="square", filename="x", actor="a")
    assert storage.put_calls == [] and sess.committed == 0


async def test_square_upload_refuses_svg_that_a_title_logo_accepts() -> None:
    variant = variant_row()
    s, _ = svc(gets=[variant], storage=FakeStorage())
    with pytest.raises(UnsupportedMediaTypeError):
        await s.upload_logo(
            variant.id,
            b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            slot="square",
            filename="x.svg",
            actor="a",
        )


# --- 4. inline lookups and resolver ----------------------------------------


def _square(**kw: Any) -> CdVariantLogo:
    return logo_row(
        slot=kw.pop("slot", "square"),
        object_key=kw.pop("object_key", "cd-logos/a/q.png"),
        file_name="q.png",
        mime=kw.pop("mime", "image/png"),
        **kw,
    )


async def test_admin_square_logo_returns_a_reference() -> None:
    row = _square()
    s, _ = svc(gets=[row])
    ref = await s.admin_square_logo(row.id)
    assert ref == SquareLogoRef(logo_id=row.id, object_key="cd-logos/a/q.png", mime="image/png")
    assert ref.etag == f'"{row.id.hex}"'


@pytest.mark.parametrize(
    "row",
    [
        None,
        _square(slot="title"),
        logo_row(slot="square", vendored_name="STUPA"),
        _square(mime="image/svg+xml"),
        _square(mime=None),
    ],
)
async def test_admin_square_logo_404_for_anything_else(row: CdVariantLogo | None) -> None:
    s, _ = svc(gets=[row] if row is not None else [])
    with pytest.raises(NotFoundError):
        await s.admin_square_logo(uuid.uuid4())


async def test_gremium_square_logo_follows_the_variant() -> None:
    row = _square()
    s, _ = svc(scalars=[uuid.uuid4(), row])
    ref = await s.gremium_square_logo(uuid.uuid4())
    assert ref.logo_id == row.id


async def test_gremium_square_logo_404_without_variant() -> None:
    s, _ = svc(scalars=[None])
    with pytest.raises(NotFoundError):
        await s.gremium_square_logo(uuid.uuid4())


async def test_gremium_square_logo_404_without_square_row() -> None:
    s, _ = svc(scalars=[uuid.uuid4(), None])
    with pytest.raises(NotFoundError):
        await s.gremium_square_logo(uuid.uuid4())


async def test_square_logo_bytes_reads_the_object() -> None:
    storage = FakeStorage()
    storage.objects["k"] = (b"img", "image/png")
    s, _ = svc(storage=storage)
    ref = SquareLogoRef(logo_id=uuid.uuid4(), object_key="k", mime="image/png")
    assert await s.square_logo_bytes(ref) == b"img"


@pytest.mark.parametrize("storage", [None, FailingStorage()])
async def test_square_logo_bytes_503_without_storage(storage: Any) -> None:
    s, _ = svc(storage=storage)
    ref = SquareLogoRef(logo_id=uuid.uuid4(), object_key="k", mime="image/png")
    with pytest.raises(ServiceUnavailableError):
        await s.square_logo_bytes(ref)


async def test_list_variants_reports_the_square_slot() -> None:
    variant = variant_row()
    square = _square(variant_id=variant.id)
    s, _ = svc([res(variant), res(square)])
    out = await s.list_variants()
    assert out[0].logos[0].slot == "square"


async def test_resolver_never_hands_the_square_slot_to_the_renderer() -> None:
    """The query filters the slot. The loop skips it too, should a row slip through."""
    variant = variant_row()
    square = _square(variant_id=variant.id)
    footer = logo_row(variant_id=variant.id, slot="footer", vendored_name="STUPA")
    session = FakeSession([res(footer, square)], scalars=[variant])
    resolved = await resolve_cd_variant_by_key(session, FakeStorage(), variant.key)  # type: ignore[arg-type]
    assert resolved is not None
    assert resolved.title_logos == () and resolved.footer_logos == ("STUPA",)
    assert resolved.assets == {}


# --- 5. who may see a Gremium ----------------------------------------------


async def test_can_view_gremium_with_view_all_skips_the_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_a: Any, **_k: Any) -> set[uuid.UUID]:
        raise AssertionError("membership must not be read")

    monkeypatch.setattr(gremium_roles, "gremium_member_ids", boom)
    principal = Principal(sub="u", permissions={GREMIUM_VIEW_ALL})
    assert await can_view_gremium(None, principal, uuid.uuid4())  # type: ignore[arg-type]


async def test_can_view_gremium_for_admin() -> None:
    principal = Principal(sub="u", roles=["admin"])
    assert await can_view_gremium(None, principal, uuid.uuid4())  # type: ignore[arg-type]


@pytest.mark.parametrize("member", [True, False])
async def test_can_view_gremium_by_membership(
    monkeypatch: pytest.MonkeyPatch, member: bool
) -> None:
    gid = uuid.uuid4()

    async def ids(*_a: Any, **_k: Any) -> set[uuid.UUID]:
        return {gid} if member else {uuid.uuid4()}

    monkeypatch.setattr(gremium_roles, "gremium_member_ids", ids)
    # A token whose scope holds the key, without the permission, falls back to the membership.
    principal = Principal(sub="u", scope_permissions=frozenset({GREMIUM_VIEW_ALL}))
    assert await can_view_gremium(None, principal, gid) is member  # type: ignore[arg-type]


async def test_can_view_gremium_refuses_a_capped_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_a: Any, **_k: Any) -> set[uuid.UUID]:
        raise AssertionError("membership must not be read")

    monkeypatch.setattr(gremium_roles, "gremium_member_ids", boom)
    # A scoped admin token without the key sees no gremium, not even its own.
    principal = Principal(sub="u", roles=["admin"], scope_permissions=frozenset({"budget.write"}))
    assert not await can_view_gremium(None, principal, uuid.uuid4())  # type: ignore[arg-type]


async def test_gremium_view_scope_is_the_set_form(monkeypatch: pytest.MonkeyPatch) -> None:
    gid = uuid.uuid4()

    async def ids(*_a: Any, **_k: Any) -> set[uuid.UUID]:
        return {gid}

    monkeypatch.setattr(gremium_roles, "gremium_member_ids", ids)
    view_all = Principal(sub="u", permissions={GREMIUM_VIEW_ALL})
    member = Principal(sub="u")
    capped = Principal(sub="u", scope_permissions=frozenset({"budget.write"}))
    assert await gremium_roles.gremium_view_scope(None, view_all) is None  # type: ignore[arg-type]
    assert await gremium_roles.gremium_view_scope(None, member) == {gid}  # type: ignore[arg-type]
    assert await gremium_roles.gremium_view_scope(None, capped) == set()  # type: ignore[arg-type]


# --- 6. routes --------------------------------------------------------------

GREMIUM_ID = uuid.uuid4()
LOGO_ID = uuid.uuid4()
REF = SquareLogoRef(logo_id=LOGO_ID, object_key="cd-logos/a/q.png", mime="image/webp")
IMG = webp_vp8l(512, 512)


class _FakeSquare:
    def __init__(self) -> None:
        self.reads = 0

    async def gremium_square_logo(self, gremium_id: uuid.UUID) -> SquareLogoRef:
        if gremium_id != GREMIUM_ID:
            raise NotFoundError("no logo")
        return REF

    async def admin_square_logo(self, logo_id: uuid.UUID) -> SquareLogoRef:
        if logo_id != LOGO_ID:
            raise NotFoundError("no logo")
        return REF

    async def square_logo_bytes(self, ref: SquareLogoRef) -> bytes:
        self.reads += 1
        return IMG


@pytest.fixture
def fake() -> _FakeSquare:
    return _FakeSquare()


@pytest.fixture
def app(fake: _FakeSquare, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    application = create_app()
    application.dependency_overrides[get_cd_variant_service] = lambda: fake

    async def _db() -> AsyncIterator[object]:
        yield object()

    application.dependency_overrides[get_session] = _db

    async def visible(_db: Any, principal: Principal, gremium_id: uuid.UUID) -> bool:
        return principal.sub == "member"

    monkeypatch.setattr(admin_router, "can_view_gremium", visible)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _as(app: FastAPI, sub: str, *perms: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub=sub, permissions=set(perms)
    )


def _assert_inline_headers(headers: Any) -> None:
    assert headers["etag"] == REF.etag
    assert headers["cache-control"] == "private, max-age=3600"
    assert headers["x-content-type-options"] == "nosniff"


def test_gremium_logo_streams_the_bytes_inline(app: FastAPI, client: TestClient) -> None:
    _as(app, "member")
    response = client.get(f"/api/gremien/{GREMIUM_ID}/logo")
    assert response.status_code == 200
    assert response.content == IMG
    assert response.headers["content-type"] == "image/webp"
    assert "content-disposition" not in response.headers
    _assert_inline_headers(response.headers)


@pytest.mark.parametrize("header", [REF.etag, f"W/{REF.etag}", f'"other", {REF.etag}', "*"])
def test_gremium_logo_answers_304_for_a_matching_etag(
    app: FastAPI, client: TestClient, fake: _FakeSquare, header: str
) -> None:
    _as(app, "member")
    response = client.get(f"/api/gremien/{GREMIUM_ID}/logo", headers={"If-None-Match": header})
    assert response.status_code == 304 and response.content == b""
    _assert_inline_headers(response.headers)
    assert fake.reads == 0


def test_gremium_logo_sends_the_bytes_for_a_stale_etag(
    app: FastAPI, client: TestClient, fake: _FakeSquare
) -> None:
    _as(app, "member")
    response = client.get(
        f"/api/gremien/{GREMIUM_ID}/logo", headers={"If-None-Match": '"stale"'}
    )
    assert response.status_code == 200 and fake.reads == 1


def test_gremium_logo_404_for_a_caller_who_may_not_see_it(
    app: FastAPI, client: TestClient, fake: _FakeSquare
) -> None:
    """Not 403: the answer must not tell that the Gremium exists."""
    _as(app, "stranger")
    response = client.get(f"/api/gremien/{GREMIUM_ID}/logo")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert fake.reads == 0


def test_gremium_logo_404_without_a_logo(app: FastAPI, client: TestClient) -> None:
    _as(app, "member")
    response = client.get(f"/api/gremien/{uuid.uuid4()}/logo")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_gremium_logo_requires_a_login(client: TestClient) -> None:
    assert client.get(f"/api/gremien/{GREMIUM_ID}/logo").status_code == 401


def test_admin_square_logo_streams_inline(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin", "admin.cd_variants")
    response = client.get(f"/api/admin/cd-variant-logos/{LOGO_ID}/square")
    assert response.status_code == 200 and response.content == IMG
    assert response.headers["content-type"] == "image/webp"
    _assert_inline_headers(response.headers)


def test_admin_square_logo_404_for_another_logo(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin", "admin.cd_variants")
    response = client.get(f"/api/admin/cd-variant-logos/{uuid.uuid4()}/square")
    assert response.status_code == 404


def test_admin_square_logo_needs_the_permission(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin", "admin.gremien")
    response = client.get(f"/api/admin/cd-variant-logos/{LOGO_ID}/square")
    assert response.status_code == 403


def test_vendored_logo_refuses_the_square_slot(app: FastAPI, client: TestClient) -> None:
    _as(app, "admin", "admin.cd_variants")
    response = client.post(
        f"/api/admin/cd-variants/{uuid.uuid4()}/logos/vendored",
        json={"slot": "square", "vendoredName": "STUPA"},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
