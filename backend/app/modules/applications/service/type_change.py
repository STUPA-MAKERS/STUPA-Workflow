"""Change the Antragsart of a submitted application (specs 001660-001663).

A change writes a new version in the active form of the new type. It carries over each
value whose field key exists in the new form with the same field type and a value that
passes the check of the new field. The old version keeps every value, so nothing is
deleted (spec 001662). When the new form misses a required value, the change also fires
a manual transition into a state with ``editAllowed``, and its note names the missing
fields (spec 001661). The version records the old and the new type, and the audit entry
``application_type_change`` holds both (spec 001663).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.modules.application_types.models import ApplicationType
from app.modules.applications.decision import CODE_AMOUNT_EXCEEDS
from app.modules.applications.diff import compute_diff, is_empty_diff
from app.modules.applications.models import Application, SubmissionVersion
from app.modules.applications.schemas import (
    TypeChangeFieldOut,
    TypeChangeIn,
    TypeChangePreviewOut,
    TypeChangeTransitionOut,
)
from app.modules.applications.service.service_base import (
    ApplicationsServiceBase,
    _amount_currency,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.form_options import budget_field_options
from app.modules.flow.models import State
from app.modules.forms.service import FormsService
from app.modules.forms.validation import (
    AnswerValidationError,
    validate_answers,
    value_is_valid,
    with_computed,
)
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.auth.principal import Principal
    from app.modules.flow.service import FlowService, StagedFire

#: Field types without an own answer: the server derives them or they only split the form.
_NO_VALUE = frozenset({"computed", "section"})

CODE_SAME_TYPE = "type_change_same_type"
CODE_NOT_SUBMITTED = "type_change_not_submitted"
CODE_TYPE_NOT_SUBMITTABLE = "type_change_type_not_submittable"
CODE_NO_EDIT_TRANSITION = "type_change_no_edit_transition"
CODE_TRANSITION_REQUIRED = "type_change_transition_required"
CODE_TRANSITION_NOT_NEEDED = "type_change_transition_not_needed"

_MISSING_NOTE: Mapping[str, str] = {
    "de": "Nach dem Wechsel der Antragsart fehlen diese Pflichtangaben: {fields}.",
    "en": "After the change of the application type these required fields are missing: {fields}.",
}


def _present(value: object) -> bool:
    """Tell whether a stored answer holds a value; an empty text, list or dict holds none."""
    if value is None:
        return False
    if isinstance(value, (str, list, dict)):
        return len(value) > 0
    return True


def carry_values(
    old_fields: Sequence[FormFieldDef],
    new_fields: Sequence[FormFieldDef],
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Pick the answers that the new form takes.

    An answer moves when the new form has a field with its key and the same type, and the
    value passes the check of the new field. A derived or structural field has no answer.
    """
    old_types = {f.key: f.type for f in old_fields}
    return {
        f.key: data[f.key]
        for f in new_fields
        if f.type not in _NO_VALUE
        and old_types.get(f.key) == f.type
        and f.key in data
        and value_is_valid(f, data[f.key])
    }


def _error_names(field_key: str, error_field: str) -> bool:
    """Tell whether the error of ``error_field`` belongs to the field ``field_key``.

    A positions or table error names a path below the field, for example ``key[0]``.
    """
    return error_field == field_key or error_field.startswith((f"{field_key}[", f"{field_key}."))


def missing_fields(
    fields: Sequence[FormFieldDef], data: Mapping[str, Any], context: Mapping[str, Any]
) -> tuple[FormFieldDef, ...]:
    """Return the fields of the new form that the carried answers do not complete.

    These are the visible required fields without a value, and the fields whose value
    fails a check across fields (for example the requested funding above the total).
    """
    try:
        validate_answers(fields, data, context)
    except AnswerValidationError as exc:
        names = [e.field for e in exc.errors]
        return tuple(f for f in fields if any(_error_names(f.key, n) for n in names))
    return ()


def dropped_fields(
    old_fields: Sequence[FormFieldDef], data: Mapping[str, Any], carried: Mapping[str, Any]
) -> tuple[FormFieldDef, ...]:
    """Return the fields of the old form with a value that the new form does not take."""
    return tuple(
        f
        for f in old_fields
        if f.type not in _NO_VALUE and f.key not in carried and _present(data.get(f.key))
    )


def missing_note(fields: Sequence[FormFieldDef], lang: str | None, extra: str | None) -> str:
    """Build the note of the transition: the missing fields, then the text of the person."""
    code = lang if lang is not None and lang in _MISSING_NOTE else "de"
    names = ", ".join(_label(f, code) for f in fields)
    text = _MISSING_NOTE[code].format(fields=names)
    tail = (extra or "").strip()
    return f"{text}\n\n{tail}" if tail else text


