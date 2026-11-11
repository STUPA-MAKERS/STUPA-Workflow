"""Calendar feed: token management plus meeting and Event data access.

The feed token authenticates the `.ics` URL without a session or OIDC. Plaintext
storage is acceptable here. The token only exposes the meeting titles and times
of the Gremien of the principal, the title, dates, place and board of the Events
that the principal reads, the title, due date and board of the open cards assigned
to the principal, and the Termine that the principal reads with the principal's own
answer, which is low-sensitivity data. Every function
binds to `principal.sub` and never commits.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.calendar.ics import AppointmentEvent, CardEvent, DueCard
from app.modules.gremien.gremium_roles import gremium_reader_ids
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting

#: 32 bytes give about 43 URL-safe characters. An unguessable token needs no rate limit.
_TOKEN_BYTES = 32


def generate_calendar_token() -> str:
    """Generate a new unguessable feed token (URL-safe)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


async def _row_by_sub(db: AsyncSession, sub: str) -> PrincipalRow | None:
    return (
        await db.execute(select(PrincipalRow).where(PrincipalRow.sub == sub))
    ).scalar_one_or_none()


async def get_calendar_token(db: AsyncSession, sub: str) -> str | None:
    """Read the current feed token of the principal, or `None` when none exists."""
    row = await _row_by_sub(db, sub)
    return row.calendar_token if row is not None else None


async def rotate_calendar_token(db: AsyncSession, sub: str) -> str | None:
    """Generate a new feed token for the principal.

    The old subscription URL becomes invalid. The function does not commit.

    Returns:
        The new token, or `None` when the principal no longer exists.
    """
    row = await _row_by_sub(db, sub)
    if row is None:
        return None
    row.calendar_token = generate_calendar_token()
    await db.flush()
    return row.calendar_token


async def principal_by_calendar_token(db: AsyncSession, token: str) -> PrincipalRow | None:
    """Resolve an active principal by feed token.

    An empty token, an unknown principal or a deactivated principal gives `None`.
    The feed then answers 404 and does not tell a wrong token from a deactivated
    principal.
    """
    if not token:
        return None
    return (
        await db.execute(
            select(PrincipalRow).where(
                PrincipalRow.calendar_token == token,
                PrincipalRow.active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def member_meetings(db: AsyncSession, sub: str) -> list[tuple[Meeting, str]]:
    """List the dated meetings of the Gremien that `sub` is a member of.

    A pool substitute of a Gremium counts as a member (`gremium_reader_ids`), as in
    the meeting list of the app.

    The query drops meetings without a date.

    Returns:
        `(Meeting, gremium_name)` pairs sorted by date and start time.
    """
    gremium_ids = await gremium_reader_ids(db, sub)
    if not gremium_ids:
        return []
    rows = (
        await db.execute(
            select(Meeting, Gremium.name)
            .join(Gremium, Gremium.id == Meeting.gremium_id)
            .where(
                Meeting.gremium_id.in_(gremium_ids),
                Meeting.date.isnot(None),
            )
            .order_by(Meeting.date, Meeting.start_time)
        )
    ).all()
    return [(meeting, name) for meeting, name in rows]


async def readable_events(db: AsyncSession, row: PrincipalRow) -> list[CardEvent]:
    """The Events with a start on the boards that the person reads (spec 000486).

    The feed has no session, so the person's rights come from the `principal` row,
    as at a login.
    """
    from app.modules.auth.rbac import resolve_principal
    from app.modules.todos.service import TodoService

    principal = await resolve_principal(db, row, datetime.now(UTC))
    rows = await TodoService(db).calendar_events(principal)
    return [
        CardEvent(
            uid=str(card.id),
            title=card.title,
            start=cast(date, event.starts_on),
            end=event.ends_on,
            stamp=card.created_at,
            place=event.place,
            board_name=board.name,
        )
        for card, board, event in rows
    ]


async def due_cards(db: AsyncSession, row: PrincipalRow, base_url: str) -> list[DueCard]:
    """The open cards with a due date that are assigned to the person (spec 000549).

    The rights come from the `principal` row, as for the Events.
    """
    from app.modules.auth.rbac import resolve_principal
    from app.modules.todos.links import card_url
    from app.modules.todos.service import TodoService

    principal = await resolve_principal(db, row, datetime.now(UTC))
    rows = await TodoService(db).calendar_due_cards(principal)
    return [
        DueCard(
            uid=str(card.id),
            title=card.title,
            due=cast(date, card.due_date),
            stamp=card.created_at,
            board_name=board.name,
            url=f"{base_url.rstrip('/')}{card_url(card.id)}",
        )
        for card, board in rows
    ]


async def feed_appointments(db: AsyncSession, row: PrincipalRow) -> list[AppointmentEvent]:
    """The Termine that the person reads, with the person's answer (spec 000724).

    The rights come from the `principal` row, as for the Events. An invited person is
    the `ATTENDEE` of the entry, so a calendar app shows the answer as the
    participation status. A Termin that the person only reads has no attendee.
    """
    from app.modules.auth.rbac import resolve_principal
    from app.modules.calendar import rules
    from app.modules.calendar.appointments import AppointmentService, my_answer, readable
    from app.modules.calendar.models import Appointment

    principal = await resolve_principal(db, row, datetime.now(UTC))
    appointments = AppointmentService(db)
    viewer = await appointments.viewer(principal)
    loaded = await appointments.load(
        (
            await db.scalars(
                select(Appointment)
                .where(readable(viewer))
                .order_by(Appointment.starts_on, Appointment.id)
            )
        ).all()
    )
    return [
        AppointmentEvent(
            uid=str(item.row.id),
            title=item.row.title,
            starts_on=item.row.starts_on,
            ends_on=item.row.ends_on,
            start_time=item.row.start_time,
            end_time=item.row.end_time,
            stamp=item.row.created_at,
            place=item.row.place,
            description=item.row.description,
            sequence=item.row.sequence,
            attendee=row.email if rules.is_invited(viewer, item.targets) else None,
            answer=my_answer(viewer, item),
        )
        for item in loaded
    ]
