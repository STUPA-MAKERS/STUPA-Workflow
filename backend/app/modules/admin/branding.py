"""Branding-/Site-Config-Schema (#21, T-24) — Single Source of Truth fürs Editor-FE.

Logos, Footer (Link-Spalten + Copyright + rechtliche Links) und i18n-Freitexte sind
config-driven statt hartkodiert. Das Schema wird über ``/admin/config-schemas`` mit
ausgeliefert (`Branding` in :data:`app.shared.config_schemas`).

**Sicherheitskontrakt (Logos):** nur Bild-Typen, **kein Inline-SVG** (XSS-Vektor).
Das FE liefert Logos als Data-URL inline im Branding-JSON (kein separater Upload);
der Server validiert hier autoritativ Media-Type (Bild-Whitelist), Größe (≤2 MB) und
weist SVG sowie `javascript:`-URLs ab. http(s)-/absolute Asset-URLs sind erlaubt.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.shared.i18n import I18nMap

# Bild-Whitelist für Logos/Favicon — bewusst **ohne** image/svg+xml (Inline-SVG-XSS).
ALLOWED_LOGO_MIME: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/x-icon",
        "image/vnd.microsoft.icon",
    }
)
MAX_LOGO_BYTES = 2 * 1024 * 1024  # 2 MB (FE LOGO_MAX_SIZE_MB)

LogoSlot = Literal["wordmark", "imagemark", "favicon"]


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar; keine Extra-Felder."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def _reject_unsafe_url(url: str) -> str:
    """`javascript:`/`data:text|...`-Schemata in (Footer-)URLs abweisen."""
    low = url.strip().lower()
    if low.startswith(("javascript:", "vbscript:", "data:")):
        raise ValueError("unsafe url scheme")
    return url


class BrandingAsset(_CamelModel):
    """Logo-/Favicon-Asset: Data-URL (inline) oder Asset-URL. Bild-only, kein SVG."""

    url: str
    filename: str
    mime: str
    size: int = Field(ge=0)

    @field_validator("mime")
    @classmethod
    def _mime_allowed(cls, v: str) -> str:
        if v not in ALLOWED_LOGO_MIME:
            raise ValueError(f"unsupported logo mime: {v!r} (no SVG / image-only)")
        return v

    @model_validator(mode="after")
    def _check_url_and_size(self) -> BrandingAsset:
        if self.size > MAX_LOGO_BYTES:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        raw = self.url.strip()
        low = raw.lower()
        # Inline-SVG in jeder Form abweisen (Markup oder data:image/svg+xml).
        if "<svg" in low or "image/svg" in low:
            raise ValueError("inline SVG logos are not allowed")
        if low.startswith("data:"):
            header = low.split(",", 1)[0]  # z.B. "data:image/png;base64"
            mediatype = header[len("data:") :].split(";", 1)[0]
            if mediatype not in ALLOWED_LOGO_MIME:
                raise ValueError(f"data-URL media type not allowed: {mediatype!r}")
            if mediatype != self.mime:
                raise ValueError("data-URL media type does not match declared mime")
            return self
        if not low.startswith(("https://", "http://", "/")):
            raise ValueError("logo url must be a data-URL, http(s) URL or absolute path")
        return self


class FooterLink(_CamelModel):
    label: I18nMap = Field(default_factory=dict)
    url: str

    @field_validator("url")
    @classmethod
    def _safe(cls, v: str) -> str:
        return _reject_unsafe_url(v)


class FooterColumn(_CamelModel):
    label: I18nMap = Field(default_factory=dict)
    links: list[FooterLink] = Field(default_factory=list)


class SiteFreetexts(_CamelModel):
    """i18n-Freitexte (Login-Hinweis, Welcome, Support, E-Mail-Footer)."""

    login_hint: I18nMap = Field(default_factory=dict, alias="loginHint")
    welcome: I18nMap = Field(default_factory=dict)
    support: I18nMap = Field(default_factory=dict)
    email_footer: I18nMap = Field(default_factory=dict, alias="emailFooter")


class Branding(_CamelModel):
    """Vollständige Branding-Config (aktiv oder Draft)."""

    logos: dict[LogoSlot, BrandingAsset] = Field(default_factory=dict)
    footer_columns: list[FooterColumn] = Field(
        default_factory=list, alias="footerColumns"
    )
    copyright: I18nMap = Field(default_factory=dict)
    legal_links: list[FooterLink] = Field(default_factory=list, alias="legalLinks")
    freetexts: SiteFreetexts = Field(default_factory=SiteFreetexts)
