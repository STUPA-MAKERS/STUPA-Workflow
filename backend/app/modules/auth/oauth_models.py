"""OAuth2 authorization-server models: authorization codes and tokens for MCP login.

The platform acts as an OAuth2 authorization server in front of the Keycloak login. After
the OIDC login it mints a short-lived authorization code with PKCE (RFC 7636). A native
client exchanges that code for an opaque access and refresh token pair. The database holds
the tokens as SHA-256 hashes only and never stores the plaintext. The scope caps the
permissions of the principal at runtime.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class OAuthAuthorizationCode(UUIDPkMixin, CreatedAtMixin, Base):
    """Short-lived, single-use authorization code, bound to a PKCE challenge."""

    __tablename__ = "oauth_authorization_code"

    code_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    client_id: Mapped[str] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(Text)  # S256, base64url
    scope: Mapped[str] = mapped_column(Text)  # space-separated scope list
    # Token lifetime in seconds, chosen in the consent. NULL means the token never expires.
    access_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OAuthToken(UUIDPkMixin, CreatedAtMixin, Base):
    """Opaque, hashed access and refresh token pair. A rotation creates a new row."""

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
    # Chosen lifetime in seconds. NULL means never. Kept here for the refresh rotation.
    access_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    # NULL means the token never expires.
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
