"""OAuth2 AS models: authorization codes plus access/refresh tokens (MCP login).

The platform acts as an OAuth2 authorization server in front of the existing
Keycloak login: after OIDC login it mints a short-lived authorization code
(PKCE, RFC 7636) that a native client exchanges for an opaque access/refresh
token pair. Tokens are persisted as SHA-256 hashes only (plaintext never
stored); the scope caps the principal's permissions at runtime.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class OAuthAuthorizationCode(UUIDPkMixin, CreatedAtMixin, Base):
    """Short-lived, single-use authorization code (PKCE-bound)."""

    __tablename__ = "oauth_authorization_code"

    code_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    client_id: Mapped[str] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(Text)  # S256, base64url
    scope: Mapped[str] = mapped_column(Text)  # space-separated scope list
    # Token lifetime chosen in the consent (seconds); NULL = never expires.
    access_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OAuthToken(UUIDPkMixin, CreatedAtMixin, Base):
    """Access/refresh token pair (opaque, hashed). Rotation creates a new row."""

    __tablename__ = "oauth_token"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    client_id: Mapped[str] = mapped_column(Text)
    access_token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    refresh_token_hash: Mapped[bytes | None] = mapped_column(
        LargeBinary, unique=True, nullable=True
    )
    scope: Mapped[str] = mapped_column(Text)
    # Chosen lifetime (seconds); NULL = never expires (kept for refresh rotation).
    access_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    # NULL = never expires.
    access_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    refresh_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_oauth_token_principal_id", "principal_id"),)
