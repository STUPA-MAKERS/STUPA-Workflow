"""Application creation: validate against the effective form, seed v1 + initial state."""

from __future__ import annotations

from datetime import UTC, datetime
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
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.service import FormsService
from app.modules.forms.validation import AnswerValidationError, validate_answers
from app.shared.errors import NotFoundError, ValidationProblem


class CreateOps(ApplicationsServiceBase):
    """Public/managed application creation."""

    async def create(
        self, payload: ApplicationCreate, *, actor: str = "applicant"
    ) -> tuple[Application, str]:
        """Create an application. Returns ``(application, applicant_email)`` for mailing.

        Order: load effective form → ``validate_answers`` (422 before any DB write) →
        application + PII row + v1 + initial state + status event. ``actor`` is the
        audit actor: ``"applicant"`` for public submission, the principal ``sub`` for
        manual creation by a manager.
        """
        app_type = await self.session.get(ApplicationType, payload.type_id)
        if app_type is None:
            raise NotFoundError(f"application type {payload.type_id} not found")
        # There is exactly ONE active global flow; missing → 404.
        flow_version_id = await self._resolve_flow_version_id(app_type)

        # Effective form (type + optional pot fields); validates pot scoping (404).
        forms = FormsService(self.session)
        effective = await forms.get_effective_form(payload.type_id, payload.budget_pot_id)
        fields = [f for section in effective.sections for f in section.fields]

        context = {"has_budget": app_type.has_budget}
        try:
            validate_answers(fields, payload.data, context)
        except AnswerValidationError as exc:
            raise ValidationProblem(
                "Invalid application data.",
                errors=[{"field": e.field, "msg": e.msg} for e in exc.errors],
            ) from exc

        initial = await self._initial_state(flow_version_id)
        # Persist only known field keys (unknown ones are discarded).
        clean = _whitelist(fields, payload.data)
        amount, currency = _amount_currency(fields, clean)

        app = Application(
            type_id=payload.type_id,
            form_version_id=effective.form_version_id,
            flow_version_id=flow_version_id,
            current_state_id=initial.id,
            gremium_id=app_type.gremium_id,
            budget_pot_id=payload.budget_pot_id,
            amount=amount,
            currency=currency,
            data=clean,
            lang=payload.lang,
            # Logged-in submission: remember the creator (anonymous → None).
            created_by=actor if actor != "applicant" else None,
            # Guest submissions start unconfirmed (invisible until magic-link verify,
            # 12h discard); a logged-in submitter's email counts as confirmed at once.
            email_confirmed_at=None if actor == "applicant" else datetime.now(UTC),
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
        await self.session.commit()

        # Materialize the initial state's deadline: a named deadline policy on it
        # (e.g. "submitted + X days") creates the due deadline row.
        from app.modules.flow.service import FlowService

        await self.session.refresh(app)
        await FlowService(self.session).schedule_state_deadline(app, initial)
        return app, str(payload.applicant_email)

    async def _resolve_flow_version_id(self, app_type: ApplicationType) -> UUID:
        """Resolve the active (global) flow for a new application.

        Type flows are removed — only the single global flow exists; missing
        (fresh install without flow config) → 404."""
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
