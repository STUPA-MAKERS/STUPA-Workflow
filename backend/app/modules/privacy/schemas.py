"""Privacy module API schemas (camelCase JSON, populate-by-name)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.modules.paperless.schemas import FiledDocumentOut
from app.shared.schemas import FrozenCamelModel

SubjectType = Literal["applicant", "principal"]
ErasureStatus = Literal["open", "executed", "rejected"]


class ErasureRequestOut(FrozenCamelModel, frozen=True):
    """An erasure request.

    ``paperlessDocuments`` lists the documents that the platform filed in Paperless for
    the data of the request. They stay there after the erasure
    (§F/administration/privacy/002532).
    """

    id: UUID
    created_at: datetime = Field(alias="createdAt")
    subject_type: SubjectType = Field(alias="subjectType")
    application_id: UUID | None = Field(default=None, alias="applicationId")
    principal_id: UUID | None = Field(default=None, alias="principalId")
    email: str | None = None
    status: ErasureStatus
    requested_by: str | None = Field(default=None, alias="requestedBy")
    handled_by: str | None = Field(default=None, alias="handledBy")
    handled_at: datetime | None = Field(default=None, alias="handledAt")
    reason: str | None = None
    paperless_documents: tuple[FiledDocumentOut, ...] = Field(
        default=(), alias="paperlessDocuments"
    )
    ticket_mails: tuple[TicketMailCountOut, ...] = Field(default=(), alias="ticketMails")


class TicketMailCountOut(FrozenCamelModel, frozen=True):
    """The mails of an erased address in one Postfach that stay on the mail server.

    ``mailbox`` is the address of the Postfach; null for a Postfach that is removed.
    ``count`` is the number of mails that the platform imported or sent (002747).
    """

    mailbox: str | None = None
    count: int


class PrincipalErasureOut(FrozenCamelModel, frozen=True):
    """What stays in Paperless and on the mail servers after the erasure of an account.

    §F/administration/privacy/002532, 002747
    """

    paperless_documents: tuple[FiledDocumentOut, ...] = Field(
        default=(), alias="paperlessDocuments"
    )
    ticket_mails: tuple[TicketMailCountOut, ...] = Field(default=(), alias="ticketMails")


class ErasureRejectBody(FrozenCamelModel, frozen=True):
    """Rejection reason. The notification to the subject shows it."""

    reason: str | None = None


class PrivacySettingsOut(FrozenCamelModel, frozen=True):
    """The privacy settings."""

    default_retention_months: int = Field(alias="defaultRetentionMonths")


class PrivacySettingsUpdate(FrozenCamelModel, frozen=True):
    """New privacy settings."""

    default_retention_months: int = Field(alias="defaultRetentionMonths", ge=1)


class EmailErasureBody(FrozenCamelModel, frozen=True):
    """The address whose applications and ticket reports go."""

    email: str = Field(min_length=1)


class EmailErasureOut(FrozenCamelModel, frozen=True):
    """What the erasure of an address anonymized.

    ``principalId`` names an account under the address. Its erasure is a separate
    step, because it deactivates the account. ``paperlessDocuments`` lists the documents
    of the anonymized Anträge that stay in Paperless (002532).
    """

    applications: int
    tickets: int
    principal_id: UUID | None = Field(default=None, alias="principalId")
    paperless_documents: tuple[FiledDocumentOut, ...] = Field(
        default=(), alias="paperlessDocuments"
    )
    ticket_mails: tuple[TicketMailCountOut, ...] = Field(default=(), alias="ticketMails")
