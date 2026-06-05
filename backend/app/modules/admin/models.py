"""Organisation & Config: gremium, mail_list, application_type (data-model §1).

Nur Tabellen (T-06). Config-CRUD/Logik: T-24 (admin).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Gremium(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "gremium"

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    # pytex CD-Variante: stupa/asta/echo/makers/report
    cd_variant: Mapped[str] = mapped_column(Text, server_default="stupa")
    default_lang: Mapped[str] = mapped_column(Text, server_default="de")


class MailList(UUIDPkMixin, Base):
    """Verteiler je Gremium."""

    __tablename__ = "mail_list"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    recipients: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class ApplicationType(UUIDPkMixin, CreatedAtMixin, Base):
    """Antragstyp; verweist auf die je aktive Form-/Flow-Version (use_alter:
    zirkulärer FK zu form_version/flow_version)."""

    __tablename__ = "application_type"

    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str] = mapped_column(Text, unique=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    has_budget: Mapped[bool] = mapped_column(Boolean, server_default="false")
    comparison_offers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active_form_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_version.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    active_flow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("flow_version.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
