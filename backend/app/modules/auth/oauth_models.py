"""OAuth2-AS-Modelle: Authorization-Codes + Access/Refresh-Token (MCP-Login, #MCP).

Die Plattform agiert als OAuth2-Authorization-Server **vor** dem bestehenden Keycloak-
Login: nach erfolgreichem OIDC-Login mintet sie einen kurzlebigen Authorization-Code
(PKCE, RFC 7636), den ein nativer Client (MCP-Server, Loopback-Redirect) gegen ein
opakes Access-/Refresh-Token-Paar tauscht. Token werden — wie Magic-Links — **nur** als
SHA-256-Hash persistiert (Klartext nie gespeichert); der Scope kappt die Permissions des
Principals zur Laufzeit (siehe ``app.modules.auth.oauth.scope_permissions``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class OAuthAuthorizationCode(UUIDPkMixin, CreatedAtMixin, Base):
    """Kurzlebiger, einmal-verwendbarer Authorization-Code (PKCE-gebunden)."""

    __tablename__ = "oauth_authorization_code"

    code_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    client_id: Mapped[str] = mapped_column(Text)
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(Text)  # S256, base64url
    scope: Mapped[str] = mapped_column(Text)  # Space-separierte Scope-Liste
    # Vom Nutzer im Consent gewählte Token-Lebensdauer (Sekunden); NULL = läuft nie ab.
    access_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class OAuthToken(UUIDPkMixin, CreatedAtMixin, Base):
    """Access-/Refresh-Token-Paar (opak, gehasht). Rotation legt eine neue Zeile an."""

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
    # Gewählte Lebensdauer (Sekunden); NULL = läuft nie ab (für Refresh-Rotation gemerkt).
    access_ttl_seconds: Mapped[int | None] = mapped_column(nullable=True)
    # NULL = läuft nie ab.
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
