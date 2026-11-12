"""Calendar endpoints: the Kalender page, the Termine and the personal iCal feed.

`GET /calendar/{token}.ics` is public. The feed token authenticates it, because
calendar clients cannot log in through OIDC. `GET /calendar/me` reads the
personal subscription URL. `POST /calendar/me/rotate` generates a new token and
invalidates the old URL.

`GET /calendar/entries` and `GET /calendar/search` read the entries of the Kalender
page, each kind under the rule of its own module (`entries`). The routes under
`/calendar/appointments` create, read, change, delete and answer a Termin; the object
rule is `calendar.rules`. A write commits here and then sends its mails as a
background task, so a mail failure never fails the write.

`GET /calendar/external/{entry_id}` reads one entry of an external calendar under the
read rule of its calendar. `admin_router` (`/admin/calendars`) manages the external
calendars behind `admin.calendars`. No route fetches an external address: a write makes
the calendar due, and the worker fetches it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from datetime import date as _date
from typing import Annotated, Any, cast
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.deps import DbSession, Principal, SettingsDep, require_principal
from app.modules.calendar import service
from app.modules.calendar.appointments import BERLIN, AppointmentMail, AppointmentService
from app.modules.calendar.entries import CalendarEntries
from app.modules.calendar.external import ExternalCalendarService
from app.modules.calendar.ics import MeetingEvent, build_calendar
from app.modules.calendar.mails import notify_appointment_mails
from app.modules.calendar.schemas import (
    AnswerIn,
    AppointmentIn,
    AppointmentOut,
    CalendarFeedOut,
    EntriesOut,
    ExternalCalendarIn,
    ExternalCalendarOut,
    ExternalEntryOut,
    PersonOut,
)
from app.modules.notifications.provider import mail_queue_from_pool
from app.settings import Settings
from app.shared.errors import NotFoundError, ProblemDetail, ValidationProblem

router = APIRouter(prefix="/calendar", tags=["calendar"])
admin_router = APIRouter(prefix="/admin/calendars", tags=["calendar"])

_ICS_MEDIA_TYPE = "text/calendar; charset=utf-8"
_PROBLEM: dict[str, Any] = {"model": ProblemDetail}


def _feed_url(settings: Settings, token: str) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/calendar/{token}.ics"


def _uid_domain(settings: Settings) -> str:
    """Derive the stable event-UID domain from the public base URL."""
    return urlsplit(settings.public_base_url).hostname or "stupa.local"


#: The longest span of one read of the entries. The week view reads 7 days and the
#: month grid 42, and the phone list loads further days in steps.
MAX_SPAN = timedelta(days=100)

type AppointmentMailSender = Callable[
    [Settings, Sequence[AppointmentMail], object], Awaitable[None]
]


async def _deliver_mails(
    settings: Settings, mails: Sequence[AppointmentMail], pool: object
) -> None:
    queue = mail_queue_from_pool(pool)  # type: ignore[arg-type]
    await notify_appointment_mails(queue=queue, settings=settings, mails=mails)


def get_appointment_mail_sender() -> AppointmentMailSender:
    """Return the injectable mail sender that a test can override."""
    return _deliver_mails


MailSenderDep = Annotated[AppointmentMailSender, Depends(get_appointment_mail_sender)]
Member = Annotated[Principal, Depends(require_principal())]


def _send(
    mails: Sequence[AppointmentMail],
    background: BackgroundTasks,
    request: Request,
    settings: Settings,
    send: AppointmentMailSender,
) -> None:
    if mails:
        pool = getattr(request.app.state, "arq_pool", None)
        background.add_task(send, settings, list(mails), pool)


@router.get("/entries", responses={401: _PROBLEM, 422: _PROBLEM})
async def calendar_entries(
    principal: Member,
    db: DbSession,
    start: Annotated[_date, Query(alias="from")],
    end: Annotated[_date, Query(alias="to")],
    mine: bool = False,
) -> EntriesOut:
    """Read the entries with a day between `from` and `to`, both included.

    `mine` limits the cards to the assigned ones and the Termine to those that the
    caller created or is invited to.
    """
    if end < start or end - start > MAX_SPAN:
        raise ValidationProblem("The span must be 0 to 100 days.")
    return EntriesOut(
        items=await CalendarEntries(db).between(principal, start, end, only_mine=mine)
    )


@router.get("/search", responses={401: _PROBLEM})
async def calendar_search(
    principal: Member, db: DbSession, q: Annotated[str, Query(max_length=100)] = ""
) -> EntriesOut:
    """Search the entries of every month by title, the nearest to today first."""
    today = datetime.now(BERLIN).date()
    return EntriesOut(items=await CalendarEntries(db).search(principal, q, today))


@router.get("/people", responses={401: _PROBLEM})
async def calendar_people(
    principal: Member, db: DbSession, q: Annotated[str, Query(max_length=100)] = ""
) -> list[PersonOut]:
    """Search the active accounts by name, for the invitation of a person."""
    return list(await AppointmentService(db).people_search(principal, q))


@router.post(
    "/appointments",
    status_code=status.HTTP_201_CREATED,
    responses={401: _PROBLEM, 403: _PROBLEM, 422: _PROBLEM},
)
async def create_appointment(
    body: AppointmentIn,
    principal: Member,
    db: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send: MailSenderDep,
) -> AppointmentOut:
    """Create a Termin of the caller and invite its Gremien and persons."""
    written = await AppointmentService(db).create(principal, body)
    await db.commit()
    _send(written.mails, background, request, settings, send)
    return cast(AppointmentOut, written.out)


@router.get("/appointments/{appointment_id}", responses={401: _PROBLEM, 404: _PROBLEM})
async def read_appointment(
    appointment_id: UUID, principal: Member, db: DbSession
) -> AppointmentOut:
    """Read one Termin. A Termin that the caller does not read answers 404."""
    return await AppointmentService(db).get(principal, appointment_id)


@router.put(
    "/appointments/{appointment_id}",
    responses={401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM, 422: _PROBLEM},
)
async def update_appointment(
    appointment_id: UUID,
    body: AppointmentIn,
    principal: Member,
    db: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send: MailSenderDep,
) -> AppointmentOut:
    """Replace the data and the invitations of a Termin (creator or `calendar.manage`)."""
    written = await AppointmentService(db).update(principal, appointment_id, body)
    await db.commit()
    _send(written.mails, background, request, settings, send)
    return cast(AppointmentOut, written.out)


@router.delete(
    "/appointments/{appointment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM},
)
async def delete_appointment(
    appointment_id: UUID,
    principal: Member,
    db: DbSession,
    settings: SettingsDep,
    background: BackgroundTasks,
    request: Request,
    send: MailSenderDep,
) -> Response:
    """Delete a Termin (creator or `calendar.manage`)."""
    written = await AppointmentService(db).delete(principal, appointment_id)
    await db.commit()
    _send(written.mails, background, request, settings, send)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/appointments/{appointment_id}/answer",
    responses={401: _PROBLEM, 403: _PROBLEM, 404: _PROBLEM, 409: _PROBLEM},
)
async def answer_appointment(
    appointment_id: UUID, body: AnswerIn, principal: Member, db: DbSession
) -> AppointmentOut:
    """Store the answer of the caller to a Termin, until the Termin ends."""
    out = await AppointmentService(db).answer(
        principal, appointment_id, body.answer, now=datetime.now(UTC)
    )
    await db.commit()
    return out


@router.get("/me", responses={401: _PROBLEM})
async def my_calendar(
    principal: Annotated[Principal, Depends(require_principal())],
    db: DbSession,
    settings: SettingsDep,
) -> CalendarFeedOut:
    """Read the personal subscription URL.

    The URL is `null` until a feed token exists.
    """
    token = await service.get_calendar_token(db, principal.sub)
    return CalendarFeedOut(url=_feed_url(settings, token) if token else None)


@router.post("/me/rotate", responses={401: _PROBLEM})
async def rotate_my_calendar(
    principal: Annotated[Principal, Depends(require_principal())],
    db: DbSession,
    settings: SettingsDep,
) -> CalendarFeedOut:
    """Generate a new feed token.

    The previous subscription URL becomes invalid.
    """
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
async def calendar_feed(token: str, db: DbSession, settings: SettingsDep) -> Response:
    """Serve the public iCal feed for a feed token.

    An unknown or deactivated token gives a 404.

    `member_meetings` filters on `date IS NOT NULL`, so every meeting here has a date. The cache is
    short, so a new or changed meeting shows up quickly. A rotated token is a new URL and therefore
    its own cache key.
    """
    principal = await service.principal_by_calendar_token(db, token)
    if principal is None:
        raise NotFoundError("Unknown calendar feed.")
    meetings = await service.member_meetings(db, principal.sub)
    card_events = await service.readable_events(db, principal)
    due_cards = await service.due_cards(db, principal, settings.public_base_url)
    appointments = await service.feed_appointments(db, principal)
    external = await service.feed_external(db, principal)
    events = [
        MeetingEvent(
            uid=str(meeting.id),
            title=meeting.title,
            date=cast(_date, meeting.date),
            start_time=meeting.start_time,
            end_time=meeting.end_time,
            stamp=meeting.created_at,
            gremium_name=gremium_name,
        )
        for meeting, gremium_name in meetings
    ]
    body = build_calendar(
        events,
        domain=_uid_domain(settings),
        card_events=card_events,
        due_cards=due_cards,
        appointments=appointments,
        external=external,
    )
    return Response(
        content=body,
        status_code=status.HTTP_200_OK,
        media_type=_ICS_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'inline; filename="stupa-sitzungen.ics"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.get("/external/{entry_id}", responses={401: _PROBLEM, 404: _PROBLEM})
async def calendar_external_entry(
    entry_id: UUID, principal: Member, db: DbSession
) -> ExternalEntryOut:
    """Read one entry of an external calendar that the caller reads."""
    return await ExternalCalendarService(db).entry(principal, entry_id)


CalendarsAdmin = Annotated[Principal, Depends(require_principal("admin.calendars"))]
_ADMIN_ERRORS: dict[int | str, dict[str, Any]] = {401: _PROBLEM, 403: _PROBLEM}


@admin_router.get("", responses=_ADMIN_ERRORS)
async def list_external_calendars(
    _admin: CalendarsAdmin, db: DbSession
) -> list[ExternalCalendarOut]:
    """List the external calendars with the state of their newest fetch."""
    return list(await ExternalCalendarService(db).listing())


@admin_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**_ADMIN_ERRORS, 422: _PROBLEM},
)
async def create_external_calendar(
    data: ExternalCalendarIn, _admin: CalendarsAdmin, db: DbSession
) -> ExternalCalendarOut:
    """Subscribe an external calendar. The worker fetches it within a minute."""
    created = await ExternalCalendarService(db).create(data)
    await db.commit()
    return created


@admin_router.put("/{calendar_id}", responses={**_ADMIN_ERRORS, 404: _PROBLEM, 422: _PROBLEM})
async def change_external_calendar(
    calendar_id: UUID, data: ExternalCalendarIn, _admin: CalendarsAdmin, db: DbSession
) -> ExternalCalendarOut:
    """Change an external calendar. A new address starts a fetch."""
    changed = await ExternalCalendarService(db).change(calendar_id, data)
    await db.commit()
    return changed


@admin_router.delete(
    "/{calendar_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_ADMIN_ERRORS, 404: _PROBLEM},
)
async def delete_external_calendar(
    calendar_id: UUID, _admin: CalendarsAdmin, db: DbSession
) -> Response:
    """Delete an external calendar together with its entries."""
    await ExternalCalendarService(db).remove(calendar_id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.post("/{calendar_id}/fetch", responses={**_ADMIN_ERRORS, 404: _PROBLEM})
async def fetch_external_calendar(
    calendar_id: UUID, _admin: CalendarsAdmin, db: DbSession
) -> ExternalCalendarOut:
    """Make an external calendar due at once ("Jetzt abrufen")."""
    due = await ExternalCalendarService(db).request_fetch(calendar_id)
    await db.commit()
    return due
