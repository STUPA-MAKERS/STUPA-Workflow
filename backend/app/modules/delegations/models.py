"""Sitzungs-Delegationen (#delegation-rework): Tabellen.

:class:`MeetingDelegation` — die **sitzungsgebundene** Vertretung: genau eine
ausgehende Delegation je (Sitzung, Delegierender). Ersetzt das frühere Modell
»``role_assignment`` mit ``delegated_by``« (T-45): eine Delegation gilt nie blanko
für einen Zeitraum, sondern immer für **eine konkrete Sitzung**; ihr Gremium ist
das der Sitzung. ``delegate_voting`` überträgt zusätzlich das Stimmrecht
(exklusiver Transfer, kein Duplikat — der Delegierende ist für Votes dieser
Sitzung gesperrt).

:class:`DelegationSubstitute` — der pro Gremium gepflegte **Stellvertreter-Pool**
(gewählte/bestimmte Vertreter, z. B. Fachschaften): an Pool-Mitglieder darf ohne
Vorlauf-Deadline bis Sitzungsbeginn delegiert werden, auch wenn sie nicht selbst
Gremium-Mitglied sind. ``member_principal_id IS NULL`` = Stellvertreter für jedes
Mitglied des Gremiums, sonst nur für das benannte Mitglied.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class MeetingDelegation(UUIDPkMixin, CreatedAtMixin, Base):
    """Vertretung für **eine** Sitzung; Stimmrecht optional mit übertragen."""

    __tablename__ = "meeting_delegation"

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("meeting.id", ondelete="CASCADE")
    )
    # Denormalisiert (= meeting.gremium_id): erspart den Join im heißen
    # Stimmrechts-Check (cast) und in »meine Delegationen«-Abfragen.
    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    delegator_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    delegate_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    delegate_voting: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Über den Stellvertreter-Pool legitimiert (→ keine Vorlauf-Deadline beim Anlegen).
    via_pool: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # ``sub`` des Anlegenden (Selbst-Service oder Admin) — Audit-Anker.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Genau eine ausgehende Vertretung je (Sitzung, Mitglied).
        UniqueConstraint(
            "meeting_id", "delegator_principal_id", name="uq_meeting_delegation_delegator"
        ),
        # Höchstens eine Stimmrechts-Übernahme je (Sitzung, Empfänger): ein Principal
        # gibt genau einen Stimmzettel ab — eine zweite Stimm-Delegation an dieselbe
        # Person verfiele stillschweigend (Transfer ≠ Duplikat).
        Index(
            "uq_meeting_delegation_voting_delegate",
            "meeting_id",
            "delegate_principal_id",
            unique=True,
            postgresql_where=text("delegate_voting"),
        ),
        Index("ix_meeting_delegation_meeting", "meeting_id"),
        Index("ix_meeting_delegation_delegate", "delegate_principal_id"),
    )


class DelegationSubstitute(UUIDPkMixin, CreatedAtMixin, Base):
    """Pool-Eintrag: ``substitute`` darf ``member`` (oder jedes Mitglied, wenn
    ``member_principal_id IS NULL``) im Gremium ohne Vorlauf vertreten."""

    __tablename__ = "delegation_substitute"

    gremium_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE")
    )
    # NULL = gremium-weiter Stellvertreter (vertritt jedes Mitglied).
    member_principal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), nullable=True
    )
    substitute_principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # NULLS NOT DISTINCT gibt es erst ab PG15 einheitlich — der gremium-weite
        # Eintrag (member IS NULL) wird über einen partiellen Unique-Index dedupliziert.
        UniqueConstraint(
            "gremium_id",
            "member_principal_id",
            "substitute_principal_id",
            name="uq_delegation_substitute",
        ),
        Index(
            "uq_delegation_substitute_gremiumwide",
            "gremium_id",
            "substitute_principal_id",
            unique=True,
            postgresql_where=text("member_principal_id IS NULL"),
        ),
        Index("ix_delegation_substitute_gremium", "gremium_id"),
    )
