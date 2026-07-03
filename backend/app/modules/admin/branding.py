"""Branding/site-config schema — single source of truth for the editor frontend.

Logos, footer (link columns + copyright + legal links) and i18n freetexts are
config-driven. The schema is served via ``/admin/config-schemas``.

Security contract (logos): the frontend sends logos inline as base64 data URLs;
the server validates authoritatively. Data URLs are decoded and the actual byte
size is checked against the 2 MB cap (not the client ``size`` field); the image
type is sniffed from decoded magic bytes (PNG/JPEG/WebP/ICO whitelist) and must
match the declared ``mime``. No inline SVG (XSS vector). http(s)/absolute asset
URLs are allowed but not fetched, so only declared values are checked.
Footer/legal URLs reject ``javascript:``/``data:`` schemes. Freetexts/labels
have server-side length caps (guards the auth-free ``GET /api/site-config``
against JSONB bloat).
"""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.shared.i18n import I18nMap

# Image whitelist for logos/favicon — deliberately without image/svg+xml (SVG XSS).
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

# Length caps for i18n texts (guards the auth-free public config against bloat).
MAX_FREETEXT_CHARS = 10_000
MAX_LABEL_CHARS = 500
MAX_I18N_KEY_CHARS = 16

LogoSlot = Literal["wordmark", "imagemark", "favicon"]

# image/vnd.microsoft.icon is an alias of image/x-icon; normalized for comparison.
_MIME_ALIASES = {"image/vnd.microsoft.icon": "image/x-icon"}


def _norm_mime(mime: str) -> str:
    return _MIME_ALIASES.get(mime, mime)


def _sniff_image(data: bytes) -> str | None:
    """Sniff the image type from magic bytes (None = unknown/not whitelisted, e.g. SVG)."""
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
    """Enforce length caps per i18n value and language key (server-side authoritative)."""
    for key, text in value.items():
        if len(key) > MAX_I18N_KEY_CHARS:
            raise ValueError(f"i18n key too long: {key!r}")
        if len(text) > limit:
            raise ValueError(f"i18n text exceeds {limit} characters")
    return value


class _CamelModel(BaseModel):
    """camelCase aliases in JSON; fields populatable by name; no extra fields."""

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
        # Reject inline SVG in any form (markup or data:image/svg+xml).
        if "<svg" in low or "image/svg" in low:
            raise ValueError("inline SVG logos are not allowed")
        if low.startswith("data:"):
            self._validate_data_url(raw)
            return self
        # External/absolute asset URL: not fetchable, so check declared values only.
        if not low.startswith(("https://", "http://", "/")):
            raise ValueError("logo url must be a data-URL, http(s) URL or absolute path")
        if self.size > MAX_LOGO_BYTES:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        return self

    def _validate_data_url(self, raw: str) -> None:
        """Decode the data URL and validate against the actual bytes (magic type + size)."""
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
        # Roughly cap the encoded length before decoding (bounds the work).
        if len(payload) > MAX_LOGO_BYTES * 2:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64 logo payload") from exc
        # Actual size against the cap — the client `size` field is untrusted.
        if len(decoded) > MAX_LOGO_BYTES:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        sniffed = _sniff_image(decoded)
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


class FooterColumn(_CamelModel):
    label: I18nMap = Field(default_factory=dict)
    links: list[FooterLink] = Field(default_factory=list, max_length=50)

    @field_validator("label")
    @classmethod
    def _cap_label(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_LABEL_CHARS)


class SiteFreetexts(_CamelModel):
    """i18n freetexts (login hint, welcome, support, e-mail footer, apply info)."""

    login_hint: I18nMap = Field(default_factory=dict, alias="loginHint")
    welcome: I18nMap = Field(default_factory=dict)
    support: I18nMap = Field(default_factory=dict)
    email_footer: I18nMap = Field(default_factory=dict, alias="emailFooter")
    # Info text below the application-type selection — Markdown, per language.
    apply_info: I18nMap = Field(default_factory=dict, alias="applyInfo")

    @field_validator("login_hint", "welcome", "support", "email_footer", "apply_info")
    @classmethod
    def _cap_text(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_FREETEXT_CHARS)


class Branding(_CamelModel):
    """Full branding config (active or draft)."""

    # App name (config-driven, language-neutral). Drives the PWA manifest,
    # browser-tab title, header aria-label and the home H1. Empty falls back to
    # the hardcoded defaults / i18n values.
    app_name: str = Field(default="", alias="appName", max_length=MAX_LABEL_CHARS)
    app_short_name: str = Field(
        default="", alias="appShortName", max_length=MAX_LABEL_CHARS
    )
    logos: dict[LogoSlot, BrandingAsset] = Field(default_factory=dict)
    footer_columns: list[FooterColumn] = Field(
        default_factory=list, alias="footerColumns", max_length=20
    )
    copyright: I18nMap = Field(default_factory=dict)
    legal_links: list[FooterLink] = Field(
        default_factory=list, alias="legalLinks", max_length=50
    )
    freetexts: SiteFreetexts = Field(default_factory=SiteFreetexts)

    @field_validator("copyright")
    @classmethod
    def _cap_copyright(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_LABEL_CHARS)
