"""Identität & Rechte (data-model §1 »Identität & Rechte«).

Nur Tabellen-Definitionen (T-06) — keine Logik. RBAC-Auflösung/Magic-Link: T-10.
"""

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
    """OIDC-Subjekt (Keycloak). PII (email) bleibt hier, nicht in `data`."""

    __tablename__ = "principal"

    sub: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    oidc_groups: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Role(UUIDPkMixin, Base):
    __tablename__ = "role"

    key: Mapped[str] = mapped_column(Text, unique=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, server_default="{}")


class RolePermission(Base):
    """`PK(role_id, permission)` — Permission-Strings je Rolle."""

    __tablename__ = "role_permission"

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("role.id", ondelete="CASCADE")
    )
    permission: Mapped[str] = mapped_column(Text)

    __table_args__ = (PrimaryKeyConstraint("role_id", "permission"),)


class RoleAssignment(UUIDPkMixin, Base):
    """Rollenzuweisung mit Gremium-Scope + Gültigkeitsfenster (Vertretung)."""

    __tablename__ = "role_assignment"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    granted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delegate_voting: Mapped[bool] = mapped_column(Boolean, server_default="false")

    __table_args__ = (Index("ix_role_assignment_principal_id", "principal_id"),)


class AuthSession(UUIDPkMixin, CreatedAtMixin, Base):
    """Server-Session eines OIDC-Principals (security.md §2).

    Der Browser bekommt nur ein signiertes, opakes `sid` im HttpOnly+Secure+
    SameSite=Lax-Cookie — kein JWT im JS. id/refresh-Token bleiben serverseitig
    (Refresh/Logout). Über Instanzen konsistent via gemeinsamer DB."""

    __tablename__ = "auth_session"

    sid: Mapped[str] = mapped_column(Text, unique=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_auth_session_principal_id", "principal_id"),)


class GroupMapping(UUIDPkMixin, Base):
    """OIDC-Gruppe → Rolle (optional, scope-bar je Gremium)."""

    __tablename__ = "group_mapping"

    oidc_group: Mapped[str] = mapped_column(Text)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("role.id", ondelete="CASCADE"))
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
