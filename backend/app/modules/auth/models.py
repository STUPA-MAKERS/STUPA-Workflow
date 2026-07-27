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
    """OIDC subject from Keycloak.

    The PII, the email address, stays in this table. It never enters the audit `data`
    column.
    """

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
    # Personal iCal feed token that the user can rotate. The subscription URL carries it
    # in plaintext. The sensitivity is low: it exposes only the titles and times of the
    # meetings of the own Gremien. A rotation revokes the old URL.
    calendar_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # A unique index on purpose, not a constraint. The migration can then create and
        # drop it idempotently with CREATE/DROP INDEX IF [NOT] EXISTS. Postgres allows
        # more than one NULL under a unique index.
        Index("uq_principal_calendar_token", "calendar_token", unique=True),
    )


class Role(UUIDPkMixin, Base):
    __tablename__ = "role"

    key: Mapped[str] = mapped_column(Text, unique=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class RolePermission(Base):
    """Permission strings per role, keyed by `PK(role_id, permission)`."""

    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE")
    )
    permission: Mapped[str] = mapped_column(Text)

    __table_args__ = (PrimaryKeyConstraint("role_id", "permission"),)


class RoleAssignment(UUIDPkMixin, Base):
    """Role assignment with a Gremium scope and a validity window for a delegation."""

    __tablename__ = "role_assignment"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    granted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    # `delegated_by` marks a self-delegation. It holds the `sub` of the member who hands
    # over one of their own rights for a time. It is `NULL` for a plain admin assignment.
    # It anchors the listing and the revocation of the own delegations. It also anchors
    # the double-voting block: a delegator who handed over the voting right must not vote.
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
        # Serves the lookup of the active outgoing voting delegations of a member. The
        # cast block needs it.
        Index("ix_role_assignment_delegated_by", "delegated_by"),
    )


class AuthSession(UUIDPkMixin, CreatedAtMixin, Base):
    """Server session of an OIDC principal.

    The browser gets only a signed, opaque `sid` in an HttpOnly, Secure, SameSite=Lax
    cookie. No JWT reaches JavaScript. The id token and the refresh token stay on the
    server for the refresh and the logout. The shared database keeps the session
    consistent across instances.
    """

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

    This table is the counterpart to `AuthSession`. The browser holds only a signed,
    opaque `sid`. The `application_id` and the `scope` stay on the server. Nobody can forge
    an applicant token from `SESSION_SECRET` alone, because the token also needs an
    existing row. The server can revoke the token: a logout deletes the row, and the kill
    switch sets `revoked_at`, for example on anonymization. The `application_id` foreign
    key cascades when the application is deleted.
    """

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
    """Optional mapping from an OIDC group to a role, scopable per Gremium."""

    __tablename__ = "group_mapping"

    oidc_group: Mapped[str] = mapped_column(Text)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
