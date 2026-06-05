"""Modell-Aggregator: importiert alle Modul-Modelle, damit `Base.metadata`
vollständig befüllt ist (Single Source für Alembic-`migrations/` und Tests).

T-06 deckt den DB-Kern ab (data-model §1–4). Spätere Tasks ergänzen ihre Modelle
+ eigene Migrationen.
"""

from __future__ import annotations

from app.db import Base
from app.modules.admin.models import ApplicationType, Gremium, MailList
from app.modules.applications.models import (
    Applicant,
    Application,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.auth.models import (
    GroupMapping,
    Principal,
    Role,
    RoleAssignment,
    RolePermission,
)
from app.modules.budget.models import BudgetField, BudgetPot
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.models import FormField, FormVersion

__all__ = [
    "Applicant",
    "Application",
    "ApplicationType",
    "Base",
    "BudgetField",
    "BudgetPot",
    "FlowVersion",
    "FormField",
    "FormVersion",
    "Gremium",
    "GroupMapping",
    "MailList",
    "Principal",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "State",
    "StatusEvent",
    "SubmissionVersion",
    "Transition",
]
