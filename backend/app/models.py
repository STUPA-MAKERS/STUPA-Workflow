"""Model aggregator.

This module imports every module model, so `Base.metadata` is complete. That
metadata is the single source for Alembic and for the tests.
"""

from __future__ import annotations

from app.db import Base
from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import (
    Applicant,
    Application,
    ApplicationDecision,
    ApplicationLink,
    ApplicationLinkEvent,
    ApplicationObserver,
    Comment,
    GuestApplicationSettings,
    MagicLink,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.audit.models import AuditEntry, AuditVerification
from app.modules.auth.models import (
    AuthSession,
    EmailLoginLink,
    GroupMapping,
    Principal,
    Role,
    RoleAssignment,
    RolePermission,
)
from app.modules.auth.oauth_models import OAuthAuthorizationCode, OAuthToken
from app.modules.backup.models import Backup
from app.modules.budget.plan_models import (
    BudgetPlan,
    BudgetPlanLine,
    BudgetPlanStep,
    BudgetPlanVersion,
)
from app.modules.budget.tree_models import (
    Budget,
    BudgetAllocation,
    BudgetExpense,
    FiscalYear,
)
from app.modules.calendar.models import Answer as CalendarAnswer
from app.modules.calendar.models import Appointment as CalendarAppointment
from app.modules.calendar.models import ExternalCalendar as CalendarExternal
from app.modules.calendar.models import ExternalEntry as CalendarExternalEntry
from app.modules.calendar.models import Invitation as CalendarInvitation
from app.modules.config_revision.models import ConfigRevision
from app.modules.delegations.models import MeetingDelegation
from app.modules.files.models import Attachment, AttachmentDraftToken
from app.modules.flow.models import FlowVersion, State, Transition
from app.modules.forms.models import FormField, FormVersion
from app.modules.gremien.models import DelegationSubstitute, Gremium
from app.modules.media.models import MarkdownImage
from app.modules.meetings.models import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingGuest,
    MeetingSettings,
    ProtocolKeeperPeriod,
)
from app.modules.meetings.protocol_models import Protocol, ProtocolVoteRef
from app.modules.notifications.models import (
    MailTemplate,
    NotificationPreference,
    NotificationSettings,
    TaskReminderLog,
)
from app.modules.privacy.models import ErasureRequest, PrivacySettings
from app.modules.site_config.models import SiteConfigVersion
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote, TicketSenderBlock
from app.modules.todos.models import (
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoCardLabel,
    TodoCheckItem,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoLabel,
    TodoLink,
)
from app.modules.translations.models import UiLanguage, UiTranslation
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.webhooks.models import Webhook, WebhookDelivery

__all__ = [
    "Applicant",
    "Application",
    "ApplicationDecision",
    "ApplicationLink",
    "ApplicationLinkEvent",
    "ApplicationObserver",
    "ApplicationType",
    "Attachment",
    "AttachmentDraftToken",
    "AuditEntry",
    "AuditVerification",
    "AuthSession",
    "EmailLoginLink",
    "Base",
    "Budget",
    "BudgetAllocation",
    "BudgetPlan",
    "BudgetPlanLine",
    "BudgetPlanStep",
    "BudgetPlanVersion",
    "BudgetExpense",
    "ConfigRevision",
    "FiscalYear",
    "Comment",
    "DelegationSubstitute",
    "MeetingDelegation",
    "FlowVersion",
    "FormField",
    "FormVersion",
    "Gremium",
    "GroupMapping",
    "GuestApplicationSettings",
    "MagicLink",
    "MailTemplate",
    "MarkdownImage",
    "NotificationPreference",
    "NotificationSettings",
    "TaskReminderLog",
    "Meeting",
    "MeetingAgendaItem",
    "MeetingAttendance",
    "MeetingGuest",
    "MeetingSettings",
    "ProtocolKeeperPeriod",
    "OAuthAuthorizationCode",
    "OAuthToken",
    "ErasureRequest",
    "Principal",
    "Backup",
    "CalendarAnswer",
    "CalendarAppointment",
    "CalendarExternal",
    "CalendarExternalEntry",
    "CalendarInvitation",
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
    "Ticket",
    "TicketEvent",
    "TicketNote",
    "TicketSenderBlock",
    "TodoAssignee",
    "TodoBoard",
    "TodoCard",
    "TodoCardLabel",
    "TodoCheckItem",
    "TodoColumn",
    "TodoComment",
    "TodoEvent",
    "TodoLabel",
    "TodoLink",
    "Transition",
    "UiLanguage",
    "UiTranslation",
    "Vote",
    "VotedMarker",
    "Webhook",
    "WebhookDelivery",
]
