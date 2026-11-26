"""The tables of the teams: ``team``, ``team_member`` and ``team_info``.

A team is either the inherent team of a Gremium (``gremium_id`` set) or a free team
(``gremium_id`` NULL). An inherent team has no name of its own: it shows the name of its
Gremium, so a rename of the Gremium renames the team at once. It has no parent and no
``team_member`` rows, because its members are the members and the substitute pool of the
Gremium. A free team has a name and hand-picked members with the role ``member`` or
``manager``, and it can be the sub-team of any team.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin

#: The roles of a member of a free team.
TEAM_ROLES: tuple[str, ...] = ("member", "manager")


class Team(UUIDPkMixin, CreatedAtMixin, Base):
    """A team: the inherent team of a Gremium or a free team with its own members."""

    __tablename__ = "team"

    #: The name of a free team. NULL for an inherent team, which shows its Gremium's name.
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The parent team. RESTRICT: a team with sub-teams is not deleted (409).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("team.id", ondelete="RESTRICT"), nullable=True
    )
    #: The Gremium of an inherent team. The team goes with its Gremium.
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True, unique=True
    )

    __table_args__ = (
        CheckConstraint("(gremium_id IS NULL) <> (name IS NULL)", name="name"),
        CheckConstraint("gremium_id IS NULL OR parent_id IS NULL", name="inherent_root"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        Index("ix_team_parent_id", "parent_id"),
    )


class TeamMember(Base):
    """A member of a free team, with the role ``member`` or ``manager``."""

    __tablename__ = "team_member"

    team_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("team.id", ondelete="CASCADE"))
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text, server_default="member")

    __table_args__ = (
        PrimaryKeyConstraint("team_id", "principal_id"),
        CheckConstraint("role IN ('member', 'manager')", name="role"),
        Index("ix_team_member_principal_id", "principal_id"),
    )


class TeamInfo(Base):
    """The Info tab of a free team: one Markdown text and a list of labelled links.

    The same shape as ``gremium_info``: one row per team, created by the first save, the
    links as ``[{"label": ..., "url": ...}]`` in the order of the editor, and ``version``
    counting the saves so two editors cannot overwrite each other unseen (409).
    """

    __tablename__ = "team_info"

    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("team.id", ondelete="CASCADE"), primary_key=True
    )
    body_md: Mapped[str] = mapped_column(Text, server_default="")
    links: Mapped[list[dict[str, str]]] = mapped_column(JSONB, server_default="[]")
    version: Mapped[int] = mapped_column(Integer, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("principal.id", ondelete="SET NULL"), nullable=True, index=True
    )
