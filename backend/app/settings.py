"""Anwendungs-Settings aus `.env` (Pydantic-Settings).

Pflicht-Secrets ohne Default → fehlen sie, wirft `load_settings` einen klaren
`SettingsError` (statt einer rohen Pydantic-ValidationError) beim Start.
Layout/Namen siehe `deploy/.env.example`.
"""

from functools import lru_cache
from typing import Any

from pydantic import Field, ValidationError, model_validator
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

    # — Reverse-Proxy (security.md §3): eng, nie "*". In `production` ist "*" verboten
    #   (X-Forwarded-* dürfte sonst von jeder Quelle gespooft werden) → SettingsError. —
    forwarded_allow_ips: str = "127.0.0.1"

    # — CSRF (Double-Submit, security.md §10). Schützt cookie-authentifizierte
    #   schreibende Requests; Bearer-Token-Requests sind ausgenommen. Namen folgen dem
    #   Angular-Default (HttpClient liest `XSRF-TOKEN`, sendet `X-XSRF-TOKEN`), damit der
    #   FE-Interceptor (frontend/.../auth.interceptor.ts) ohne Änderung greift. —
    csrf_enabled: bool = True
    csrf_cookie_name: str = "XSRF-TOKEN"
    csrf_header_name: str = "X-XSRF-TOKEN"

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

    # — Bootstrap-Admins (#70). Kommagetrennt: OIDC-`sub` und/oder E-Mail. Beim
    #   OIDC-Login (Callback) **und** beim Startup wird den gematchten Principals
    #   idempotent die `admin`-Rolle zugewiesen. Verhindert die Selbstaussperrung
    #   einer frischen, echten OIDC-Installation (ohne Mock hätte niemand `admin.*`
    #   und könnte daher auch keine Rollen vergeben). Leer = aus. —
    bootstrap_admin_subjects: str = ""
    bootstrap_admin_emails: str = ""

    @property
    def bootstrap_admin_subject_set(self) -> set[str]:
        """OIDC-`sub`s aus `BOOTSTRAP_ADMIN_SUBJECTS` (kommagetrennt, getrimmt)."""
        return {s.strip() for s in self.bootstrap_admin_subjects.split(",") if s.strip()}

    @property
    def bootstrap_admin_email_set(self) -> set[str]:
        """E-Mails aus `BOOTSTRAP_ADMIN_EMAILS` (kommagetrennt, getrimmt, lowercase)."""
        return {
            e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()
        }

    # — Session-/Applicant-Cookie (security.md §1/§2: HttpOnly+Secure+SameSite=Lax) —
    session_cookie_name: str = "ap_session"
    applicant_cookie_name: str = "ap_applicant"
    oidc_tx_cookie_name: str = "ap_oidc_tx"
    session_ttl_hours: int = 12
    cookie_secure: bool = True

    # — Magic-Link-Laufzeiten (security.md §1) —
    magic_link_edit_ttl_days: int = 7
    magic_link_action_ttl_minutes: int = 15

    # — Mail/SMTP (T-18). Ohne `smtp_host` ist der Versand »aus« (Worker loggt +
    #   verwirft statt zu senden) — DEV/Tests laufen ohne echten MTA. Das Passwort
    #   ist ein Secret und wird **nie** geloggt. —
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: int = 30
    mail_from: str = "noreply@antragsplattform.local"
    mail_from_name: str = "Antragsplattform"
    mail_default_lang: str = "de"
    # Versand-Retry im Worker (arq): max. Versuche + Backoff-Basis (Sekunden).
    mail_max_tries: int = 5
    mail_retry_backoff_seconds: int = 30

    @property
    def smtp_enabled(self) -> bool:
        """Echter Versand nur bei gesetztem `smtp_host`; sonst Worker-No-op (DEV/Test)."""
        return bool(self.smtp_host)

    # — Object-Storage / MinIO (T-13, security.md §6). Ohne `minio_endpoint` ist der
    #   Upload »aus« (POST /attachments → 503); DEV/Contract-CI laufen ohne Bucket. Die
    #   Keys sind Secrets und werden **nie** geloggt. —
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "attachments"
    minio_secure: bool = False  # TLS zur MinIO-API (intern i. d. R. plain HTTP)
    # Upload-Schranke (data-model: CHECK(size <= 10485760)) + Lebensdauer signierter URLs.
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_url_ttl_seconds: int = 300

    # — ClamAV (T-13, security.md §6). Ohne `clamav_host` ist der Scan »aus«: Uploads
    #   bleiben `scanned=false` (Quarantäne, kein Download) — fail-closed (DEV/Test). —
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 60
    # Scan-Retry im Worker (arq): max. Versuche + Backoff-Basis (Sekunden).
    scan_max_tries: int = 5
    scan_retry_backoff_seconds: int = 30

    # — Webhook-Dispatch (T-19, security.md §5). Versand läuft im arq-Worker; die API
    #   legt nur ``webhook_delivery``-Zeilen + Jobs an. SSRF-Guard ist **immer** aktiv
    #   (private/loopback/link-local/metadata blockiert); die optionale Host-Allowlist
    #   schränkt zusätzlich auf erlaubte Ziel-Hosts ein (leer = jeder *öffentliche*
    #   Host). Das pro-Webhook-``secret`` wird **nie** geloggt. —
    webhook_timeout_seconds: float = 10.0
    webhook_max_tries: int = 5
    webhook_retry_backoff_seconds: int = 30
    webhook_host_allowlist: list[str] = []

    # --- Deadlines/Cron (T-44, flows §9.4) ---------------------------------- #
    #   Vorlauf für die `deadline_approaching`-Erinnerung: gesendet, sobald
    #   `due_at - lead <= now < due_at` (Default 24 h).
    deadline_reminder_lead_minutes: int = 1440

    @property
    def storage_enabled(self) -> bool:
        """Object-Storage nur aktiv, wenn ein MinIO-Endpunkt gesetzt ist."""
        return bool(self.minio_endpoint)

    @property
    def clamav_enabled(self) -> bool:
        """ClamAV-Scan nur aktiv, wenn ein clamd-Host gesetzt ist."""
        return bool(self.clamav_host)

    # — pytex-Render-Container (T-20/T-21, deployment §3). `api`→`pytex` nur `/render`.
    #   `PYTEX_URL` zeigt auf den internen Container; `trusted` schaltet das
    #   tectonic-Bundle frei (App-generierte, erst­partei­liche Dokumente). Der Render
    #   kann dauern (Erst-Build lädt das Bundle) → großzügiger Timeout. —
    pytex_url: str = "http://pytex:8099"
    pytex_trust: str = "trusted"
    pytex_timeout_seconds: int = 120
    # PDF-Render-Retry im Worker (arq): max. Versuche + Backoff-Basis (Sekunden).
    pdf_max_tries: int = 4
    pdf_retry_backoff_seconds: int = 30
    # Lebensdauer der signierten Ergebnis-URL (GET /jobs/{id}).
    pdf_url_ttl_seconds: int = 300

    # — Nextcloud-WebDAV-Export (T-20, deployment §3). Optional: ohne vollständige
    #   Config bleibt der Export »aus« (PDF liegt dann nur in MinIO, kein Crash). Das
    #   App-Passwort ist ein Secret und wird **nie** geloggt. —
    nextcloud_webdav_url: str | None = None
    nextcloud_user: str | None = None
    nextcloud_app_password: str | None = None
    nextcloud_base_path: str = "Antraege/"
    nextcloud_timeout_seconds: int = 60

    @property
    def nextcloud_enabled(self) -> bool:
        """WebDAV-Export nur aktiv, wenn URL + Credentials vollständig gesetzt sind."""
        return bool(
            self.nextcloud_webdav_url
            and self.nextcloud_user
            and self.nextcloud_app_password
        )

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
    rl_attachments_per_hour: int = 30  # POST /attachments: 30/Std/applicant (api.md §7)
    # Default-Limit auf allen *schreibenden* Endpunkten (api.md §7): IP-Schlüssel,
    # großzügig → fängt Endpunkte ohne eigenes (strengeres) Limit ab, Defense-in-Depth.
    rl_default_write_per_hour: int = 100

    @model_validator(mode="after")
    def _no_wildcard_proxy_in_prod(self) -> "Settings":
        """`production` darf `FORWARDED_ALLOW_IPS` nicht auf "*" setzen (security.md §3).

        "*" würde uvicorn jede X-Forwarded-*-Quelle vertrauen lassen → IP-Spoofing
        (Rate-Limit-Bypass, falsche Audit-IP). Außerhalb von `production` (Dev/CI/
        Container-Smoke) bleibt "*" erlaubt."""
        if self.environment == "production" and "*" in self.forwarded_allow_ips:
            raise ValueError(
                'FORWARDED_ALLOW_IPS must not be "*" in production (security.md §3).'
            )
        return self

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
