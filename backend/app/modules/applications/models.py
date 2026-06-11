"""Anträge: application, applicant, submission_version, status_event (data-model §1).

Nur Tabellen (T-06). CRUD/Diff/Timeline: T-12.

PII liegt in `applicant` (R14.3, ausgelagert); `application.data` möglichst ohne PII.
Anonymisierung (nicht Hard-Delete) ist der Default-Löschweg → `applicant`-FK CASCADE
greift nur bei tatsächlichem Antrags-Delete.
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
    """Antrag. `data` = aktuelle Feldwerte (JSONB, GIN-indiziert); promoted
    `amount`/`currency` werden vom Service aus `data` synchronisiert (data-model §2)."""

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
    # Kostenstelle (Budget-Baum, i.d.R. Leaf) + Haushaltsjahr [CR R7.1e]. HHJ wird bei
    # der Budget-Zuordnung gesetzt (nicht bei Antragstellung); verschiebbar via
    # `move-fiscal-year`. Beide additiv zum flachen `budget_pot_id` (T-17).
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
    # OIDC-``sub`` der/des erstellenden Principals (eingeloggte Antragstellung, #24).
    # ``None`` bei anonymer Einreichung. Erlaubt Lesen/Bearbeiten/Löschen des eigenen
    # Antrags ohne ``application.manage``.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Zeitpunkt der E-Mail-Bestätigung (Gast-Einreichung): bis dahin ist der Antrag
    # **unsichtbar** und wird nach 12 h verworfen. Eingeloggte Anträge sind sofort
    # bestätigt (OIDC-Mail vertrauenswürdig); Gäste bestätigen per Magic-Link-Verify.
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
    """Ausgelagerte PII (1:1 zum Antrag), nur für Berechtigte sichtbar."""

    __tablename__ = "applicant"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), unique=True
    )
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubmissionVersion(UUIDPkMixin, Base):
    """Versionierter Snapshot der Antwortdaten + Diff."""

    __tablename__ = "submission_version"

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    changed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(server_default=func.now())
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (UniqueConstraint("application_id", "version"),)


class StatusEvent(UUIDPkMixin, Base):
    """Status-Timeline-Eintrag (Übergang)."""

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
    at: Mapped[datetime] = mapped_column(server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_status_event_application_id_at", "application_id", "at"),)


class MagicLink(UUIDPkMixin, CreatedAtMixin, Base):
    """Magic-Link für Antragsteller (security.md §1).

    DB hält **nur** `sha256(token||pepper)` — der Klartext-Token existiert allein im
    Mail-Link. Scope bindet an genau eine `application_id` + `edit|view`; Expiry +
    `single_use` (`used_at`) erzwingen Einmal-/Ablauf-Logik (Verify → 410)."""

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
        # UNIQUE: trägt die atomare Single-Use-Einlösung (UPDATE … WHERE used_at IS
        # NULL) + verhindert Hash-Kollisions-Mehrdeutigkeit (security.md §1).
        Index("ix_magic_link_token_hash", "token_hash", unique=True),
    )


class Comment(UUIDPkMixin, Base):
    """Antrags-Kommentar (data-model §1 »comment«).

    `visibility='internal'` sehen nur Principals (RBAC); `'public'` auch der
    Antragsteller (Magic-Link). `author_kind` trennt Principal- von Applicant-Autor."""

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
