"""Form-Versionierung: form_version, form_field (data-model §1 »Form/Flow«).

Nur Tabellen (T-06). Validierung/effective_form: T-11.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class FormVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Eine Form-Version je Antragstyp. Max. eine `active` pro Typ (partial unique)."""

    __tablename__ = "form_version"

    application_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # NC-Forms-Beschreibung (mehrsprachiges Markdown); optional (#13).
    description_i18n: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint("application_type_id", "version"),
        Index(
            "uq_form_version_one_active_per_type",
            "application_type_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )


class FormField(UUIDPkMixin, Base):
    """Feld-Definition einer Form-Version (= FormFieldDef, config_schemas §5.1)."""

    __tablename__ = "form_field"

    form_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("form_version.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    label_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    help_i18n: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, server_default="false")
    validation: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    visible_if: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    compute: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")
    is_promoted: Mapped[bool] = mapped_column(Boolean, server_default="false")
    promote_target: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (UniqueConstraint("form_version_id", "key"),)
