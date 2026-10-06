"""Redis cache of the Gravatar proxy.

One key per hash and size bucket. The value is either the miss marker ``0`` (Gravatar
has no image, or the fetch failed) or ``1`` + MIME + newline + the image bytes. Redis
sets the lifetime. The key holds the e-mail hash; it stays on the server.

The cache fails open: when Redis is unreachable, a read gives "not cached" and a
write does nothing. The proxy then asks Gravatar directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, cast

from app.modules.avatars.gravatar import AvatarImage, AvatarMime, sniff_avatar

logger = logging.getLogger("app.avatars")

_PREFIX = "avatar:v1:"
_MISS = b"0"
_HIT = b"1"


@dataclass(frozen=True, slots=True)
class CachedAvatar:
    """A cache entry. ``image`` is ``None`` for a cached miss."""

    image: AvatarImage | None


class AvatarCache(Protocol):
    async def get(self, digest: str, size: int) -> CachedAvatar | None: ...

    async def put(
        self, digest: str, size: int, image: AvatarImage | None, *, ttl_seconds: int
    ) -> None: ...


def cache_key(digest: str, size: int) -> str:
    return f"{_PREFIX}{digest}:{size}"


def encode_entry(image: AvatarImage | None) -> bytes:
    if image is None:
        return _MISS
    return _HIT + image.mime.encode("ascii") + b"\n" + image.data


def decode_entry(raw: bytes) -> CachedAvatar | None:
    """Decode a stored value. An unknown or broken value counts as not cached."""
    if raw == _MISS:
        return CachedAvatar(None)
    if not raw.startswith(_HIT):
        return None
    mime, sep, data = raw[1:].partition(b"\n")
    if not sep:
        return None
    sniffed = sniff_avatar(data)
    # The stored MIME must match the bytes; else the entry is broken.
    if sniffed is None or sniffed.encode("ascii") != mime:
        return None
    return CachedAvatar(AvatarImage(mime=cast(AvatarMime, sniffed), data=data))


class RedisAvatarCache:
    """Avatar cache on a shared ``redis.asyncio`` client. It fails open."""

    def __init__(self, client: object) -> None:
        self._client = client

    async def get(self, digest: str, size: int) -> CachedAvatar | None:
        try:
            raw = await self._client.get(cache_key(digest, size))  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - fail open: Redis is only a cache
            logger.warning("avatar cache read failed: %s", type(exc).__name__)
            return None
        if raw is None:
            return None
        return decode_entry(bytes(raw))

    async def put(
        self, digest: str, size: int, image: AvatarImage | None, *, ttl_seconds: int
    ) -> None:
        try:
            await self._client.set(  # type: ignore[attr-defined]
                cache_key(digest, size), encode_entry(image), ex=ttl_seconds
            )
        except Exception as exc:  # noqa: BLE001 - fail open: Redis is only a cache
            logger.warning("avatar cache write failed: %s", type(exc).__name__)
