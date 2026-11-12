"""Single-application reads: detail view, pinned effective form, status timeline."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.modules.applications.decision import amount_deviates, decisions_by_event
from app.modules.applications.models import (
    Applicant,
    Application,
    ApplicationDecision,
    StatusEvent,
)
from app.modules.applications.schemas import (
    ActorOut,
    ApplicationOut,
    StateOut,
    TimelineDecisionOut,
    TimelineEventOut,
)
from app.modules.applications.service.service_base import ApplicationsServiceBase
from app.modules.budget.form_options import budget_field_options
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
        return await FormsService(self.session, budget_field_options).get_effective_form(
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
        requester_edits_any: bool = False,
        allow_unconfirmed: bool = True,
        strip_pii_fields: bool = False,
        applicant_view: bool = False,
        magic_link_view: bool = False,
        observer: bool = False,
    ) -> ApplicationOut:
        """Read one application.

        ``include_pii`` adds the applicant block. ``strip_pii_fields`` removes the
        ``isPII`` form fields from ``data`` for a reader without the PII right.
        ``applicant_view`` and ``magic_link_view`` follow `timeline`: the capture
        block then names the Gremium instead of the capturing member.
        ``requester_edits_any`` is ``application.edit_any``: it sets ``canEdit`` and
        ``canEditLocked``, because the PATCH lifts the state lock for that holder.
        ``observer`` marks the observer view and adds the applicant name as
        ``submittedBy``.
        """
        app = await self._get_app(application_id, allow_unconfirmed=allow_unconfirmed)
        is_owner = requester_sub is not None and app.created_by == requester_sub
        can_edit = requester_can_manage or requester_edits_any or is_owner
        out = await self._to_out(
            app,
            include_pii=include_pii,
            can_edit=can_edit,
            can_edit_locked=requester_edits_any,
            is_owner=is_owner,
            strip_pii_fields=strip_pii_fields,
            applicant_view=applicant_view,
            magic_link_view=magic_link_view,
        )
        submitted_by = (
            await self.session.scalar(
                select(Applicant.name).where(Applicant.application_id == application_id)
            )
            if observer
            else None
        )
        return (
            out.model_copy(update={"observer": True, "submitted_by": submitted_by})
            if observer
            else out
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

        Each event carries the label of the fired transition. In the
        ``applicant_view`` the actor of every event that the applicant did not do is
        the name of the Gremium of the application. The applicant then
        never sees the name of a member. ``magic_link_view`` marks the magic-link
        reader; see `_applicant_actors` for the creator who submitted for another
        email.

        All actors resolve in one batch, because the UI must never show a raw sub or key. A vote
        close writes the note ``vote:<result>`` and the vote id. A meeting delete deletes the
        vote and clears the id: the event stays and the application keeps its status.
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
        actors = await self._resolve_actors(
            app,
            (ev.actor for ev, _ in rows),
            applicant_view=applicant_view,
            magic_link_view=magic_link_view,
        )
        decisions = await decisions_by_event(self.session, application_id)
        return [
            _event_out(
                app,
                ev,
                label,
                await self._state_out_resolved(await self._get_state(ev.to_state_id)),
                actors.get(ev.actor) if ev.actor else None,
                decisions.get(ev.id) if decisions else None,
                applicant_view=applicant_view,
            )
            for ev, label in rows
        ]


def _event_out(
    app: Application,
    ev: StatusEvent,
    label: dict[str, Any] | None,
    to_state: StateOut | None,
    info: ActorOut | None,
    decision: ApplicationDecision | None,
    *,
    applicant_view: bool,
) -> TimelineEventOut:
    """Build one event of the timeline from its row and its resolved parts."""
    from_vote = (ev.note or "").startswith("vote:")
    return TimelineEventOut(
        fromStateId=ev.from_state_id,
        toStateId=ev.to_state_id,
        toState=to_state,
        transitionLabel=label or None,
        actor=info.legacy(ev.actor) if info and ev.actor else None,
        actorInfo=info,
        at=ev.at,
        note=ev.note,
        voteId=None if applicant_view else ev.vote_id,
        voteDeleted=from_vote and ev.vote_id is None,
        decision=TimelineDecisionOut(
            requestedAmount=app.amount,
            approvedAmount=decision.approved_amount,
            amountDeviates=amount_deviates(app.amount, decision.approved_amount),
            conditionCount=len(decision.conditions or []),
        )
        if decision is not None
        else None,
    )
