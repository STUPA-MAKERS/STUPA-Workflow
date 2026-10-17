"""The anti-abuse dependencies of the media routes: body cap and rate limits."""

from __future__ import annotations

import pytest
from starlette.requests import Request

from app.modules.auth.principal import Principal
from app.settings import get_settings
from app.shared import antiabuse
from app.shared.errors import PayloadTooLargeError, RateLimitedError
from app.shared.ratelimit import InMemoryRateLimiter


def _request(content_length: str | None = None) -> Request:
    headers = [] if content_length is None else [(b"content-length", content_length.encode())]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/media/images",
            "headers": headers,
            "client": ("10.0.0.9", 1),
        }
    )


def test_body_cap() -> None:
    settings = get_settings().model_copy(update={"markdown_image_max_bytes": 10})
    antiabuse.enforce_media_body_cap(_request(), settings)
    antiabuse.enforce_media_body_cap(_request("1000"), settings)
    with pytest.raises(PayloadTooLargeError):
        antiabuse.enforce_media_body_cap(_request(str(10 + 64 * 1024 + 1)), settings)


async def test_upload_limit_per_principal() -> None:
    settings = get_settings().model_copy(update={"rl_media_images_per_hour": 1})
    limiter = InMemoryRateLimiter()
    alice = Principal(sub="alice", permissions=set())
    await antiabuse.rate_limit_media_images(settings, limiter, alice)
    with pytest.raises(RateLimitedError):
        await antiabuse.rate_limit_media_images(settings, limiter, alice)
    # Another person has an own budget; an anonymous caller gets the 401 of the route.
    await antiabuse.rate_limit_media_images(
        settings, limiter, Principal(sub="bob", permissions=set())
    )
    await antiabuse.rate_limit_media_images(settings, limiter, None)


async def test_upload_limit_skips_the_logged_in_mcp() -> None:
    settings = get_settings().model_copy(update={"rl_media_images_per_hour": 1})
    limiter = InMemoryRateLimiter()
    mcp = Principal(sub="mcp", permissions=set(), scope_permissions=frozenset())
    for _ in range(3):
        await antiabuse.rate_limit_media_images(settings, limiter, mcp)


async def test_public_image_limit_per_ip() -> None:
    settings = get_settings().model_copy(update={"rl_public_protocol_images_ip_per_hour": 1})
    limiter = InMemoryRateLimiter()
    await antiabuse.rate_limit_public_protocol_images(_request(), settings, limiter)
    with pytest.raises(RateLimitedError):
        await antiabuse.rate_limit_public_protocol_images(_request(), settings, limiter)
