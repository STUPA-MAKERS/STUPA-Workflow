"""Table ``application_type``."""

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
    #: The Antrag PDF of this type ends with the signature section (spec 000887).
    pdf_signatures: Mapped[bool] = mapped_column(Boolean, server_default="false")
    comparison_offers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: GDPR retention in months until the anonymization. NULL = the global default
    #: ``privacy_settings.default_retention_months``.
    retention_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_form_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_version.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
