"""Application creation: validate against the effective form, seed v1 and the state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.admin.models import ApplicationType
from app.modules.applications.models import (
    Applicant,
    Application,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.applications.schemas import ApplicationCreate
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _amount_currency,
    _whitelist,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.service import FormsService
from app.modules.forms.validation import AnswerValidationError, validate_answers
from app.shared.errors import NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.flow.dispatch import ActionDispatcher


class CreateOps(ApplicationsServiceBase):
    """Public and managed application creation."""

    async def create(
        self,
        payload: ApplicationCreate,
        *,
        actor: str = "applicant",
        dispatcher: ActionDispatcher | None = None,
        email_confirmed: bool | None = None,
    ) -> tuple[Application, str]:
        """Create an application.

        The method runs in a fixed order:

        1. Load the effective form.
        2. Run ``validate_answers``. A bad answer raises 422 before any DB write.
        3. Write the application, the PII row, version 1, the initial state and
           the status event.
        4. Start the flow of a confirmed application
           (``FlowService.start_confirmed``): the deadline of the initial state,
           the automatic transitions and the task mail. ``dispatcher`` sends the
           mails and the other flow actions.

        ``actor`` names the audit actor. A public submission passes
        ``"applicant"``. A manual creation by a manager passes the ``sub`` of the
        principal.

        A public submission starts unconfirmed and rests in the flow: no deadline,
        no automatic transition and no mail. The magic-link verify starts the flow
        (``auth.service.verify_magic_link``).

        ``email_confirmed`` tells whether the applicant email is already confirmed.
        The router sets it to False for a logged-in person who enters an email
        other than the account email (F23). That application then rests like a
        guest submission. ``None`` keeps the old rule: only a guest submission
        (``actor == "applicant"``) is unconfirmed.

        The create writes an ``application_create`` audit entry in the same
        transaction (F12). It holds the type, the gremium, the initial state and
        the confirmation flag, never PII.

        Returns:
            The application and the applicant email, for the magic-link mail.
        """
        app_type = await self.session.get(ApplicationType, payload.type_id)
        if app_type is None:
            raise NotFoundError(f"application type {payload.type_id} not found")
        # Exactly one global flow is active. A missing flow answers 404.
        flow_version_id = await self._resolve_flow_version_id(app_type)

        forms = FormsService(self.session)
        effective = await forms.get_effective_form(payload.type_id)
        fields = [f for section in effective.sections for f in section.fields]

        context = {"has_budget": app_type.has_budget}
        try:
            validate_answers(fields, payload.data, context)
        except AnswerValidationError as exc:
            raise ValidationProblem(
                "Invalid application data.",
                errors=[{"field": e.field, "msg": e.msg} for e in exc.errors],
            ) from exc

        confirmed = actor != "applicant" if email_confirmed is None else email_confirmed
        initial = await self._initial_state(flow_version_id)
        # Store the known field keys only. The code discards an unknown key.
        clean = _whitelist(fields, payload.data)
        amount, currency = _amount_currency(fields, clean)

        app = Application(
            type_id=payload.type_id,
            form_version_id=effective.form_version_id,
            flow_version_id=flow_version_id,
            current_state_id=initial.id,
            gremium_id=app_type.gremium_id,
            amount=amount,
            currency=currency,
            data=clean,
            lang=payload.lang,
            # A logged-in submission remembers the creator. An anonymous one
            # stores None.
            created_by=actor if actor != "applicant" else None,
            # An unconfirmed submission stays invisible until the magic-link
            # verify. The worker discards it after `confirm_ttl_hours`.
            email_confirmed_at=datetime.now(UTC) if confirmed else None,
        )
        self.session.add(app)
        await self.session.flush()

        self.session.add(
            Applicant(
                application_id=app.id,
                email=str(payload.applicant_email),
                name=payload.applicant_name,
            )
        )
        self.session.add(
            SubmissionVersion(
                application_id=app.id,
                version=1,
                data=clean,
                changed_by=actor,
                diff=None,
            )
        )
        self.session.add(
            StatusEvent(
                application_id=app.id,
                from_state_id=None,
                to_state_id=initial.id,
                actor=actor,
            )
        )
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.APPLICATION_CREATE,
            target_type="application",
            target_id=str(app.id),
            data={
                "typeId": str(app.type_id),
                "gremiumId": str(app.gremium_id) if app.gremium_id else None,
                "initialStateId": str(initial.id),
                "emailConfirmed": confirmed,
            },
        )
        await self.session.commit()

        if app.email_confirmed_at is not None:
            # A logged-in submission with the account email is confirmed at once.
            # Start its flow now. Any other submission waits for the magic-link
            # verify.
            from app.modules.flow.service import FlowService

            await FlowService(self.session, dispatcher).start_confirmed(app.id)
            await self.session.refresh(app)
        return app, str(payload.applicant_email)

    async def _resolve_flow_version_id(self, app_type: ApplicationType) -> UUID:
        """Resolve the active global flow for a new application.

        There is one global flow and no per-type flows. A fresh install without a flow
        config has none, so the method answers 404.
        """
        global_flow_id = (
            await self.session.execute(select(FlowVersion.id).where(FlowVersion.active.is_(True)))
        ).scalar_one_or_none()
        if global_flow_id is not None:
            return global_flow_id
        raise NotFoundError(f"no active global flow for application type {app_type.id}")

    async def _initial_state(self, flow_version_id: UUID) -> State:
        state = (
            await self.session.execute(
                select(State).where(
                    State.flow_version_id == flow_version_id,
                    State.is_initial.is_(True),
                )
            )
        ).scalar_one_or_none()
        if state is None:
            raise NotFoundError("flow has no initial state")
        return state
