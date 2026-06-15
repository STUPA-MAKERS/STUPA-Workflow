"""Organisation & Config: gremium, mail_list, application_type (data-model §1)
sowie die Config-Persistenz aus T-24: webhook(+delivery) und site_config_version.

Tabellen-Kern (gremium/mail_list/application_type): T-06. Config-CRUD/Logik +
webhook/site_config: T-24 (admin). Die webhook-Tabellen leben bewusst im admin-Modul
(nicht ``modules/webhooks``), weil T-19 keine Persistenz angelegt hat und das
Admin-CRUD der einzige Konsument ist (`webhook.manage`).
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
    # Stimm-Delegation in diesem Gremium erlaubt (#14, pro Gremium statt pro Zuweisung).
    allow_vote_delegation: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Vorlauf in Minuten vor Sitzungsbeginn, bis zu dem eine (Nicht-Pool-)Delegation
    # eingerichtet werden darf; 0 = bis Sitzungsbeginn (#delegation-rework).
    delegation_lead_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    # Delegation an Nutzer außerhalb von Gremium & Stellvertreter-Pool erlauben.
    delegation_allow_external: Mapped[bool] = mapped_column(
        Boolean, server_default="false"
    )
    # Default-Quorum (% der Stimmberechtigten, die teilnehmen müssen) für Abstimmungen
    # dieses Gremiums; NULL = kein Default. 0–100.
    quorum_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GremiumRole(UUIDPkMixin, Base):
    """Gremium-spezifische Rolle (#42/#62) — ein **eigener** Rollensatz, getrennt von
    den globalen Rollen (``role``) und **pro Gremium** gepflegt (z. B. Vorsitz,
    Beisitz, Kassenwart je Gremium). Die konkrete Zugehörigkeit hält
    :class:`GremiumMembership`."""

    __tablename__ = "gremium_role"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(Text)
    name_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Granulare, pro Gremium-Rolle konfigurierbare Berechtigungen der Sitzungs-Domäne
    # (session.manage / vote.manage / vote.cast / protocol.write). Liste von Keys.
    permissions: Mapped[list] = mapped_column(JSONB, server_default="[]")

    __table_args__ = (
        UniqueConstraint("gremium_id", "key", name="uq_gremium_role_gremium_key"),
    )


class GremiumMembership(UUIDPkMixin, Base):
    """Zeitlich begrenzte Zugehörigkeit eines Principals zu einem Gremium (#42).

    Pro (Principal, Gremium) ist zu jedem Zeitpunkt **genau eine** Rolle aktiv —
    überlappende Amtszeiten sind verboten (Service-seitig geprüft). Mehrere
    **nicht-überlappende** Mitgliedschaften (aufeinanderfolgende Amtszeiten) sind
    erlaubt. ``valid_from``/``valid_until`` = Amtszeit (NULL = offen)."""

    __tablename__ = "gremium_membership"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    gremium_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium_role.id", ondelete="RESTRICT")
    )
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_gremium_membership_principal", "principal_id"),
        Index("ix_gremium_membership_gremium", "gremium_id"),
    )


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
    # DSGVO-Aufbewahrung: Monate bis Anonymisierung; NULL = globaler Default
    # (``privacy_settings.default_retention_months``).
    retention_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_form_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("form_version.id", ondelete="SET NULL", use_alter=True),
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

    ``idempotency_key`` (T-19, Migration 0012) entkoppelt Event-Instanz von Versand:
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
    last_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_at: Mapped[datetime | None] = mapped_column(
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
