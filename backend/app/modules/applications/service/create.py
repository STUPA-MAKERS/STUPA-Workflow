"""Application creation: validate against the effective form, seed v1 and the state."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any
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
from app.modules.files.drafts import DRAFT_ATTACHMENTS_MISSING, bind_drafts, check_drafts
from app.modules.flow.models import FlowVersion, State
from app.modules.flow.vote_gremium import resolve_vote_gremium
from app.modules.forms.service import FormsService
from app.modules.forms.validation import AnswerValidationError, validate_answers
from app.settings import get_settings
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.flow.dispatch import ActionDispatcher


@dataclass(frozen=True, slots=True)
class Capture:
    """A capture on behalf of the applicant (#11).

    ``owner_sub`` is the ``sub`` of the applicant account, or None for a guest
    applicant. It becomes ``created_by``, so the applicant owns the application as if
    the applicant had submitted it. The capturing person (the ``actor`` of the create)
    shows only in the history and the audit log.
    """

    owner_sub: str | None
    applicant_principal_id: UUID | None
    received_on: date
    intake: str | None
    #: A guest e-mail matched an active account, which became the applicant.
    matched_by_email: bool = False


class CreateOps(ApplicationsServiceBase):
    """Public and managed application creation."""

    async def create(
        self,
        payload: ApplicationCreate,
        *,
        actor: str = "applicant",
        dispatcher: ActionDispatcher | None = None,
        email_confirmed: bool | None = None,
        draft_pepper: str | None = None,
        capture: Capture | None = None,
    ) -> tuple[Application, str]:
        """Create an application.

        The method runs in a fixed order:

        1. Load the effective form.
        2. Run ``validate_answers``. A bad answer raises 422 before any DB write.
           Check and lock the draft uploads of the wizard (Z4, ``_check_drafts``).
           A missing, expired, foreign or infected draft raises 422 too.
        3. Write the application, the PII row, version 1, the initial state and
           the status event. Bind the drafts to the application.
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
        transaction (F12). It holds the type, the gremium, the initial state, the
        confirmation flag and the number of bound drafts, never PII.

        ``capture`` marks a capture on behalf of the applicant (#11). The owner
        (``created_by``) is then ``capture.owner_sub`` and not the actor. The actor
        (the capturing person) writes version 1 and the first status event, and the
        create writes a second audit entry ``application_create_on_behalf``.

        ``draft_pepper`` is the pepper of the draft-token hash
        (``MAGIC_LINK_SECRET``). The router passes the value of its settings.
        ``None`` reads it from ``get_settings``.

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
        # Draft uploads of the wizard (Z4). The check locks the drafts, so nothing
        # removes them before the bind below. It runs before the first write.
        pepper = await self._check_drafts(payload, fields, clean, draft_pepper)

        app = Application(
            type_id=payload.type_id,
            form_version_id=effective.form_version_id,
            flow_version_id=flow_version_id,
            current_state_id=initial.id,
            # A vote state as the initial state has a fixed Gremium (the validator
            # forbids `gremiumSource` there), so the snapshot starts at once.
            vote_gremium_id=await resolve_vote_gremium(self.session, initial, None),
            gremium_id=app_type.gremium_id,
            amount=amount,
            currency=currency,
            data=clean,
            lang=payload.lang,
            # A logged-in submission remembers the creator. An anonymous one
            # stores None. A capture stores the applicant account (or None for a
            # guest), never the capturing person.
            created_by=(
                capture.owner_sub
                if capture is not None
                else (actor if actor != "applicant" else None)
            ),
            captured_by=actor if capture is not None else None,
            capture_intake=capture.intake if capture is not None else None,
            received_on=capture.received_on if capture is not None else None,
            # An unconfirmed submission stays invisible until the magic-link
            # verify. The worker discards it after `confirm_ttl_hours`.
            email_confirmed_at=datetime.now(UTC) if confirmed else None,
        )
        self.session.add(app)
        await self.session.flush()
        if pepper is not None and payload.draft_token is not None:
            await bind_drafts(
                self.session,
                application_id=app.id,
                attachment_ids=payload.attachment_ids,
                token=payload.draft_token,
                pepper=pepper,
            )

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
                "attachments": len(set(payload.attachment_ids)),
            },
        )
        if capture is not None:
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.APPLICATION_CREATE_ON_BEHALF,
                target_type="application",
                target_id=str(app.id),
                data={
                    "applicantKind": "principal" if capture.owner_sub else "guest",
                    "applicantPrincipalId": (
                        str(capture.applicant_principal_id)
                        if capture.applicant_principal_id
                        else None
                    ),
                    "receivedOn": capture.received_on.isoformat(),
                    "intake": capture.intake is not None,
                    "matchedByEmail": capture.matched_by_email,
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

    async def _check_drafts(
        self,
        payload: ApplicationCreate,
        fields: list[FormFieldDef],
        clean: dict[str, Any],
        draft_pepper: str | None = None,
    ) -> str | None:
        """Check the draft uploads that the create binds (Z4).

        Without ``attachmentIds`` and ``draftToken`` the method does nothing. With
        them, it checks three things and answers 422 for each failure:

        1. A list of ids needs the token.
        2. Every reference in a ``file`` field is one of ``attachmentIds``.
        3. The token owns every listed draft, and each draft is neither expired nor
           infected. A pending scan passes. The errors name each failed id.

        Returns:
            The pepper of the token hash for the bind, or None without drafts.
        """
        ids = payload.attachment_ids
        if not ids and payload.draft_token is None:
            return None
        if payload.draft_token is None:
            raise ValidationProblem(
                "attachmentIds needs a draftToken.",
                errors=[{"field": "draftToken", "msg": "required with attachmentIds"}],
            )
        listed = set(ids)
        foreign = [
            {"field": f"data.{key}", "msg": f"{ref} is not in attachmentIds"}
            for key, ref in _file_refs(fields, clean)
            if _as_uuid(ref) not in listed
        ]
        if foreign:
            raise ValidationProblem(
                "A file field names an attachment that is not part of the submission.",
                code=DRAFT_ATTACHMENTS_MISSING,
                errors=foreign,
            )
        pepper = draft_pepper or get_settings().magic_link_secret
        if ids:
            await check_drafts(
                self.session, attachment_ids=ids, token=payload.draft_token, pepper=pepper
            )
        return pepper

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


def _file_refs(
    fields: list[FormFieldDef], data: dict[str, Any]
) -> Iterator[tuple[str, str]]:
    """Yield ``(field key, reference)`` for each value of a ``file`` field."""
    for field in fields:
        if field.type != "file":
            continue
        value = data.get(field.key)
        refs = [value] if isinstance(value, str) else value
        if isinstance(refs, list):
            for ref in refs:
                if isinstance(ref, str) and ref:
                    yield field.key, ref


def _as_uuid(ref: str) -> UUID | None:
    """Parse an attachment reference. A value that is no UUID gives None."""
    try:
        return UUID(ref)
    except ValueError:
        return None
