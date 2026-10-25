"""Unit tests for MIME sniffing and the allowlist.

A fake `magic` module replaces `libmagic`. The unit run needs no system libmagic.
"""

from __future__ import annotations

import io
import sys
import types
import zipfile

import pytest

from app.modules.files import mime as mime_mod
from app.modules.files.mime import (
    MimeRejected,
    file_extension,
    sniff_mime,
    validate_upload,
)


def _ooxml_zip(top_dir: str) -> bytes:
    """Build a minimal valid OOXML package: `[Content_Types].xml` and a format directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(f"{top_dir}document.xml", "<xml/>")
    return buf.getvalue()


@pytest.fixture
def fake_magic(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Install a fake `magic` module and return the mutable sniff state."""
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
    """Accept a .docx sniffed as zip when the container has the OOXML structure."""
    fake_magic["mime"] = "application/zip"
    assert validate_upload("brief.docx", _ooxml_zip("word/")) == "application/zip"


def test_validate_xlsx_pptx_zip_sniff_ok(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "application/zip"
    assert validate_upload("tab.xlsx", _ooxml_zip("xl/")) == "application/zip"
    assert validate_upload("slides.pptx", _ooxml_zip("ppt/")) == "application/zip"


def test_validate_arbitrary_zip_as_docx_rejected(fake_magic: dict[str, str]) -> None:
    """Reject a ZIP without OOXML structure disguised as .docx."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("evil.sh", "rm -rf /")
    fake_magic["mime"] = "application/zip"
    with pytest.raises(MimeRejected):
        validate_upload("brief.docx", buf.getvalue())


def test_validate_zip_wrong_format_dir_rejected(fake_magic: dict[str, str]) -> None:
    """Reject a Word structure declared as .xlsx: the top-level directory is wrong."""
    fake_magic["mime"] = "application/zip"
    with pytest.raises(MimeRejected):
        validate_upload("tab.xlsx", _ooxml_zip("word/"))


def test_validate_corrupt_zip_as_docx_rejected(fake_magic: dict[str, str]) -> None:
    """Reject a magic header without a readable ZIP."""
    fake_magic["mime"] = "application/zip"
    with pytest.raises(MimeRejected):
        validate_upload("brief.docx", b"PK\x03\x04")


def test_validate_disallowed_type_rejected(fake_magic: dict[str, str]) -> None:
    fake_magic["mime"] = "application/x-dosexec"
    with pytest.raises(MimeRejected):
        validate_upload("evil.pdf", b"MZ")


def test_validate_mismatch_ext_rejected(fake_magic: dict[str, str]) -> None:
    """Reject PDF content declared as .png."""
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
