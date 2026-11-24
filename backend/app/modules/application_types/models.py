"""Tables ``application_type`` and ``application_type_group``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class ApplicationTypeGroup(UUIDPkMixin, CreatedAtMixin, Base):
    """A group of Antragsarten in step 1 of the apply wizard (spec 001180).

    ``text_i18n`` is a Markdown text per language that step 1 shows under the name.
    ``position`` sets the order of the groups (spec 001183).
    """

    __tablename__ = "application_type_group"

    name_i18n: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    text_i18n: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    position: Mapped[int] = mapped_column(Integer, server_default="0")


class ApplicationType(UUIDPkMixin, CreatedAtMixin, Base):
    """Application type.

    The row references the active form version. The foreign key to
    ``form_version`` is circular, so it uses ``use_alter``.
    """

    __tablename__ = "application_type"

    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str] = mapped_column(Text, unique=True)
    name_i18n: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    has_budget: Mapped[bool] = mapped_column(Boolean, server_default="false")
    #: The Antrag PDF of this type ends with the signature section (spec 000888).
    pdf_signatures: Mapped[bool] = mapped_column(Boolean, server_default="false")
    #: The signature rows of the Antrag PDF, in order: ``[{"label", "signer"}]``
    #: (spec 003005).
    signature_rows: Mapped[list[dict[str, str]]] = mapped_column(JSONB, server_default="[]")
    #: The Antrag needs a file before it leaves the initial state (spec 001732).
    attachment_required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    comparison_offers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: GDPR retention in months until the anonymization. NULL = the global default
    #: ``privacy_settings.default_retention_months``.
    retention_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The group in step 1 of the apply wizard (spec 001180). NULL = "Weitere Anträge".
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_type_group.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The order inside the group, or among the types without a group (spec 001183).
    position: Mapped[int] = mapped_column(Integer, server_default="0")
    active_form_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_version.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
