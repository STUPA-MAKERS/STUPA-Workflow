"""Flow versioning tables: flow_version, state, transition."""

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
    """The global flow: one graph for all application types.

    Vote states decide which path and which Gremium apply. There is no per-type
    binding. Exactly one row is active (partial unique index).
    """

    __tablename__ = "flow_version"

    version: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, server_default="false")
    editor_layout: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    __table_args__ = (
        UniqueConstraint("version"),
        Index(
            "uq_flow_version_one_active_global",
            "active",
            unique=True,
            postgresql_where=text("active"),
        ),
    )


class State(UUIDPkMixin, Base):
    """A flow state. Exactly one state per flow_version has `is_initial` (partial unique).

    Attributes:
        is_terminal: Terminal state for GDPR retention. The platform may anonymize an
            application in a terminal state.
        kind: `normal` has guarded manual or automatic transitions. `vote` means that a
            Gremium votes, with `config={gremiumId,...}` and two branch exits, pass and
            fail.
    """

    __tablename__ = "state"

    flow_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flow_version.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(Text)
    label_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_allowed: Mapped[bool] = mapped_column(Boolean, server_default="true")
    is_initial: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_terminal: Mapped[bool] = mapped_column(Boolean, server_default="false")
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
    """A directed edge between two states of a flow version.

    Attributes:
        color: Optional color. It tints the editor arrow and the decision button on the
            application.
        automatic: The transition fires without a user action once the guard holds. The
            worker evaluates it periodically with `manual=False`.
        branch: Result branch of a vote-state exit, `pass` or `fail`. NULL otherwise.
        requires_action: The firable transition counts as an open task. False marks an
            optional action.
    """

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
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    guard: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    actions: Mapped[list] = mapped_column(JSONB, server_default="[]")
    order: Mapped[int] = mapped_column("order", Integer, server_default="0")
    automatic: Mapped[bool] = mapped_column(Boolean, server_default="false")
    branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_action: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (Index("ix_transition_flow_version_id_from_state_id",
                            "flow_version_id", "from_state_id"),)
