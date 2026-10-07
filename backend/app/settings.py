"""Application settings from `.env` (pydantic-settings).

A required secret has no default. If a secret is missing, `load_settings` raises a
clear `SettingsError` at startup instead of a raw pydantic ValidationError. See
`deploy/.env.example` for the layout and the names.
"""

import json
import logging
from functools import lru_cache
from typing import Annotated, Any

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Minimum length for signing/client secrets (no weak secrets).
_MIN_SECRET_LEN = 16

_log = logging.getLogger("app.settings")

# A list that an operator writes as a comma-separated string in `.env`.
#
# `NoDecode` turns the JSON decoding of pydantic-settings off for the field. Without
# it, `HOSTS=a,b` is not valid JSON and the app aborts the start with a
# `SettingsError`. The `_split_csv` validator below accepts both the comma format of
# `deploy/.env.example` and the older JSON list.
CsvList = Annotated[list[str], NoDecode]


def _split_csv(value: Any) -> Any:
    """Turn a comma-separated (or JSON) env value into a list of trimmed entries."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    return [part.strip() for part in text.split(",") if part.strip()]


class SettingsError(RuntimeError):
    """Clear startup error for missing/invalid configuration."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Antragsplattform API"
    app_version: str = "0.0.2"
    environment: str = "development"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost"

    # Hardening switch (fail-safe). `environment` defaults to "development" for DEV
    # ergonomics. This switch defaults ON, so the production-critical guards (invoice
    # AV fail-closed, proxy spoofing guard) stay active even when someone forgets to
    # set ENVIRONMENT=production. See `strict_security_enabled`.
    strict_security: bool = True

    # Required secrets. They have no default, and the model enforces a minimum length.
    database_url: str
    session_secret: str = Field(min_length=_MIN_SECRET_LEN)
    magic_link_secret: str = Field(min_length=_MIN_SECRET_LEN)

    # Reverse proxy: keep it narrow, never "*". Production forbids "*", because any
    # source could then spoof X-Forwarded-*. The validator raises SettingsError.
    forwarded_allow_ips: str = "127.0.0.1"

    # CSRF double-submit. It protects cookie-authenticated writes. A bearer-token
    # request stays exempt. The names follow the Angular default (HttpClient reads
    # `XSRF-TOKEN` and sends `X-XSRF-TOKEN`), so the FE interceptor works unchanged.
    csrf_enabled: bool = True
    csrf_cookie_name: str = "XSRF-TOKEN"
    csrf_header_name: str = "X-XSRF-TOKEN"

    # The empty default keeps cross-origin access off. Comma-separated in `.env`.
    cors_allow_origins: CsvList = []

    redis_url: str = "redis://redis:6379/0"
    db_migration_url: str | None = None

    # OIDC, against any IdP that serves an OpenID discovery document. The endpoints come
    # from `{oidc_issuer}/.well-known/openid-configuration`. Set `oidc_issuer` exactly as
    # the IdP writes it into the `iss` claim, trailing slash included: authentik uses
    # `https://<host>/application/o/<slug>/`, Keycloak `https://<host>/realms/<realm>`.
    # Without the full config, OIDC stays off and login and callback answer 404. The
    # magic link stays usable on its own.
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    oidc_redirect_url: str | None = None
    oidc_scopes: str = "openid email profile"
    oidc_groups_claim: str = "groups"
    oidc_post_logout_redirect_url: str | None = None

    # Bootstrap admins. Comma-separated OIDC `sub` values and/or emails. On OIDC login
    # and at startup the app grants the matched principals the `admin` role, and it
    # does so idempotently. This prevents a lockout on a fresh real OIDC install, where
    # nobody holds `admin.*` without a mock and thus nobody could assign a role. An
    # empty value turns the bootstrap off.
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

    # Session and applicant cookie (HttpOnly + Secure + SameSite=Lax).
    session_cookie_name: str = "ap_session"
    applicant_cookie_name: str = "ap_applicant"
    oidc_tx_cookie_name: str = "ap_oidc_tx"
    session_ttl_hours: int = 12
    # Applicant session from a magic link: server-side (`applicant_session` table)
    # with an opaque signed `sid`. It is decoupled from `session_ttl_hours` on
    # purpose, so the applicant window can be tuned on its own. A shorter window
    # narrows the replay window.
    applicant_session_ttl_hours: int = 12
    cookie_secure: bool = True
    # Device token of a guest of a public meeting (#17): HttpOnly, SameSite=Strict, path
    # `/api/public/meetings`. The server keeps only its SHA-256 hash. The token stops
    # working when the meeting closes; the cookie lifetime is a safety bound.
    guest_cookie_name: str = "mg_token"
    guest_cookie_ttl_hours: int = 24

    # OAuth2 AS for native and MCP clients (browser grant + PKCE, RFC 7636). It is
    # a public client with no secret, and it allows loopback redirects only. The
    # tokens are opaque and scoped (see `app.modules.auth.oauth`). It is active only
    # when OIDC is configured.
    oauth_mcp_client_id: str = "antragsplattform-mcp"
    oauth_tx_cookie_name: str = "ap_oauth_tx"
    oauth_code_ttl_seconds: int = 300
    oauth_access_ttl_seconds: int = 3600
    oauth_refresh_ttl_seconds: int = 60 * 60 * 24 * 30
    # Source directory of the MCP package for the self-service download. None means
    # relative to the repo root (`<repo>/mcp`). A container without a source tree
    # answers 404.
    mcp_package_dir: str | None = None

    # The magic-link lifetime is no environment setting any more. It lives in
    # `guest_application_settings.link_ttl_days` (admin UI, default: no expiry). An old
    # `.env` that still sets `MAGIC_LINK_EDIT_TTL_DAYS` or
    # `MAGIC_LINK_ACTION_TTL_MINUTES` keeps starting, because `extra="ignore"` drops
    # the keys.

    # Mail/SMTP. Without `smtp_host` the app sends nothing. The worker logs the mail
    # and drops it, so DEV and the tests run without a real MTA. The password is a
    # secret and never reaches the log.
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
    # Worker retry for arq send jobs: maximum tries and the backoff base in seconds.
    mail_max_tries: int = 5
    mail_retry_backoff_seconds: int = 30

    @property
    def smtp_enabled(self) -> bool:
        """Report whether the worker really sends mail.

        Real sending needs `smtp_host`. Without it the worker logs the mail and
        drops it, which suits DEV and the tests.
        """
        return bool(self.smtp_host)

    # Object storage / MinIO. Without `minio_endpoint` upload is off, and POST
    # /attachments answers 503. DEV and contract CI run without a bucket. The keys
    # are secrets and never reach the log.
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "attachments"
    minio_secure: bool = False  # TLS to the MinIO API (usually plain HTTP internally)
    # Upload cap (the data model holds CHECK(size <= 10485760)) and signed-URL lifetime.
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_url_ttl_seconds: int = 300
    # Draft uploads of the wizard (Z4, POST /apply/attachments). Each upload moves the
    # end of all drafts of the token to now + this many days. One token holds at most
    # this many files and bytes.
    attachment_draft_ttl_days: int = Field(default=7, ge=1)
    attachment_draft_max_files: int = Field(default=20, ge=1)
    attachment_draft_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1)

    # Whole-platform backups (/admin/backups). An archive holds the pg_dump plus a
    # mirror of the attachment bucket, age-encrypted, in its own MinIO bucket. Without
    # `backup_age_recipient` the feature is off and every route answers 503. DEV and
    # contract CI run without it.
    backup_bucket: str = "backups"
    # age public key. The API encrypts every archive to it and can do nothing else
    # with it.
    backup_age_recipient: str | None = None
    # Path to the age private key inside the container, mounted read-only. A restore
    # and a download of a decrypted archive need it. Keep the disaster-recovery key
    # that lives off host SEPARATE from this one: a stack compromise then exposes only
    # the archives that the app itself wrote.
    backup_age_identity_file: str | None = None
    # Retention: keep this many archives and drop the oldest beyond it. A pinned
    # archive never counts and is never pruned. 0 disables the pruning.
    backup_retention_count: int = 14
    # Cap for an uploaded archive (import) and for the pg_dump/restore subprocess.
    backup_max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    backup_subprocess_timeout_seconds: int = 3600

    # ClamAV. Without `clamav_host` the scan is off. An upload then stays
    # `scanned=false`, which quarantines it and blocks the download. This is
    # fail-closed (DEV/test).
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 60
    # Worker retry for arq scan jobs: maximum tries and the backoff base in seconds.
    scan_max_tries: int = 5
    scan_retry_backoff_seconds: int = 30

    # Webhook dispatch. Delivery runs in the arq worker. The API only creates
    # `webhook_delivery` rows and jobs. The SSRF guard is always active and blocks
    # private, loopback, link-local and metadata targets. The optional host allowlist
    # restricts the targets further (empty = any public host). The per-webhook
    # `secret` never reaches the log.
    webhook_timeout_seconds: float = 10.0
    webhook_max_tries: int = 5
    webhook_retry_backoff_seconds: int = 30
    # Optional host allowlist for webhook targets. Empty = any public host, and the
    # SSRF guard stays active either way. Set it in production. Under hardening
    # `_strict_security_warnings` warns loudly when it is empty.
    #
    # `deploy/.env.example` named this `WEBHOOK_ALLOWLIST` up to and including v0.0.2.
    # `extra="ignore"` dropped that name without a word, so a deployment that copied
    # the example ran with an EMPTY allowlist and could not silence the warning. The
    # alias keeps such a deployment working. `WEBHOOK_HOST_ALLOWLIST` is the canonical
    # name and wins when both are set.
    webhook_host_allowlist: CsvList = Field(
        default=[],
        validation_alias=AliasChoices("webhook_host_allowlist", "webhook_allowlist"),
    )

    @field_validator("cors_allow_origins", "webhook_host_allowlist", mode="before")
    @classmethod
    def _accept_csv_lists(cls, value: Any) -> Any:
        """Accept a comma-separated list, as `deploy/.env.example` documents it."""
        return _split_csv(value)

    # Delegation. Vote delegation needs bylaws approval and defaults to OFF. A
    # delegation may transfer roles and rights. The server accepts
    # `delegateVoting=true` only after the operator enables vote delegation, and it
    # answers 422 otherwise. Pure rights delegation stays free.
    delegation_voting_enabled: bool = False
    # Local timezone for meeting times. `meeting.date` and `start_time` are naive, and
    # this zone is the basis of the delegation deadline.
    local_timezone: str = "Europe/Berlin"

    # Deadlines/cron. Lead time for the `deadline_approaching` reminder. The app sends
    # it once `due_at - lead <= now < due_at` holds (default 24 h).
    deadline_reminder_lead_minutes: int = 1440

    @property
    def storage_enabled(self) -> bool:
        """Object storage is active only when a MinIO endpoint is set."""
        return bool(self.minio_endpoint)

    @property
    def backup_enabled(self) -> bool:
        """Backups need object storage and the age recipient the API encrypts to."""
        return bool(self.minio_endpoint) and bool(self.backup_age_recipient)

    @property
    def backup_restore_enabled(self) -> bool:
        """A restore also needs the private key, so the API can decrypt an archive."""
        return self.backup_enabled and bool(self.backup_age_identity_file)

    @property
    def clamav_enabled(self) -> bool:
        """ClamAV scan is active only when a clamd host is set."""
        return bool(self.clamav_host)

    # typst render container. `api` and `worker` call only `/render` on `typst`.
    # `TYPST_URL` points at the internal container. A protocol renders in well under a
    # second; the timeout leaves room for a long protocol on a busy host.
    typst_url: str = "http://typst:8099"
    typst_timeout_seconds: int = 60
    # Worker retry for arq PDF render jobs: maximum tries and backoff base in seconds.
    pdf_max_tries: int = 4
    pdf_retry_backoff_seconds: int = 30

    # Application payload cap for the public POST /applications (anti-DoS). It applies
    # to the serialized field values (`data`) and as a Content-Length bound. A larger
    # body gets 413. 64 KiB covers every real form.
    max_application_payload_bytes: int = 65536

    # Body cap of the auth POSTs (magic-link and verify, anti-DoS). An auth body holds
    # only a mail address or a token, so the bound stays tight. A larger body gets 413.
    max_auth_payload_bytes: int = 8192

    # Altcha proof-of-work. Without a secret the verification is off (dev/test), and
    # the field only passes through. The Altcha sidecar shares this secret
    # (deploy/.env: ALTCHA_HMAC_SECRET).
    altcha_hmac_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    altcha_max_number: int = 100_000
    altcha_challenge_ttl_seconds: int = 300

    # Rate limiting (sliding window).
    rate_limit_enabled: bool = True
    rl_magic_link_ip_per_hour: int = 5
    rl_magic_link_mail_per_hour: int = 3
    rl_magic_link_verify_ip_per_hour: int = 20
    rl_applications_ip_per_hour: int = 10
    rl_attachments_per_hour: int = 30  # POST /attachments: 30 per hour per applicant
    # Default limit on all writing endpoints. It keys on the IP and stays generous. It
    # catches an endpoint without its own stricter limit (defense in depth).
    rl_default_write_per_hour: int = 100
    # GET /principals/{id}/avatar: requests per hour per logged-in principal. A page
    # with a long member list asks for one avatar per row, so the limit stays generous.
    rl_avatar_per_hour: int = 1200
    # GET /applications/on-behalf/applicants: searches per hour per principal (#11). The
    # search discloses names and e-mails of accounts; the dialog searches while the user
    # types (debounced), so the limit stays generous for a person and stops a scraper.
    rl_applicant_search_per_hour: int = 300
    # Public meeting (#17). Many guests often share one IP (the campus NAT), so the
    # per-IP limits stay generous: ALTCHA is the main guard of the join. The join
    # counts per IP and per join code. The reads of the public routes (the head of the
    # meeting, the own state) count per IP. The writes of an admitted or waiting guest
    # (name, leave, ballot) count per guest. The public routes are outside the default
    # write limit per IP, because each one has its own limit.
    rl_public_join_ip_per_hour: int = 120
    rl_public_join_code_per_hour: int = 400
    rl_public_meeting_read_ip_per_hour: int = 3000
    rl_public_guest_write_per_hour: int = 120
    # Public protocols page: the reads of the list and the detail, and the PDF
    # downloads, per IP. Many readers share the campus NAT, so the limits stay
    # generous; they stop a scraper that walks every protocol.
    rl_public_protocols_ip_per_hour: int = 3000
    rl_public_protocol_pdf_ip_per_hour: int = 600

    # Gravatar proxy (GET /principals/{id}/avatar). The API fetches the image from the
    # fixed host gravatar.com and keeps the result in Redis. A found image and a missing
    # one (404) stay for `gravatar_cache_ttl_seconds`. A failed fetch (timeout, 5xx)
    # stays only for `gravatar_error_ttl_seconds`, so a short outage heals itself. The
    # admin switch `gravatarEnabled` in the site config turns the proxy off.
    # `gravatar_timeout_seconds` is one total deadline for the DNS lookup, the connect
    # and all reads of one fetch.
    gravatar_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    gravatar_cache_ttl_seconds: int = Field(default=86_400, ge=60)
    gravatar_error_ttl_seconds: int = Field(default=300, ge=1)

    @model_validator(mode="after")
    def _no_wildcard_proxy_in_prod(self) -> "Settings":
        """Refuse `FORWARDED_ALLOW_IPS` set to "*" in `production`.

        With "*" uvicorn trusts any X-Forwarded-* source. An attacker can then spoof
        the client IP, bypass the rate limit and poison the audit IP. Outside
        `production` (dev, CI, container smoke) "*" stays allowed.

        Raises:
            ValueError: The environment is `production` and `forwarded_allow_ips`
                contains "*".
        """
        if self.environment == "production" and "*" in self.forwarded_allow_ips:
            raise ValueError(
                'FORWARDED_ALLOW_IPS must not be "*" in production (security.md §3).'
            )
        return self

    @property
    def is_production(self) -> bool:
        """Report whether the app runs the production profile (`ENVIRONMENT=production`)."""
        return self.environment == "production"

    @property
    def strict_security_enabled(self) -> bool:
        """Report whether the strict hardening guards apply (fail-safe).

        The value is True as soon as `strict_security` is on OR `environment` equals
        "production". A consumer such as the invoice AV fail-closed path or the proxy
        guard must query this instead of a bare `environment == "production"` check.
        A forgotten ENVIRONMENT=production then does not silently disable the guards.
        """
        return self.strict_security or self.is_production

    @model_validator(mode="after")
    def _strict_security_warnings(self) -> "Settings":
        """Warn loudly when the configuration stays weak under hardening.

        The validator does NOT abort startup, to keep DEV ergonomics and backward
        compatibility. It only makes visible in the log that production-critical
        guards are affected.
        """
        if not self.is_production:
            _log.warning(
                "ENVIRONMENT=%r (not 'production'): production-only security guards "
                "may be disabled. Set ENVIRONMENT=production for hardened deployments "
                "(see deploy/.env.example).",
                self.environment,
            )
        if self.strict_security_enabled and not self.webhook_host_allowlist:
            _log.warning(
                "WEBHOOK_HOST_ALLOWLIST is empty under strict security: webhook targets are "
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
    """Load the settings.

    Raises:
        SettingsError: A required field is missing, or the configuration is invalid.
            The message names the fields.
    """
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
