"""Guard the protocol title-page monkeypatch and the runtime version string.

The service reads the FastAPI `version` from `importlib.metadata`, so it cannot
drift from the installed `pytex-preprocessor` pin. The title-page patch fails
loud when a later version renames the private `_SCALAR_ROWS` attribute. These
tests check the extra cover-page labels and the version against the pin.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

from pytex_markdown.protocol import document as _protocol_document

import app as app_module


def test_scalar_rows_carry_extra_title_page_labels() -> None:
    labels = {label for label, _ in _protocol_document._SCALAR_ROWS}
    assert "Gremium" in labels
    assert "Beschlussfähigkeit" in labels


def test_beschlussfaehigkeit_keys_cover_both_spellings() -> None:
    rows = dict(_protocol_document._SCALAR_ROWS)
    assert rows["Beschlussfähigkeit"] == ("beschlussfaehigkeit", "beschlussfähigkeit")


def test_service_version_matches_installed_pytex() -> None:
    assert _pkg_version("pytex-preprocessor") == app_module._PYTEX_VERSION
    assert app_module.app.version == _pkg_version("pytex-preprocessor")
