"""Termine: create, read, change, delete and answer.

`AppointmentService` holds the database reads and writes, and `rules` holds the
decisions. No method commits; the router commits and then sends the mails that a write
returns (`Written.mails`).

An invited Gremium stands for its members and its substitute pool at the time of the
read (`gremium_person_ids`), the persons who read its meetings without a global
permission. A holder of ``meeting.view_all`` reads the meetings of every Gremium and is
not invited by that, because the permission is a view and no membership.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, delete, exists, false, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.calendar import rules
from app.modules.calendar.models import Answer, Appointment, Invitation
from app.modules.calendar.rules import Span, Targets, Viewer
from app.modules.calendar.schemas import (
    AnswerKey,
    AnswerOut,
    AppointmentIn,
    AppointmentOut,
    GremiumRefOut,
    PersonOut,
)
from app.modules.gremien.gremium_roles import gremium_reader_ids
from app.modules.gremien.models import DelegationSubstitute, Gremium, GremiumMembership
from app.modules.meetings.rules import MeetingRules
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.search import escape_like

CALENDAR_MANAGE = "calendar.manage"
CALENDAR_PUBLISH = "calendar.publish"

#: The times of a Termin are local values of this zone, like the times of a meeting.
BERLIN = ZoneInfo("Europe/Berlin")

MailKind = Literal["invited", "changed", "cancelled"]


@dataclass(frozen=True, slots=True)
class AppointmentFacts:
    """The data of a Termin that a mail and its ``.ics`` file need.

    The mail of a deleted Termin is sent after the commit, when the row is gone, so the
    mail carries the facts and not the id alone.
    """

    id: UUID
    title: str
    span: Span
    description: str | None
    sequence: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AppointmentMail:
    """A mail that the router sends after the commit.

    ``event_id`` is new for every mail and goes into the idempotency key, because the
    key is the arq job id and a second change of the same Termin must not reuse it.
    """

    kind: MailKind
    facts: AppointmentFacts
    recipients: tuple[UUID, ...]
    actor_id: UUID
    event_id: UUID = field(default_factory=uuid.uuid4, compare=False)


@dataclass(frozen=True, slots=True)
class Written:
    """The result of a write: the Termin as the caller sees it, and the mails to send."""

    out: AppointmentOut | None
    mails: tuple[AppointmentMail, ...] = ()


@dataclass(frozen=True, slots=True)
class Loaded:
    """A Termin row with its invitations and answers."""

    row: Appointment
    targets: Targets
    answers: tuple[Answer, ...]


def span_of(row: Appointment | AppointmentIn) -> Span:
    """The start, the end and the place of a row or of a request body."""
    return Span(
        starts_on=row.starts_on,
        ends_on=row.ends_on,
        start_time=row.start_time,
        end_time=row.end_time,
        place=(row.place or "").strip() or None,
    )


def _facts(row: Appointment) -> AppointmentFacts:
    return AppointmentFacts(
        id=row.id,
        title=row.title,
        span=span_of(row),
        description=row.description,
        sequence=row.sequence,
        created_at=row.created_at,
    )


def _mail(
    kind: MailKind, row: Appointment, recipients: Collection[UUID], actor_id: UUID
) -> tuple[AppointmentMail, ...]:
    to = tuple(sorted(set(recipients) - {actor_id}, key=str))
    return (
        (AppointmentMail(kind=kind, facts=_facts(row), recipients=to, actor_id=actor_id),)
        if to
        else ()
    )


def readable(viewer: Viewer) -> ColumnElement[bool]:
    """The SQL form of `rules.can_read` for a list of Termine."""
    if viewer.id is None:
        return false()
    if viewer.manages:
        return true()
    return or_(Appointment.for_all.is_(True), Appointment.public.is_(True), mine(viewer))


def mine(viewer: Viewer) -> ColumnElement[bool]:
    """The Termine that the viewer created or is invited to (the filter "Nur meine")."""
    if viewer.id is None:
        return false()
    return or_(
        Appointment.creator_id == viewer.id,
        exists().where(
            Invitation.appointment_id == Appointment.id,
            or_(
                Invitation.principal_id == viewer.id,
                Invitation.gremium_id.in_(viewer.gremium_ids),
            ),
        ),
    )


async def gremium_person_ids(
    session: AsyncSession, gremium_ids: Collection[UUID]
) -> frozenset[UUID]:
    """The persons that an invitation of the Gremien reaches: members and pool substitutes."""
    if not gremium_ids:
        return frozenset()
    members = await session.scalars(
        select(GremiumMembership.principal_id).where(GremiumMembership.gremium_id.in_(gremium_ids))
    )
    pool = await session.scalars(
        select(DelegationSubstitute.substitute_principal_id).where(
            DelegationSubstitute.gremium_id.in_(gremium_ids)
        )
    )
    return frozenset(members.all()) | frozenset(pool.all())


class AppointmentService:
    """The reads and writes of the Termine, bound to one session."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to the session of the request."""
        self.session = session

    async def viewer(self, principal: Principal) -> Viewer:
        """Resolve the caller. A scoped OAuth token gives a viewer without an id."""
        if principal.scope_permissions is not None:
            return Viewer(id=None)
        return Viewer(
            id=await self.session.scalar(
                select(PrincipalRow.id).where(PrincipalRow.sub == principal.sub)
            ),
            gremium_ids=frozenset(await gremium_reader_ids(self.session, principal.sub)),
            manages=principal.has(CALENDAR_MANAGE),
            publishes=principal.has(CALENDAR_PUBLISH),
        )

    async def people(self, targets: Targets) -> frozenset[UUID]:
        """Every person that the invitations reach at this moment."""
        return targets.principal_ids | await gremium_person_ids(self.session, targets.gremium_ids)

    async def load(self, rows: Sequence[Appointment]) -> tuple[Loaded, ...]:
        """Read the invitations and the answers of the rows with two statements.

        The answers are read fresh (``populate_existing``), because `answer` writes one
        with a statement and the session would keep the older row.
        """
        ids = [row.id for row in rows]
        if not ids:
            return ()
        invitations = (
            await self.session.scalars(select(Invitation).where(Invitation.appointment_id.in_(ids)))
        ).all()
        answers = (
            await self.session.scalars(
                select(Answer)
                .where(Answer.appointment_id.in_(ids))
                .execution_options(populate_existing=True)
            )
        ).all()
        return tuple(
            Loaded(
                row=row,
                targets=Targets(
                    gremium_ids=frozenset(
                        i.gremium_id
                        for i in invitations
                        if i.appointment_id == row.id and i.gremium_id is not None
                    ),
                    principal_ids=frozenset(
                        i.principal_id
                        for i in invitations
                        if i.appointment_id == row.id and i.principal_id is not None
                    ),
                ),
                answers=tuple(a for a in answers if a.appointment_id == row.id),
            )
            for row in rows
        )

    async def between(
        self, viewer: Viewer, start: date, end: date, *, only_mine: bool = False
    ) -> tuple[Loaded, ...]:
        """The readable Termine with a day in the span, both ends included."""
        rows = (
            await self.session.scalars(
                select(Appointment)
                .where(
                    Appointment.starts_on <= end,
                    Appointment.ends_on >= start,
                    mine(viewer) if only_mine else readable(viewer),
                )
                .order_by(Appointment.starts_on, Appointment.start_time, Appointment.id)
            )
        ).all()
        return await self.load(rows)

    async def matching(self, viewer: Viewer, pattern: str, limit: int) -> tuple[Loaded, ...]:
        """The readable Termine whose title or place matches the ILIKE pattern, newest first."""
        rows = (
            await self.session.scalars(
                select(Appointment)
                .where(
                    or_(
                        Appointment.title.ilike(pattern, escape="\\"),
                        Appointment.place.ilike(pattern, escape="\\"),
                    ),
                    readable(viewer),
                )
                .order_by(Appointment.starts_on.desc(), Appointment.id)
                .limit(limit)
            )
        ).all()
        return await self.load(rows)

    async def people_search(
        self, principal: Principal, q: str, limit: int = 10
    ) -> tuple[PersonOut, ...]:
        """The active accounts whose name holds ``q``, for the invitation of a person.

        The search needs two characters and answers the name only, never the e-mail
        address. A scoped token finds nobody.
        """
        term = q.strip()
        viewer = await self.viewer(principal)
        if viewer.id is None or len(term) < 2:
            return ()
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name)
                .where(
                    PrincipalRow.active.is_(True),
                    PrincipalRow.display_name.ilike(f"%{escape_like(term)}%", escape="\\"),
                )
                .order_by(PrincipalRow.display_name, PrincipalRow.id)
                .limit(limit)
            )
        ).all()
        return tuple(PersonOut(id=pid, name=name or "") for pid, name in rows)

    async def _names(self, ids: Collection[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.id.in_(ids)
                )
            )
        ).all()
        return {pid: name or (email or "").partition("@")[0] for pid, name, email in rows}

    async def _gremium_names(self, ids: Collection[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        rows = (
            await self.session.execute(select(Gremium.id, Gremium.name).where(Gremium.id.in_(ids)))
        ).all()
        return {row[0]: row[1] for row in rows}

    async def gremium_names(self, loaded: Sequence[Loaded]) -> dict[UUID, str]:
        """The names of every Gremium that the Termine invite."""
        return await self._gremium_names(
            {gid for item in loaded for gid in item.targets.gremium_ids}
        )

    async def out(self, viewer: Viewer, item: Loaded) -> AppointmentOut:
        """Build the body of one Termin for the viewer."""
        row = item.row
        shows = rules.sees_answers(viewer, row.creator_id, item.targets)
        answers = item.answers if shows else ()
        answered = frozenset(a.principal_id for a in answers)
        unanswered = (await self.people(item.targets)) - answered if shows else frozenset[UUID]()
        names = await self._names(
            {*item.targets.principal_ids, *answered, *unanswered}
            | ({row.creator_id} if row.creator_id is not None else set())
        )
        gremien = await self._gremium_names(item.targets.gremium_ids)
        return AppointmentOut(
            id=row.id,
            title=row.title,
            starts_on=row.starts_on,
            ends_on=row.ends_on,
            start_time=row.start_time,
            end_time=row.end_time,
            place=row.place,
            description=row.description,
            for_all=row.for_all,
            public=row.public,
            creator=(
                PersonOut(id=row.creator_id, name=names.get(row.creator_id, ""))
                if row.creator_id is not None
                else None
            ),
            gremien=tuple(
                sorted(
                    (GremiumRefOut(id=gid, name=name) for gid, name in gremien.items()),
                    key=lambda g: g.name.casefold(),
                )
            ),
            persons=tuple(
                sorted(
                    (
                        PersonOut(id=pid, name=names.get(pid, ""))
                        for pid in item.targets.principal_ids
                    ),
                    key=lambda p: p.name.casefold(),
                )
            ),
            answers=tuple(
                sorted(
                    (
                        AnswerOut(
                            principal_id=a.principal_id,
                            name=names.get(a.principal_id, ""),
                            answer=cast(AnswerKey, a.answer),
                        )
                        for a in answers
                    ),
                    key=lambda a: a.name.casefold(),
                )
            ),
            unanswered=tuple(
                sorted(
                    (PersonOut(id=pid, name=names[pid]) for pid in unanswered if pid in names),
                    key=lambda p: p.name.casefold(),
                )
            ),
            my_answer=my_answer(viewer, item),
            invited=rules.is_invited(viewer, item.targets),
            can_edit=rules.can_edit(viewer, row.creator_id),
        )

    async def _readable_row(self, viewer: Viewer, appointment_id: UUID, *, lock: bool) -> Loaded:
        """Read one Termin, or answer 404 when the viewer does not read it."""
        stmt = select(Appointment).where(Appointment.id == appointment_id)
        row = await self.session.scalar(stmt.with_for_update() if lock else stmt)
        loaded = await self.load([row] if row is not None else [])
        if not loaded or not rules.can_read(
            viewer,
            loaded[0].row.creator_id,
            loaded[0].targets,
            for_all=loaded[0].row.for_all or loaded[0].row.public,
        ):
            raise NotFoundError("Unknown appointment.")
        return loaded[0]

    async def get(self, principal: Principal, appointment_id: UUID) -> AppointmentOut:
        """Read one Termin.

        Raises:
            NotFoundError: The Termin is unknown or not readable by the caller.
        """
        viewer = await self.viewer(principal)
        return await self.out(viewer, await self._readable_row(viewer, appointment_id, lock=False))

    async def _check_targets(
        self, principal: Principal, viewer: Viewer, data: AppointmentIn, before: Targets
    ) -> None:
        """Refuse an unknown target and a Gremium that the caller must not invite."""
        known_gremien = await self._gremium_names(data.gremium_ids)
        known_persons = (
            set(
                (
                    await self.session.scalars(
                        select(PrincipalRow.id).where(
                            PrincipalRow.id.in_(data.principal_ids), PrincipalRow.active.is_(True)
                        )
                    )
                ).all()
            )
            if data.principal_ids
            else set()
        )
        if set(data.gremium_ids) - set(known_gremien):
            raise ValidationProblem(
                "Unknown Gremium.", errors=[{"field": "gremiumIds", "msg": "unknown"}]
            )
        if set(data.principal_ids) - known_persons - before.principal_ids:
            raise ValidationProblem(
                "Unknown person.", errors=[{"field": "principalIds", "msg": "unknown"}]
            )
        scope = (
            None
            if viewer.manages
            else (await MeetingRules(self.session).meeting_read_scope(principal))[0]
        )
        if rules.forbidden_gremien(data.gremium_ids, scope, before.gremium_ids):
            raise ForbiddenError(
                "You cannot invite this Gremium.", code="calendar_gremium_forbidden"
            )

    async def create(self, principal: Principal, data: AppointmentIn) -> Written:
        """Create a Termin of the caller with its invitations.

        Raises:
            ForbiddenError: A scoped token, the switches "Für alle" and "Öffentlich" without
                ``calendar.publish``, or a Gremium that the caller must not invite.
            ValidationProblem: An unknown Gremium or person.
        """
        viewer = await self.viewer(principal)
        if viewer.id is None:
            raise ForbiddenError("The Kalender needs a session.")
        if (data.for_all or data.public) and not viewer.publishes:
            raise ForbiddenError("You cannot show a Termin to everyone.", code="calendar_publish")
        await self._check_targets(principal, viewer, data, Targets())
        span = span_of(data)
        row = Appointment(
            title=data.title.strip(),
            starts_on=span.starts_on,
            ends_on=span.ends_on,
            start_time=span.start_time,
            end_time=span.end_time,
            place=span.place,
            description=(data.description or "").strip() or None,
            creator_id=viewer.id,
            for_all=data.for_all,
            public=data.public,
        )
        self.session.add(row)
        await self.session.flush()
        targets = Targets(frozenset(data.gremium_ids), frozenset(data.principal_ids))
        self.session.add_all(
            [
                *(Invitation(appointment_id=row.id, gremium_id=gid) for gid in targets.gremium_ids),
                *(
                    Invitation(appointment_id=row.id, principal_id=pid)
                    for pid in targets.principal_ids
                ),
            ]
        )
        await self.session.flush()
        await self.session.refresh(row)
        return Written(
            out=await self.out(viewer, Loaded(row=row, targets=targets, answers=())),
            mails=_mail("invited", row, await self.people(targets), viewer.id),
        )

    async def update(
        self, principal: Principal, appointment_id: UUID, data: AppointmentIn
    ) -> Written:
        """Replace the data and the invitations of a Termin.

        A change of the start or the end deletes the answers. A person who is no longer
        invited loses the answer too.

        Raises:
            NotFoundError: The Termin is unknown or not readable by the caller.
            ForbiddenError: The caller is neither the creator nor a manager, changes the
                switch "Für alle" without ``calendar.publish`` or invites a Gremium that
                the caller must not invite.
            ValidationProblem: An unknown Gremium or person.
        """
        viewer = await self.viewer(principal)
        item = await self._readable_row(viewer, appointment_id, lock=True)
        row = item.row
        if viewer.id is None or not rules.can_edit(viewer, row.creator_id):
            raise ForbiddenError("Only the creator changes a Termin.")
        if (data.for_all, data.public) != (row.for_all, row.public) and not viewer.publishes:
            raise ForbiddenError("You cannot show a Termin to everyone.", code="calendar_publish")
        await self._check_targets(principal, viewer, data, item.targets)
        before = span_of(row)
        after = span_of(data)
        targets = Targets(frozenset(data.gremium_ids), frozenset(data.principal_ids))
        people_before = await self.people(item.targets)
        await self.session.execute(
            update(Appointment)
            .where(Appointment.id == row.id)
            .values(
                title=data.title.strip(),
                starts_on=after.starts_on,
                ends_on=after.ends_on,
                start_time=after.start_time,
                end_time=after.end_time,
                place=after.place,
                description=(data.description or "").strip() or None,
                for_all=data.for_all,
                public=data.public,
                sequence=Appointment.sequence + (1 if rules.needs_mail(before, after) else 0),
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(
            delete(Invitation).where(
                Invitation.appointment_id == row.id,
                or_(
                    Invitation.gremium_id.in_(item.targets.gremium_ids - targets.gremium_ids),
                    Invitation.principal_id.in_(item.targets.principal_ids - targets.principal_ids),
                ),
            )
        )
        self.session.add_all(
            [
                *(
                    Invitation(appointment_id=row.id, gremium_id=gid)
                    for gid in targets.gremium_ids - item.targets.gremium_ids
                ),
                *(
                    Invitation(appointment_id=row.id, principal_id=pid)
                    for pid in targets.principal_ids - item.targets.principal_ids
                ),
            ]
        )
        await self.session.flush()
        people_after = await self.people(targets)
        gone = (
            delete(Answer).where(Answer.appointment_id == row.id)
            if rules.time_changed(before, after)
            else delete(Answer).where(
                Answer.appointment_id == row.id, Answer.principal_id.not_in(people_after)
            )
        )
        await self.session.execute(gone)
        await self.session.flush()
        await self.session.refresh(row)
        fresh = (await self.load([row]))[0]
        return Written(
            out=await self.out(viewer, fresh),
            mails=(
                *_mail("invited", row, people_after - people_before, viewer.id),
                *(
                    _mail("changed", row, people_after & people_before, viewer.id)
                    if rules.needs_mail(before, after)
                    else ()
                ),
            ),
        )

    async def delete(self, principal: Principal, appointment_id: UUID) -> Written:
        """Delete a Termin with its invitations and answers.

        Raises:
            NotFoundError: The Termin is unknown or not readable by the caller.
            ForbiddenError: The caller is neither the creator nor a manager.
        """
        viewer = await self.viewer(principal)
        item = await self._readable_row(viewer, appointment_id, lock=True)
        if viewer.id is None or not rules.can_edit(viewer, item.row.creator_id):
            raise ForbiddenError("Only the creator deletes a Termin.")
        mails = _mail("cancelled", item.row, await self.people(item.targets), viewer.id)
        await self.session.delete(item.row)
        await self.session.flush()
        return Written(out=None, mails=mails)

    async def answer(
        self, principal: Principal, appointment_id: UUID, answer: AnswerKey, *, now: datetime
    ) -> AppointmentOut:
        """Store the answer of the caller, replacing an older one.

        Raises:
            NotFoundError: The Termin is unknown or not readable by the caller.
            ForbiddenError: The caller is not invited.
            ConflictError: The Termin is over.
        """
        viewer = await self.viewer(principal)
        item = await self._readable_row(viewer, appointment_id, lock=True)
        if viewer.id is None or not rules.is_invited(viewer, item.targets):
            raise ForbiddenError("Only an invited person answers a Termin.")
        local = now.astimezone(BERLIN)
        if rules.has_ended(span_of(item.row), local.date(), _wall(local)):
            raise ConflictError("The Termin is over.", code="calendar_appointment_over")
        await self.session.execute(
            insert(Answer)
            .values(
                appointment_id=item.row.id, principal_id=viewer.id, answer=answer, answered_at=now
            )
            .on_conflict_do_update(
                index_elements=[Answer.appointment_id, Answer.principal_id],
                set_={"answer": answer, "answered_at": now},
            )
        )
        await self.session.flush()
        return await self.out(viewer, (await self.load([item.row]))[0])


def _wall(moment: datetime) -> time:
    return moment.time().replace(tzinfo=None)


def my_answer(viewer: Viewer, item: Loaded) -> AnswerKey | None:
    """The answer of the viewer to the Termin, or None."""
    return next(
        (cast(AnswerKey, a.answer) for a in item.answers if a.principal_id == viewer.id), None
    )
