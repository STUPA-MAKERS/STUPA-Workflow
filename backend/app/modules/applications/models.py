"""Application tables: application, applicant, submission_version, status_event.

The `applicant` table holds the PII. Keep `application.data` free of PII.
Anonymization is the default erasure path, not a hard delete. The `applicant`
foreign-key CASCADE fires only on a real application delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin


class Application(UUIDPkMixin, TimestampMixin, Base):
    """One application.

    `data` holds the current field values as JSONB with a GIN index. The service
    syncs the promoted `amount` and `currency` columns from `data`.
    """

    __tablename__ = "application"

    type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("application_type.id"))
    form_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("form_version.id"))
    flow_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("flow_version.id"))
    current_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("state.id"), nullable=True
    )
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id"), nullable=True
    )
    # Cost center in the budget tree, most often a leaf, plus the fiscal year.
    # The budget assignment sets the fiscal year, not the submission.
    # `move-fiscal-year` moves it.
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id"), nullable=True
    )
    fiscal_year_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fiscal_year.id"), nullable=True
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    lang: Mapped[str | None] = mapped_column(Text, nullable=True)
    # OIDC ``sub`` of the creating principal. An anonymous submission stores ``None``.
    # The creator reads, edits and deletes the own application without
    # ``application.manage``.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Email-confirmation timestamp for a guest submission. Until it is set, the
    # application stays invisible, and the platform discards it after 12 h. A
    # logged-in submission counts as confirmed at once, because the OIDC mail is
    # trusted. A guest confirms through the magic-link verify route.
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Archived: out of the working list, still fully readable. A timestamp rather than a
    # flag, because it answers "whether" and "when" in one column and makes the un-archive
    # obvious. Deliberately NOT a flow state: an application can be archived from any
    # state, and the flow is about where a decision stands, not about whether the record
    # is still in front of anyone.
    #
    # This is NOT anonymization. `be-privacy` erases PII under the DSGVO; archiving hides
    # nothing and deletes nothing. The two must never be confused for one another.
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # OIDC ``sub`` of whoever archived it. NOT a foreign key: a principal can be removed
    # and the record of who archived must survive that, the same way ``created_by`` does.
    archived_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_application_data",
            "data",
            postgresql_using="gin",
            postgresql_ops={"data": "jsonb_path_ops"},
        ),
        Index("ix_application_current_state_id", "current_state_id"),
        Index("ix_application_gremium_id", "gremium_id"),
        Index("ix_application_budget_id", "budget_id"),
        Index("ix_application_fiscal_year_id", "fiscal_year_id"),
        Index("ix_application_type_id", "type_id"),
        Index("ix_application_created_at", "created_at"),
        # The default list filters archived rows out, so every listing query touches
        # this column.
        Index("ix_application_archived_at", "archived_at"),
    )


class Applicant(UUIDPkMixin, Base):
    """PII of the applicant, split out 1:1 from the application.

    Anonymization sets `email` and `name` to NULL and writes `anonymized_at`.
    The application itself stays.
    """

    __tablename__ = "applicant"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), unique=True
    )
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    anonymized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SubmissionVersion(UUIDPkMixin, Base):
    """Versioned snapshot of the answer data plus diff."""

    __tablename__ = "submission_version"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    changed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (UniqueConstraint("application_id", "version"),)


class StatusEvent(UUIDPkMixin, Base):
    """Status-timeline entry (one transition)."""

    __tablename__ = "status_event"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    from_state_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("state.id"), nullable=True
    )
    to_state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("state.id"))
    transition_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transition.id"), nullable=True
    )
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_status_event_application_id_at", "application_id", "at"),)


class MagicLink(UUIDPkMixin, CreatedAtMixin, Base):
    """Magic link for an applicant.

    The database holds only `sha256(token||pepper)`. The plaintext token exists
    only in the mail link. The scope binds the link to exactly one
    `application_id` and to `edit` or `view`. The expiry and `single_use`
    (`used_at`) enforce the one-shot rule. The verify route answers 410 for a
    used or expired link.
    """

    __tablename__ = "magic_link"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    scope: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    single_use: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        CheckConstraint("scope IN ('edit','view')", name="magic_link_scope"),
        # The UNIQUE index backs the atomic single-use redemption
        # (UPDATE ... WHERE used_at IS NULL). It also prevents an ambiguous hash
        # collision.
        Index("ix_magic_link_token_hash", "token_hash", unique=True),
    )


class ApplicationShare(UUIDPkMixin, CreatedAtMixin, Base):
    """A public, read-only link to one application.

    The database holds only ``HMAC-SHA256(pepper, token)``, like `MagicLink`: the
    plaintext exists once, in the URL handed to whoever created it. A stolen database
    yields no working links.

    Revocable and expiring, both on purpose. A link that has been pasted into a chat is
    outside our control, and the only way to take it back is to stop honouring it.
    ``revoked_at`` is what makes "revocable" real rather than theoretical, and it is a
    timestamp rather than a flag so the audit answers when.

    NOT single-use, unlike a magic link: the whole point is that several people open it,
    and often more than once.
    """

    __tablename__ = "application_share"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # OIDC ``sub`` of whoever created the link, and a note they can leave for themselves.
    # Not a foreign key, like ``created_by`` on the application: the record of who made a
    # record public has to outlive the account.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # UNIQUE: the lookup is by hash, and two rows with the same digest would make the
        # answer ambiguous at exactly the moment it must not be.
        Index("ix_application_share_token_hash", "token_hash", unique=True),
        Index("ix_application_share_application_id", "application_id"),
    )


class Comment(UUIDPkMixin, Base):
    """Comment on an application.

    RBAC shows `visibility='internal'` to a principal only. It shows `'public'`
    also to the applicant behind the magic link. `author_kind` separates a
    principal author from an applicant author.
    """

    __tablename__ = "comment"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_kind: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "author_kind IN ('principal','applicant')", name="comment_author_kind"
        ),
        CheckConstraint(
            "visibility IN ('internal','public')", name="comment_visibility"
        ),
        Index("ix_comment_application_id_at", "application_id", "at"),
    )
