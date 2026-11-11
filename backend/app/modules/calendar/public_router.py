"""The public routes of the calendar, without a sign-in.

The routes serve the public calendar page (`/public-calendar`) and the public ICS feed.
Every route is read-only, has the rate limit of the public pages per IP, and answers
404 for anything that is not public (fail closed). The security middleware adds
`X-Robots-Tag: noindex` to every answer under `/api/public/`.

The feed has no token, because it holds only what the page shows. The server keeps its
bytes for 5 minutes (`public.FEED_TTL_SECONDS`), because many calendar apps fetch it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from app.deps import DbSession, SettingsDep
from app.modules.calendar.external_feed import BERLIN
from app.modules.calendar.ics import build_calendar
from app.modules.calendar.public import (
    FEED_TTL_SECONDS,
    FeedCache,
    PublicAppointmentOut,
    PublicCalendarService,
    PublicGremiumOut,
    PublicMeetingOut,
    RedisFeedCache,
)
from app.modules.calendar.schemas import EntriesOut
from app.shared.antiabuse import _redis_client, rate_limit_public_protocols
from app.shared.errors import ProblemDetail, ValidationProblem

router = APIRouter(prefix="/public", tags=["public-calendar"])

_PROBLEM: dict[str, Any] = {"model": ProblemDetail}
_LIMIT = Depends(rate_limit_public_protocols)
_ICS_MEDIA_TYPE = "text/calendar; charset=utf-8"

#: The longest span of one read of the entries, as on the Kalender page.
MAX_SPAN = timedelta(days=100)


def _errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return dict.fromkeys(codes, _PROBLEM)


def get_public_calendar_service(session: DbSession) -> PublicCalendarService:
    """Build the public calendar reads on the session of the request."""
    return PublicCalendarService(session)


def get_public_feed_cache(request: Request, settings: SettingsDep) -> FeedCache:
    """Build the Redis cache of the public feed."""
    return RedisFeedCache(_redis_client(request, settings))


ServiceDep = Annotated[PublicCalendarService, Depends(get_public_calendar_service)]
FeedCacheDep = Annotated[FeedCache, Depends(get_public_feed_cache)]
GremiumQuery = Annotated[list[UUID] | None, Query(alias="gremium", max_length=50)]
#: No control characters: a NUL byte would make Postgres fail on the LIKE pattern.
SearchQuery = Annotated[str, Query(max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")]


@router.get(
    "/calendar/committees",
    response_model=tuple[PublicGremiumOut, ...],
    dependencies=[_LIMIT],
    responses=_errors(429),
)
async def public_calendar_gremien(service: ServiceDep) -> tuple[PublicGremiumOut, ...]:
    """List the Gremien whose meetings are public, for the filter of the page."""
    return await service.gremien()


@router.get(
    "/calendar/entries",
    response_model=EntriesOut,
    dependencies=[_LIMIT],
    responses=_errors(422, 429),
)
async def public_calendar_entries(
    service: ServiceDep,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
    gremium: GremiumQuery = None,
) -> EntriesOut:
    """List the public entries with a day between ``from`` and ``to``.

    The entries are the public Termine and the meetings of the Gremien with public
    protocols. A filter by Gremium keeps only the meetings of these Gremien.
    """
    if end < start or end - start > MAX_SPAN:
        raise ValidationProblem("The span is not valid.", code="calendar_span")
    return EntriesOut(items=await service.between(start, end, tuple(gremium or ())))


@router.get(
    "/calendar/search",
    response_model=EntriesOut,
    dependencies=[_LIMIT],
    responses=_errors(422, 429),
)
async def public_calendar_search(service: ServiceDep, q: SearchQuery = "") -> EntriesOut:
    """Search the public entries of every month by title, the nearest to today first."""
    return EntriesOut(items=await service.search(q, datetime.now(UTC).astimezone(BERLIN).date()))


@router.get(
    "/calendar/appointments/{appointment_id}",
    response_model=PublicAppointmentOut,
    dependencies=[_LIMIT],
    responses=_errors(404, 422, 429),
)
async def public_calendar_appointment(
    appointment_id: UUID, service: ServiceDep
) -> PublicAppointmentOut:
    """Return the public fields of one Termin. 404 for a Termin that is not public."""
    return await service.appointment(appointment_id)


@router.get(
    "/calendar/meetings/{meeting_id}",
    response_model=PublicMeetingOut,
    dependencies=[_LIMIT],
    responses=_errors(404, 422, 429),
)
async def public_calendar_meeting(meeting_id: UUID, service: ServiceDep) -> PublicMeetingOut:
    """Return the public fields of one meeting.

    404 for a meeting of a Gremium that does not publish its protocols.
    """
    return await service.meeting(meeting_id)


@router.get(
    "/calendar.ics",
    response_class=Response,
    dependencies=[_LIMIT],
    responses={
        200: {"content": {"text/calendar": {"schema": {"type": "string"}}}},
        429: _PROBLEM,
    },
)
async def public_calendar_feed(
    service: ServiceDep, cache: FeedCacheDep, settings: SettingsDep
) -> Response:
    """Serve the public calendar as an ICS feed, without a token.

    The feed holds the entries of the public calendar page, with no organiser and no
    attendee. The bytes come from the cache when it holds them.
    """
    cached = await cache.get()
    body = cached if cached is not None else await _build_feed(service, settings.public_base_url)
    if cached is None:
        await cache.put(body)
    return Response(
        content=body,
        media_type=_ICS_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'inline; filename="stupa-kalender.ics"',
            "Cache-Control": f"public, max-age={FEED_TTL_SECONDS}",
        },
    )


async def _build_feed(service: PublicCalendarService, base_url: str) -> bytes:
    meetings, appointments = await service.feed()
    return build_calendar(
        meetings,
        domain=urlsplit(base_url).hostname or "stupa.local",
        appointments=appointments,
        calendar_name="STUPA — Öffentlicher Kalender",
    )
