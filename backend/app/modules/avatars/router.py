"""Avatar endpoints: the Gravatar image of a principal, from our own origin.

``GET /principals/{id}/avatar`` and ``GET /principals/me/avatar`` answer the image
bytes, or 404 when the person has no Gravatar (the frontend then shows the
initials). Every logged-in principal may read the avatar of every principal: the
image is public at Gravatar, and the response holds neither the e-mail address nor
its hash. An applicant session gets 401.

The browser may keep an image for ``gravatar_cache_ttl_seconds`` (``private``) and
revalidates it with the ETag. The ``me`` route also varies on the cookie and the
bearer token, because its URL is the same for every user.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.avatars import service
from app.modules.avatars.cache import AvatarCache, RedisAvatarCache
from app.modules.avatars.gravatar import (
    AvatarImage,
    GravatarFetcher,
    HttpGravatarFetcher,
    size_bucket,
)
from app.settings import Settings
from app.shared.antiabuse import RateLimiterDep, _redis_client
from app.shared.errors import NotFoundError, ProblemDetail, RateLimitedError

router = APIRouter(prefix="/principals", tags=["avatars"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_HOUR = 3600
# How long the browser keeps a 404: a new Gravatar shows within the hour.
_MISS_MAX_AGE = 3600
# How long the browser keeps the 404 of the switched-off proxy.
_DISABLED_MAX_AGE = 300

_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "content": {
            "image/png": {"schema": {"type": "string", "format": "binary"}},
            "image/jpeg": {"schema": {"type": "string", "format": "binary"}},
            "image/gif": {"schema": {"type": "string", "format": "binary"}},
            "image/webp": {"schema": {"type": "string", "format": "binary"}},
        },
        "description": "The avatar image.",
    },
    304: {"description": "The cached image is still valid (If-None-Match)."},
    401: _PROBLEM,
    404: _PROBLEM,
    429: _PROBLEM,
}

SizeQuery = Annotated[
    int,
    Query(ge=1, le=512, description="Wanted edge length in px; the server rounds it up."),
]


def get_avatar_cache(request: Request, settings: SettingsDep) -> AvatarCache:
    """Build the Redis avatar cache once per app and keep it on ``app.state``."""
    state = request.app.state
    cache = getattr(state, "_avatar_cache", None)
    if cache is None:
        cache = RedisAvatarCache(_redis_client(request, settings))
        state._avatar_cache = cache
    return cache


def get_gravatar_fetcher(settings: SettingsDep) -> GravatarFetcher:
    return HttpGravatarFetcher(timeout_seconds=settings.gravatar_timeout_seconds)


AvatarCacheDep = Annotated[AvatarCache, Depends(get_avatar_cache)]
FetcherDep = Annotated[GravatarFetcher, Depends(get_gravatar_fetcher)]
PrincipalDep = Annotated[Principal, Depends(require_principal())]


def _not_found(max_age: int, extra: dict[str, str]) -> NotFoundError:
    return NotFoundError(
        "No avatar for this person.",
        code="avatar_not_found",
        headers={"Cache-Control": f"private, max-age={max_age}", **extra},
    )


def _etag_matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    tags = [t.strip().removeprefix("W/") for t in if_none_match.split(",")]
    return "*" in tags or etag in tags


async def _serve(
    request: Request,
    email: str | None,
    size: int,
    *,
    db: DbSession,
    settings: Settings,
    cache: AvatarCache,
    fetcher: GravatarFetcher,
    extra: dict[str, str],
) -> Response:
    if not await service.gravatar_enabled(db):
        raise _not_found(_DISABLED_MAX_AGE, extra)
    if not email:
        raise _not_found(_MISS_MAX_AGE, extra)
    image: AvatarImage | None = await service.load_avatar(
        email, size_bucket(size), cache=cache, fetcher=fetcher, settings=settings
    )
    if image is None:
        raise _not_found(_MISS_MAX_AGE, extra)
    headers = {
        "Cache-Control": f"private, max-age={settings.gravatar_cache_ttl_seconds}",
        "ETag": image.etag,
        **extra,
    }
    if _etag_matches(request.headers.get("if-none-match"), image.etag):
        return Response(status_code=304, headers=headers)
    return Response(content=image.data, media_type=image.mime, headers=headers)


async def _throttle(principal: Principal, settings: Settings, limiter: RateLimiterDep) -> None:
    result = await limiter.hit(
        f"avatar:principal:{principal.sub}",
        limit=settings.rl_avatar_per_hour,
        window_seconds=_HOUR,
    )
    if not result.allowed:
        raise RateLimitedError(
            "Too many avatar requests. Try again later.", retry_after=result.retry_after
        )


@router.get("/me/avatar", response_class=Response, responses=_RESPONSES)
async def my_avatar(
    request: Request,
    principal: PrincipalDep,
    db: DbSession,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    cache: AvatarCacheDep,
    fetcher: FetcherDep,
    s: SizeQuery = 80,
) -> Response:
    """Serve the avatar of the logged-in principal."""
    await _throttle(principal, settings, limiter)
    email = await service.email_by_sub(db, principal.sub)
    return await _serve(
        request,
        email,
        s,
        db=db,
        settings=settings,
        cache=cache,
        fetcher=fetcher,
        extra={"Vary": "Cookie, Authorization"},
    )


@router.get("/{principal_id}/avatar", response_class=Response, responses=_RESPONSES)
async def principal_avatar(
    principal_id: UUID,
    request: Request,
    principal: PrincipalDep,
    db: DbSession,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    cache: AvatarCacheDep,
    fetcher: FetcherDep,
    s: SizeQuery = 80,
) -> Response:
    """Serve the avatar of a principal. An unknown id gives 404 like a missing image."""
    await _throttle(principal, settings, limiter)
    email = await service.email_by_id(db, principal_id)
    return await _serve(
        request,
        email,
        s,
        db=db,
        settings=settings,
        cache=cache,
        fetcher=fetcher,
        extra={},
    )
