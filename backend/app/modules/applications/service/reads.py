"""Single-application reads: detail view, pinned effective form, status timeline."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import StatusEvent
from app.modules.applications.schemas import ApplicationOut, TimelineEventOut
from app.modules.applications.service.service_base import ApplicationsServiceBase
from app.modules.forms.schemas import EffectiveFormOut
from app.modules.forms.service import FormsService


class ReadOps(ApplicationsServiceBase):
    """Detail view, pinned effective form and status timeline of one application."""

    async def effective_form(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> EffectiveFormOut:
        """Build the effective form from the pinned version of the application.

        The result also holds the budget-pot fields. The detail view then renders and
        edits the same form that the server validates against. A later change of the
        active form version does not apply, because a running application keeps its
        `form_version_id`.
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        return await FormsService(self.session).get_effective_form(
            app.type_id,
            app.budget_pot_id,
            form_version_id=app.form_version_id,
        )

    async def get(
        self,
        application_id: UUID,
        *,
        include_pii: bool,
        requester_sub: str | None = None,
        requester_can_manage: bool = False,
        allow_unconfirmed: bool = True,
    ) -> ApplicationOut:
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        is_owner = requester_sub is not None and app.created_by == requester_sub
        can_edit = requester_can_manage or is_owner
        return await self._to_out(
            app, include_pii=include_pii, can_edit=can_edit, is_owner=is_owner
        )

    async def timeline(
        self, application_id: UUID, *, allow_unconfirmed: bool = True
    ) -> list[TimelineEventOut]:
        await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        events = (
            await self.session.scalars(
                select(StatusEvent)
                .where(StatusEvent.application_id == application_id)
                .order_by(StatusEvent.at)
            )
        ).all()
        out: list[TimelineEventOut] = []
        # Map the actor sub to a display name. The user interface must never show a
        # raw UUID.
        names = await self._author_names({ev.actor for ev in events if ev.actor})
        for ev in events:
            to_state = await self._get_state(ev.to_state_id)
            out.append(
                TimelineEventOut(
                    fromStateId=ev.from_state_id,
                    toStateId=ev.to_state_id,
                    toState=await self._state_out_resolved(to_state),
                    actor=(names.get(ev.actor, ev.actor) if ev.actor else None),
                    at=ev.at,
                    note=ev.note,
                )
            )
        return out
