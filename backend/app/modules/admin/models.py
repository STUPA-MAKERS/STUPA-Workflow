"""Organisation & Config: gremium, mail_list, application_type (data-model §1)
sowie die Config-Persistenz aus T-24: webhook(+delivery) und site_config_version.

Tabellen-Kern (gremium/mail_list/application_type): T-06. Config-CRUD/Logik +
webhook/site_config: T-24 (admin). Die webhook-Tabellen leben bewusst im admin-Modul
(nicht ``modules/webhooks``), weil T-19 keine Persistenz angelegt hat und das
Admin-CRUD der einzige Konsument ist (`webhook.manage`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
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


class Webhook(UUIDPkMixin, CreatedAtMixin, Base):
    """Outbound-Webhook-Config (data-model §1, api.md admin `webhook.manage`).

    Persistenz fürs Admin-CRUD (T-24). ``secret`` wird serverseitig erzeugt (HMAC-
    Signing der Auslieferung, T-19) und nie über die API ausgegeben. ``events`` ist
    eine Whitelist aus :data:`app.shared.config_schemas.EventName`.
    """

    __tablename__ = "webhook"

    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class WebhookDelivery(UUIDPkMixin, Base):
    """Auslieferungs-Versuch eines Webhooks (Worker-Pickup, data-model §1).

    Von T-24 mit angelegt, damit das Schema vollständig ist; der Delivery-Worker
    (T-19) ist der Schreiber. Index ``(status, next_at)`` = Worker-Pickup.

    ``idempotency_key`` (T-19, Migration 0011) entkoppelt Event-Instanz von Versand:
    ein Flow-Retry desselben Status-Events legt **keine** zweite Delivery an
    (unique ``(webhook_id, idempotency_key)``; ``NULL`` = keine Dedup, z. B. manuell).
    """

    __tablename__ = "webhook_delivery"

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook.id", ondelete="CASCADE")
    )
    event: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_at: Mapped[object | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    response_code: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','ok','failed','dead')",
            name="webhook_delivery_status",
        ),
        Index("ix_webhook_delivery_status_next_at", "status", "next_at"),
        UniqueConstraint(
            "webhook_id",
            "idempotency_key",
            name="uq_webhook_delivery_idempotency",
        ),
    )


class SiteConfigVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Versionierte Branding-/Site-Config (#21, T-24).

    Wie form/flow versioniert: neue Version statt In-place-Edit der aktiven Version;
    max. **eine** ``active`` (partial-unique ``WHERE active``). ``branding`` ist das
    Schema-validierte JSON (`app.modules.admin.branding.Branding`). ``created_by``
    hält den OIDC-``sub`` des aktivierenden Principals (kein PII).
    """

    __tablename__ = "site_config_version"

    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    branding: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("version", name="uq_site_config_version_version"),
        Index(
            "uq_site_config_version_one_active",
            "active",
            unique=True,
            postgresql_where=text("active"),
        ),
    )
