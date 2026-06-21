"""Unit-Tests MinIO-Storage-Adapter (T-13). `minio` wird über ein Fake-Modul ersetzt."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.modules.files.storage import (
    MinioStorage,
    StorageError,
    _safe_disposition,
    build_object_storage,
)
from app.settings import load_settings


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.closed = False
        self.released = False

    def read(self, amt: int | None = None) -> bytes:
        # ohne amt: alles (wie urllib3); mit amt: häppchenweise (Stream-Pfad)
        if amt is None:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + amt]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _FakeMinio:
    def __init__(self, *, buckets: set[str] | None = None) -> None:
        self.buckets = buckets if buckets is not None else set()
        self.objects: dict[str, bytes] = {}
        self.removed: list[str] = []
        self.made: list[str] = []
        self.fail = False

    def bucket_exists(self, bucket: str) -> bool:
        return bucket in self.buckets

    def make_bucket(self, bucket: str) -> None:
        self.made.append(bucket)
        self.buckets.add(bucket)

    def put_object(
        self, bucket: str, key: str, stream: Any, length: int, content_type: str
    ) -> None:
        if self.fail:
            raise RuntimeError("put boom")
        self.objects[key] = stream.read()

    def get_object(self, bucket: str, key: str) -> _FakeResponse:
        if key not in self.objects:
            raise RuntimeError("not found")
        return _FakeResponse(self.objects[key])

    def remove_object(self, bucket: str, key: str) -> None:
        self.removed.append(key)

    def presigned_get_object(
        self, bucket: str, key: str, expires: Any, response_headers: Any = None
    ) -> str:
        return f"https://minio/{bucket}/{key}"


def _storage(client: _FakeMinio | None = None) -> MinioStorage:
    return MinioStorage(client=client or _FakeMinio(), bucket="attachments")  # type: ignore[arg-type]


async def test_put_creates_bucket_and_stores() -> None:
    client = _FakeMinio()
    await _storage(client).put("k1", b"data", "application/pdf")
    assert client.made == ["attachments"]
    assert client.objects["k1"] == b"data"


async def test_put_skips_existing_bucket() -> None:
    client = _FakeMinio(buckets={"attachments"})
    await _storage(client).put("k1", b"data", "application/pdf")
    assert client.made == []


async def test_put_error_wrapped() -> None:
    client = _FakeMinio(buckets={"attachments"})
    client.fail = True
    with pytest.raises(StorageError):
        await _storage(client).put("k1", b"data", "application/pdf")


async def test_get_returns_bytes_and_closes() -> None:
    client = _FakeMinio(buckets={"attachments"})
    client.objects["k1"] = b"payload"
    assert await _storage(client).get("k1") == b"payload"


async def test_get_error_wrapped() -> None:
    with pytest.raises(StorageError):
        await _storage().get("missing")


async def test_get_stream_yields_chunks_and_closes() -> None:
    client = _FakeMinio(buckets={"attachments"})
    client.objects["k1"] = b"abcdefghij"
    stream = await _storage(client).get_stream("k1", chunk_size=4)
    chunks = [c async for c in stream]
    assert chunks == [b"abcd", b"efgh", b"ij"]
    assert b"".join(chunks) == b"abcdefghij"


async def test_get_stream_closes_and_releases_connection() -> None:
    client = _FakeMinio(buckets={"attachments"})
    client.objects["k1"] = b"payload"
    captured: dict[str, _FakeResponse] = {}
    original = client.get_object

    def _spy(bucket: str, key: str) -> _FakeResponse:
        resp = original(bucket, key)
        captured["resp"] = resp
        return resp

    client.get_object = _spy  # type: ignore[method-assign]
    stream = await _storage(client).get_stream("k1", chunk_size=3)
    _ = [c async for c in stream]
    assert captured["resp"].closed is True
    assert captured["resp"].released is True


async def test_get_stream_connect_error_wrapped() -> None:
    # Objekt fehlt → get_object wirft → StorageError VOR dem Stream-Start (→ 503).
    with pytest.raises(StorageError):
        await _storage().get_stream("missing")


async def test_remove() -> None:
    client = _FakeMinio(buckets={"attachments"})
    await _storage(client).remove("k1")
    assert client.removed == ["k1"]


async def test_remove_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeMinio(buckets={"attachments"})

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("remove boom")

    monkeypatch.setattr(client, "remove_object", _boom)
    with pytest.raises(StorageError):
        await _storage(client).remove("k1")


def test_presigned_url_with_disposition() -> None:
    url = _storage().presigned_get_url(
        "k1", expires_seconds=300, download_name='a"b.pdf'
    )
    assert url == "https://minio/attachments/k1"


def test_presigned_url_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeMinio()

    def _boom(*_a: Any, **_kw: Any) -> str:
        raise RuntimeError("presign boom")

    monkeypatch.setattr(client, "presigned_get_object", _boom)
    with pytest.raises(StorageError):
        MinioStorage(client=client, bucket="b").presigned_get_url(  # type: ignore[arg-type]
            "k", expires_seconds=60
        )


def test_safe_disposition_strips_quotes_and_controls() -> None:
    assert _safe_disposition('a"b\r\n.pdf') == "ab.pdf"


def test_build_object_storage_disabled_none() -> None:
    assert build_object_storage(load_settings()) is None


def test_build_object_storage_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    module = types.ModuleType("minio")

    def _minio(endpoint: str, **kw: Any) -> _FakeMinio:
        captured["endpoint"] = endpoint
        captured.update(kw)
        return _FakeMinio()

    module.Minio = _minio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "minio", module)
    settings = load_settings(
        minio_endpoint="minio:9000",
        minio_access_key="ak",
        minio_secret_key="sk",
        minio_bucket="attachments",
    )
    storage = build_object_storage(settings)
    assert isinstance(storage, MinioStorage)
    assert captured["endpoint"] == "minio:9000"
    assert captured["access_key"] == "ak"
