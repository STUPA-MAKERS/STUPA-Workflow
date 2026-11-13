"""The check of an embedded PDF (spec 000869).

A PDF cannot be re-encoded like an image, so the upload checks it before it is
stored: libmagic must sniff ``application/pdf``, pypdf must open it, it must not be
encrypted and it must have between 1 and ``MAX_PAGES`` pages. The service scans the
bytes with ClamAV before it calls ``check_pdf``, so pypdf reads only scanned bytes.

pypdf raises assorted error types on a broken PDF, so every exception of the read
makes the file "not readable" (415). A page count over the limit is a size problem
(413), not a type problem.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from app.modules.files.mime import sniff_mime

#: The only stored type of an embedded PDF.
PDF_MIME: Final[str] = "application/pdf"
#: The most pages of one embedded PDF.
MAX_PAGES: Final[int] = 100


class DocumentRejected(ValueError):
    """The bytes are no PDF that the server can read (415)."""


class DocumentTooLarge(ValueError):
    """The PDF has more than ``MAX_PAGES`` pages (413)."""


@dataclass(frozen=True, slots=True)
class CheckedPdf:
    """A PDF that passed the check, with its page count."""

    pages: int


def _page_count(data: bytes) -> tuple[bool, int]:
    """Return whether the PDF is encrypted and its page count.

    Raises:
        DocumentRejected: pypdf cannot read the PDF.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return (True, 0) if reader.is_encrypted else (False, len(reader.pages))
    except Exception as exc:
        raise DocumentRejected("The PDF cannot be read.") from exc


def check_pdf(data: bytes, *, max_pages: int = MAX_PAGES) -> CheckedPdf:
    """Check that ``data`` is a readable, unencrypted PDF within the page limit.

    Raises:
        DocumentRejected: No PDF by its content, unreadable or encrypted (415).
        DocumentTooLarge: More than ``max_pages`` pages (413).
    """
    if sniff_mime(data) != PDF_MIME:
        raise DocumentRejected("Only PDF files are accepted.")
    encrypted, pages = _page_count(data)
    if encrypted:
        raise DocumentRejected("An encrypted PDF is not accepted.")
    if pages < 1:
        raise DocumentRejected("The PDF has no pages.")
    if pages > max_pages:
        raise DocumentTooLarge(f"The PDF has more than {max_pages} pages.")
    return CheckedPdf(pages=pages)
