"""Identity and access tables — definitions only, no logic."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Principal(UUIDPkMixin, Base):
    """OIDC subject (Keycloak). PII (email) stays here, never in audit `data`."""

    __tablename__ = "principal"

    sub: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    oidc_groups: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Deactivated principals must not log in.
    active: Mapped[bool] = mapped_column(
        Boolean, server_default="true", default=True
    )
    # Personal, rotatable iCal feed token. Plaintext in the subscription URL —
    # low sensitivity (exposes only meeting titles/times of the own gremien);
    # rotating revokes the old URL.
    calendar_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Unique feed token. Deliberately a unique index, not a constraint: the
        # migration can create/drop it idempotently (CREATE/DROP INDEX IF
        # [NOT] EXISTS). Multiple NULLs are allowed (Postgres).
        Index("uq_principal_calendar_token", "calendar_token", unique=True),
    )


class Role(UUIDPkMixin, Base):
    __tablename__ = "role"

    key: Mapped[str] = mapped_column(Text, unique=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class RolePermission(Base):
    """`PK(role_id, permission)` — permission strings per role."""

    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE")
    )
    permission: Mapped[str] = mapped_column(Text)

    __table_args__ = (PrimaryKeyConstraint("role_id", "permission"),)


class RoleAssignment(UUIDPkMixin, Base):
    """Role assignment with gremium scope plus validity window (representation)."""

    __tablename__ = "role_assignment"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    granted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `delegated_by` marks a self-delegation: the `sub` of the member temporarily
    # handing over one of their own rights (`NULL` for plain admin assignments).
    # Anchor for listing/revoking own delegations and for the double-voting block
    # (a delegator who handed over voting rights must not vote themselves).
    delegated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delegate_voting: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (
        Index("ix_role_assignment_principal_id", "principal_id"),
        # Lookup "active outgoing (voting) delegations of a member" (cast block).
        Index("ix_role_assignment_delegated_by", "delegated_by"),
    )


class AuthSession(UUIDPkMixin, CreatedAtMixin, Base):
    """Server session of an OIDC principal.

    The browser gets only a signed, opaque `sid` in an HttpOnly+Secure+
    SameSite=Lax cookie — no JWT in JS. id/refresh tokens stay server-side
    (refresh/logout). Consistent across instances via the shared DB."""

    __tablename__ = "auth_session"

    sid: Mapped[str] = mapped_column(Text, unique=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_auth_session_principal_id", "principal_id"),)


class ApplicantSession(UUIDPkMixin, CreatedAtMixin, Base):
    """Server session of a magic-link applicant.

    Counterpart to :class:`AuthSession`: the browser holds only a signed, opaque
    `sid`; `application_id`+`scope` live server-side. An applicant token is thus
    NOT forgeable from `SESSION_SECRET` alone (it needs an existing row) and is
    server-side revocable — via logout (row deleted) or kill switch
    (`revoked_at`, e.g. on anonymization). The `application_id` FK cascades on
    application delete."""

    __tablename__ = "applicant_session"

    sid: Mapped[str] = mapped_column(Text, unique=True)
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE")
    )
    scope: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_applicant_session_application_id", "application_id"),
    )


class GroupMapping(UUIDPkMixin, Base):
    """OIDC group to role mapping (optional, scopable per gremium)."""

    __tablename__ = "group_mapping"

    oidc_group: Mapped[str] = mapped_column(Text)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
