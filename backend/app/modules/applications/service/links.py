"""Folgeanträge: the Vorgänger link of an application, its history and the prefill.

An application has at most one Vorgänger of the same application type, and a chain of
Vorgänger links never forms a cycle. The create sets the link in its own transaction
(`check_predecessor`, `write_link`). A later change (`LinkOps.set_predecessor`,
`LinkOps.remove_predecessor`) changes only the link: it adds no submission version and
leaves the answers as they are. Every change writes an `application_link_event` for
the history and an audit entry.

The read rights stay in the router, because only the router knows the caller. This
module checks the rules that hold for every caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import func, select, update

from app.modules.applications.models import (
    Application,
    ApplicationLink,
    ApplicationLinkEvent,
)
from app.modules.applications.schemas import (
    ApplicationPrefillOut,
    LinkedApplicationOut,
    LinkEventOut,
)
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _state_out,
    _title_of,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.flow.models import State
from app.modules.forms.service import FormsService
from app.modules.forms.validation import value_is_valid
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.applications.schemas import ActorOut

#: Error codes of a refused link.
LINK_SELF = "predecessor_self"
LINK_TYPE_MISMATCH = "predecessor_type_mismatch"
LINK_CYCLE = "predecessor_cycle"

#: Field types that a prefill never copies: a file is a document of the old Antrag, and
#: a derived or structural field has no answer of its own.
_NOT_COPIED = frozenset({"file", "computed", "section"})


def _refused(code: str, msg: str) -> ValidationProblem:
    """Build the 422 of a refused Vorgänger, on the field ``predecessorId``."""
    return ValidationProblem(
        "The Vorgänger cannot be linked.",
        code=code,
        errors=[{"field": "predecessorId", "msg": msg}],
    )


async def _chain_contains(session: AsyncSession, start: UUID, target: UUID) -> bool:
    """Tell whether ``target`` is ``start`` or one of the Vorgänger above ``start``.

    The recursive query follows the links upward. ``UNION`` drops a row it has seen,
    so a broken chain cannot loop forever.
    """
    base = (
        select(ApplicationLink.predecessor_id.label("id"))
        .where(ApplicationLink.application_id == start)
        .cte("chain", recursive=True)
    )
    chain = base.union(
        select(ApplicationLink.predecessor_id).join(
            base, ApplicationLink.application_id == base.c.id
        )
    )
    found = await session.scalar(select(chain.c.id).where(chain.c.id == target).limit(1))
    return start == target or found is not None


async def check_predecessor(
    session: AsyncSession,
    *,
    type_id: UUID,
    predecessor_id: UUID,
    application_id: UUID | None = None,
) -> None:
    """Check the rules of a Vorgänger that hold for every caller.

    The Vorgänger must exist and be confirmed, must have the application type of the
    application, must not be the application and must not have the application above
    it in its own chain. ``application_id`` is None at the create, where no chain exists
    yet.

    Raises:
        NotFoundError: The Vorgänger does not exist or is not confirmed.
        ValidationProblem: A self link, another type or a cycle.
    """
    row = (
        await session.execute(
            select(Application.type_id, Application.email_confirmed_at).where(
                Application.id == predecessor_id
            )
        )
    ).first()
    if row is None or row[1] is None:
        raise NotFoundError(f"application {predecessor_id} not found")
    if application_id is not None and application_id == predecessor_id:
        raise _refused(LINK_SELF, "must not be the application itself")
    if row[0] != type_id:
        raise _refused(LINK_TYPE_MISMATCH, "must have the same application type")
    if application_id is not None and await _chain_contains(
        session, predecessor_id, application_id
    ):
        raise _refused(LINK_CYCLE, "must not form a cycle")


async def write_link(
    session: AsyncSession,
    *,
    application_id: UUID,
    predecessor_id: UUID,
    actor: str,
    previous: UUID | None = None,
) -> None:
    """Set the Vorgänger and write its history entry and its audit entry, without a commit.

    ``previous`` is the Vorgänger that the change replaces, None for a new link. The
    caller has run `check_predecessor` and the read and edit checks.
    """
    linked = await session.scalar(
        select(ApplicationLink.application_id).where(
            ApplicationLink.application_id == application_id
        )
    )
    if linked is None:
        session.add(
            ApplicationLink(
                application_id=application_id, predecessor_id=predecessor_id, linked_by=actor
            )
        )
    else:
        await session.execute(
            update(ApplicationLink)
            .where(ApplicationLink.application_id == application_id)
            .values(predecessor_id=predecessor_id, linked_by=actor, linked_at=func.now())
        )
    session.add(
        ApplicationLinkEvent(
            application_id=application_id,
            predecessor_id=predecessor_id,
            action="set",
            actor=actor,
        )
    )
    await audit_record(
        session,
        actor=actor,
        action=AuditAction.APPLICATION_LINK_SET,
        target_type="application",
        target_id=str(application_id),
        data={
            "predecessorId": str(predecessor_id),
            "previousId": str(previous) if previous is not None else None,
        },
    )


def prefill_data(
    fields: list[FormFieldDef], data: dict[str, Any], hidden: set[str]
) -> dict[str, Any]:
    """Pick the answers of a Vorgänger that the current form takes.

    An answer is copied when its field key exists in ``fields``, its field type is no
    file, derived or structural field, its key is not in ``hidden`` (the ``isPII`` keys
    that the caller may not read), and its value passes the type check of the field.
    """
    return {
        field.key: data[field.key]
        for field in fields
        if field.type not in _NOT_COPIED
        and field.key not in hidden
        and field.key in data
        and value_is_valid(field, data[field.key])
    }


class LinkOps(ApplicationsServiceBase):
    """The Vorgänger link of an application after its create, and the prefill."""

    async def predecessor_of(self, application_id: UUID) -> UUID | None:
        """Return the Vorgänger of an application, or None."""
        return await self.session.scalar(
            select(ApplicationLink.predecessor_id).where(
                ApplicationLink.application_id == application_id
            )
        )

    async def set_predecessor(
        self, application_id: UUID, predecessor_id: UUID, *, actor: str
    ) -> None:
        """Set or change the Vorgänger of an existing application.

        The answers and the versions stay as they are. Setting the same Vorgänger again
        changes nothing and writes nothing.

        Raises:
            NotFoundError: The application or the Vorgänger does not exist.
            ValidationProblem: A self link, another type or a cycle.
        """
        app = await self._get_app(application_id)
        await check_predecessor(
            self.session,
            type_id=app.type_id,
            predecessor_id=predecessor_id,
            application_id=application_id,
        )
        previous = await self.predecessor_of(application_id)
        if previous == predecessor_id:
            return
        await write_link(
            self.session,
            application_id=application_id,
            predecessor_id=predecessor_id,
            actor=actor,
            previous=previous,
        )
        await self.session.commit()

    async def remove_predecessor(self, application_id: UUID, *, actor: str) -> None:
        """Remove the Vorgänger of an existing application.

        An application without a Vorgänger stays as it is and writes nothing.

        Raises:
            NotFoundError: The application does not exist.
        """
        await self._get_app(application_id)
        link = await self.session.get(ApplicationLink, application_id)
        if link is None:
            return
        removed = link.predecessor_id
        await self.session.delete(link)
        self.session.add(
            ApplicationLinkEvent(
                application_id=application_id,
                predecessor_id=removed,
                action="removed",
                actor=actor,
            )
        )
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.APPLICATION_LINK_REMOVE,
            target_type="application",
            target_id=str(application_id),
            data={"predecessorId": str(removed)},
        )
        await self.session.commit()

    async def successors_of(self, application_id: UUID) -> list[UUID]:
        """Return the Folgeanträge of an application, oldest link first."""
        return list(
            (
                await self.session.scalars(
                    select(ApplicationLink.application_id)
                    .where(ApplicationLink.predecessor_id == application_id)
                    .order_by(ApplicationLink.linked_at)
                )
            ).all()
        )

    async def link_events(self, application_id: UUID) -> list[ApplicationLinkEvent]:
        """Return the link history of an application, oldest first."""
        return list(
            (
                await self.session.scalars(
                    select(ApplicationLinkEvent)
                    .where(ApplicationLinkEvent.application_id == application_id)
                    .order_by(ApplicationLinkEvent.at)
                )
            ).all()
        )

    async def linked_out(self, ids: set[UUID]) -> dict[UUID, LinkedApplicationOut]:
        """Build the rows of the linked applications, in one query.

        An unconfirmed application is left out, as in the lists.
        """
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                select(Application, State)
                .outerjoin(State, State.id == Application.current_state_id)
                .where(Application.id.in_(ids), Application.email_confirmed_at.is_not(None))
            )
        ).all()
        colors = await self._resolve_state_colors()
        return {
            app.id: LinkedApplicationOut(
                id=app.id,
                title=_title_of(app.data),
                state=_state_out(state, colors.get(state.key)) if state else None,
                createdAt=app.created_at,
                archived=app.archived_at is not None,
            )
            for app, state in rows
        }

    async def link_event_actors(
        self,
        application_id: UUID,
        events: list[ApplicationLinkEvent],
        *,
        applicant_view: bool,
        magic_link_view: bool,
    ) -> dict[str, ActorOut]:
        """Resolve the actors of the link history like those of the timeline."""
        app = await self._get_app(application_id)
        return await self._resolve_actors(
            app,
            (ev.actor for ev in events),
            applicant_view=applicant_view,
            magic_link_view=magic_link_view,
        )

    async def prefill(self, predecessor_id: UUID, *, hidden: set[str]) -> ApplicationPrefillOut:
        """Return the answers of a Vorgänger that fit the current form of its type.

        ``hidden`` holds the ``isPII`` keys that the caller may not read.

        Raises:
            NotFoundError: The Vorgänger does not exist or its type has no form.
        """
        app = await self._get_app(predecessor_id, allow_unconfirmed=False)
        effective = await FormsService(self.session).get_effective_form(app.type_id)
        fields = [f for section in effective.sections for f in section.fields]
        return ApplicationPrefillOut(
            typeId=app.type_id, data=prefill_data(fields, app.data or {}, hidden)
        )


def link_event_out(
    ev: ApplicationLinkEvent,
    actors: dict[str, ActorOut],
    shown: dict[UUID, LinkedApplicationOut],
) -> LinkEventOut:
    """Build one entry of the link history; a hidden Vorgänger stays null."""
    return LinkEventOut(
        action="set" if ev.action == "set" else "removed",
        at=ev.at,
        actorInfo=actors.get(ev.actor) if ev.actor else None,
        predecessor=shown.get(ev.predecessor_id) if ev.predecessor_id else None,
    )
