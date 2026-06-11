"""Flow-Versionierung: flow_version, state, transition (data-model §1 »Form/Flow«).

Nur Tabellen (T-06). Guards/Engine: T-14.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class FlowVersion(UUIDPkMixin, CreatedAtMixin, Base):
    """Flow-Version je Antragstyp. Max. eine `active` pro Typ (partial unique)."""

    __tablename__ = "flow_version"

    # Global-Flow-Redesign (#28): ein **globaler** Flow für ALLE Antragstypen.
    # ``application_type_id`` ist daher nullable — ``NULL`` = globaler Flow. Welcher
    # Pfad/welches Gremium wann greift, regeln Decision-/Vote-/Approval-States, nicht
    # die Typ-Bindung. (Pre-Alpha: harter Cutover, Alt-Flows werden gedroppt.)
    application_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    editor_layout: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("application_type_id", "version"),
        # Genau ein aktiver globaler Flow (``application_type_id IS NULL``).
        Index(
            "uq_flow_version_one_active_global",
            "active",
            unique=True,
            postgresql_where=text("active AND application_type_id IS NULL"),
        ),
        # Übergangsweise: max. ein aktiver per-Typ-Flow (Alt-Pfad bis Cutover).
        Index(
            "uq_flow_version_one_active_per_type",
            "application_type_id",
            unique=True,
            postgresql_where=text("active AND application_type_id IS NOT NULL"),
        ),
    )


class State(UUIDPkMixin, Base):
    """Status eines Flows. Genau ein `is_initial` pro flow_version (partial unique)."""

    __tablename__ = "state"

    flow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flow_version.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(Text)
    label_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_allowed: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_initial: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Global-Flow-Redesign (#28, Cleanup): nur noch zwei State-Arten.
    #  * ``normal`` — gewöhnlicher Status; manuelle/automatische Übergänge per Guard.
    #  * ``vote``   — ein Gremium stimmt ab; ``config={gremiumId,...}``; 2 Ausgänge
    #                 (branch ``pass``/``fail``). (approval/decision entfernt — durch
    #                 manuelle ``roleIs``-Übergänge bzw. automatische Guard-Übergänge
    #                 abgedeckt.)
    kind: Mapped[str] = mapped_column(Text, server_default="normal")
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("flow_version_id", "key"),
        CheckConstraint("kind IN ('normal','vote')", name="state_kind"),
        Index(
            "uq_state_one_initial_per_flow",
            "flow_version_id",
            unique=True,
            postgresql_where=text("is_initial"),
        ),
    )


class Transition(UUIDPkMixin, Base):
    __tablename__ = "transition"

    flow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flow_version.id", ondelete="CASCADE")
    )
    from_state_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("state.id", ondelete="CASCADE")
    )
    to_state_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("state.id", ondelete="CASCADE")
    )
    label_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Optionale Farbe (#flow): färbt Pfeil im Editor + Entscheidungs-Button im Antrag.
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    guard: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actions: Mapped[list] = mapped_column(JSONB, server_default="[]")
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")
    # Automatischer Übergang (#8): feuert ohne Nutzer-Aktion, sobald der Guard
    # erfüllt ist (vom Worker zyklisch ausgewertet, ``manual=False``).
    automatic: Mapped[bool] = mapped_column(Boolean, server_default="false")
    # Ergebnis-Zweig (#28): für die 2 Ausgänge von vote/approval-States —
    # ``pass``/``fail`` bzw. ``accept``/``reject`` (sonst ``NULL``).
    branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    # »Erfordert Aktion« (#requires-action): zählt der feuerbare Übergang als offene
    # Aufgabe (Tasks-Tab)? ``false`` = optionale Aktion, erzeugt keine Aufgabe.
    requires_action: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (Index("ix_transition_flow_version_id_from_state_id",
                            "flow_version_id", "from_state_id"),)