def _label(field: FormFieldDef, lang: str) -> str:
    """Return the label of a field in ``lang``, then German, then the key."""
    label = field.label or {}
    return label.get(lang) or label.get("de") or next(iter(label.values()), None) or field.key


def _field_out(field: FormFieldDef) -> TypeChangeFieldOut:
    return TypeChangeFieldOut(key=field.key, label=dict(field.label or {}))


def _move_to_type(plan: _Plan, amount: Decimal | None, currency: str | None) -> None:
    """Point the application at the new type, its active form, its Gremium and the answers."""
    columns = {
        "type_id": plan.new_type.id,
        "form_version_id": plan.new_form_version_id,
        "gremium_id": plan.new_type.gremium_id,
        "data": plan.carried,
        "amount": amount,
        "currency": currency,
    }
    for column, value in columns.items():
        setattr(plan.app, column, value)


@dataclass(frozen=True, slots=True)
class _Plan:
    """The computed effect of a change before any write."""

    app: Application
    new_type: ApplicationType
    new_form_version_id: UUID
    new_fields: tuple[FormFieldDef, ...]
    carried: dict[str, Any]
    missing: tuple[FormFieldDef, ...]
    dropped: tuple[FormFieldDef, ...]
    carried_fields: tuple[FormFieldDef, ...]


