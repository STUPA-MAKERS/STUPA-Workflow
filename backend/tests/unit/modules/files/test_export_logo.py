"""Unit tests of the export logo of the branding (spec 000891)."""

from __future__ import annotations

import pytest

from app.modules.admin.service.export_logo import check_export_logo
from app.modules.files.export_logo import (
    ExportLogo,
    asset_name,
    export_render_assets,
    export_render_config,
)
from app.shared.errors import PayloadTooLargeError, UnsupportedMediaTypeError

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
PDF = b"%PDF-1.7\n1 0 obj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
ICO = b"\x00\x00\x01\x00" + b"\x00" * 16


def test_the_export_logo_slot() -> None:
    """Rule: §F/administration/admin/000891. PNG, JPEG, WebP, SVG and PDF pass by their bytes."""
    assert check_export_logo(PNG) == "image/png"
    assert check_export_logo(SVG) == "image/svg+xml"
    assert check_export_logo(PDF) == "application/pdf"
    with pytest.raises(UnsupportedMediaTypeError):
        check_export_logo(ICO)
    with pytest.raises(UnsupportedMediaTypeError):
        check_export_logo(b"")
    with pytest.raises(PayloadTooLargeError):
        check_export_logo(PNG + b"\x00" * (2 * 1024 * 1024))
    assert asset_name("image/svg+xml") == "export-logo.svg"
    assert asset_name("application/pdf") == "export-logo.pdf"
    assert asset_name("image/x-icon") is None


def test_the_export_logo_config() -> None:
    """Rule: §F/administration/admin/000891. Both logo lists are always set."""
    logo = ExportLogo("export-logo.svg", SVG)
    assert export_render_config(logo, footer=False) == {
        "logos": ["export-logo.svg"],
        "footer_logos": [],
    }
    assert export_render_config(logo, footer=True) == {
        "logos": [],
        "footer_logos": ["export-logo.svg"],
    }
    assert export_render_config(None, footer=True) == {"logos": [], "footer_logos": []}
    assert export_render_assets(logo) == {"export-logo.svg": SVG}
    assert export_render_assets(None) is None
