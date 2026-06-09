"""Modell-Aggregator: importiert alle Modul-Modelle, damit `Base.metadata`
vollständig befüllt ist (Single Source für Alembic-`migrations/` und Tests).

T-06 deckt den DB-Kern ab (data-model §1–4). Spätere Tasks ergänzen ihre Modelle
+ eigene Migrationen.
"""

from __future__ import annotations

from app.db import Base
from app.modules.admin.models import (
    ApplicationType,
    Gremium,
    MailList,
    SiteConfigVersion,
    Webhook,
    WebhookDelivery,
)
from app.modules.applications.models import (
    Applicant,
    Application,
    Comment,
    MagicLink,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import (
    AuthSession,
    GroupMapping,
    Principal,
    Role,
    RoleAssignment,
    RolePermission,
)
from app.modules.budget.models import BudgetEntry, BudgetField, BudgetPot
from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.deadlines.models import Deadline
from app.modules.files.models import Attachment
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.models import FormField, FormVersion
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.notifications.models import MailTemplate, NotificationRule
from app.modules.pdf.models import RenderJob
from app.modules.protocol.models import Protocol, ProtocolVoteRef
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker

__all__ = [
    "Applicant",
    "Application",
    "ApplicationType",
    "Attachment",
    "AuditEntry",
    "AuthSession",
    "Ballot",
    "Base",
    "Budget",
    "BudgetAllocation",
    "BudgetEntry",
    "BudgetExpense",
    "BudgetField",
    "BudgetPot",
    "FiscalYear",
    "Comment",
    "Deadline",
    "FlowVersion",
    "FormField",
    "FormVersion",
    "Gremium",
    "GroupMapping",
    "MagicLink",
    "MailList",
    "MailTemplate",
    "Meeting",
    "MeetingAgendaItem",
    "MeetingAttendance",
    "NotificationRule",
    "Principal",
    "Protocol",
    "ProtocolVoteRef",
    "RenderJob",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "SecretBallot",
    "SiteConfigVersion",
    "State",
    "StatusEvent",
    "SubmissionVersion",
    "Transition",
    "Vote",
    "VotedMarker",
    "Webhook",
    "WebhookDelivery",
]
