"""Application settings from `.env` (pydantic-settings).

A required secret has no default. If a secret is missing, `load_settings` raises a
clear `SettingsError` at startup instead of a raw pydantic ValidationError. See
`deploy/.env.example` for the layout and the names.

A list setting (`CsvList`) is a comma-separated string in `.env`. `NoDecode` turns the
JSON decoding of pydantic-settings off for such a field, because `HOSTS=a,b` is not
valid JSON and the app then aborts the start with a `SettingsError`. `_split_csv`
accepts both the comma format of `deploy/.env.example` and the older JSON list.

A session lifetime and a magic-link lifetime are no environment settings. They live in
`login_settings` and `guest_application_settings` (admin UI). An old `.env` that still
sets `SESSION_TTL_HOURS`, `MAGIC_LINK_EDIT_TTL_DAYS` or `MAGIC_LINK_ACTION_TTL_MINUTES`
keeps starting, because `extra="ignore"` drops the keys.
"""

import json
import logging
from functools import lru_cache
from typing import Annotated, Any

from pydantic import AliasChoices, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Minimum length of a signing or client secret.
_MIN_SECRET_LEN = 16

_log = logging.getLogger("app.settings")

CsvList = Annotated[list[str], NoDecode]


def _split_csv(value: object) -> object:
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
    """Typed configuration of the API and the worker, read from the environment.

    A field without a default is a required secret, and a secret field enforces a
    minimum length. A feature whose host or key is not set stays off.

    Hardening:
        `strict_security` defaults ON, although `environment` defaults to
        "development". The production-critical guards (invoice AV fail-closed, proxy
        spoofing guard) then stay active when someone forgets
        `ENVIRONMENT=production`. See `strict_security_enabled`.
        `forwarded_allow_ips` stays narrow, never "*": production forbids "*",
        because any source could then spoof X-Forwarded-*.

    CSRF:
        The double-submit check protects cookie-authenticated writes. A bearer-token
        request stays exempt. The names follow the Angular default (HttpClient reads
        `XSRF-TOKEN` and sends `X-XSRF-TOKEN`), so the FE interceptor works
        unchanged. The empty `cors_allow_origins` default keeps cross-origin access
        off.

    OIDC:
        Works against any IdP that serves an OpenID discovery document at
        `{oidc_issuer}/.well-known/openid-configuration`. Set `oidc_issuer` exactly
        as the IdP writes it into the `iss` claim, trailing slash included (authentik:
        `https://<host>/application/o/<slug>/`, Keycloak:
        `https://<host>/realms/<realm>`). Without the full config, OIDC stays off and
        login and callback answer 404; the magic link stays usable on its own.
        `oidc_scopes` asks for `offline_access`, because a long principal session
        checks the account at the IdP with the refresh token every
        `session_revalidate_hours`. Without a refresh token the session ends at the
        first check (see `app.modules.auth.session_renewal`).

    Bootstrap admins:
        `bootstrap_admin_subjects` and `bootstrap_admin_emails` hold comma-separated
        OIDC `sub` values and emails. On OIDC login and at startup the app grants the
        matched principals the `admin` role idempotently. This prevents a lockout on
        a fresh OIDC install, where nobody holds `admin.*` and thus nobody could
        assign a role. An empty value turns the bootstrap off.

    Sessions and cookies:
        The cookies are HttpOnly, Secure and SameSite=Lax. The principal session asks
        the IdP again after `session_revalidate_hours` (refresh token grant). The
        check refreshes the groups, the gremium memberships and the active flag, and
        it ends the session when the IdP refuses the token, so it bounds how long a
        removed group or a disabled account keeps its rights. When the IdP is
        unreachable, the session stays open for `session_revalidate_grace_hours`
        after the last successful check, so an outage does not log everybody out and
        a long outage cannot keep a removed account in forever. The applicant session
        from a magic link is server-side (`applicant_session`) with an opaque signed
        `sid`. It is decoupled from the principal session, so its window can be tuned
        on its own; a shorter window narrows the replay window. The guest device
        token of a public meeting is HttpOnly, SameSite=Strict, path
        `/api/public/meetings`. The server keeps only its SHA-256 hash, and the token
        stops working when the meeting closes; the cookie lifetime is a safety bound.

    OAuth2 for native and MCP clients:
        Browser grant with PKCE (RFC 7636) for a public client without a secret, with
        loopback redirects only. The tokens are opaque and scoped (see
        `app.modules.auth.oauth`). Active only when OIDC is configured.
        `mcp_package_dir` is the source of the MCP self-service download; None means
        `<repo>/mcp`, and a container without a source tree answers 404.

    UI texts:
        `ui_catalog_dir` holds `de.json` and `en.json`, the built-in UI texts of the
        frontend. compose mounts them into the api container; None means
        `<repo>/frontend/src/app/core/i18n/catalog`.

    Mail:
        Without `smtp_host` the worker logs each mail and drops it, so DEV and the
        tests run without an MTA. The password never reaches the log.
        `mail_max_tries`, `scan_max_tries`, `pdf_max_tries` and `webhook_max_tries`
        with their `*_retry_backoff_seconds` set the arq retries per job kind.

    Storage and uploads:
        Without `minio_endpoint` upload is off and POST /attachments answers 503;
        DEV and contract CI run without a bucket. `minio_secure` enables TLS to the
        MinIO API, which is usually plain HTTP internally. `attachment_max_bytes`
        matches the database CHECK(size <= 10485760). Each wizard draft upload moves
        the end of all drafts of its token to now plus `attachment_draft_ttl_days`;
        one token holds at most `attachment_draft_max_files` files and
        `attachment_draft_max_bytes` bytes. `markdown_image_max_bytes` caps the
        uploaded image and the encoded result (413 beyond).

    Backups:
        An archive holds the pg_dump and a mirror of the attachment bucket,
        age-encrypted, in its own bucket. Without `backup_age_recipient` the feature
        is off and every route answers 503. The API encrypts to the recipient key and
        can do nothing else with it. `backup_age_identity_file` is the read-only
        mounted private key that a restore and a decrypted download need. Keep the
        off-host disaster-recovery key SEPARATE from it, so a stack compromise
        exposes only the archives that the app itself wrote.
        `backup_retention_count` keeps that many archives (0 disables pruning); a
        pinned archive never counts and is never pruned.

    ClamAV:
        Without `clamav_host` the scan is off. An upload then stays
        `scanned=false`, which quarantines it and blocks the download (fail-closed).

    Webhooks:
        Delivery runs in the arq worker; the API only creates `webhook_delivery` rows
        and jobs. The SSRF guard is always active and blocks private, loopback,
        link-local and metadata targets. `webhook_host_allowlist` restricts the
        targets further (empty means any public host); set it in production, and
        `_strict_security_warnings` warns when it is empty under hardening. The
        alias `WEBHOOK_ALLOWLIST` is the name of `deploy/.env.example` up to v0.0.2.
        `extra="ignore"` dropped that name silently, so a deployment that copied the
        example ran with an empty allowlist. `WEBHOOK_HOST_ALLOWLIST` wins when both
        are set. The per-webhook `secret` never reaches the log.

    Delegation:
        Vote delegation needs bylaws approval and defaults to OFF. The server
        accepts `delegateVoting=true` only when `delegation_voting_enabled` is on and
        answers 422 otherwise; pure rights delegation stays free. `local_timezone`
        is the zone of the naive `meeting.date` and `start_time` and the basis of the
        delegation deadline.

    typst:
        `api` and `worker` call only `/render` on the internal container at
        `typst_url`. A protocol renders in well under a second; the timeout leaves
        room for a long protocol on a busy host.

    Body caps (anti-DoS, 413 beyond):
        `max_application_payload_bytes` applies to the serialized field values of
        the public POST /applications and as a Content-Length bound; 64 KiB covers
        every real form. `max_auth_payload_bytes` stays tight, because an auth body
        holds only a mail address or a token. `max_ticket_payload_bytes` covers a
        title, a Markdown body of at most 10000 characters and a small context.

    ALTCHA:
        Without `altcha_hmac_secret` the verification is off (dev/test) and the
        field only passes through. The ALTCHA sidecar shares the secret.

    Rate limits (sliding window, per hour):
        The ticket report counts per IP, a session too, because a campus NAT rarely
        sends ten reports an hour; an OAuth token is exempt. A reporter message mails
        the team, so `rl_ticket_messages_per_hour` keeps a flood of messages from
        becoming a flood of mails. `rl_attachments_per_hour` counts per applicant.
        `rl_media_images_per_hour` counts per principal and is higher than the
        attachment limit, because a protocol can hold many pasted screenshots.
        `rl_default_write_per_hour` keys on the IP and catches an endpoint without
        its own limit (defense in depth). `rl_default_write_session_per_hour` keys
        on a signed principal session instead, because a campus NAT puts all users
        behind one IP and the protocol editor saves on every edit.
        `rl_avatar_per_hour` stays generous, because a member list asks for one
        avatar per row. `rl_applicant_search_per_hour` limits a search that
        discloses names and e-mails: generous for a person typing (debounced), low
        enough to stop a scraper. The public meeting limits stay generous, because
        many guests share the campus NAT; ALTCHA is the main guard of the join. The
        join counts per IP and per join code, the public reads per IP, and the
        writes of a guest (name, leave, ballot) per guest. The public routes are
        outside the default per-IP write limit, because each one has its own. The
        public protocol limits count per IP and stop a scraper that walks every
        protocol; the image limit equals the read limit, because one detail page
        loads every image of the protocol.

    Gravatar:
        The proxy fetches from the fixed host gravatar.com and caches in Redis. A
        found and a missing image (404) stay for `gravatar_cache_ttl_seconds`; a
        failed fetch (timeout, 5xx) only for `gravatar_error_ttl_seconds`, so a short
        outage heals itself. The site config switch `gravatarEnabled` turns the proxy
        off. `gravatar_timeout_seconds` is one total deadline for the DNS lookup, the
        connect and all reads of one fetch.
    """

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

    strict_security: bool = True

    database_url: str
    session_secret: str = Field(min_length=_MIN_SECRET_LEN)
    magic_link_secret: str = Field(min_length=_MIN_SECRET_LEN)

    forwarded_allow_ips: str = "127.0.0.1"

    csrf_enabled: bool = True
    csrf_cookie_name: str = "XSRF-TOKEN"
    csrf_header_name: str = "X-XSRF-TOKEN"

    cors_allow_origins: CsvList = []

    redis_url: str = "redis://redis:6379/0"
    db_migration_url: str | None = None

    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    oidc_redirect_url: str | None = None
    oidc_scopes: str = "openid email profile offline_access"
    oidc_groups_claim: str = "groups"
    oidc_post_logout_redirect_url: str | None = None

    @field_validator(
        "oidc_issuer",
        "oidc_client_id",
        "oidc_client_secret",
        "oidc_redirect_url",
        "oidc_post_logout_redirect_url",
        mode="before",
    )
    @classmethod
    def _empty_oidc_value_is_unset(cls, value: object) -> object:
        """Read an empty or blank OIDC value as not set.

        `deploy/.env.example` ships `OIDC_CLIENT_SECRET=` empty. Without this step the
        16-character minimum rejects the empty string and the app does not start. With
        it, the empty value means "OIDC is not configured" and `oidc_enabled` is False.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

    bootstrap_admin_subjects: str = ""
    bootstrap_admin_emails: str = ""

    @property
    def bootstrap_admin_subject_set(self) -> set[str]:
        """OIDC `sub`s from `BOOTSTRAP_ADMIN_SUBJECTS` (comma-separated, trimmed)."""
        return {s.strip() for s in self.bootstrap_admin_subjects.split(",") if s.strip()}

    @property
    def bootstrap_admin_email_set(self) -> set[str]:
        """Emails from `BOOTSTRAP_ADMIN_EMAILS` (comma-separated, trimmed, lowercased)."""
        return {e.strip().lower() for e in self.bootstrap_admin_emails.split(",") if e.strip()}

    session_cookie_name: str = "ap_session"
    applicant_cookie_name: str = "ap_applicant"
    oidc_tx_cookie_name: str = "ap_oidc_tx"
    session_revalidate_hours: int = Field(default=12, ge=1, le=168)
    session_revalidate_grace_hours: int = Field(default=72, ge=1, le=720)
    applicant_session_ttl_hours: int = 12
    cookie_secure: bool = True
    guest_cookie_name: str = "mg_token"
    guest_cookie_ttl_hours: int = 24

    oauth_mcp_client_id: str = "antragsplattform-mcp"
    oauth_tx_cookie_name: str = "ap_oauth_tx"
    oauth_code_ttl_seconds: int = 300
    oauth_access_ttl_seconds: int = 3600
    oauth_refresh_ttl_seconds: int = 60 * 60 * 24 * 30
    mcp_package_dir: str | None = None
    ui_catalog_dir: str | None = None

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
    mail_max_tries: int = 5
    mail_retry_backoff_seconds: int = 30

    @property
    def smtp_enabled(self) -> bool:
        """Report whether the worker really sends mail.

        Real sending needs `smtp_host`. Without it the worker logs the mail and
        drops it, which suits DEV and the tests.
        """
        return bool(self.smtp_host)

    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "attachments"
    minio_secure: bool = False
    attachment_max_bytes: int = 10 * 1024 * 1024
    attachment_url_ttl_seconds: int = 300
    attachment_draft_ttl_days: int = Field(default=7, ge=1)
    attachment_draft_max_files: int = Field(default=20, ge=1)
    attachment_draft_max_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    markdown_image_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1)

    backup_bucket: str = "backups"
    backup_age_recipient: str | None = None
    backup_age_identity_file: str | None = None
    backup_retention_count: int = 14
    backup_max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    backup_subprocess_timeout_seconds: int = 3600

    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 60
    scan_max_tries: int = 5
    scan_retry_backoff_seconds: int = 30

    webhook_timeout_seconds: float = 10.0
    webhook_max_tries: int = 5
    webhook_retry_backoff_seconds: int = 30
    webhook_host_allowlist: CsvList = Field(
        default=[],
        validation_alias=AliasChoices("webhook_host_allowlist", "webhook_allowlist"),
    )

    @field_validator("cors_allow_origins", "webhook_host_allowlist", mode="before")
    @classmethod
    def _accept_csv_lists(cls, value: object) -> object:
        """Accept a comma-separated list, as `deploy/.env.example` documents it."""
        return _split_csv(value)

    delegation_voting_enabled: bool = False
    local_timezone: str = "Europe/Berlin"

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

    typst_url: str = "http://typst:8099"
    typst_timeout_seconds: int = 60
    pdf_max_tries: int = 4
    pdf_retry_backoff_seconds: int = 30

    max_application_payload_bytes: int = 65536

    max_auth_payload_bytes: int = 8192

    max_ticket_payload_bytes: int = 65536

    altcha_hmac_secret: str | None = Field(default=None, min_length=_MIN_SECRET_LEN)
    altcha_max_number: int = 100_000
    altcha_challenge_ttl_seconds: int = 300

    rate_limit_enabled: bool = True
    rl_magic_link_ip_per_hour: int = 5
    rl_magic_link_mail_per_hour: int = 3
    rl_magic_link_verify_ip_per_hour: int = 20
    rl_applications_ip_per_hour: int = 10
    rl_tickets_ip_per_hour: int = 10
    rl_ticket_messages_per_hour: int = 60
    rl_attachments_per_hour: int = 30
    rl_media_images_per_hour: int = 120
    rl_default_write_per_hour: int = 100
    rl_default_write_session_per_hour: int = 3000
    rl_avatar_per_hour: int = 1200
    rl_applicant_search_per_hour: int = 300
    rl_public_join_ip_per_hour: int = 120
    rl_public_join_code_per_hour: int = 400
    rl_public_meeting_read_ip_per_hour: int = 3000
    rl_public_guest_write_per_hour: int = 120
    rl_public_protocols_ip_per_hour: int = 3000
    rl_public_protocol_pdf_ip_per_hour: int = 600
    rl_public_protocol_images_ip_per_hour: int = 3000

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
            raise ValueError('FORWARDED_ALLOW_IPS must not be "*" in production.')
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
                "only restricted by the SSRF guard, not pinned to known hosts."
            )
        if self.storage_enabled and not self.clamav_enabled:
            _log.warning(
                "MINIO storage is enabled but CLAMAV is disabled: uploaded attachments "
                "are stored and enqueued for scanning, but the worker has no scanner and "
                "leaves them scanned=False — downloads stay quarantined (409) forever. "
                "Configure CLAMAV_HOST or disable MINIO storage."
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


def load_settings(**overrides: Any) -> Settings:  # noqa: ANN401
    """Load the settings.

    Raises:
        SettingsError: A required field is missing, or the configuration is invalid.
            The message names the fields.
    """
    try:
        return Settings(**overrides)
    except ValidationError as exc:
        missing = [
            ".".join(str(p) for p in err["loc"]) for err in exc.errors() if err["type"] == "missing"
        ]
        if missing:
            raise SettingsError(
                "Fehlende Pflicht-Konfiguration (env): " + ", ".join(sorted(missing))
            ) from exc
        raise SettingsError(f"Ungültige Konfiguration: {exc}") from exc


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once."""
    return load_settings()