class TypeChangeOps(ApplicationsServiceBase):
    """Change of the Antragsart: the preview of the dialog and the change."""

    async def _type_change_plan(self, application_id: UUID, type_id: UUID) -> _Plan:
        """Compute what a change to ``type_id`` does.

        Raises:
            NotFoundError: The application or the type does not exist (404).
            ConflictError: The application is still in the initial state (409).
            ValidationProblem: The type is the current one, or it has no active form (422).
        """
        app = await self._get_app(application_id, allow_unconfirmed=False)
        if type_id == app.type_id:
            raise ValidationProblem(
                "The application already has this type.",
                code=CODE_SAME_TYPE,
                errors=[{"field": "typeId", "msg": "same type"}],
            )
        state = await self._get_state(app.current_state_id)
        if state is None or state.is_initial:
            raise ConflictError(
                "Only a submitted application can change its type.", code=CODE_NOT_SUBMITTED
            )
        new_type = await self.session.get(ApplicationType, type_id)
        if new_type is None:
            raise NotFoundError(f"application type {type_id} not found")
        if new_type.active_form_version_id is None:
            raise ValidationProblem(
                "The application type has no active form.",
                code=CODE_TYPE_NOT_SUBMITTABLE,
                errors=[{"field": "typeId", "msg": "no active form"}],
            )
        forms = FormsService(self.session, budget_field_options)
        new_form = await forms.get_effective_form(type_id)
        old_form = await forms.get_effective_form(app.type_id, form_version_id=app.form_version_id)
        new_fields = tuple(f for s in new_form.sections for f in s.fields)
        old_fields = tuple(f for s in old_form.sections for f in s.fields)
        data = app.data or {}
        context = {"has_budget": new_type.has_budget}
        carried = with_computed(new_fields, carry_values(old_fields, new_fields, data), context)
        return _Plan(
            app=app,
            new_type=new_type,
            new_form_version_id=new_form.form_version_id,
            new_fields=new_fields,
            carried=carried,
            missing=missing_fields(new_fields, carried, context),
            dropped=dropped_fields(old_fields, data, carried),
            carried_fields=tuple(
                f for f in new_fields if f.key in carried and f.type not in _NO_VALUE
            ),
        )

    async def _edit_transitions(
        self, flow: FlowService, application_id: UUID, principal: Principal
    ) -> tuple[TypeChangeTransitionOut, ...]:
        """List the manual transitions the person may fire into a state with ``editAllowed``."""
        available = await flow.available_transitions(
            application_id, principal, allow_unconfirmed=False
        )
        targets = [(t, await self.session.get(State, t.to_state_id)) for t in available]
        return tuple(
            TypeChangeTransitionOut(
                id=t.id,
                label=t.label,
                toStateId=t.to_state_id,
                toStateLabel=dict(state.label_i18n or {}),
            )
            for t, state in targets
            if state is not None and state.edit_allowed
        )

    async def type_change_preview(
        self, application_id: UUID, type_id: UUID, principal: Principal, flow: FlowService
    ) -> TypeChangePreviewOut:
        """Return what a change to ``type_id`` carries, misses and drops (spec 001661)."""
        plan = await self._type_change_plan(application_id, type_id)
        transitions = (
            await self._edit_transitions(flow, application_id, principal) if plan.missing else ()
        )
        return TypeChangePreviewOut(
            typeId=type_id,
            carried=tuple(_field_out(f) for f in plan.carried_fields),
            missing=tuple(_field_out(f) for f in plan.missing),
            dropped=tuple(_field_out(f) for f in plan.dropped),
            transitions=transitions,
            possible=not plan.missing or bool(transitions),
        )

    async def stage_type_change(
        self,
        application_id: UUID,
        payload: TypeChangeIn,
        principal: Principal,
        flow: FlowService,
    ) -> StagedFire | None:
        """Write a change of the Antragsart into the open transaction (specs 001660-001663).

        The change writes a new version with the carried answers in the active form of the
        new type, and moves the type, the form version and the Gremium of the type to the
        application. The version holds the old and the new type and the old form version, so
        the history names both types and the labels of the removed fields. The old version
        keeps every value.

        With a missing required value the change fires ``payload.transitionId`` in the same
        transaction. Its note names the missing fields in the language of the application.
        Without such a transition the change answers 409. The caller commits, then runs
        `FlowService.after_commit` with the returned staged transition (the mail to the
        applicant), because a service does not commit.

        Returns:
            The staged transition, or None when no required value is missing.

        The audit entry ``application_type_change`` holds the ids and the field keys, never
        a value. A concurrent edit that wrote the same version number answers 409.

        Raises:
            ConflictError: Not submitted yet, no transition into an editable state, or a
                concurrent edit (409).
            ValidationProblem: The same type, a type without a form, a missing or a needless
                ``transitionId``, or a new requested amount below the approved one (422).
        """
        plan = await self._type_change_plan(application_id, payload.type_id)
        app = plan.app
        if plan.missing:
            transitions = await self._edit_transitions(flow, application_id, principal)
            if not transitions:
                raise ConflictError(
                    "No transition sends the application back to the applicant.",
                    code=CODE_NO_EDIT_TRANSITION,
                )
            if payload.transition_id not in {t.id for t in transitions}:
                raise ValidationProblem(
                    "Pick a transition that sends the application back to the applicant.",
                    code=CODE_TRANSITION_REQUIRED,
                    errors=[{"field": "transitionId", "msg": "required"}],
                )
        elif payload.transition_id is not None:
            raise ValidationProblem(
                "No required field is missing, so no transition fires.",
                code=CODE_TRANSITION_NOT_NEEDED,
                errors=[{"field": "transitionId", "msg": "not needed"}],
            )

        fields = list(plan.new_fields)
        new_amount, new_currency = _amount_currency(fields, plan.carried)
        if app.approved_amount is not None and (
            new_amount is None or new_amount < app.approved_amount
        ):
            raise ValidationProblem(
                "The requested amount must not fall below the approved amount.",
                code=CODE_AMOUNT_EXCEEDS,
                errors=[{"field": "amount", "msg": "below the approved amount"}],
            )

        old_type_id, old_form_version_id = app.type_id, app.form_version_id
        diff = compute_diff(app.data or {}, plan.carried)
        next_version = await self._current_version(application_id) + 1
        self.session.add(
            SubmissionVersion(
                application_id=app.id,
                version=next_version,
                data=plan.carried,
                changed_by=principal.sub,
                diff=None if is_empty_diff(diff) else dict(diff),
                from_type_id=old_type_id,
                to_type_id=plan.new_type.id,
                from_form_version_id=old_form_version_id,
            )
        )
        _move_to_type(plan, new_amount, new_currency)
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.APPLICATION_TYPE_CHANGE,
            target_type="application",
            target_id=str(app.id),
            data={
                "fromTypeId": str(old_type_id),
                "toTypeId": str(plan.new_type.id),
                "fromFormVersionId": str(old_form_version_id),
                "toFormVersionId": str(plan.new_form_version_id),
                "version": next_version,
                "carriedFields": sorted(plan.carried),
                "droppedFields": sorted(f.key for f in plan.dropped),
                "missingFields": sorted(f.key for f in plan.missing),
                "transitionId": (
                    str(payload.transition_id) if plan.missing and payload.transition_id else None
                ),
            },
        )
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError(
                "Concurrent update detected; please retry.", code="concurrent_update"
            ) from exc
        transition_id = payload.transition_id if plan.missing else None
        return (
            await flow.stage_fire(
                app.id,
                transition_id,
                principal,
                note=missing_note(plan.missing, app.lang, payload.note),
                allow_unconfirmed=False,
            )
            if transition_id is not None
            else None
        )
