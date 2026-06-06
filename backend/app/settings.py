"""Anwendungs-Settings aus `.env` (Pydantic-Settings).

Pflicht-Secrets ohne Default → fehlen sie, wirft `load_settings` einen klaren
`SettingsError` (statt einer rohen Pydantic-ValidationError) beim Start.
Layout/Namen siehe `deploy/.env.example`.
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Mindestlänge für Signing-/Client-Secrets (security.md §10: keine schwachen Secrets).
_MIN_SECRET_LEN = 16


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

    # — Pflicht-Secrets (kein Default; Mindestlänge erzwungen) —
    database_url: str
    session_secret: str = Field(min_length=_MIN_SECRET_LEN)
    magic_link_secret: str = Field(min_length=_MIN_SECRET_LEN)

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
    oidc_client_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
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

    # — Antrags-Payload-Obergrenze (öffentlicher POST /applications, anti-DoS) —
    #   Gilt für die serialisierten Feldwerte (`data`) und als Content-Length-Schranke;
    #   darüber → 413. 64 KiB reicht für alle realen Formulare.
    max_application_payload_bytes: int = 65536

    # — Body-Cap der Auth-POSTs (magic-link / verify, anti-DoS, Issue #24). Auth-Bodies
    #   sind winzig (Mail/Token) → enge Schranke; darüber → 413. —
    max_auth_payload_bytes: int = 8192

    # — Altcha (Proof-of-Work, security.md §7, Issue #23). Ohne Secret ist die
    #   Verifikation **aus** (Dev/Test); das Feld wird dann nur durchgereicht. Das
    #   Secret wird mit dem Altcha-Sentinel geteilt (deploy/.env: ALTCHA_HMAC_SECRET). —
    altcha_hmac_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    altcha_max_number: int = 100_000
    altcha_challenge_ttl_seconds: int = 300

    # — Rate-Limiting (sliding window, security.md §8 / api.md §7, Issue #24). —
    rate_limit_enabled: bool = True
    rl_magic_link_ip_per_hour: int = 5
    rl_magic_link_mail_per_hour: int = 3
    rl_magic_link_verify_ip_per_hour: int = 20
    rl_applications_ip_per_hour: int = 10

    @property
    def altcha_enabled(self) -> bool:
        """Altcha-Verifikation nur aktiv, wenn ein HMAC-Secret gesetzt ist."""
        return bool(self.altcha_hmac_secret)

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
