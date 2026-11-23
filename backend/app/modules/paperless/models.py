"""ORM models of the Paperless integration: the connection and the filings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin

#: The kinds of a filing. `protocol_public` is the public PDF of a protocol, and
#: `attachment` is one attachment of an Antrag.
FILING_KINDS = ("protocol", "protocol_public", "application", "attachment", "plan")

#: The states of a filing. `pending` waits for the upload, `uploaded` waits until
#: Paperless has read the file, `filed` has a document number, and `failed` got no
#: document after the last try.
FILING_STATES = ("pending", "uploaded", "filed", "failed")


class PaperlessSettings(Base):
    """The connection to one Paperless-ngx instance and its switches (single row id=1).

    Attributes:
        base_url: The address of the instance, or NULL without a connection.
        token: The token of the account of the platform. No read of the API returns it
            (§NF/security/network/002515).
        file_protocols: The switch `Protokolle ablegen`. Each switch starts off
            (§F/integrations/paperless/002512).
        protocols_since: The moment the switch went on. An event before it is filed
            only by the action `Bestehende Dokumente ablegen`.
        insert_enabled: The switch `Aus Paperless einfügen`.
    """

    __tablename__ = "paperless_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    token: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_protocols: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    protocols_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_applications: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    applications_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    file_plans: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    plans_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    insert_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)

    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)


class PaperlessFiling(UUIDPkMixin, CreatedAtMixin, Base):
    """One file that the platform files in Paperless, with the state of its job.

    The row is the job: the worker takes each row whose ``due_at`` is over. The unique
    key keeps one row per file, so a second event or a retry never makes a second
    document (§F/integrations/paperless/002520).

    The row has no foreign key to its element. It stays after the element is gone,
    because the document stays in Paperless and an erasure must name it
    (§F/administration/privacy/002532).

    Attributes:
        kind: One of `FILING_KINDS`.
        element_id: The protocol, the Antrag or the Haushaltsplan that the file belongs
            to. The page of the element links to the document.
        source_id: The record that names the file: the protocol, the status event of
            the decision, the attachment, or the plan version.
        source_at: The moment of the event that filed the file. A protocol that becomes
            final again has a new moment and so a new row.
        application_id: The Antrag of the file, for the privacy lists. NULL for a
            protocol and a plan.
        title: The title of the document in Paperless.
        link: The address of the element in the platform, which the custom field
            `Plattform` of the document gets.
        actor: The person who caused the filing, or NULL for an event of the system.
        state: One of `FILING_STATES`.
        attempts: The failed tries of the job.
        due_at: The moment of the next try.
        last_error: The short cause code of the newest failure, never a text of an
            exception.
        task_id: The id of the consume task of Paperless after the upload.
        document_id: The number of the document in Paperless. The row stays `uploaded`
            with its number until the document has its link.
        replaced_at: The moment the document got the tag `Ersetzt`.
    """

    __tablename__ = "paperless_filing"

    kind: Mapped[str] = mapped_column(Text)
    element_id: Mapped[uuid.UUID] = mapped_column()
    source_id: Mapped[uuid.UUID] = mapped_column()
    source_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    application_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    title: Mapped[str] = mapped_column(Text, server_default="")
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(Text, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('protocol','protocol_public','application','attachment','plan')",
            name="kind",
        ),
        CheckConstraint("state IN ('pending','uploaded','filed','failed')", name="state"),
        UniqueConstraint("kind", "source_id", "source_at", name="uq_paperless_filing_source"),
        Index("ix_paperless_filing_element", "kind", "element_id"),
        Index("ix_paperless_filing_application_id", "application_id"),
        Index(
            "ix_paperless_filing_open",
            "due_at",
            postgresql_where=text("state IN ('pending','uploaded')"),
        ),
    )
