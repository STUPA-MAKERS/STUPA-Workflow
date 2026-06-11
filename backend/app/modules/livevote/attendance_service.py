"""Anwesenheits-Service für Sitzungen (#Meetings/#55/#56).

Roster = die **aktuellen** Mitglieder des Sitzungs-Gremiums (gremium_membership im
gültigen Amtszeit-Fenster). Mitglieder markieren sich selbst (``source='self'``),
die Sitzungsleitung kann jede:n setzen (``source='lead'``). Pro (Sitzung, Mitglied)
existiert genau ein Eintrag (Upsert über die Unique-Constraint).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.models import Meeting, MeetingAttendance
from app.modules.livevote.schemas import AttendanceOut, AttendanceStatus
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError


class AttendanceService:
    """Roster + Anwesenheits-Upsert, an eine ``AsyncSession`` gebunden."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = (
            await self.session.execute(select(Meeting).where(Meeting.id == meeting_id))
        ).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _current_members(self, gremium_id: UUID) -> list[PrincipalRow]:
        """Aktuelle Gremium-Mitglieder (Amtszeit-Fenster gültig), je Principal einmalig."""
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(PrincipalRow)
                .join(
                    GremiumMembership,
                    GremiumMembership.principal_id == PrincipalRow.id,
                )
                .where(
                    GremiumMembership.gremium_id == gremium_id,
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
                .order_by(PrincipalRow.display_name)
                .distinct()
            )
        ).scalars().all()
        return list(rows)

    async def roster(self, meeting_id: UUID, requester_sub: str) -> list[AttendanceOut]:
        """Mitglieder + ihre (ggf. noch leere) Anwesenheit für diese Sitzung."""
        meeting = await self._meeting(meeting_id)
        members = await self._current_members(meeting.gremium_id)
        records = (
            await self.session.execute(
                select(MeetingAttendance).where(
                    MeetingAttendance.meeting_id == meeting_id
                )
            )
        ).scalars().all()
        by_principal = {r.principal_id: r for r in records}
        out: list[AttendanceOut] = []
        for m in members:
            rec = by_principal.get(m.id)
            out.append(
                AttendanceOut(
                    principalId=m.id,
                    displayName=m.display_name,
                    email=m.email,
                    status=rec.status if rec else None,  # type: ignore[arg-type]
                    source=rec.source if rec else None,  # type: ignore[arg-type]
                    isSelf=m.sub == requester_sub,
                )
            )
        return out

    async def _upsert(
        self,
        meeting_id: UUID,
        principal_id: UUID,
        status: AttendanceStatus,
        source: str,
    ) -> None:
        existing = (
            await self.session.execute(
                select(MeetingAttendance).where(
                    MeetingAttendance.meeting_id == meeting_id,
                    MeetingAttendance.principal_id == principal_id,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            self.session.add(
                MeetingAttendance(
                    meeting_id=meeting_id,
                    principal_id=principal_id,
                    status=status,
                    source=source,
                )
            )
        else:
            existing.status = status
            existing.source = source
        await self.session.flush()
        await self.session.commit()

    @staticmethod
    def _ensure_not_closed(meeting: Meeting) -> None:
        """Anwesenheit ist nach dem Schließen eingefroren (#attendance-lock).

        Das finalisierte Protokoll trägt die Anwesenheitslisten — nachträgliche
        Änderungen würden PDF und System auseinanderlaufen lassen → 409."""
        if meeting.status == "closed":
            raise ConflictError(
                "Attendance is read-only once the meeting is closed.", code="conflict"
            )

    async def set_self(
        self, meeting_id: UUID, status: AttendanceStatus, requester_sub: str
    ) -> list[AttendanceOut]:
        """Eigene Anwesenheit setzen (nur Gremium-Mitglieder, nicht nach Schließen)."""
        meeting = await self._meeting(meeting_id)
        self._ensure_not_closed(meeting)
        member = next(
            (
                m
                for m in await self._current_members(meeting.gremium_id)
                if m.sub == requester_sub
            ),
            None,
        )
        if member is None:
            raise ForbiddenError("only committee members can mark their attendance")
        await self._upsert(meeting_id, member.id, status, source="self")
        return await self.roster(meeting_id, requester_sub)

    async def set_for(
        self,
        meeting_id: UUID,
        principal_id: UUID,
        status: AttendanceStatus,
        requester_sub: str,
    ) -> list[AttendanceOut]:
        """Anwesenheit eines Mitglieds durch die Sitzungsleitung setzen (nicht nach Schließen)."""
        meeting = await self._meeting(meeting_id)
        self._ensure_not_closed(meeting)
        members = await self._current_members(meeting.gremium_id)
        if not any(m.id == principal_id for m in members):
            raise NotFoundError("principal is not a current member of this committee")
        await self._upsert(meeting_id, principal_id, status, source="lead")
        return await self.roster(meeting_id, requester_sub)
