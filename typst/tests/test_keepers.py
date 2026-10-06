"""The protocol keepers, the excused members and the real start (Z3, F17, Z7).

The backend sends `keepers` as a list of records, `entschuldigt` as a list and
`started_at` as a local `YYYY-MM-DD HH:MM` value. The legacy `protokoll` name
stays the fallback when `keepers` is missing.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from typst_service.compiler import default_compiler
from typst_service.document import build_document
from typst_service.frontmatter import parse_frontmatter, split_frontmatter

KEEPERS_DOC = """---
title: "GV"
typ: protokoll
datum: "2026-06-20 18:04"
beginn: "18:04"
ende: "20:10"
started_at: "2026-06-20 18:04"
protokoll: "Anna, Bert"
keepers:
  - name: "Anna"
    from: "18:04"
    to: "19:30"
    from_top: "1"
    to_top: "2"
  - name: "Bert"
    from: "19:30"
    to: "20:10"
    from_top: "3"
    to_top: "3"
anwesend:
  - "Anna"
  - "Bert"
entschuldigt:
  - "Cora"
abwesend:
  - "Dirk"
unterschriften:
  - "Schriftführung"
  - "Vorstand"
---

# Eins

Text eins.

# Zwei

# Drei

Text drei.
"""


def _row(doc: dict[str, object], label: str) -> str | None:
    rows = doc["data"]
    assert isinstance(rows, list)
    return next((r[1] for r in rows if r[0] == label), None)


def test_parse_frontmatter_keeps_records_apart() -> None:
    meta, records, body = parse_frontmatter(KEEPERS_DOC)
    assert "keepers" not in meta
    assert records["keepers"][1] == {
        "name": "Bert",
        "from": "19:30",
        "to": "20:10",
        "from_top": "3",
        "to_top": "3",
    }
    assert meta["entschuldigt"] == ["Cora"]
    assert body.startswith("# Eins")
    # The old entry point leaves the records out.
    assert "keepers" not in split_frontmatter(KEEPERS_DOC)[0]


def test_records_keep_only_strings() -> None:
    _, records, _ = parse_frontmatter("---\nkeepers:\n  - name: A\n    x: [1]\n---\n")
    assert records == {"keepers": [{"name": "A"}]}


def test_keepers_fill_the_protocol_row_and_the_signatures() -> None:
    doc = build_document(KEEPERS_DOC, variant="protocol-stupa")
    assert _row(doc, "Protokoll") == "Anna (TOP 1 – TOP 2), Bert (TOP 3 – TOP 3)"
    body = doc["body"]
    assert isinstance(body, list)
    assert body[-1] == {
        "t": "signatures",
        "signers": [["Schriftführung", "Anna"], ["Schriftführung", "Bert"], ["Vorstand", ""]],
    }


def test_handover_line_follows_the_heading_of_its_agenda_item() -> None:
    doc = build_document(KEEPERS_DOC, variant="protocol-stupa")
    body = doc["body"]
    assert isinstance(body, list)
    kinds = [(b["t"], b.get("level")) for b in body]
    third = [i for i, b in enumerate(body) if b["t"] == "heading" and b["level"] == 1][2]
    line = body[third + 1]
    assert line == {
        "t": "par",
        "c": [
            {
                "t": "emph",
                "c": [{"t": "text", "v": "Die Protokollführung übernimmt Bert um 19:30 Uhr."}],
            }
        ],
    }
    # The first period starts with the meeting and has no line.
    assert kinds.count(("par", None)) == 3


def test_period_without_top_shows_the_time_and_no_line() -> None:
    source = (
        "---\nkeepers:\n  - name: A\n    from: '18:00'\n    to: '18:30'\n"
        "  - name: B\n    from: '18:30'\n---\n\n# Eins\n"
    )
    doc = build_document(source, variant=None)
    assert _row(doc, "Protokoll") == "A (18:00 – 18:30), B (ab 18:30)"
    body = doc["body"]
    assert isinstance(body, list)
    assert [b["t"] for b in body] == ["heading"]


def test_single_keeper_prints_the_name_only() -> None:
    source = "---\nprotokoll: Alt\nkeepers:\n  - name: Neu\n    from: '18:00'\n---\n"
    assert _row(build_document(source, variant=None), "Protokoll") == "Neu"


def test_span_with_an_end_only() -> None:
    source = "---\nkeepers:\n  - name: A\n    to_top: '2'\n  - name: B\n---\n"
    assert _row(build_document(source, variant=None), "Protokoll") == "A (bis TOP 2), B"


def test_legacy_protokoll_without_keepers() -> None:
    source = "---\nprotokoll: Berta\nunterschriften:\n  - Schriftführung\n---\n"
    doc = build_document(source, variant=None)
    assert _row(doc, "Protokoll") == "Berta"
    body = doc["body"]
    assert isinstance(body, list)
    assert body[-1] == {"t": "signatures", "signers": [["Schriftführung", "Berta"]]}


def test_keepers_without_a_name_are_ignored() -> None:
    source = "---\nprotokoll: Berta\nkeepers:\n  - from: '18:00'\n---\n"
    assert _row(build_document(source, variant=None), "Protokoll") == "Berta"


def test_excused_members_are_their_own_group() -> None:
    doc = build_document(KEEPERS_DOC, variant="protocol-stupa")
    assert _row(doc, "Entschuldigt (1)") == "Cora"
    assert _row(doc, "Abwesend (1)") == "Dirk"
    doc = build_document("---\nexcused:\n  - Cora\n---\n", variant=None)
    assert _row(doc, "Entschuldigt (1)") == "Cora"


def test_started_at_fills_a_missing_date_and_start() -> None:
    source = "---\nstarted_at: '2026-06-20 18:04'\nende: '20:00'\n---\n"
    doc = build_document(source, variant=None)
    assert _row(doc, "Datum") == "20.06.2026, 18:04"
    assert _row(doc, "Zeit") == "18:04 – 20:00"  # noqa: RUF001 - an en dash
    # An explicit `datum` and `beginn` win.
    assert _row(build_document(KEEPERS_DOC, variant=None), "Datum") == "20.06.2026, 18:04"
    doc = build_document("---\nstarted_at: 'gestern'\n---\n", variant=None)
    assert _row(doc, "Datum") is None


@pytest.mark.integration
@pytest.mark.skipif(
    shutil.which("typst") is None or shutil.which("pdftotext") is None,
    reason="needs the typst CLI and poppler (nix develop .#typst)",
)
def test_keepers_render_into_the_pdf(tmp_path: Path) -> None:
    doc = build_document(KEEPERS_DOC, variant="protocol-stupa")
    pdf = asyncio.run(default_compiler().compile(doc, {}))
    out = tmp_path / "doc.pdf"
    out.write_bytes(pdf)
    text = subprocess.run(
        ["pdftotext", "-layout", str(out), "-"], check=True, capture_output=True, text=True
    ).stdout
    assert "Die Protokollführung übernimmt Bert um 19:30 Uhr." in text
    assert "Entschuldigt (1)" in text
