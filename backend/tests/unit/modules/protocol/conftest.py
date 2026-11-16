"""Shared fixtures: the protocol render reads no PDF branding from the fake sessions."""

from __future__ import annotations

import pytest

from app.modules.files.pdf_branding import PdfBranding
from app.modules.protocol import service as protocol_service


@pytest.fixture(autouse=True)
def _no_pdf_branding(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake sessions hold no ``pdf_asset`` rows: the render gets an empty branding.

    ``test_protocol_images`` overrides it to test the footer graphic.
    """

    async def empty(_session: object, _storage: object) -> PdfBranding:
        return PdfBranding()

    monkeypatch.setattr(protocol_service, "active_pdf_branding", empty)
