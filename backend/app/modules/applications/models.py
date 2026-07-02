"""Application tables: application, applicant, submission_version, status_event.

PII lives in `applicant` (split out); `application.data` should stay PII-free.
Anonymization (not hard delete) is the default erasure path — the `applicant`
FK CASCADE only fires on an actual application delete.
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
    """Application. `data` holds the current field values (JSONB, GIN-indexed);
    promoted `amount`/`currency` are synced from `data` by the service."""

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
    budget_pot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_pot.id"), nullable=True
    )
    # Cost centre (budget tree, usually a leaf) plus fiscal year. The fiscal year
    # is set at budget assignment (not at submission) and movable via
    # `move-fiscal-year`. Both are additive to the flat `budget_pot_id`.
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
    # OIDC ``sub`` of the creating principal; ``None`` for anonymous submissions.
    # Allows reading/editing/deleting the own application without
    # ``application.manage``.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Email-confirmation timestamp (guest submissions): until set, the application
    # is invisible and discarded after 12 h. Logged-in submissions are confirmed
    # immediately (OIDC mail is trusted); guests confirm via magic-link verify.
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_application_data",
            "data",
            postgresql_using="gin",
            postgresql_ops={"data": "jsonb_path_ops"},
        ),
        Index("ix_application_current_state_id", "current_state_id"),
        Index("ix_application_gremium_id", "gremium_id"),
        Index("ix_application_budget_pot_id", "budget_pot_id"),
        Index("ix_application_budget_id", "budget_id"),
        Index("ix_application_fiscal_year_id", "fiscal_year_id"),
        Index("ix_application_type_id", "type_id"),
        Index("ix_application_created_at", "created_at"),
    )


class Applicant(UUIDPkMixin, Base):
    """Split-out PII (1:1 with the application). Anonymize = NULL email/name and
    set `anonymized_at` (the application stays)."""

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
    """Magic link for applicants.

    The DB holds only `sha256(token||pepper)` — the plaintext token exists solely
    in the mail link. Scope binds to exactly one `application_id` plus
    `edit|view`; expiry and `single_use` (`used_at`) enforce one-shot/expiry
    logic (verify answers 410)."""

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
        # UNIQUE: backs the atomic single-use redemption (UPDATE ... WHERE used_at
        # IS NULL) and prevents hash-collision ambiguity.
        Index("ix_magic_link_token_hash", "token_hash", unique=True),
    )


class Comment(UUIDPkMixin, Base):
    """Application comment.

    `visibility='internal'` is visible to principals only (RBAC); `'public'`
    also to the applicant (magic link). `author_kind` separates principal from
    applicant authors."""

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
