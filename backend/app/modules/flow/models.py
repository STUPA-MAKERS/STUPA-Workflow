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

    application_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application_type.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    editor_layout: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("application_type_id", "version"),
        Index(
            "uq_flow_version_one_active_per_type",
            "application_type_id",
            unique=True,
            postgresql_where=text("active"),
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
    category: Mapped[str] = mapped_column(Text)
    edit_allowed: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_initial: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        UniqueConstraint("flow_version_id", "key"),
        CheckConstraint(
            "category IN ('open','running','closed')", name="state_category"
        ),
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
    guard: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actions: Mapped[list] = mapped_column(JSONB, server_default="[]")
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")

    __table_args__ = (Index("ix_transition_flow_version_id_from_state_id",
                            "flow_version_id", "from_state_id"),)
