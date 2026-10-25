"""Application tables: application, applicant, submission_version, status_event.

The `applicant` table holds the PII. Keep `application.data` free of PII.
Anonymization is the default erasure path, not a hard delete. The `applicant`
foreign-key CASCADE fires only on a real application delete.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, TimestampMixin, UUIDPkMixin

#: Guest applications: the default and the upper bound of the confirmation window.
DEFAULT_CONFIRM_TTL_HOURS = 12
MAX_CONFIRM_TTL_HOURS = 720


class Application(UUIDPkMixin, TimestampMixin, Base):
    """One application.

    `data` holds the current field values as JSONB with a GIN index. The service
    syncs the promoted `amount` and `currency` columns from `data`.

    The default list filters archived rows out, so every listing query touches the index on
    ``archived_at``.

    Attributes:
        budget_id: Cost center in the budget tree, most often a leaf. The budget
            assignment sets the fiscal year, not the submission, and
            ``move-fiscal-year`` moves it.
        vote_gremium_id: Snapshot of the Gremium that decides the current vote state.
            The flow engine sets it when the application enters a ``vote`` state (the
            fixed ``gremiumId`` of the state, or the effective deciding Gremium of the
            cost center for ``gremiumSource: "budget"``). It clears it when the
            application leaves the vote state, in the same transaction as the state
            change. Every reader of "the Gremium of the vote" (read scope, tasks,
            agenda, vote create, task mail) reads this column.
        approved_amount: The amount of the valid decision, a denormalized copy for the
            budget roll-up, the guard ``budgetFitsApplication`` and the lists. NULL
            means "as requested" or "no decision": the committed amount is then
            ``amount``.
        created_by: OIDC ``sub`` of the creating principal, ``None`` for an anonymous
            submission. The creator reads, edits and deletes the own application
            without ``application.manage``.
        email_confirmed_at: Email confirmation of a guest submission. Until it is set,
            the application stays invisible, and the platform discards it after 12 h.
            A logged-in submission counts as confirmed at once, because the OIDC mail
            is trusted. A guest confirms through the magic-link verify route.
        archived_at: Archived: out of the working list, still fully readable. It is a
            timestamp, because it answers "whether" and "when" in one column. It is
            NOT a flow state, because an application can be archived from any state.
            It is NOT anonymization either: archiving hides nothing and deletes
            nothing, while ``be-privacy`` erases PII under the DSGVO.
        archived_by: OIDC ``sub`` of whoever archived it. It is no foreign key,
            because the record of who archived must survive the removal of the
            principal, as with ``created_by``.
        captured_by: OIDC ``sub`` of the person with
            ``application.create_on_behalf`` who entered an application that reached
            the platform another way, for example as a PDF or a mail. It is NOT the
            owner: ``created_by`` names the applicant account, or stays None for a
            guest applicant. It is no foreign key, so the record survives the removal
            of the account. The three capture columns stay None for an application
            that the applicant submitted.
        capture_intake: The free-text intake channel ("Eingang"), for example
            "per PDF" or "per Mail".
        received_on: The date on which the application reached the Gremium. The
            capturing person sets it (default: the day of the capture). It is
            information only.
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
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id"), nullable=True
    )
    fiscal_year_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fiscal_year.id"), nullable=True
    )
    vote_gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    lang: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archived_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    captured_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    capture_intake: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_on: Mapped[date | None] = mapped_column(Date, nullable=True)

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
        Index("ix_application_vote_gremium_id", "vote_gremium_id"),
        Index("ix_application_type_id", "type_id"),
        Index("ix_application_created_at", "created_at"),
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
    """Status-timeline entry (one transition).

    Attributes:
        vote_id: The vote whose close fired this event (the ``pass`` or ``fail``
            branch). NULL for every other event. A meeting delete deletes the votes of
            the meeting and sets this reference to NULL first. The note
            ``vote:<result>`` stays, so the timeline shows "vote deleted (with its
            meeting)" for such an event. The foreign key is ``SET NULL`` as a second
            line of defense.
    """

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
    vote_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vote.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index("ix_status_event_application_id_at", "application_id", "at"),
        Index("ix_status_event_vote_id", "vote_id"),
    )


