"""Guard-Kontext-Aufbau für die Flow-Engine (flows §9.2).

``eval_guard`` (T-05) ist eine **reine** Funktion über einem
:class:`~app.shared.guards.GuardContext`. Dieses Modul füllt den Kontext aus dem
Antrag + Principal + abgeleiteten Signalen:

* ``roles``/``permissions`` — aus dem :class:`Principal` (RBAC, fail-closed).
* ``fields_complete`` — Antwortdaten gegen die **gepinnte** Form validiert (T-11/T-12).
* ``vote_result`` — vom Aufrufer (T-15 ``voting.close`` → ``flow.fire``); default ``None``.
* ``deadline_passed`` — vom Aufrufer (T-44 Cron); default ``False``.
* ``manual`` — ob der Übergang manuell ausgelöst wird (Default ``True`` für die API).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.budget.models import BudgetField
from app.modules.forms.models import FormField
from app.modules.forms.validation import AnswerValidationError, validate_answers
from app.shared.config_schemas import FormFieldDef
from app.shared.guards import GuardContext


def _field_from_row(row: FormField) -> FormFieldDef:
    """``form_field``-Zeile → ``FormFieldDef`` (camelCase-Eingabe wie im forms-Modul)."""
    return FormFieldDef.model_validate(
        {
            "key": row.key,
            "type": row.type,
            "label": row.label_i18n,
            "help": row.help_i18n,
            "required": row.required,
            "validation": row.validation or None,
            "visibleIf": row.visible_if,
            "compute": row.compute,
            "options": row.options,
            "isPII": row.is_pii,
            "isPromoted": row.is_promoted,
            "promoteTarget": row.promote_target,
        }
    )


async def _pinned_fields(session: AsyncSession, app: Application) -> list[FormFieldDef]:
    """Felder der **gepinnten** Form-Version des Antrags (+ Topf-Felder)."""
    rows = (
        await session.execute(
            select(FormField)
            .where(FormField.form_version_id == app.form_version_id)
            .order_by(FormField.order)
        )
    ).scalars().all()
    fields = [_field_from_row(r) for r in rows]
    if app.budget_pot_id is not None:
        pot_rows = (
            await session.execute(
                select(BudgetField)
                .where(BudgetField.budget_pot_id == app.budget_pot_id)
                .order_by(BudgetField.order)
            )
        ).scalars().all()
        fields.extend(FormFieldDef.model_validate(r.field) for r in pot_rows)
    return fields


async def fields_complete(session: AsyncSession, app: Application) -> bool:
    """``True`` wenn die aktuellen Antwortdaten die gepinnte Form vollständig erfüllen.

    ``has_budget``-Kontext kommt aus dem **Typ** (nicht aus ``budget_pot_id``) —
    konsistent zu T-12 ``patch`` (sonst flippt ``visibleIf: has_budget``)."""
    fields = await _pinned_fields(session, app)
    app_type = (
        await session.execute(
            select(ApplicationType).where(ApplicationType.id == app.type_id)
        )
    ).scalar_one_or_none()
    context: dict[str, Any] = {
        "has_budget": app_type.has_budget if app_type is not None else False
    }
    try:
        validate_answers(fields, app.data, context)
    except AnswerValidationError:
        return False
    return True


def build_context(
    principal: Principal,
    *,
    fields_complete: bool,
    vote_result: str | None,
    deadline_passed: bool,
    manual: bool,
) -> GuardContext:
    """Reinen :class:`GuardContext` aus Principal + Signalen bauen (kein I/O)."""
    return GuardContext(
        roles=frozenset(principal.roles),
        permissions=frozenset(principal.permissions),
        fields_complete=fields_complete,
        vote_result=vote_result,
        deadline_passed=deadline_passed,
        manual=manual,
    )
