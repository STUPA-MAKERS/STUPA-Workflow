"""Attachments: the ``attachment`` table.

One row holds one uploaded file. The binary object lives in MinIO under
``storage_key``, never in the database. ``scanned`` and ``scan_result`` carry the ClamAV
result. The file stays quarantined and nobody can download it until ``scanned`` is true.
On a finding the worker deletes the object, sets ``storage_key`` to NULL and writes the
signature into ``scan_result``.

A row is either bound or a draft. A bound row has exactly one of five owners:
``application_id``, ``ticket_id`` (the attachment of a ticket report), or one chat
message: ``ticket_note_id``, ``todo_comment_id`` or ``comment_id`` (an application
comment). A draft row
comes from the wizard before the application exists: it has ``draft_token_hash`` and
``draft_expires_at`` instead, and its object lives under ``drafts/<id>/``. The create of
the application binds the draft. It sets ``application_id`` and clears both draft
columns, and the storage key stays. The ticket create binds the same way with
``ticket_id``, and the send of a chat message with its owner column. Two CHECKs make
this an exclusive choice. Every application-scoped query must filter
``application_id IS NOT NULL`` (``BOUND``), so neither a draft, a ticket attachment
nor the file of a message shows up in an application path. A file of an application
comment has ``application_id`` NULL on purpose: the file of an internal comment must
not reach the applicant through the attachment list.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UUIDPkMixin

# The database enforces this bound with CHECK(size <= 10485760).
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

# The storage-key prefix of a draft upload. The key stays the same after the bind.
DRAFT_KEY_PREFIX = "drafts/"


class Attachment(UUIDPkMixin, Base):
    """An attachment of an application, or a draft upload of the wizard.

    ``application_id`` cascades. A deleted application removes its attachments. It is
    NULL for a draft, for the attachment of a ticket and for the file of a message.
    ``ticket_id``, ``ticket_note_id``, ``todo_comment_id`` and ``comment_id`` cascade the
    same way. A soft delete of a message does not cascade; the service removes the
    files of the message then (``delete_for_messages``).

    Attributes:
        field_key: Optional link to a form field.
        draft_token_hash: HMAC-SHA256 of the draft token. Set on a draft only.
        draft_expires_at: End of the draft. Set on a draft only. Each upload with the
            token moves it for all drafts of the token.
        scanned: True after the ClamAV run finishes.
        scan_result: NULL, ``clean``, or the signature of the finding.
        storage_key: NULL after a finding, because the worker removed the object.
    """

    __tablename__ = "attachment"

    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket.id", ondelete="CASCADE"), nullable=True
    )
    ticket_note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ticket_note.id", ondelete="CASCADE"), nullable=True
    )
    todo_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("todo_comment.id", ondelete="CASCADE"), nullable=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comment.id", ondelete="CASCADE"), nullable=True
    )
    field_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    scanned: Mapped[bool] = mapped_column(Boolean, server_default="false")
    scan_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    draft_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    draft_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            f"size <= {MAX_ATTACHMENT_BYTES}", name="attachment_size_limit"
        ),
        # Exactly one owner: an application, a ticket, a message or a draft token.
        CheckConstraint(
            "num_nonnulls(application_id, ticket_id, ticket_note_id, todo_comment_id, "
            "comment_id, draft_token_hash) = 1",
            name="draft_xor_application",
        ),
        # A draft has both draft columns, a bound row has neither.
        CheckConstraint(
            "(draft_token_hash IS NULL) = (draft_expires_at IS NULL)",
            name="draft_columns_paired",
        ),
        Index("ix_attachment_application_id", "application_id"),
        Index("ix_attachment_ticket_id", "ticket_id"),
        Index("ix_attachment_ticket_note_id", "ticket_note_id"),
        Index("ix_attachment_todo_comment_id", "todo_comment_id"),
        Index("ix_attachment_comment_id", "comment_id"),
        # The hourly purge and the token lookup read the drafts only.
        Index(
            "ix_attachment_draft_expires_at",
            "draft_expires_at",
            postgresql_where=text("draft_token_hash IS NOT NULL"),
        ),
        Index(
            "ix_attachment_draft_token_hash",
            "draft_token_hash",
            postgresql_where=text("draft_token_hash IS NOT NULL"),
        ),
    )


# The filter of every application-scoped query. A draft has no application, so this
# excludes it explicitly, also where an id lookup would not.
BOUND = Attachment.application_id.is_not(None)


class AttachmentDraftToken(Base):
    """The lifetime of one draft token of the wizard.

    The token lives on its own, independent of its draft rows. It stays valid until
    ``expires_at``, also when the owner deletes the last draft. Each upload with the
    token moves ``expires_at`` to now + ``attachment_draft_ttl_days``. The hourly purge
    removes the expired rows.

    Attributes:
        token_hash: HMAC-SHA256 of the draft token, as in ``Attachment.draft_token_hash``.
        expires_at: End of the token.
    """

    __tablename__ = "attachment_draft_token"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_attachment_draft_token_expires_at", "expires_at"),
    )
