"""The Kalender part of the erasure and of the Auskunft.

``erase_appointments`` deletes the Termine of the person that invite nobody, because a
private Termin is the person's own note. A Termin with an invitation stays for the
invited persons and loses its creator. The invitations and the answers of the person
go, because both name the person.

``appointment_export`` collects the Termine that the person created and the answers of
the person for the Auskunft workbook.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.calendar.models import Answer, Appointment, Invitation


async def erase_appointments(session: AsyncSession, principal_id: UUID) -> None:
    """Remove the person from the Termine, without a commit.

    The invitations of the person go first, so a Termin that invited only this person
    counts as private and goes with the person's own Termine.
    """
    await session.execute(delete(Answer).where(Answer.principal_id == principal_id))
    await session.execute(delete(Invitation).where(Invitation.principal_id == principal_id))
    await session.execute(
        delete(Appointment)
        .where(
            Appointment.creator_id == principal_id,
            ~exists().where(Invitation.appointment_id == Appointment.id),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Appointment)
        .where(Appointment.creator_id == principal_id)
        .values(creator_id=None)
        .execution_options(synchronize_session=False)
    )


async def appointment_export(session: AsyncSession, principal_ids: list[UUID]) -> dict[str, Any]:
    """Collect the Termine and the answers of the principals for the Auskunft.

    Returns:
        ``{"appointments": [...], "answers": [...]}``, ready for the workbook.
    """
    if not principal_ids:
        return {"appointments": [], "answers": []}
    created = (
        await session.scalars(
            select(Appointment)
            .where(Appointment.creator_id.in_(principal_ids))
            .order_by(Appointment.starts_on, Appointment.id)
        )
    ).all()
    answered = (
        await session.execute(
            select(Answer, Appointment.title, Appointment.starts_on)
            .join(Appointment, Appointment.id == Answer.appointment_id)
            .where(Answer.principal_id.in_(principal_ids))
            .order_by(Appointment.starts_on, Appointment.id)
        )
    ).all()
    return {
        "appointments": [
            {
                "title": row.title,
                "startsOn": row.starts_on,
                "endsOn": row.ends_on,
                "startTime": row.start_time,
                "endTime": row.end_time,
                "place": row.place,
                "description": row.description,
                "createdAt": row.created_at,
            }
            for row in created
        ],
        "answers": [
            {
                "title": title,
                "startsOn": starts_on,
                "answer": answer.answer,
                "answeredAt": answer.answered_at,
            }
            for answer, title, starts_on in answered
        ],
    }
