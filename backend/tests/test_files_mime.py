"""Unit-Tests MIME-Sniffing + Allowlist (T-13, security.md §6).

`libmagic` wird über ein Fake-`magic`-Modul ersetzt (kein System-libmagic im Unit-Lauf).
"""

from __future__ import annotations

import sys
import types

import pytest

from app.modules.files import mime as mime_mod
from app.modules.files.mime import (
    MimeRejected,
    file_extension,
    sniff_mime,
    validate_upload,
)


@pytest.fixture
def fake_magic(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Installiert ein Fake-`magic`-Modul; Rückgabe = veränderbarer Sniff-Wert."""
    state = {"mime": "application/pdf"}
    module = types.ModuleType("magic")
    module.from_buffer = lambda data, mime: state["mime"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "magic", module)
    return state


def test_file_extension() -> None:
    assert file_extension("a.PDF") == ".pdf"
    assert file_extension("noext") == ""
    assert file_extension(None) == ""
    assert file_extension("archive.tar.gz") == ".gz"


def test_sniff_empty_is_x_empty() -> None:
    assert sniff_mime(b"") == "application/x-empty"


def test_sniff_uses_libmagic(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "image/png"
    assert sniff_mime(b"\x89PNG...") == "image/png"


def test_validate_pdf_ok(fake_magic: dict[str, str]) -> None:
    assert validate_upload("report.pdf", b"%PDF") == "application/pdf"


def test_validate_png_ok(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "image/png"
    assert validate_upload("logo.png", b"\x89PNG") == "image/png"


def test_validate_docx_zip_sniff_ok(fake_magic: dict[str, str]) -> None:
    # OOXML snifft teils als application/zip → für .docx zulässig.
    fake_magic["mime"] = "application/zip"
    assert validate_upload("brief.docx", b"PK\x03\x04") == "application/zip"


def test_validate_disallowed_type_rejected(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "application/x-dosexec"
    with pytest.raises(MimeRejected):
        validate_upload("evil.pdf", b"MZ")


def test_validate_mismatch_ext_rejected(fake_magic: dict[str, str]) -> None:
    # Inhalt PDF, aber als .png deklariert → Sniff ≠ Endung.
    fake_magic["mime"] = "application/pdf"
    with pytest.raises(MimeRejected):
        validate_upload("photo.png", b"%PDF")


def test_validate_unknown_extension_rejected(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "application/pdf"
    with pytest.raises(MimeRejected):
        validate_upload("file.xyz", b"%PDF")


def test_validate_no_extension_rejected(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "application/pdf"
    with pytest.raises(MimeRejected):
        validate_upload("noext", b"%PDF")


def test_allowlist_contains_office_and_images() -> None:
    assert "application/pdf" in mime_mod.ALLOWED_MIME_TYPES
    assert "image/jpeg" in mime_mod.ALLOWED_MIME_TYPES
    assert (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        in mime_mod.ALLOWED_MIME_TYPES
    )
