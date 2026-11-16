"""Unit tests of the PDF branding (specs 000891, 000892)."""

from __future__ import annotations

import pytest

from app.modules.admin.service.pdf_branding import check_pdf_asset
from app.modules.files.pdf_branding import (
    PdfBranding,
    RenderGraphic,
    asset_name,
    export_render_assets,
    export_render_config,
    footer_render_assets,
    footer_render_config,
)
from app.shared.errors import PayloadTooLargeError, UnsupportedMediaTypeError

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'
PDF = b"%PDF-1.7\n1 0 obj\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
ICO = b"\x00\x00\x01\x00" + b"\x00" * 16


def test_the_upload_policy() -> None:
    """Rule: §F/administration/admin/000891. PNG, JPEG, WebP, SVG and PDF pass by their bytes."""
    assert check_pdf_asset(PNG) == "image/png"
    assert check_pdf_asset(SVG) == "image/svg+xml"
    assert check_pdf_asset(PDF) == "application/pdf"
    with pytest.raises(UnsupportedMediaTypeError):
        check_pdf_asset(ICO)
    with pytest.raises(UnsupportedMediaTypeError):
        check_pdf_asset(b"")
    with pytest.raises(PayloadTooLargeError):
        check_pdf_asset(PNG + b"\x00" * (2 * 1024 * 1024))
    assert asset_name("logo", "image/svg+xml") == "export-logo.svg"
    assert asset_name("footer", "application/pdf") == "footer-graphic.pdf"
    assert asset_name("logo", "image/x-icon") is None


def test_the_render_config() -> None:
    """Rule: §F/administration/admin/000892. The logo lists and the graphic are always set."""
    branding = PdfBranding(RenderGraphic("export-logo.svg", SVG), RenderGraphic("Skyline"))
    assert export_render_config(branding, footer=False) == {
        "logos": ["export-logo.svg"],
        "footer_logos": [],
        "footer_graphic": "Skyline",
    }
    assert export_render_config(branding, footer=True) == {
        "logos": [],
        "footer_logos": ["export-logo.svg"],
        "footer_graphic": "Skyline",
    }
    assert export_render_config(PdfBranding(), footer=True) == {
        "logos": [],
        "footer_logos": [],
        "footer_graphic": "",
    }
    assert export_render_assets(branding) == {"export-logo.svg": SVG}
    assert export_render_assets(PdfBranding()) is None
    builtin_logo = PdfBranding(RenderGraphic("STUPA"), RenderGraphic("footer-graphic.svg", SVG))
    assert footer_render_config(builtin_logo) == {"footer_graphic": "footer-graphic.svg"}
    assert footer_render_assets(builtin_logo) == {"footer-graphic.svg": SVG}
    assert export_render_assets(builtin_logo) == {"footer-graphic.svg": SVG}
