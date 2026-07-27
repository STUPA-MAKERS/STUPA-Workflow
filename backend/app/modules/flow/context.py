"""Guard-context assembly for the flow engine.

`eval_guard` is a pure function over a `GuardContext` (`app.shared.guards`). This module
fills that context from the application, the triggering principal, and derived facts.
The facts are actor roles and Gremien (manual transitions only), applicant roles and
Gremien, budget fit, and form field values and types for `compare`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import ApplicationType, GremiumMembership
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import BudgetAllocation, BudgetExpense
from app.modules.files.models import Attachment
from app.modules.forms.models import FormField
from app.shared.guards import GuardContext

# Form field type to `compare` value type (guards.COMPARE_TYPES).
_FIELD_TYPE_MAP: dict[str, str] = {
    "number": "number",
    "currency": "currency",
    "date": "date",
    "checkbox": "bool",
    "boolean": "bool",
}


def _compare_type(field_type: str) -> str:
    """Map a form field type to a `compare` value type. The default is `text`."""
    return _FIELD_TYPE_MAP.get(field_type, "text")


async def _committees_for_sub(session: AsyncSession, sub: str | None) -> frozenset[str]:
    """Return the Gremium ids where `sub` is a member now, inside the term window."""
    if not sub:
        return frozenset()
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(GremiumMembership.gremium_id)
            .join(PrincipalRow, PrincipalRow.id == GremiumMembership.principal_id)
            .where(
                PrincipalRow.sub == sub,
                (GremiumMembership.valid_from.is_(None))
                | (GremiumMembership.valid_from <= now),
                (GremiumMembership.valid_until.is_(None))
                | (GremiumMembership.valid_until > now),
            )
        )
    ).scalars().all()
    return frozenset(str(g) for g in rows)


async def _budget_fits(session: AsyncSession, app: Application) -> bool:
    """Return True when the requested amount fits the free remainder of the cost center.

    The available amount is the node allocation minus expenses plus income for the
    fiscal year. This is the same direction as `tree_rules.node_available`. A missing
    budget, fiscal year or amount gives `False` (fail-closed).
    """
    if app.budget_id is None or app.fiscal_year_id is None or app.amount is None:
        return False
    allocated = await session.scalar(
        select(BudgetAllocation.allocated).where(
            BudgetAllocation.budget_id == app.budget_id,
            BudgetAllocation.fiscal_year_id == app.fiscal_year_id,
        )
    )
    flow = await session.scalar(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (BudgetExpense.kind == "income", BudgetExpense.amount),
                        else_=-BudgetExpense.amount,
                    )
                ),
                Decimal("0"),
            )
        ).where(
            BudgetExpense.budget_id == app.budget_id,
            BudgetExpense.fiscal_year_id == app.fiscal_year_id,
        )
    )
    available = (allocated or Decimal("0")) + (flow or Decimal("0"))
    return app.amount <= available


async def _has_attachment(session: AsyncSession, app: Application) -> bool:
    """Report whether the application has at least one attachment out of quarantine.

    This backs the `attachmentPresent` guard, for example when receipts or offers are
    required. `storage_key IS NULL` marks an attachment that a ClamAV hit removed. Such
    an attachment does not count as present.
    """
    return bool(
        await session.scalar(
            select(
                exists().where(
                    Attachment.application_id == app.id,
                    Attachment.storage_key.is_not(None),
                )
            )
        )
    )


async def _application_type_key(session: AsyncSession, app: Application) -> str | None:
    """Return the application type key, for example `qsm` or `vsm`.

    The `applicationTypeIs` guard reads this key. The result is `None` when the type
    does not resolve after data drift. The guard then falls back to `False`
    (fail-closed).
    """
    return await session.scalar(
        select(ApplicationType.key).where(ApplicationType.id == app.type_id)
    )


async def _field_types(session: AsyncSession, app: Application) -> dict[str, str]:
    """Return `{fieldKey: compareType}` for the pinned form plus the built-in `amount`."""
    rows = (
        await session.execute(
            select(FormField.key, FormField.type).where(
                FormField.form_version_id == app.form_version_id
            )
        )
    ).all()
    types = {key: _compare_type(ftype) for key, ftype in rows}
    types["amount"] = "currency"
    return types


async def build_base_context(
    session: AsyncSession,
    app: Application,
    *,
    manual: bool,
    deadline_passed: bool = False,
) -> GuardContext:
    """Build the actor-free part of the guard context from the database and the application.

    The context holds every fact that comes from the application alone: applicant,
    budget, fields and deadline. The actor fields keep their empty defaults. Overlay
    them per actor with `with_actor`.
    """
    raw_roles = app.data.get("_applicantRoles") if isinstance(app.data, dict) else None
    applicant_roles = frozenset(raw_roles) if isinstance(raw_roles, list) else frozenset()
    applicant_committees = await _committees_for_sub(session, app.created_by)
    application_type_key = await _application_type_key(session, app)
    has_attachment = await _has_attachment(session, app)
    field_values: dict[str, Any] = dict(app.data) if isinstance(app.data, dict) else {}
    field_values["amount"] = app.amount
    field_types = await _field_types(session, app)

    return GuardContext(
        manual=manual,
        deadline_passed=deadline_passed,
        applicant_roles=applicant_roles,
        applicant_committees=applicant_committees,
        budget_id=str(app.budget_id) if app.budget_id is not None else None,
        budget_fits=await _budget_fits(session, app),
        application_type_key=application_type_key,
        has_attachment=has_attachment,
        field_values=field_values,
        field_types=field_types,
    )


def with_actor(
    ctx: GuardContext,
    *,
    roles: frozenset[str],
    committees: frozenset[str],
    is_applicant: bool,
) -> GuardContext:
    """Overlay the actor facts on a base context (pure, no I/O).

    Actor gates apply only to manual transitions. On a non-manual context the actor
    fields stay empty whatever the arguments say. This keeps the guard fail-closed.
    """
    if not ctx.manual:
        return replace(
            ctx,
            roles=frozenset(),
            actor_committees=frozenset(),
            actor_is_applicant=False,
        )
    return replace(
        ctx,
        roles=roles,
        actor_committees=committees,
        actor_is_applicant=is_applicant,
    )


async def build_context(
    session: AsyncSession,
    app: Application,
    principal: Principal,
    *,
    manual: bool,
    deadline_passed: bool = False,
    as_applicant: bool = False,
) -> GuardContext:
    """Build the full `GuardContext` from the database and the principal.

    `as_applicant=True` marks the magic-link holder as the applicant actor whatever
    `created_by` says. The link holder is the applicant for exactly this application.
    """
    base = await build_base_context(
        session, app, manual=manual, deadline_passed=deadline_passed
    )
    actor_committees = (
        await _committees_for_sub(session, principal.sub) if manual else frozenset()
    )
    return with_actor(
        base,
        roles=frozenset(principal.roles),
        committees=actor_committees,
        is_applicant=as_applicant
        or (app.created_by is not None and principal.sub == app.created_by),
    )
