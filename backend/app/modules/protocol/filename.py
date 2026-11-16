r"""The download name of a protocol PDF: the meeting title and the meeting day.

Every place that hands out a protocol PDF uses this name: the mail attachment at the
finalization, the internal stream (`/protocols/{id}/pdf`), the redacted internal stream
(`/protocols/{id}/pdf/public`) and the public download (`/public/protocols/{id}/pdf`).
A saved file then says which meeting it belongs to, instead of a bare `protokoll.pdf`.

The name keeps the Unicode letters of the title, so `Sitzung Fachschaft Ökonomie` keeps
its umlaut. It removes the characters that a file system or a header cannot take
(`/ \\ : * ? " < > |`, control and format characters) and joins the words with `_`, so
the name survives a mail client, a shell and Windows. The day is ISO (`2026-11-05`),
because a folder of protocols then sorts by date. The caller passes the name through
`content_disposition` or the mail encoder, which handle the non-ASCII part.
"""

from __future__ import annotations

from datetime import date

from app.shared.filenames import TITLE_MAX, title_token

__all__ = ["TITLE_MAX", "protocol_pdf_filename"]


def protocol_pdf_filename(title: str | None, day: date, *, public: bool = False) -> str:
    """Build the download name of a protocol PDF.

    Args:
        title: The meeting title. An empty title leaves only the day.
        day: The meeting day (`meeting_day`).
        public: `True` for the redacted public variant, which ends in `_oeffentlich`.

    Returns:
        For example `Protokoll_3._ordentliche_Sitzung_STUPA_2026-11-05.pdf`, or
        `Protokoll_2026-11-05_oeffentlich.pdf` without a title.
    """
    stem = title_token(title)
    parts = (
        "Protokoll",
        *([stem] if stem else []),
        day.isoformat(),
        *(["oeffentlich"] if public else []),
    )
    return "_".join(parts) + ".pdf"
