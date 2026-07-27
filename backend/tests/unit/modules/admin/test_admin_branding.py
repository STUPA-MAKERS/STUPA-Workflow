"""Unit tests without a DB: branding schema validation (#21, T-24).

Security contract: a logo must be an image, must not be an inline SVG and must stay
at or below 2 MB. A footer or legal URL must not use the `javascript:` or `data:`
scheme. The server enforces these rules. The frontend gate is only UX.
"""

from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from app.modules.admin.branding import (
    MAX_FREETEXT_CHARS,
    MAX_LOGO_BYTES,
    Branding,
    BrandingAsset,
)


# `iVBORw0KGgo=` is exactly the 8-byte PNG signature, so the magic-byte check passes.
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
    assert Branding.model_validate(dumped).model_dump(by_alias=True) == dumped


def test_http_and_absolute_logo_urls_allowed() -> None:
    for url in ("https://cdn.x/l.png", "http://cdn.x/l.png", "/assets/l.png"):
        BrandingAsset(url=url, filename="l.png", mime="image/png", size=10)


def test_favicon_ico_allowed() -> None:
    # The 4-byte ICO header 00 00 01 00 gives the base64 string "AAABAA==".
    BrandingAsset(
        url="data:image/x-icon;base64,AAABAA==",
        filename="favicon.ico",
        mime="image/vnd.microsoft.icon",  # alias of image/x-icon, so it is accepted
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
            mime="image/png",  # deliberately wrong: the check blocks an inline SVG anyway
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


def test_data_url_real_bytes_exceed_cap_rejected() -> None:
    """The real byte count decides because the server distrusts the client `size` field."""
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_LOGO_BYTES + 1)
    url = "data:image/png;base64," + base64.b64encode(big).decode()
    with pytest.raises(ValidationError):
        BrandingAsset(url=url, filename="l.png", mime="image/png", size=0)


def test_png_declared_but_svg_bytes_rejected() -> None:
    """The magic-byte sniff rejects an SVG in base64 that claims to be image/png."""
    svg = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>").decode()
    with pytest.raises(ValidationError):
        BrandingAsset(
            url=f"data:image/png;base64,{svg}", filename="l.png", mime="image/png", size=10
        )


def test_png_declared_but_jpeg_bytes_rejected() -> None:
    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0\x00\x10").decode()
    with pytest.raises(ValidationError):
        BrandingAsset(
            url=f"data:image/png;base64,{jpeg}", filename="l.png", mime="image/png", size=10
        )


def test_non_base64_data_url_rejected() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="data:image/png,rawbytes", filename="l.png", mime="image/png", size=10
        )


def test_invalid_base64_payload_rejected() -> None:
    with pytest.raises(ValidationError):
        BrandingAsset(
            url="data:image/png;base64,@@not-base64@@",
            filename="l.png", mime="image/png", size=10,
        )


def test_overlong_freetext_rejected() -> None:
    with pytest.raises(ValidationError):
        Branding.model_validate(
            {"freetexts": {"welcome": {"de": "x" * (MAX_FREETEXT_CHARS + 1)}}}
        )


def test_overlong_footer_label_rejected() -> None:
    with pytest.raises(ValidationError):
        Branding.model_validate(
            {"footerColumns": [{"label": {"de": "y" * 600}, "links": []}]}
        )


def test_overlong_copyright_rejected() -> None:
    with pytest.raises(ValidationError):
        Branding.model_validate({"copyright": {"de": "z" * 600}})
