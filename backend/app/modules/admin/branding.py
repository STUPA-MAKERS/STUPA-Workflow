"""Branding-/Site-Config-Schema (#21, T-24) — Single Source of Truth fürs Editor-FE.

Logos, Footer (Link-Spalten + Copyright + rechtliche Links) und i18n-Freitexte sind
config-driven statt hartkodiert. Das Schema wird über ``/admin/config-schemas`` mit
ausgeliefert (`Branding` in :data:`app.shared.config_schemas`).

**Sicherheitskontrakt (Logos).** Das FE liefert Logos als **Base64-Data-URL** inline
im Branding-JSON (kein separater Upload). Der Server validiert autoritativ — das
Client-Gate ist nur UX:

* Data-URLs werden **dekodiert**; die **tatsächliche** Byte-Größe (nicht das
  Client-Feld ``size``) wird gegen das 2-MB-Cap geprüft.
* Der Bild-Typ wird aus den **dekodierten Magic-Bytes** bestimmt (PNG/JPEG/WebP/ICO-
  Whitelist) und muss zum deklarierten ``mime`` passen — ein als ``image/png``
  getarntes SVG/anderes Format fliegt raus. **Kein Inline-SVG** (XSS-Vektor).
* http(s)-/absolute Asset-URLs sind erlaubt (nicht gefetcht → nur deklarierter
  ``mime`` + Client-``size`` geprüft). Footer-/Legal-URLs weisen ``javascript:``/
  ``data:``-Schemata ab.

Freitexte/Labels haben serverseitige Längen-Caps (Schutz gegen JSONB-Aufblähen über
das auth-freie ``GET /api/site-config``).
"""

from __future__ import annotations

import base64
import binascii
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

# Längen-Caps für i18n-Texte (Schutz gegen Aufblähen der auth-freien Public-Config).
MAX_FREETEXT_CHARS = 10_000
MAX_LABEL_CHARS = 500
MAX_I18N_KEY_CHARS = 16

LogoSlot = Literal["wordmark", "imagemark", "favicon"]

# image/vnd.microsoft.icon ist ein Alias von image/x-icon → für den Vergleich normiert.
_MIME_ALIASES = {"image/vnd.microsoft.icon": "image/x-icon"}


def _norm_mime(mime: str) -> str:
    return _MIME_ALIASES.get(mime, mime)


def _sniff_image(data: bytes) -> str | None:
    """Bild-Typ aus Magic-Bytes (None = unbekannt/kein Whitelist-Bild, z.B. SVG)."""
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
    """Längen-Cap je i18n-Wert + Sprach-Key (serverseitig autoritativ)."""
    for key, text in value.items():
        if len(key) > MAX_I18N_KEY_CHARS:
            raise ValueError(f"i18n key too long: {key!r}")
        if len(text) > limit:
            raise ValueError(f"i18n text exceeds {limit} characters")
    return value


class _CamelModel(BaseModel):
    """camelCase-Aliase im JSON; Felder per Name befüllbar; keine Extra-Felder."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


def _reject_unsafe_url(url: str) -> str:
    """`javascript:`/`data:`/`vbscript:`-Schemata in (Footer-)URLs abweisen."""
    low = url.strip().lower()
    if low.startswith(("javascript:", "vbscript:", "data:")):
        raise ValueError("unsafe url scheme")
    return url


class BrandingAsset(_CamelModel):
    """Logo-/Favicon-Asset: Base64-Data-URL (inline) oder Asset-URL. Bild-only, kein SVG."""

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
        # Inline-SVG in jeder Form abweisen (Markup oder data:image/svg+xml).
        if "<svg" in low or "image/svg" in low:
            raise ValueError("inline SVG logos are not allowed")
        if low.startswith("data:"):
            self._validate_data_url(raw)
            return self
        # Externe/absolute Asset-URL: nicht fetchbar → deklarierte Werte prüfen.
        if not low.startswith(("https://", "http://", "/")):
            raise ValueError("logo url must be a data-URL, http(s) URL or absolute path")
        if self.size > MAX_LOGO_BYTES:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        return self

    def _validate_data_url(self, raw: str) -> None:
        """Data-URL dekodieren + gegen **echte** Bytes härten (Magic-Type + Größe)."""
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
        # Kodierte Länge grob begrenzen, bevor dekodiert wird (Aufwand beschränken).
        if len(payload) > MAX_LOGO_BYTES * 2:
            raise ValueError(f"logo exceeds {MAX_LOGO_BYTES} bytes")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("invalid base64 logo payload") from exc
        # **Echte** Größe gegen Cap — Client-`size` ist nicht vertrauenswürdig.
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
    """i18n-Freitexte (Login-Hinweis, Welcome, Support, E-Mail-Footer, Antrags-Info)."""

    login_hint: I18nMap = Field(default_factory=dict, alias="loginHint")
    welcome: I18nMap = Field(default_factory=dict)
    support: I18nMap = Field(default_factory=dict)
    email_footer: I18nMap = Field(default_factory=dict, alias="emailFooter")
    # Info-Text unter der Antrags-(Typ-)Auswahl (#18) — Markdown, je Sprache.
    apply_info: I18nMap = Field(default_factory=dict, alias="applyInfo")

    @field_validator("login_hint", "welcome", "support", "email_footer", "apply_info")
    @classmethod
    def _cap_text(cls, v: I18nMap) -> I18nMap:
        return _cap_i18n(v, MAX_FREETEXT_CHARS)


class Branding(_CamelModel):
    """Vollständige Branding-Config (aktiv oder Draft)."""

    # App-Name (config-driven, sprach-neutral). Treibt PWA-Manifest (name/short_name),
    # Browser-Tab-Titel, Header-aria-label und die Home-H1. Leer → FE/Manifest fallen
    # auf die hartkodierten Defaults bzw. die i18n-Werte (app.title/home.heading) zurück.
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
