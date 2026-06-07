"""Unit (ohne DB): Branding-Schema-Validierung (#21, T-24).

Sicherheitskontrakt: Logos sind **Bild-only**, **kein Inline-SVG**, ≤2 MB; Footer-/
Legal-URLs ohne `javascript:`/`data:`-Schemata. Diese Regeln greifen serverseitig
autoritativ (das FE-Client-Gate ist nur UX).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.admin.branding import MAX_LOGO_BYTES, Branding, BrandingAsset


def _png(url: str = "data:image/png;base64,iVBORw0KGgo=") -> dict:
    return {"url": url, "filename": "logo.png", "mime": "image/png", "size": 1024}


def test_empty_branding_defaults() -> None:
    b = Branding()
    assert b.logos == {}
    assert b.footer_columns == []
    assert b.freetexts.welcome == {}


def test_full_branding_roundtrip_by_alias() -> None:
    raw = {
        "logos": {"wordmark": _png(), "imagemark": _png(), "favicon": _png()},
        "footerColumns": [
            {"label": {"de": "Links"}, "links": [{"label": {"de": "X"}, "url": "/x"}]}
        ],
        "copyright": {"de": "© 2026"},
        "legalLinks": [{"label": {"de": "Impressum"}, "url": "https://e.x/impressum"}],
        "freetexts": {
            "loginHint": {"de": "Hinweis"},
            "welcome": {"de": "Willkommen"},
            "support": {"de": "support@x"},
            "emailFooter": {"de": "Fuß"},
        },
    }
    b = Branding.model_validate(raw)
    assert set(b.logos) == {"wordmark", "imagemark", "favicon"}
    dumped = b.model_dump(by_alias=True)
    assert "footerColumns" in dumped
    assert dumped["freetexts"]["loginHint"] == {"de": "Hinweis"}
    # deterministischer Roundtrip
    assert Branding.model_validate(dumped).model_dump(by_alias=True) == dumped


def test_http_and_absolute_logo_urls_allowed() -> None:
    for url in ("https://cdn.x/l.png", "http://cdn.x/l.png", "/assets/l.png"):
        BrandingAsset(url=url, filename="l.png", mime="image/png", size=10)


def test_favicon_ico_allowed() -> None:
    BrandingAsset(
        url="data:image/x-icon;base64,AAAB",
        filename="favicon.ico",
        mime="image/x-icon",
        size=10,
    )


@pytest.mark.parametrize(
    "mime",
    ["image/svg+xml", "text/html", "application/pdf", "image/gif"],
)
def test_rejects_non_whitelisted_mime(mime: str) -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(url="https://x/l", filename="l", mime=mime, size=1)


def test_rejects_inline_svg_data_url() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="data:image/svg+xml;base64,PHN2Zz4=",
            filename="l.svg",
            mime="image/png",  # gelogen — Inline-SVG wird unabhängig vom mime geblockt
            size=10,
        )


def test_rejects_inline_svg_markup() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="<svg onload=alert(1)></svg>",
            filename="l",
            mime="image/png",
            size=10,
        )


def test_data_url_mediatype_must_match_mime() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="data:image/jpeg;base64,/9j/4AAQ",
            filename="l.png",
            mime="image/png",
            size=10,
        )


def test_data_url_disallowed_mediatype() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="data:application/octet-stream;base64,AAAA",
            filename="l",
            mime="image/png",
            size=10,
        )


def test_rejects_unknown_url_scheme() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(url="ftp://x/l.png", filename="l", mime="image/png", size=10)


def test_rejects_oversize_logo() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="https://x/l.png",
            filename="l",
            mime="image/png",
            size=MAX_LOGO_BYTES + 1,
        )


@pytest.mark.parametrize("scheme", ["javascript:alert(1)", "data:text/html,x", "vbscript:x"])
def test_footer_link_rejects_unsafe_url(scheme: str) -> None:
    with pytest.raises(ValidationError):
        Branding.model_validate(
            {"legalLinks": [{"label": {"de": "x"}, "url": scheme}]}
        )


def test_branding_forbids_extra_keys() -> None:
    with pytest.raises(ValidationError):
        Branding.model_validate({"bogus": 1})


def test_unknown_logo_slot_rejected() -> None:
    with pytest.raises(ValidationError):
        Branding.model_validate({"logos": {"banner": _png()}})
