"""Unit tests of the media service: upload, read and render collection."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.modules.files.storage import StorageError
from app.modules.media.models import image_storage_key
from app.modules.media.service import MediaService, render_asset_name
from app.shared.errors import (
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaTypeError,
)
from tests._support.files_fakes import FailingStorage
from tests._support.media_fakes import MediaSession, MediaStorage, add_image

from ._images import SVG, encode


def _service(
    session: MediaSession | None = None, storage: object = None, max_bytes: int = 10 * 1024 * 1024
) -> MediaService:
    return MediaService(
        session or MediaSession(),  # pyright: ignore[reportArgumentType]
        storage=storage,  # pyright: ignore[reportArgumentType]
        max_bytes=max_bytes,
    )


async def test_upload_stores_the_clean_image() -> None:
    session, storage = MediaSession(), MediaStorage()
    out = await _service(session, storage).upload(encode("PNG"))
    assert out.url == f"/api/media/images/{out.id}"
    assert (out.mime, out.width, out.height) == ("image/png", 40, 20)
    data, content_type = storage.objects[f"media/images/{out.id}"]
    assert content_type == "image/png"
    assert out.size == len(data)
    assert session.rows[out.id].storage_key == f"media/images/{out.id}"
    assert session.committed == 1


async def test_upload_without_storage_is_503() -> None:
    with pytest.raises(ServiceUnavailableError):
        await _service(storage=None).upload(encode("PNG"))


async def test_upload_storage_failure_is_503() -> None:
    session = MediaSession()
    with pytest.raises(ServiceUnavailableError, match="write failed"):
        await _service(session, FailingStorage()).upload(encode("PNG"))
    assert session.committed == 0


@pytest.mark.parametrize("data", [SVG, b"garbage" * 20])
async def test_upload_of_no_image_is_415(data: bytes) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        await _service(storage=MediaStorage()).upload(data)


async def test_upload_whose_result_is_too_large_is_413() -> None:
    with pytest.raises(PayloadTooLargeError):
        await _service(storage=MediaStorage(), max_bytes=10).upload(encode("PNG"))


async def test_open_streams_the_image() -> None:
    session, storage = MediaSession(), MediaStorage()
    image_id = add_image(session, storage, b"PNGDATA", "image/png")
    image = await _service(session, storage).open(image_id)
    assert (image.mime, image.size) == ("image/png", 7)
    chunks = [c async for c in image.stream]
    assert b"".join(chunks) == b"PNGDATA"


async def test_open_unknown_is_404() -> None:
    with pytest.raises(NotFoundError):
        await _service(storage=MediaStorage()).open(uuid.uuid4())


async def test_open_without_storage_is_503() -> None:
    session, storage = MediaSession(), MediaStorage()
    image_id = add_image(session, storage, b"x")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, None).open(image_id)


async def test_open_storage_failure_is_503() -> None:
    class _Broken(MediaStorage):
        async def get_stream(
            self, key: str, *, chunk_size: int = 64 * 1024
        ) -> AsyncIterator[bytes]:
            raise StorageError("down")

    session, storage = MediaSession(), _Broken()
    image_id = add_image(session, storage, b"x")
    with pytest.raises(ServiceUnavailableError):
        await _service(session, storage).open(image_id)


def _md(*ids: uuid.UUID) -> str:
    return "\n\n".join(f"![b{i}](/api/media/images/{x})" for i, x in enumerate(ids))


async def test_render_assets_in_order_with_names() -> None:
    session, storage = MediaSession(), MediaStorage()
    a = add_image(session, storage, b"A" * 4, "image/png")
    b = add_image(session, storage, b"B" * 4, "image/jpeg")
    c = add_image(session, storage, b"C" * 4, "image/gif")
    d = add_image(session, storage, b"D" * 4, "image/webp")
    assets = await _service(session, storage).render_assets(_md(d, a, b, c, a))
    assert list(assets) == [
        f"img-{d}.webp",
        f"img-{a}.png",
        f"img-{b}.jpg",
        f"img-{c}.gif",
    ]
    assert assets[render_asset_name(a, "image/png")] == b"AAAA"


async def test_render_assets_without_storage_or_images_is_empty() -> None:
    session, storage = MediaSession(), MediaStorage()
    a = add_image(session, storage, b"A")
    assert await _service(session, None).render_assets(_md(a)) == {}
    assert await _service(session, storage).render_assets("no image here") == {}


async def test_render_assets_skips_unknown_and_missing_objects() -> None:
    session, storage = MediaSession(), MediaStorage()
    a = add_image(session, storage, b"A")
    gone = add_image(session, storage, b"G")
    del storage.objects[image_storage_key(gone)]
    assets = await _service(session, storage).render_assets(_md(uuid.uuid4(), gone, a))
    assert list(assets) == [f"img-{a}.png"]


async def test_render_assets_respects_the_count_budget() -> None:
    session, storage = MediaSession(), MediaStorage()
    ids = [add_image(session, storage, b"x") for _ in range(4)]
    assets = await _service(session, storage).render_assets(_md(*ids), max_images=2)
    assert list(assets) == [f"img-{ids[0]}.png", f"img-{ids[1]}.png"]


async def test_render_assets_respects_the_byte_budgets() -> None:
    session, storage = MediaSession(), MediaStorage()
    big = add_image(session, storage, b"x" * 9)
    first = add_image(session, storage, b"x" * 6)
    second = add_image(session, storage, b"x" * 6)
    small = add_image(session, storage, b"x" * 2)
    assets = await _service(session, storage).render_assets(
        _md(big, first, second, small), max_bytes=10, max_asset_bytes=8
    )
    # `big` passes the asset cap, `second` the total; `small` still fits.
    assert list(assets) == [f"img-{first}.png", f"img-{small}.png"]


async def test_render_assets_checks_the_real_size_of_the_object() -> None:
    session, storage = MediaSession(), MediaStorage()
    a = add_image(session, storage, b"x")
    # The object grew behind the row: the real bytes count.
    storage.objects[image_storage_key(a)] = (b"x" * 50, "image/png")
    assert await _service(session, storage).render_assets(_md(a), max_asset_bytes=8) == {}


async def test_upload_runs_at_most_two_cleans_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    import threading

    from app.modules.media import service as media_service
    from app.modules.media.images import clean_image

    lock = threading.Lock()
    running = 0
    peak = 0
    release = threading.Event()

    def slow_clean(data: bytes) -> object:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        release.wait(5)
        with lock:
            running -= 1
        return clean_image(data)

    monkeypatch.setattr(media_service, "clean_image", slow_clean)
    monkeypatch.setattr(media_service, "_clean_slots", asyncio.Semaphore(2))
    storage = MediaStorage()
    tasks = [
        asyncio.create_task(_service(MediaSession(), storage).upload(encode("PNG")))
        for _ in range(4)
    ]
    for _ in range(50):
        await asyncio.sleep(0.01)
        if peak == 2:
            break
    await asyncio.sleep(0.05)
    assert peak == 2
    release.set()
    outs = await asyncio.gather(*tasks)
    assert len({o.id for o in outs}) == 4
    assert peak == 2
    assert media_service.CLEAN_CONCURRENCY == 2
