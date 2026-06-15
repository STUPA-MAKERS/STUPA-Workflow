"""Kalender-Endpunkte (#ics): öffentlicher iCal-Feed + eigene Abo-URL.

* ``GET /calendar/{token}.ics`` — **öffentlich**, per Feed-Token authentifiziert
  (Kalender-Clients können sich nicht per OIDC anmelden). Liefert die Sitzungen der
  Gremien des Token-Inhabers als ``text/calendar``.
* ``GET /calendar/me`` — eigene Abo-URL lesen (``null``, falls noch nicht erzeugt).
* ``POST /calendar/me/rotate`` — Feed-Token (neu) erzeugen; alte URL wird ungültig.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Annotated, Any, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Response, status

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.calendar import service
from app.modules.calendar.ics import MeetingEvent, build_calendar
from app.modules.calendar.schemas import CalendarFeedOut
from app.settings import Settings
from app.shared.errors import NotFoundError, ProblemDetail

router = APIRouter(prefix="/calendar", tags=["calendar"])

_ICS_MEDIA_TYPE = "text/calendar; charset=utf-8"
_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _feed_url(settings: Settings, token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/calendar/{token}.ics"


def _uid_domain(settings: Settings) -> str:
    """Host der öffentlichen Basis-URL → stabile, globale Event-UID-Domain."""
    return urlsplit(settings.public_base_url).hostname or "stupa.local"


@router.get("/me", responses={401: _PROBLEM})
async def my_calendar(
    principal: Annotated[Principal, Depends(require_principal())],
    db: DbSession,
    settings: SettingsDep,
) -> CalendarFeedOut:
    """Eigene Abo-URL (``null``, solange noch kein Feed-Token erzeugt wurde)."""
    token = await service.get_calendar_token(db, principal.sub)
    return CalendarFeedOut(url=_feed_url(settings, token) if token else None)


@router.post("/me/rotate", responses={401: _PROBLEM})
async def rotate_my_calendar(
    principal: Annotated[Principal, Depends(require_principal())],
    db: DbSession,
    settings: SettingsDep,
) -> CalendarFeedOut:
    """Feed-Token (neu) erzeugen — invalidiert die bisherige Abo-URL."""
    token = await service.rotate_calendar_token(db, principal.sub)
    await db.commit()
    return CalendarFeedOut(url=_feed_url(settings, token) if token else None)


@router.get(
    "/{token}.ics",
    responses={
        200: {"content": {"text/calendar": {"schema": {"type": "string"}}}},
        404: _PROBLEM,
    },
)
async def calendar_feed(
    token: str, db: DbSession, settings: SettingsDep
) -> Response:
    """Öffentlicher iCal-Feed (per Feed-Token). Unbekannter/​deaktivierter Token → 404."""
    principal = await service.principal_by_calendar_token(db, token)
    if principal is None:
        raise NotFoundError("Unknown calendar feed.")
    meetings = await service.member_meetings(db, principal.sub)
    events = [
        MeetingEvent(
            uid=str(meeting.id),
            title=meeting.title,
            # member_meetings filtert ``date IS NOT NULL`` → hier garantiert gesetzt.
            date=cast(_date, meeting.date),
            start_time=meeting.start_time,
            end_time=meeting.end_time,
            stamp=meeting.created_at,
            gremium_name=gremium_name,
        )
        for meeting, gremium_name in meetings
    ]
    body = build_calendar(events, domain=_uid_domain(settings))
    return Response(
        content=body,
        status_code=status.HTTP_200_OK,
        media_type=_ICS_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'inline; filename="stupa-sitzungen.ics"',
            # Kurzer Cache: neue/​geänderte Sitzungen erscheinen zeitnah; ein rotierter
            # Token (neue URL) ist ohnehin sofort gültig (eigener Cache-Key).
            "Cache-Control": "private, max-age=300",
        },
    )
