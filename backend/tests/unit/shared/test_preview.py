"""The sandboxed inline preview of a served file (spec 001083)."""

from __future__ import annotations

import pytest

from app.shared.preview import PREVIEW_CSP, file_response


def test_inline_preview_headers() -> None:
    """``inline`` and a PDF give the framable, sandboxed preview."""
    res = file_response(b"%PDF-1.7", name="Antrag.pdf", mime="application/pdf", inline=True)
    assert res.media_type == "application/pdf"
    assert res.headers["Content-Disposition"].startswith("inline;")
    assert res.headers["Content-Security-Policy"] == PREVIEW_CSP
    assert "sandbox" in PREVIEW_CSP
    assert "frame-ancestors 'self'" in PREVIEW_CSP
    assert res.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_without_inline_the_answer_stays() -> None:
    """Without ``inline`` the answer is the download, without frame headers."""
    res = file_response(b"%PDF-1.7", name="Antrag.pdf", mime="application/pdf", inline=False)
    assert res.headers["Content-Disposition"].startswith("attachment;")
    assert "Content-Security-Policy" not in res.headers
    assert "X-Frame-Options" not in res.headers


def test_inline_disposition_keeps_inline_without_frame_headers() -> None:
    """A route that always answered ``inline`` keeps that, but stays unframable."""
    res = file_response(
        b"%PDF-1.7",
        name="Protokoll.pdf",
        mime="application/pdf",
        inline=False,
        disposition="inline",
        extra={"Cache-Control": "no-store"},
    )
    assert res.headers["Content-Disposition"].startswith("inline;")
    assert res.headers["Cache-Control"] == "no-store"
    assert "X-Frame-Options" not in res.headers


@pytest.mark.parametrize("mime", ["image/svg+xml", "application/octet-stream", "text/html"])
def test_no_preview_outside_the_allowlist(mime: str) -> None:
    """An SVG or an unknown type never becomes a preview, also with ``inline``."""
    res = file_response(
        b"<svg/>",
        name="logo.svg",
        mime=mime,
        inline=True,
        fallback_mime="application/octet-stream",
    )
    assert res.media_type == "application/octet-stream"
    assert res.headers["Content-Disposition"].startswith("attachment;")
    assert "X-Frame-Options" not in res.headers


def test_raster_logo_preview_uses_the_sniffed_type() -> None:
    """A PNG logo previews as ``image/png``; its download stays octet-stream."""
    preview = file_response(
        b"\x89PNG",
        name="logo.png",
        mime="image/png",
        inline=True,
        fallback_mime="application/octet-stream",
    )
    plain = file_response(
        b"\x89PNG",
        name="logo.png",
        mime="image/png",
        inline=False,
        fallback_mime="application/octet-stream",
    )
    assert preview.media_type == "image/png"
    assert plain.media_type == "application/octet-stream"
