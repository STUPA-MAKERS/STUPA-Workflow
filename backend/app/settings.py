"""Anwendungs-Settings aus `.env` (Pydantic-Settings).

Pflicht-Secrets ohne Default → fehlen sie, wirft `load_settings` einen klaren
`SettingsError` (statt einer rohen Pydantic-ValidationError) beim Start.
Layout/Namen siehe `deploy/.env.example`.
"""

from functools import lru_cache
from typing import Any

from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class SettingsError(RuntimeError):
    """Klarer Startfehler bei fehlender/ungültiger Konfiguration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # — Identität / Betrieb —
    app_name: str = "Antragsplattform API"
    app_version: str = "0.0.2"
    environment: str = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost"

    # — Pflicht-Secrets (kein Default) —
    database_url: str
    session_secret: str
    magic_link_secret: str

    # — Reverse-Proxy (security.md §3): eng, nie "*" —
    forwarded_allow_ips: str = "127.0.0.1"

    # — CORS aus per Default (overview/security: kein Cross-Origin) —
    cors_allow_origins: list[str] = []

    # — Optionale Infra (in späteren Tasks genutzt) —
    redis_url: str = "redis://redis:6379/0"
    db_migration_url: str | None = None

    # — OIDC / Keycloak (security.md §2). Ohne vollständige Config ist OIDC »aus«
    #   (Login/Callback → 503), Magic-Link bleibt unabhängig nutzbar. —
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_url: str | None = None
    oidc_scopes: str = "openid email profile"
    oidc_groups_claim: str = "groups"
    oidc_post_logout_redirect_url: str | None = None

    # — Session-/Applicant-Cookie (security.md §1/§2: HttpOnly+Secure+SameSite=Lax) —
    session_cookie_name: str = "ap_session"
    applicant_cookie_name: str = "ap_applicant"
    oidc_tx_cookie_name: str = "ap_oidc_tx"
    session_ttl_hours: int = 12
    cookie_secure: bool = True

    # — Magic-Link-Laufzeiten (security.md §1) —
    magic_link_edit_ttl_days: int = 7
    magic_link_action_ttl_minutes: int = 15

    @property
    def oidc_enabled(self) -> bool:
        """OIDC nur aktiv, wenn alle Pflicht-Parameter gesetzt sind."""
        return bool(
            self.oidc_issuer
            and self.oidc_client_id
            and self.oidc_client_secret
            and self.oidc_redirect_url
        )


def load_settings(**overrides: Any) -> Settings:
    """Settings laden; fehlende Pflichtfelder → `SettingsError` mit klarer Meldung."""
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing = [
            ".".join(str(p) for p in err["loc"])
            for err in exc.errors()
            if err["type"] == "missing"
        ]
        if missing:
            raise SettingsError(
                "Fehlende Pflicht-Konfiguration (env): " + ", ".join(sorted(missing))
            ) from exc
        raise SettingsError(f"Ungültige Konfiguration: {exc}") from exc


@lru_cache
def get_settings() -> Settings:
    return load_settings()
