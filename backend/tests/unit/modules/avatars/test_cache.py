"""Unit tests of the Redis avatar cache: encoding, fail-open behaviour."""

from __future__ import annotations

from typing import Any

from app.modules.avatars.cache import (
    CachedAvatar,
    RedisAvatarCache,
    cache_key,
    decode_entry,
    encode_entry,
)
from app.modules.avatars.gravatar import AvatarImage

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\n\x00" * 8
DIGEST = "b" * 64


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.ttl: dict[str, int] = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: bytes, *, ex: int) -> None:
        self.store[key] = value
        self.ttl[key] = ex


class _BrokenRedis:
    async def get(self, key: str) -> Any:
        raise ConnectionError("down")

    async def set(self, key: str, value: bytes, *, ex: int) -> None:
        raise ConnectionError("down")


def test_key_holds_hash_and_size() -> None:
    assert cache_key(DIGEST, 64) == f"avatar:v1:{DIGEST}:64"


def test_round_trip_of_an_image_and_of_a_miss() -> None:
    image = AvatarImage(mime="image/png", data=PNG)
    assert decode_entry(encode_entry(image)) == CachedAvatar(image)
    assert decode_entry(encode_entry(None)) == CachedAvatar(None)


def test_broken_entries_count_as_not_cached() -> None:
    assert decode_entry(b"x") is None  # unknown marker
    assert decode_entry(b"1image/png") is None  # no separator
    assert decode_entry(b"1image/png\n<svg/>") is None  # not an image
    assert decode_entry(b"1image/gif\n" + PNG) is None  # MIME does not match the bytes


async def test_put_then_get_with_ttl() -> None:
    redis = _FakeRedis()
    cache = RedisAvatarCache(redis)
    image = AvatarImage(mime="image/png", data=PNG)
    assert await cache.get(DIGEST, 64) is None
    await cache.put(DIGEST, 64, image, ttl_seconds=600)
    await cache.put(DIGEST, 128, None, ttl_seconds=30)
    assert await cache.get(DIGEST, 64) == CachedAvatar(image)
    assert await cache.get(DIGEST, 128) == CachedAvatar(None)
    assert redis.ttl == {cache_key(DIGEST, 64): 600, cache_key(DIGEST, 128): 30}


async def test_unreachable_redis_fails_open() -> None:
    cache = RedisAvatarCache(_BrokenRedis())
    assert await cache.get(DIGEST, 64) is None
    await cache.put(DIGEST, 64, None, ttl_seconds=30)  # no exception
