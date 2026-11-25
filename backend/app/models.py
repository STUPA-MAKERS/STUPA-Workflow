"""Model aggregator.

This module imports every module model, so `Base.metadata` is complete. That
metadata is the single source for Alembic and for the tests.
"""

from __future__ import annotations

from app.db import Base
from app.modules.activity.models import ActivityVisit
from app.modules.application_types.models import ApplicationType, ApplicationTypeGroup
from app.modules.applications.models import (
    Applicant,
    Application,
    ApplicationDecision,
    ApplicationLink,
    ApplicationLinkEvent,
    ApplicationObserver,
    ApplicationOrderEvent,
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
from app.modules.gremien.models import DelegationSubstitute, Gremium, GremiumInfo
from app.modules.media.models import MarkdownDocument, MarkdownImage
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
from app.modules.notifications.push_models import (
    PushPreference,
    PushSubscription,
    PushVapidKey,
)
from app.modules.orders.models import PurchaseOrder, PurchaseOrderPosition
from app.modules.paperless.models import (
    PaperlessDocument,
    PaperlessFiling,
    PaperlessSettings,
)
from app.modules.privacy.models import ErasureRequest, PrivacySettings
from app.modules.site_config.models import SiteConfigVersion
from app.modules.tickets.models import (
    Ticket,
    TicketArea,
    TicketCategory,
    TicketEvent,
    TicketNote,
    TicketSenderBlock,
)
from app.modules.todos.models import (
    Link,
    TodoAssignee,
    TodoBoard,
    TodoCard,
    TodoCardLabel,
    TodoCheckItem,
    TodoColumn,
    TodoComment,
    TodoEvent,
    TodoLabel,
)
from app.modules.translations.models import UiLanguage, UiTranslation
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.webhooks.models import Webhook, WebhookDelivery

__all__ = [
    "ApplicationOrderEvent",
    "PurchaseOrder",
    "PurchaseOrderPosition",
    "ActivityVisit",
    "Applicant",
    "Application",
    "ApplicationDecision",
    "ApplicationLink",
    "ApplicationLinkEvent",
    "ApplicationObserver",
    "ApplicationType",
    "ApplicationTypeGroup",
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
    "GremiumInfo",
    "GroupMapping",
    "GuestApplicationSettings",
    "MagicLink",
    "MailTemplate",
    "MarkdownDocument",
    "MarkdownImage",
    "NotificationPreference",
    "PushPreference",
    "PushSubscription",
    "PushVapidKey",
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
    "PaperlessDocument",
    "PaperlessFiling",
    "PaperlessSettings",
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
    "TicketArea",
    "TicketCategory",
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
    "Link",
    "Transition",
    "UiLanguage",
    "UiTranslation",
    "Vote",
    "VotedMarker",
    "Webhook",
    "WebhookDelivery",
]
