"""Guard the protocol title-page monkeypatch and the runtime version string.

AUD-061: the FastAPI ``version`` is read from ``importlib.metadata`` so it can
never drift from the installed ``pytex-preprocessor`` pin, and the title-page
patch fails loud (not silent) if the private ``_SCALAR_ROWS`` attribute is ever
renamed by a future bump. These tests assert the two extra cover-page labels are
actually installed and that the version surfaces the real pin.
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
    assert app_module._PYTEX_VERSION == _pkg_version("pytex-preprocessor")
    assert app_module.app.version == _pkg_version("pytex-preprocessor")
