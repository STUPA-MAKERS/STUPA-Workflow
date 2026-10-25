"""Branding and site-config schema for the editor frontend.

This schema is the single source of truth. Logos, footer (copyright and legal
links) and i18n freetexts come from the config. The route
``/admin/config-schemas`` serves the schema.

Security contract for the logos. The frontend sends a logo inline as a base64
data URL. The server validates it authoritatively. The server decodes the data
URL and checks the real byte size against the 2 MB cap. It does not trust the
client ``size`` field. It sniffs the image type from the decoded magic bytes and
accepts the PNG, JPEG, WebP and ICO whitelist only. The sniffed type must match
the declared ``mime``. Inline SVG is an XSS vector, so the server refuses it.
The validator here runs synchronously, so the ClamAV scan of the inline bytes
(``BrandingAsset.inline_bytes``) runs in ``SiteConfigService`` before the store. An
http(s) URL or an absolute asset URL is allowed, but the server never fetches
it. For such a URL the server checks the declared values only. Footer and legal
URLs refuse the ``javascript:`` and ``data:`` schemes. Freetexts and labels have
server-side length caps. The caps guard the auth-free ``GET /api/site-config``
against JSONB bloat.
"""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.shared.i18n import I18nMap

# Image whitelist for the logos and the favicon. image/svg+xml is left out on purpose,
# because SVG carries an XSS risk.
ALLOWED_LOGO_MIME: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
)
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB (matches frontend LOGO_MAX_SIZE_MB)

# Length caps for the i18n texts. They guard the auth-free public config against bloat.
MAX_FREETEXT_CHARS = 10_000
MAX_LABEL_CHARS = 500
MAX_I18N_KEY_CHARS = 16

LogoSlot = Literal["wordmark", "imagemark", "favicon"]

# image/vnd.microsoft.icon is an alias of image/x-icon. Normalize it before a comparison.
_MIME_ALIASES = {"image/vnd.microsoft.icon": "image/x-icon"}


def _norm_mime(mime: str) -> str:
    return _MIME_ALIASES.get(mime, mime)


def sniff_raster_image(data: bytes) -> str | None:
    """Sniff the raster image type from the magic bytes.

    ``admin.cd_logos`` reuses this sniffer and adds the SVG and PDF cases that
    only the LaTeX renderer accepts. Do not widen the set here.

    Returns:
        The sniffed MIME type. ``None`` means unknown or not in the whitelist,
        for example SVG.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    return None


def _cap_i18n(value: I18nMap, limit: int) -> I18nMap:
    """Apply the authoritative server-side length caps per i18n text and language key."""
    for key, text in value.items():
        if len(key) > MAX_I18N_KEY_CHARS:
            raise ValueError(f"i18n key too long: {key!r}")
        if len(text) > limit:
            raise ValueError(f"i18n text exceeds {limit} characters")
    return value


class _CamelModel(BaseModel):
    """Base model with camelCase JSON aliases, population by name and no extra fields."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def _reject_unsafe_url(url: str) -> str:
    """Reject `javascript:`/`data:`/`vbscript:` schemes in (footer) URLs."""
    low = url.strip().lower()
    if low.startswith(("javascript:", "vbscript:", "data:")):
        raise ValueError("unsafe url scheme")
    return url