class ApplicationDecision(UUIDPkMixin, Base):
    """One decision on an application: approval with deviations.

    A passed vote with a proposal or a manual transition into an accepted state writes
    a row. The valid decision is the newest row with `superseded_at IS NULL`. A new
    decision supersedes the old one. Nobody edits a row: only a new decision or an
    audit revert of its status change replaces it.

    A partial unique index allows at most one valid decision per application, so two
    concurrent writes cannot both stay valid.

    Attributes:
        approved_amount: NULL means "as requested" (``application.amount``).
        conditions: The conditions (Auflagen) as a list of texts.
        vote_id: The vote whose close made the decision. NULL for a manual transition.
        status_event_id: The status event of the transition that carried the decision.
            NULL when a passed vote could not fire its branch.
        decided_by: The OIDC ``sub`` of the person who fired the transition. NULL for a
            vote.
    """

    __tablename__ = "application_decision"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    approved_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    conditions: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")
    vote_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vote.id", ondelete="SET NULL"), nullable=True
    )
    status_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("status_event.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_application_decision_application_id", "application_id"),
        Index("ix_application_decision_status_event_id", "status_event_id"),
        Index(
            "uq_application_decision_one_valid",
            "application_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )


class MagicLink(UUIDPkMixin, CreatedAtMixin, Base):
    """Magic link for an applicant.

    The database holds only `sha256(token||pepper)`. The plaintext token exists
    only in the mail link. The link binds to exactly one `application_id`.

    A new link always has `scope = 'edit'` and `single_use = false`. The
    session it opens has no fixed scope: each action checks the current state. The
    `view` scope and `single_use` stay only for the rows written before that change.

    `expires_at` NULL means "no expiry" (`guest_application_settings.link_ttl_days`
    is NULL). Only an `edit` link can be unlimited. A link stops working when it
    expires, when a newer link of the same application is redeemed, or when the
    application is archived or anonymized. Archiving ends only the existing links:
    the applicant can still request a new link for an archived application, because
    an archived application stays readable. Anonymizing removes the email, so no new
    link is possible. The verify route answers 410 for a used or expired link.

    A CHECK allows a link without an expiry only for an edit link. The UNIQUE index on the
    hash backs the atomic single-use redemption (``UPDATE ... WHERE used_at IS NULL``) and
    prevents an ambiguous hash collision.
    """

    __tablename__ = "magic_link"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    scope: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    single_use: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        CheckConstraint("scope IN ('edit','view')", name="magic_link_scope"),
        CheckConstraint(
            "expires_at IS NOT NULL OR scope = 'edit'",
            name="magic_link_unlimited_edit_only",
        ),
        Index("ix_magic_link_token_hash", "token_hash", unique=True),
    )


class GuestApplicationSettings(Base):
    """Settings for applications without an account (single row id=1).

    `confirm_ttl_hours` is the time a guest has to confirm the email. After it the
    worker discards the unconfirmed application. The worker reads the value on each
    run, so a change applies to the waiting applications too.

    `link_ttl_days` is the lifetime of a new magic link. NULL means no expiry.
    """

    __tablename__ = "guest_application_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    confirm_ttl_hours: Mapped[int] = mapped_column(
        Integer, server_default="12", default=DEFAULT_CONFIRM_TTL_HOURS
    )
    link_ttl_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint(
            f"confirm_ttl_hours BETWEEN 1 AND {MAX_CONFIRM_TTL_HOURS}",
            name="confirm_ttl",
        ),
        CheckConstraint(
            "link_ttl_days IS NULL OR link_ttl_days > 0",
            name="link_ttl",
        ),
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

    ``created_by`` is the OIDC ``sub`` of the creator, next to a private note. It is no
    foreign key, like ``created_by`` on the application, because the record of who made a
    record public must outlive the account. The hash index is UNIQUE, because two rows with
    the same digest make the lookup ambiguous.
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
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_application_share_token_hash", "token_hash", unique=True),
        Index("ix_application_share_application_id", "application_id"),
    )


class Comment(UUIDPkMixin, Base):
    """Comment on an application.

    RBAC shows `visibility='internal'` to a principal only. It shows `'public'`
    also to the applicant behind the magic link. `author_kind` separates a
    principal author from an applicant author. ``mentions`` holds principal ids.

    Only a member who reads the internal comments is mentionable, and the applicant view
    never shows ``mentions``.
    """

    __tablename__ = "comment"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    author: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_kind: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text)
    mentions: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
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
