"""Model aggregator.

This module imports every module model, so `Base.metadata` is complete. That
metadata is the single source for Alembic and for the tests.
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
from app.modules.auth.oauth_models import OAuthAuthorizationCode, OAuthToken
from app.modules.backup.models import Backup
from app.modules.budget.models import BudgetEntry, BudgetField, BudgetPot
from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.config_revision.models import ConfigRevision
from app.modules.deadlines.models import Deadline, DeadlinePolicy
from app.modules.delegations.models import DelegationSubstitute, MeetingDelegation
from app.modules.files.models import Attachment
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.models import FormField, FormVersion
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.notifications.models import (
    MailTemplate,
    NotificationPreference,
    NotificationSettings,
    TaskReminderLog,
)
from app.modules.privacy.models import ErasureRequest, PrivacySettings
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
    "ConfigRevision",
    "BudgetField",
    "BudgetPot",
    "FiscalYear",
    "Comment",
    "Deadline",
    "DeadlinePolicy",
    "DelegationSubstitute",
    "MeetingDelegation",
    "FlowVersion",
    "FormField",
    "FormVersion",
    "Gremium",
    "GroupMapping",
    "MagicLink",
    "MailList",
    "MailTemplate",
    "NotificationPreference",
    "NotificationSettings",
    "TaskReminderLog",
    "Meeting",
    "MeetingAgendaItem",
    "MeetingAttendance",
    "OAuthAuthorizationCode",
    "OAuthToken",
    "ErasureRequest",
    "Principal",
    "Backup",
    "PrivacySettings",
    "Protocol",
    "ProtocolVoteRef",
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