class BrandingAsset(_CamelModel):
    """Logo/favicon asset: inline base64 data URL or asset URL. Image-only, no SVG."""

    url: str
    filename: str = Field(max_length=MAX_LABEL_CHARS)
    mime: str
    size: int = Field(ge=0)

    @field_validator("mime")
    @classmethod
    def _mime_allowed(cls, v: str) -> str:
        if v not in ALLOWED_LOGO_MIME:
            raise ValueError(f"unsupported logo mime: {v!r} (no SVG / image-only)")
        return v

    @model_validator(mode="after")
    def _check_url_and_bytes(self) -> BrandingAsset:
        raw = self.url.strip()
        low = raw.lower()
        if "<svg" in low or "image/svg" in low:
            raise ValueError("inline SVG logos are not allowed")
        if low.startswith("data:"):
            self._validate_data_url(raw)
            return self
        # External or absolute asset URL: the server does not fetch it and therefore
        # checks the declared values only.
        if not low.startswith(("https://", "http://", "/")):
            raise ValueError("logo url must be a data-URL, http(s) URL or absolute path")
        if self.size > MAX_LOGO_BYTES:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        return self

    def inline_bytes(self) -> bytes | None:
        """Return the decoded bytes of an inline data-URL logo, else ``None``.

        The model validator already checked the data URL, so the decode cannot fail
        here. A logo behind an http(s) or absolute URL has no bytes on the server.
        """
        raw = self.url.strip()
        if not raw.lower().startswith("data:"):
            return None
        return base64.b64decode(raw.split(",", 1)[1], validate=True)

    def _validate_data_url(self, raw: str) -> None:
        """Decode the data URL and validate the real bytes against the magic type and size."""
        try:
            header, payload = raw.split(",", 1)
        except ValueError as exc:
            raise ValueError("malformed data-URL") from exc
        meta = header[len("data:") :].lower()
        if ";base64" not in meta:
            raise ValueError("only base64 data-URLs are accepted for logos")
        mediatype = meta.split(";", 1)[0]
        if mediatype not in ALLOWED_LOGO_MIME:
            raise ValueError(f"data-URL media type not allowed: {mediatype!r}")
        if _norm_mime(mediatype) != _norm_mime(self.mime):
            raise ValueError("data-URL media type does not match declared mime")
        # Cap the encoded length before the decode. This bounds the decode work.
        if len(payload) > MAX_LOGO_BYTES * 2:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64 logo payload") from exc
        # Check the real size against the cap. The client `size` field is untrusted.
        if len(decoded) > MAX_LOGO_BYTES:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        sniffed = sniff_raster_image(decoded)
        if sniffed is None:
            raise ValueError("logo payload is not a recognized image (no SVG / image-only)")
        if _norm_mime(sniffed) != _norm_mime(self.mime):
            raise ValueError(f"logo bytes are {sniffed!r}, not the declared {self.mime!r}")


class FooterLink(_CamelModel):
    label: I18nMap = Field(default_factory=dict)
    url: str = Field(max_length=2048)

    @field_validator("label")
    @classmethod
    def _cap_label(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_LABEL_CHARS)

    @field_validator("url")
    @classmethod
    def _safe(cls, v: str) -> str:
        return _reject_unsafe_url(v)


class SiteFreetexts(_CamelModel):
    """i18n freetexts (login hint, welcome, support, e-mail footer, apply info,
    texts after the submission)."""

    login_hint: I18nMap = Field(default_factory=dict, alias="loginHint")
    welcome: I18nMap = Field(default_factory=dict)
    support: I18nMap = Field(default_factory=dict)
    email_footer: I18nMap = Field(default_factory=dict, alias="emailFooter")
    # Info text below the application-type selection — Markdown, per language.
    apply_info: I18nMap = Field(default_factory=dict, alias="applyInfo")
    # The text on the page after the submission, Markdown, per language. "Internal" is
    # for a signed-in applicant (the application is submitted at once), "external" is
    # for a guest (the e-mail link confirms the application). An empty language falls
    # back to the built-in text of the frontend.
    submitted_internal: I18nMap = Field(default_factory=dict, alias="submittedInternal")
    submitted_external: I18nMap = Field(default_factory=dict, alias="submittedExternal")

    @field_validator(
        "login_hint",
        "welcome",
        "support",
        "email_footer",
        "apply_info",
        "submitted_internal",
        "submitted_external",
    )
    @classmethod
    def _cap_text(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_FREETEXT_CHARS)


#: The default handbook of the help menu: the only wiki link of the app.
DEFAULT_WIKI_URL = "https://wiki.reutlingen.university/books/antragsplattform"


