"""Tables of the committees: ``gremium``, its roles, its memberships and the OIDC group mappings."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Gremium(UUIDPkMixin, CreatedAtMixin, Base):
    """A gremium: the body that holds members, meetings and votes."""

    __tablename__ = "gremium"

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    #: Corporate design of the rendered documents. NULL = no variant, so the
    #: render path falls back to the renderer default. The FK is RESTRICT: a variant
    #: that a gremium still references cannot be deleted (the service answers 409).
    cd_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cd_variant.id", ondelete="RESTRICT"), nullable=True
    )
    default_lang: Mapped[str] = mapped_column(Text, server_default="de")
    #: Vote delegation allowed in this gremium (per gremium, not per assignment).
    allow_vote_delegation: Mapped[bool] = mapped_column(Boolean, server_default="false")
    #: Lead time in minutes before the meeting start. A non-pool delegation must
    #: be set up before this lead time. 0 = until the meeting start.
    delegation_lead_minutes: Mapped[int] = mapped_column(Integer, server_default="0")
    #: Allow delegation to users outside gremium & substitute pool.
    delegation_allow_external: Mapped[bool] = mapped_column(Boolean, server_default="false")
    #: Default quorum for the votes of this gremium. It is the percentage of
    #: eligible voters that must take part, from 0 to 100. NULL = no default.
    quorum_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The final protocols of this gremium appear without login on the public
    #: protocols page, as the public version only. Off by default.
    protocols_public: Mapped[bool] = mapped_column(Boolean, server_default="false")
    #: Extra addresses that get the final protocol in addition to the members.
    protocol_recipients: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")


class GremiumRole(UUIDPkMixin, Base):
    """Gremium-specific role.

    Each gremium maintains its own role set, separate from the global roles
    (``role``). `GremiumRoleMapping` maps an OIDC group to a role.
    `GremiumMembership` holds the derived membership.
    """

    __tablename__ = "gremium_role"

    gremium_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gremium.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(Text)
    name_i18n: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    #: Granular meeting-domain permissions of this role, as a list of keys:
    #: session.manage, vote.manage, vote.cast, protocol.write, protocol.finalize.
    permissions: Mapped[list[str]] = mapped_column(JSONB, server_default="[]")

    __table_args__ = (UniqueConstraint("gremium_id", "key", name="uq_gremium_role_gremium_key"),)


class GremiumMembership(UUIDPkMixin, Base):
    """Membership of a principal in a gremium, derived from the OIDC groups.

    ``membership_sync`` is the only writer. It derives the rows from
    ``principal.oidc_groups``, ``GremiumMembershipMapping`` and
    ``GremiumRoleMapping``. A membership has no term: a row exists while the
    OIDC groups make the principal a member, and the sync deletes it when they
    stop. The unique constraint keeps one row, and so one role, per
    (principal, gremium) pair. It closes the TOCTOU gap of parallel inserts.
    """

    __tablename__ = "gremium_membership"

    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principal.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gremium.id", ondelete="CASCADE"))
    gremium_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium_role.id", ondelete="RESTRICT")
    )

    __table_args__ = (
        Index("ix_gremium_membership_principal", "principal_id"),
        Index("ix_gremium_membership_gremium", "gremium_id"),
        UniqueConstraint(
            "principal_id", "gremium_id", name="uq_gremium_membership_principal_gremium"
        ),
    )


class GremiumMembershipMapping(UUIDPkMixin, Base):
    """Map an OIDC group to the membership in one gremium.

    The IdP is the only source of gremium membership. A principal whose
    ``oidc_groups`` contain ``oidc_group`` is a member of the gremium. The role in
    the gremium comes from ``GremiumRoleMapping``, or else it is the forced role
    ``member``. ``membership_sync`` writes the ``gremium_membership`` rows.
    """

    __tablename__ = "gremium_membership_mapping"

    gremium_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gremium.id", ondelete="CASCADE"))
    oidc_group: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "gremium_id", "oidc_group", name="uq_gremium_membership_mapping_gremium_group"
        ),
        Index("ix_gremium_membership_mapping_oidc_group", "oidc_group"),
    )


class GremiumRoleMapping(UUIDPkMixin, Base):
    """Map an OIDC group to a role in a gremium.

    The mapping gives the role only to a principal who is a member of the gremium
    through ``GremiumMembershipMapping``. It never makes a principal a member.
    """

    __tablename__ = "gremium_role_mapping"

    gremium_role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gremium_role.id", ondelete="RESTRICT")
    )
    oidc_group: Mapped[str] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "gremium_role_id", "oidc_group", name="uq_gremium_role_mapping_role_group"
        ),
        Index("ix_gremium_role_mapping_oidc_group", "oidc_group"),
    )
