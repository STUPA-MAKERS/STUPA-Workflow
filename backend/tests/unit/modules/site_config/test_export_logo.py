"""Unit tests of the export logo of the branding (spec 000891)."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.site_config.branding import Branding, PublicBranding
from app.modules.site_config.export_logo import (
    ExportLogo,
    export_logo_of,
    export_render_assets,
    export_render_config,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_ICO = b"\x00\x00\x01\x00" + b"\x00" * 16


def _asset(data: bytes = _PNG, mime: str = "image/png", **kwargs: Any) -> dict[str, Any]:
    return {
        "url": f"data:{mime};base64," + base64.b64encode(data).decode(),
        "filename": "logo",
        "mime": mime,
        "size": len(data),
        **kwargs,
    }


def test_the_export_logo_slot() -> None:
    """The branding takes an inline PNG, JPEG or WebP export logo, and the public one drops it."""
    branding = Branding.model_validate({"logos": {"export": _asset(), "favicon": _asset()}})
    assert set(branding.logos) == {"export", "favicon"}
    public = PublicBranding.model_validate(branding.model_dump(by_alias=True))
    assert set(public.logos) == {"favicon"}
    with pytest.raises(ValidationError, match="inline data-URL"):
        Branding.model_validate(
            {"logos": {"export": _asset(url="https://example.org/logo.png")}}
        )
    with pytest.raises(ValidationError, match="unsupported export logo mime"):
        Branding.model_validate({"logos": {"export": _asset(_ICO, "image/x-icon")}})


def test_the_export_logo_config() -> None:
    """The render config always names both logo lists, so no default logo comes in."""
    logo = export_logo_of(_asset())
    assert logo == ExportLogo("export-logo.png", _PNG)
    assert export_logo_of(None) is None
    assert export_logo_of({"url": "broken"}) is None
    assert export_logo_of(_asset(_ICO, "image/x-icon")) is None
    assert export_render_config(logo, footer=False) == {
        "logos": ["export-logo.png"],
        "footer_logos": [],
    }
    assert export_render_config(logo, footer=True) == {
        "logos": [],
        "footer_logos": ["export-logo.png"],
    }
    assert export_render_config(None, footer=True) == {"logos": [], "footer_logos": []}
    assert export_render_assets(logo) == {"export-logo.png": _PNG}
    assert export_render_assets(None) is None
