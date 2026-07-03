"""Application settings from `.env` (pydantic-settings).

Required secrets have no default: if missing, `load_settings` raises a clear
`SettingsError` at startup instead of a raw pydantic ValidationError. See
`deploy/.env.example` for layout and names.
"""

import logging
from functools import lru_cache
from typing import Any

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Minimum length for signing/client secrets (no weak secrets).
_MIN_SECRET_LEN = 16

_log = logging.getLogger("app.settings")


class SettingsError(RuntimeError):
    """Clear startup error for missing/invalid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Identity / operation.
    app_name: str = "Antragsplattform API"
    app_version: str = "0.0.2"
    environment: str = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost"

    # Hardening switch (fail-safe). ``environment`` defaults to "development" for
    # DEV ergonomics; so production-critical guards (invoice AV fail-closed, proxy
    # spoofing guard) do not silently disable when someone forgets to set
    # ENVIRONMENT=production, this switch defaults ON. See ``strict_security_enabled``.
    strict_security: bool = True

    # Required secrets (no default; minimum length enforced).
    database_url: str
    session_secret: str = Field(min_length=_MIN_SECRET_LEN)
    magic_link_secret: str = Field(min_length=_MIN_SECRET_LEN)

    # Reverse proxy: narrow, never "*". In production "*" is forbidden (X-Forwarded-*
    # could otherwise be spoofed by any source) -> SettingsError.
    forwarded_allow_ips: str = "127.0.0.1"

    # CSRF (double-submit). Protects cookie-authenticated writes; bearer-token
    # requests are exempt. Names follow the Angular default (HttpClient reads
    # `XSRF-TOKEN`, sends `X-XSRF-TOKEN`) so the FE interceptor works unchanged.
    csrf_enabled: bool = True
    csrf_cookie_name: str = "XSRF-TOKEN"
    csrf_header_name: str = "X-XSRF-TOKEN"

    # CORS off by default (no cross-origin).
    cors_allow_origins: list[str] = []

    # Optional infra.
    redis_url: str = "redis://redis:6379/0"
    db_migration_url: str | None = None

    # OIDC / Keycloak. Without full config OIDC is off (login/callback -> 503);
    # magic-link stays usable independently.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    oidc_redirect_url: str | None = None
    oidc_scopes: str = "openid email profile"
    oidc_groups_claim: str = "groups"
    oidc_post_logout_redirect_url: str | None = None

    # Bootstrap admins. Comma-separated OIDC `sub` and/or email. On OIDC login and
    # at startup the matched principals are idempotently granted the `admin` role.
    # Prevents lockout of a fresh real OIDC install (without a mock nobody would
    # hold `admin.*` and thus could not assign roles). Empty = off.
    bootstrap_admin_subjects: str = ""
    bootstrap_admin_emails: str = ""

    @property
    def bootstrap_admin_subject_set(self) -> set[str]:
        """OIDC `sub`s from `BOOTSTRAP_ADMIN_SUBJECTS` (comma-separated, trimmed)."""
        return {s.strip() for s in self.bootstrap_admin_subjects.split(",") if s.strip()}

    @property
    def bootstrap_admin_email_set(self) -> set[str]:
        """Emails from `BOOTSTRAP_ADMIN_EMAILS` (comma-separated, trimmed, lowercased)."""
        return {
            e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()
        }

    # Session/applicant cookie (HttpOnly+Secure+SameSite=Lax).
    session_cookie_name: str = "ap_session"
    applicant_cookie_name: str = "ap_applicant"
    oidc_tx_cookie_name: str = "ap_oidc_tx"
    session_ttl_hours: int = 12
    # Applicant (magic-link) session: server-side (``applicant_session`` table),
    # opaque signed ``sid``. Deliberately decoupled from ``session_ttl_hours`` so the
    # applicant window can be tuned independently (shorter = smaller replay window).
    applicant_session_ttl_hours: int = 12
    cookie_secure: bool = True

    # OAuth2 AS for native/MCP clients (browser grant + PKCE, RFC 7636). Public
    # client (no secret); loopback redirects only. Tokens are opaque + scoped (see
    # app.modules.auth.oauth). Active only when OIDC is configured.
    oauth_mcp_client_id: str = "antragsplattform-mcp"
    oauth_tx_cookie_name: str = "ap_oauth_tx"
    oauth_code_ttl_seconds: int = 300  # authorization code: 5 min
    oauth_access_ttl_seconds: int = 3600  # access token: 1 h
    oauth_refresh_ttl_seconds: int = 60 * 60 * 24 * 30  # refresh token: 30 d
    # Source dir of the MCP package for the self-service download; None -> relative
    # to the repo root (`<repo>/mcp`). In containers without a source tree -> 404.
    mcp_package_dir: str | None = None

    # Magic-link lifetimes.
    magic_link_edit_ttl_days: int = 7
    magic_link_action_ttl_minutes: int = 15

    # Mail/SMTP. Without `smtp_host` sending is off (worker logs + drops instead of
    # sending) so DEV/tests run without a real MTA. The password is a secret and is
    # never logged.
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
    # Worker (arq) send retry: max tries + backoff base (seconds).
    mail_max_tries: int = 5
    mail_retry_backoff_seconds: int = 30

    @property
    def smtp_enabled(self) -> bool:
        """Real sending only with `smtp_host` set; otherwise worker no-op (DEV/test)."""
        return bool(self.smtp_host)

    # Object storage / MinIO. Without `minio_endpoint` upload is off (POST
    # /attachments -> 503); DEV/contract CI run without a bucket. The keys are
    # secrets and are never logged.
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "attachments"
    minio_secure: bool = False  # TLS to the MinIO API (usually plain HTTP internally)
    # Upload cap (data model: CHECK(size <= 10485760)) + signed-URL lifetime.
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_url_ttl_seconds: int = 300

    # ClamAV. Without `clamav_host` the scan is off: uploads stay `scanned=false`
    # (quarantined, no download) — fail-closed (DEV/test).
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 60
    # Worker (arq) scan retry: max tries + backoff base (seconds).
    scan_max_tries: int = 5
    scan_retry_backoff_seconds: int = 30

    # Webhook dispatch. Delivery runs in the arq worker; the API only creates
    # ``webhook_delivery`` rows + jobs. The SSRF guard is always active
    # (private/loopback/link-local/metadata blocked); the optional host allowlist
    # additionally restricts targets (empty = any public host). The per-webhook
    # ``secret`` is never logged.
    webhook_timeout_seconds: float = 10.0
    webhook_max_tries: int = 5
    webhook_retry_backoff_seconds: int = 30
    # Optional host allowlist for webhook targets. Empty = any public host (the SSRF
    # guard stays active regardless). Should be set in production; ``_strict_security_
    # warnings`` warns loudly when it is empty under hardening.
    webhook_host_allowlist: list[str] = []

    # Delegation. Vote delegation is subject to bylaws approval and defaults OFF: a
    # delegation may transfer roles/rights, but `delegateVoting=true` is only
    # accepted (else 422) once the operator explicitly enables vote delegation.
    # Pure rights delegation stays free.
    delegation_voting_enabled: bool = False
    # Local timezone for meeting times (`meeting.date`/`start_time` stored naive):
    # basis of the delegation deadline.
    local_timezone: str = "Europe/Berlin"

    # Deadlines/cron. Lead time for the `deadline_approaching` reminder: sent once
    # `due_at - lead <= now < due_at` (default 24 h).
    deadline_reminder_lead_minutes: int = 1440

    # FinTS bank reconciliation. Online-banking fetch (PIN/TAN) to reconcile real
    # transactions with bookings. Without ``fints_enc_key`` the feature is off
    # (endpoints -> 503): the bank PIN is held encrypted at rest (Fernet, derived
    # from this secret), so the key is required once FinTS is used.
    # ``fints_product_id`` is the product id registered with the Deutsche
    # Kreditwirtschaft (mandatory for production access since 2019); without it the
    # lib uses its default id (DEV/sandbox, possibly rejected by real banks). The
    # secret/PIN are never logged.
    fints_enc_key: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    fints_product_id: str | None = None
    # Cap on the fetch window (days) per sync. Larger windows force a fresh SCA at
    # many banks; 90 days = PSD2 comfort window.
    fints_max_days: int = 90
    # Lifetime of a pending TAN session (between start-sync and TAN entry).
    fints_tan_session_ttl_seconds: int = 600
    # Lock cooldown: after a bank lock (FinTS 3938) or signature/PIN rejection (9340
    # etc.) the service refuses any further sync for this bookkeeper+account for this
    # many minutes. Guards against self-inflicted lock escalation (3 failed attempts
    # -> full lock). The bank-side lock itself may last longer and may only be lifted
    # via the bank (online-banking unlock/hotline).
    fints_lock_cooldown_minutes: int = 30

    @property
    def storage_enabled(self) -> bool:
        """Object storage is active only when a MinIO endpoint is set."""
        return bool(self.minio_endpoint)

    @property
    def fints_enabled(self) -> bool:
        """FinTS is active only when an encryption key is set (the bank PIN must never
        be persisted unencrypted)."""
        return bool(self.fints_enc_key)

    @property
    def clamav_enabled(self) -> bool:
        """ClamAV scan is active only when a clamd host is set."""
        return bool(self.clamav_host)

    # pytex render container. `api` -> `pytex` only `/render`. `PYTEX_URL` points at
    # the internal container; `trusted` enables the tectonic bundle (app-generated,
    # first-party documents). The render can be slow (first build fetches the
    # bundle) -> generous timeout.
    pytex_url: str = "http://pytex:8099"
    pytex_trust: str = "trusted"
    pytex_timeout_seconds: int = 120
    # Worker (arq) PDF render retry: max tries + backoff base (seconds).
    pdf_max_tries: int = 4
    pdf_retry_backoff_seconds: int = 30
    # Lifetime of the signed result URL (GET /jobs/{id}).
    pdf_url_ttl_seconds: int = 300

    # Application payload cap (public POST /applications, anti-DoS). Applies to the
    # serialized field values (`data`) and as a Content-Length bound; above -> 413.
    # 64 KiB covers every real form.
    max_application_payload_bytes: int = 65536

    # Body cap of the auth POSTs (magic-link / verify, anti-DoS). Auth bodies are
    # tiny (mail/token) -> tight bound; above -> 413.
    max_auth_payload_bytes: int = 8192

    # Altcha (proof-of-work). Without a secret verification is off (dev/test); the
    # field is then only passed through. The secret is shared with the Altcha
    # sidecar (deploy/.env: ALTCHA_HMAC_SECRET).
    altcha_hmac_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    altcha_max_number: int = 100_000
    altcha_challenge_ttl_seconds: int = 300

    # Rate limiting (sliding window).
    rate_limit_enabled: bool = True
    rl_magic_link_ip_per_hour: int = 5
    rl_magic_link_mail_per_hour: int = 3
    rl_magic_link_verify_ip_per_hour: int = 20
    rl_applications_ip_per_hour: int = 10
    rl_attachments_per_hour: int = 30  # POST /attachments: 30/h/applicant
    # FinTS sync/TAN/import: per principal/h. Curbs SSRF port-scan attempts + bank-PIN
    # lockout abuse via repeated syncs.
    rl_fints_per_hour: int = 60
    # Default limit on all writing endpoints: IP key, generous — catches endpoints
    # without their own (stricter) limit, defense-in-depth.
    rl_default_write_per_hour: int = 100

    @model_validator(mode="after")
    def _no_wildcard_proxy_in_prod(self) -> "Settings":
        """`production` must not set `FORWARDED_ALLOW_IPS` to "*".

        "*" would make uvicorn trust any X-Forwarded-* source -> IP spoofing
        (rate-limit bypass, wrong audit IP). Outside `production` (dev/CI/container
        smoke) "*" stays allowed."""
        if self.environment == "production" and "*" in self.forwarded_allow_ips:
            raise ValueError(
                'FORWARDED_ALLOW_IPS must not be "*" in production (security.md §3).'
            )
        return self

    @property
    def is_production(self) -> bool:
        """Is the app running in the production profile (``ENVIRONMENT=production``)?"""
        return self.environment == "production"

    @property
    def strict_security_enabled(self) -> bool:
        """Should the strict hardening guards apply (fail-safe)?

        True as soon as ``strict_security`` is on OR ``environment == "production"``.
        Consumers (invoice AV fail-closed, proxy guard) should query this instead of a
        bare ``environment == "production"`` check, so a forgotten ENVIRONMENT=production
        does not silently disable the guards."""
        return self.strict_security or self.is_production

    @model_validator(mode="after")
    def _strict_security_warnings(self) -> "Settings":
        """Warn loudly when the configuration stays weak under hardening.

        Does NOT abort startup (DEV ergonomics / backward compat), but makes visible
        in the log that production-critical guards are affected."""
        if not self.is_production:
            _log.warning(
                "ENVIRONMENT=%r (not 'production'): production-only security guards "
                "may be disabled. Set ENVIRONMENT=production for hardened deployments "
                "(see deploy/.env.example).",
                self.environment,
            )
        if self.strict_security_enabled and not self.webhook_host_allowlist:
            _log.warning(
                "WEBHOOK_ALLOWLIST is empty under strict security: webhook targets are "
                "only restricted by the SSRF guard, not pinned to known hosts "
                "(security.md §5)."
            )
        if self.storage_enabled and not self.clamav_enabled:
            _log.warning(
                "MINIO storage is enabled but CLAMAV is disabled: uploaded attachments "
                "are stored and enqueued for scanning, but the worker has no scanner and "
                "leaves them scanned=False — downloads stay quarantined (409) forever. "
                "Configure CLAMAV_HOST or disable MINIO storage (#AUD-071)."
            )
        return self

    @property
    def altcha_enabled(self) -> bool:
        """Altcha verification is active only when an HMAC secret is set."""
        return bool(self.altcha_hmac_secret)

    @property
    def oidc_enabled(self) -> bool:
        """OIDC is active only when all required parameters are set."""
        return bool(
            self.oidc_issuer
            and self.oidc_client_id
            and self.oidc_client_secret
            and self.oidc_redirect_url
        )


def load_settings(**overrides: Any) -> Settings:
    """Load settings; missing required fields -> `SettingsError` with a clear message."""
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
