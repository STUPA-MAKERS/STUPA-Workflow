"""Single-application reads: detail view, pinned effective form, status timeline."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import StatusEvent
from app.modules.applications.schemas import ApplicationOut, TimelineEventOut
from app.modules.applications.service.service_base import ApplicationsServiceBase
from app.modules.flow.models import Transition
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
        strip_pii_fields: bool = False,
    ) -> ApplicationOut:
        """Read one application.

        ``include_pii`` adds the applicant block. ``strip_pii_fields`` removes the
        ``isPII`` form fields from ``data`` for a reader without the PII right (O21).
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        is_owner = requester_sub is not None and app.created_by == requester_sub
        can_edit = requester_can_manage or is_owner
        return await self._to_out(
            app,
            include_pii=include_pii,
            can_edit=can_edit,
            is_owner=is_owner,
            strip_pii_fields=strip_pii_fields,
        )

    async def timeline(
        self,
        application_id: UUID,
        *,
        allow_unconfirmed: bool = True,
        applicant_view: bool = False,
        magic_link_view: bool = False,
    ) -> list[TimelineEventOut]:
        """Return the status timeline, oldest event first.

        Each event carries the label of the fired transition (A3). In the
        ``applicant_view`` the actor of every event that the applicant did not do is
        the name of the Gremium of the application (A12, O16). The applicant then
        never sees the name of a member. ``magic_link_view`` marks the magic-link
        reader; see `_applicant_actors` for the creator who submitted for another
        email (F23).
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        rows = (
            await self.session.execute(
                select(StatusEvent, Transition.label_i18n)
                .outerjoin(Transition, Transition.id == StatusEvent.transition_id)
                .where(StatusEvent.application_id == application_id)
                .order_by(StatusEvent.at)
            )
        ).all()
        out: list[TimelineEventOut] = []
        # Resolve every actor in one batch. The user interface must never show a
        # raw sub or key.
        actors = await self._resolve_actors(
            app,
            (ev.actor for ev, _ in rows),
            applicant_view=applicant_view,
            magic_link_view=magic_link_view,
        )
        for ev, label in rows:
            to_state = await self._get_state(ev.to_state_id)
            info = actors.get(ev.actor) if ev.actor else None
            out.append(
                TimelineEventOut(
                    fromStateId=ev.from_state_id,
                    toStateId=ev.to_state_id,
                    toState=await self._state_out_resolved(to_state),
                    transitionLabel=label or None,
                    actor=info.legacy(ev.actor) if info and ev.actor else None,
                    actorInfo=info,
                    at=ev.at,
                    note=ev.note,
                )
            )
        return out