def check_http_url(url: str) -> str:
    """Return the stripped URL, or raise ``ValueError`` unless it is http(s)."""
    value = url.strip()
    if not value.lower().startswith(("https://", "http://")):
        raise ValueError("the URL must start with https:// or http://")
    return value


class HelpSettings(_CamelModel):
    """The help menu: ``wikiUrl`` is the target of "Handbuch". http(s) only."""

    wiki_url: str = Field(default=DEFAULT_WIKI_URL, alias="wikiUrl", max_length=2048)

    @field_validator("wiki_url")
    @classmethod
    def _http_only(cls, v: str) -> str:
        return check_http_url(v)


class TicketSettings(_CamelModel):
    """The ticket reports.

    ``publicEnabled`` lets a person without a session report (ALTCHA). ``notifyNew``
    mails each new ticket to the holders of ``ticket.manage``. ``retentionMonths`` is
    the time after the close until the retention cron anonymizes a ticket; null means
    never.
    """

    public_enabled: bool = Field(default=True, alias="publicEnabled")
    notify_new: bool = Field(default=True, alias="notifyNew")
    retention_months: int | None = Field(default=12, alias="retentionMonths", ge=1, le=120)


#: The accent colour: six hex digits, so the frontend can derive the theme tokens.
ACCENT_PATTERN = r"^#[0-9a-fA-F]{6}$"


class Branding(_CamelModel):
    """Full branding config (active or draft)."""

    # App name from the config, language-neutral. It drives the PWA manifest, the
    # browser-tab title, the header aria-label and the home H1. An empty value falls
    # back to the hardcoded defaults and the i18n values.
    app_name: str = Field(default="", alias="appName", max_length=MAX_LABEL_CHARS)
    app_short_name: str = Field(
        default="", alias="appShortName", max_length=MAX_LABEL_CHARS
    )
    logos: dict[LogoSlot, BrandingAsset] = Field(default_factory=dict)
    copyright: I18nMap = Field(default_factory=dict)
    legal_links: list[FooterLink] = Field(
        default_factory=list, alias="legalLinks", max_length=50
    )
    freetexts: SiteFreetexts = Field(default_factory=SiteFreetexts)
    # Show the Gravatar image of a person instead of the initials. The API fetches the
    # image through its own proxy (`GET /principals/{id}/avatar`), so the browser never
    # contacts gravatar.com. False turns the proxy off: it answers 404 and the frontend
    # shows the initials. A config from before this field reads as True.
    gravatar_enabled: bool = Field(default=True, alias="gravatarEnabled")
    # The accent colour of the whole app, as ``#rrggbb``. The frontend derives the
    # accent tokens of the light and the dark theme from it. None means the built-in
    # accent of the design system.
    accent_color: str | None = Field(default=None, alias="accentColor", pattern=ACCENT_PATTERN)
    # The help menu and the ticket reports ("Hilfe & Tickets"). A config from before
    # these fields reads as the defaults.
    help: HelpSettings = Field(default_factory=HelpSettings)
    tickets: TicketSettings = Field(default_factory=TicketSettings)

    @model_validator(mode="before")
    @classmethod
    def _drop_footer_columns(cls, data: object) -> object:
        # The footer has no link columns. A stored config from before still carries
        # the key, and `extra="forbid"` would reject that config, so it is dropped.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in ("footerColumns", "footer_columns")}
        return data

    @field_validator("accent_color")
    @classmethod
    def _lower_accent(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else None

    @field_validator("copyright")
    @classmethod
    def _cap_copyright(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_LABEL_CHARS)


class PublicBranding(Branding):
    """The branding of the public ``GET /site-config``.

    The help and ticket settings stay out of it, because ``notifyNew`` and
    ``retentionMonths`` are not public. The public config names ``help.wikiUrl`` and
    ``tickets.publicEnabled`` on its top level instead.
    """

    help: HelpSettings = Field(default_factory=HelpSettings, exclude=True)
    tickets: TicketSettings = Field(default_factory=TicketSettings, exclude=True)
