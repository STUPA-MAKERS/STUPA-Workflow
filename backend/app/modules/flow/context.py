"""Guard-Kontext-Aufbau für die Flow-Engine (flows §9.2).

``eval_guard`` (T-05) ist eine **reine** Funktion über einem
:class:`~app.shared.guards.GuardContext`. Dieses Modul füllt den Kontext aus dem
Antrag + auslösendem Principal + abgeleiteten Fakten (#28-Redesign):

* **Akteur** (``roles``/``actor_committees``) — globale Rollen + Gremium-
  Mitgliedschaften des auslösenden Principals (nur für manuelle Übergänge relevant).
* **Antragsteller** (``applicant_roles``/``applicant_committees``) — aus
  ``data['_applicantRoles']`` bzw. den Mitgliedschaften des erstellenden Principals.
* **Budget** (``budget_id``/``budget_fits``) — zugeordnete Kostenstelle + ob der
  Betrag in den verfügbaren Rest (Allocation − Ausgaben) passt.
* **Felder** (``field_values``/``field_types``) — Formularfeldwerte aus ``data`` +
  Built-in ``amount`` (currency) samt abgeleiteten Typen für ``compare``/``hasField``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import GremiumMembership
from app.modules.applications.models import Application
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import BudgetAllocation, BudgetExpense
from app.modules.forms.models import FormField
from app.shared.guards import GuardContext

# Formularfeld-Typ → ``compare``-Wert-Typ (guards.COMPARE_TYPES).
_FIELD_TYPE_MAP: dict[str, str] = {
    "number": "number",
    "currency": "currency",
    "date": "date",
    "checkbox": "bool",
    "boolean": "bool",
}


def _compare_type(field_type: str) -> str:
    """Formularfeld-Typ auf einen ``compare``-Wert-Typ abbilden (Default ``text``)."""
    return _FIELD_TYPE_MAP.get(field_type, "text")


async def _committees_for_sub(session: AsyncSession, sub: str | None) -> frozenset[str]:
    """Gremium-IDs, in denen ``sub`` aktuell (Amtszeit-Fenster) Mitglied ist."""
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
    """``True`` wenn der Antragsbetrag in den freien Rest der Kostenstelle passt.

    Verfügbar = Allocation des Knotens im Haushaltsjahr − Σ Ausgaben
    (``kind='expense'``) + Σ Einnahmen (``kind='income'``) auf diesem Knoten/HHJ —
    gleiche Richtung wie ``tree_rules.node_available``. Ohne Budget/HHJ/Betrag ⇒
    ``False`` (fail-closed)."""
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


async def _field_types(session: AsyncSession, app: Application) -> dict[str, str]:
    """``{feldKey: compareTyp}`` der gepinnten Form + Built-in ``amount`` (currency)."""
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


async def build_context(
    session: AsyncSession,
    app: Application,
    principal: Principal,
    *,
    manual: bool,
    deadline_passed: bool = False,
    as_applicant: bool = False,
) -> GuardContext:
    """Vollständigen :class:`GuardContext` aus DB + Principal bauen (I/O).

    ``as_applicant=True`` markiert den Magic-Link-Antragsteller als Akteur
    (``actorIsApplicant`` greift), unabhängig von ``created_by`` — der Link-Inhaber
    *ist* die Antragsteller:in für genau diesen Antrag (#applicant-actions)."""
    # Akteur (nur manuelle Übergänge nutzen die Akteur-Gates).
    actor_committees = (
        await _committees_for_sub(session, principal.sub) if manual else frozenset()
    )
    # Antragsteller.
    raw_roles = app.data.get("_applicantRoles") if isinstance(app.data, dict) else None
    applicant_roles = frozenset(raw_roles) if isinstance(raw_roles, list) else frozenset()
    applicant_committees = await _committees_for_sub(session, app.created_by)
    # Akteur ist Antragsteller:in: Magic-Link-Inhaber:in (as_applicant) **oder**
    # eingeloggte:r Ersteller:in, die/der selbst auslöst (#guard).
    actor_is_applicant = manual and (
        as_applicant or (app.created_by is not None and principal.sub == app.created_by)
    )
    # Felder (Built-in amount + Formulardaten).
    field_values: dict[str, Any] = dict(app.data) if isinstance(app.data, dict) else {}
    field_values["amount"] = app.amount
    field_types = await _field_types(session, app)

    return GuardContext(
        manual=manual,
        deadline_passed=deadline_passed,
        actor_is_applicant=actor_is_applicant,
        roles=frozenset(principal.roles) if manual else frozenset(),
        actor_committees=actor_committees,
        applicant_roles=applicant_roles,
        applicant_committees=applicant_committees,
        budget_id=str(app.budget_id) if app.budget_id is not None else None,
        budget_fits=await _budget_fits(session, app),
        field_values=field_values,
        field_types=field_types,
    )
