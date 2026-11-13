"""Real `typst compile` runs. They need the typst CLI and poppler on PATH.

The layout checks pin the geometry that reproduces the pytex protocol: a
template change that moves the running head, the first agenda item or a box
fails here. The positions come from `pdftotext -bbox` of the pytex 1.2.0
output of the same fixtures.
"""

from __future__ import annotations

import asyncio
import html
import io
import re
import shutil
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from typst_service.compiler import default_compiler
from typst_service.document import build_document

from .conftest import FIXTURES

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("typst") is None or shutil.which("pdftotext") is None,
        reason="needs the typst CLI and poppler (nix develop .#typst)",
    ),
]


def _render(source: str, variant: str | None) -> bytes:
    doc = build_document(source, variant=variant)
    return asyncio.run(default_compiler().compile(doc, {}))


def _lines(pdf: bytes, tmp_path: Path) -> list[tuple[int, float, float, str]]:
    path = tmp_path / "out.pdf"
    path.write_bytes(pdf)
    bbox = subprocess.run(
        ["pdftotext", "-bbox-layout", str(path), "-"], capture_output=True, text=True, check=True
    ).stdout
    out: list[tuple[int, float, float, str]] = []
    for page, chunk in enumerate(bbox.split("<page ")[1:], start=1):
        line_re = r'<line xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>(.*?)</line>'
        for m in re.finditer(line_re, chunk, re.S):
            words = html.unescape(" ".join(re.findall(r">([^<]*)</word>", m.group(3))))
            out.append((page, float(m[1]), float(m[2]), words))
    return out


def _find(lines: list[tuple[int, float, float, str]], prefix: str) -> tuple[int, float, float]:
    page, x, y, _ = next(line for line in lines if line[3].startswith(prefix))
    return page, x, y


def test_full_protocol_matches_the_pytex_layout(tmp_path: Path) -> None:
    pdf = _render((FIXTURES / "protocol-full.md").read_text(), "protocol-stupa")
    assert pdf.startswith(b"%PDF")
    lines = _lines(pdf, tmp_path)
    # (text, page, x, y) from the pytex 1.2.0 render of the same fixture.
    expected = [
        ("Ordentliche Sitzung des", 1, 56.69, 197.79),
        ("Ordentliche Sitzung des Studierendenparlaments im Sommersemester", 2, 56.69, 29.09),
        ("TOP 1 Begrüßung", 2, 56.69, 61.87),
        ("TOP 1.1 Genehmigung", 2, 56.69, 156.01),
        ("Seite 1 von", 2, 270.44, 798.53),
    ]
    for text, page, x, y in expected:
        got = _find(lines, text)
        assert got[0] == page, text
        assert got[1] == pytest.approx(x, abs=0.5), text
        assert got[2] == pytest.approx(y, abs=1.5), text
    text = " ".join(line[3] for line in lines)
    for needle in (
        "Beschluss:",
        "Aufgabe:",
        "Frist:",
        "Ja:",
        "Nein:",
        "Enthaltung:",
        "Unterschriften",
        "Berta Beispiel",
    ):
        assert needle in text
    # The fixes over pytex: formatted date, no application fence, € in a box.
    assert "15.06.2026, 18:30" in text
    assert ":::" not in text and "0b9f3c5e" not in text
    assert "1.650 € gefördert" in text


def test_public_protocol_matches_the_pytex_layout(tmp_path: Path) -> None:
    pdf = _render((FIXTURES / "protocol-public.md").read_text(), "protocol-asta")
    lines = _lines(pdf, tmp_path)
    for text, page, y in (
        ("Sitzung des AStA", 1, 197.79),
        ("TOP 1 Bericht", 2, 61.87),
        ("TOP 2 Nicht-öffentlicher", 2, 136.54),
        ("Unterschriften", 2, 232.9),
    ):
        got = _find(lines, text)
        assert (got[0], got[2]) == (page, pytest.approx(y, abs=1.0)), text
    # The head counts of the public variant reach the title page.
    assert _find(lines, "Anwesend")[0] == 1


def test_markup_in_the_source_prints_as_text(tmp_path: Path) -> None:
    source = (
        '---\ntitle: "#panic(\\"x\\") *t*"\n---\n\n'
        '# #read("/etc/passwd")\n\n'
        '#set page(fill: red) $$ \\\\ _x_ <l> @r `#eval("1")`\n'
    )
    lines = _lines(_render(source, None), tmp_path)
    text = " ".join(line[3] for line in lines)
    assert '#panic("x") *t*' in text
    assert '#read("/etc/passwd")' in text
    assert "#set page(fill: red)" in text
    assert "root:" not in text


def test_poll_renders_as_a_ranking(tmp_path: Path) -> None:
    source = (
        "---\ngremium: StuPa\n---\n\n# Ausflug\n\n"
        "> [!abstimmung] **Wohin?**\n> Umfrage · Einzelwahl\n"
        "> Freiburg: 7\n> Konstanz: 7\n> Tübingen: 2\n> Enthaltungen: 1\n"
        "> Meiste Stimmen: Freiburg, Konstanz\n"
        "> 17 Antworten\n\n"
        "> [!abstimmung] **Wann?**\n> Terminumfrage\n"
        "> Mi, 4.11. · 17:00–19:00: 6 (+3)\n> Di, 3.11. · 18:00–20:00: 5 (+2)\n"
        "> Zahl = Ja, (+n) = Vielleicht\n> Bester Termin: Mi, 4.11. · 17:00–19:00\n"
        "> 10 Antworten\n\n"
        "> [!abstimmung] **Offen?**\n> Umfrage · Mehrfachwahl, höchstens 2\n"
    )
    lines = [line[3] for line in _lines(_render(source, None), tmp_path)]
    text = " ".join(lines)
    # A tie marks both options; the date poll prints Ja + Vielleicht.
    assert text.count("meiste Stimmen") == 2
    assert "bester Termin" in text
    assert "6 + 3" in text
    assert "Ja Vielleicht" in text
    assert "Zahl = Ja" not in text
    assert "Meiste Stimmen:" not in text
    assert "17 Antworten" in text
    assert "Umfrage · Mehrfachwahl, höchstens 2" in text


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    pixels = zlib.compress(b"\x00\xff\x00\x00")
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", pixels) + chunk(b"IEND", b"")
    )


def test_uploaded_logos_render(tmp_path: Path) -> None:
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
        b'<rect width="10" height="10" fill="red"/></svg>'
    )
    assets = {"a1-logo.png": _png(), "a2-logo.svg": svg}
    doc = build_document(
        "---\ngremium: StuPa\n---\n\nText\n",
        variant="protocol-stupa",
        config={"logos": ["a1-logo.png", "STUPA"], "footer_logos": ["a2-logo.svg"]},
        assets=assets.keys(),
    )
    pdf = asyncio.run(default_compiler().compile(doc, assets))
    assert pdf.startswith(b"%PDF")


def test_uploaded_images_render_inline_and_as_block() -> None:
    image_id = "0b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d"
    name = f"img-{image_id}.png"
    path = f"/api/media/images/{image_id}"
    source = (
        "---\ngremium: StuPa\n---\n\n# Bericht\n\n"
        f"![Foto]({path})\n\nText ![klein]({path}) im Satz.\n\n"
        f"| Bild | Text |\n|---|---|\n| ![z]({path}) | x |\n\n"
        "![fehlt](/api/media/images/11111111-2222-4333-8444-555555555555)\n"
    )
    doc = build_document(source, variant="protocol-stupa", assets=[name])
    pdf = asyncio.run(default_compiler().compile(doc, {name: _png()}))
    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" in pdf or b"/Subtype/Image" in pdf


def test_invalid_math_is_a_compile_error() -> None:
    from typst_service.compiler import CompileError

    with pytest.raises(CompileError):
        _render("Formel $\\frac{a}{$ und $\\begin{x}$", None)


def test_signatures_never_split_across_pages(tmp_path: Path) -> None:
    filler = "".join(f"\n\nZusatzzeile {k} mit etwas Text." for k in range(28))
    source = (FIXTURES / "protocol-full.md").read_text() + filler
    lines = _lines(_render(source, None), tmp_path)
    heading_page = _find(lines, "Unterschriften")[0]
    assert _find(lines, "Vorstand")[0] == heading_page


def test_protocol_is_pdf_ua_1_with_title_and_language() -> None:
    """The PDF declares PDF/UA-1, a title and German (§ NF/accessibility/documents/000524)."""
    pdf = _render((FIXTURES / "protocol-full.md").read_text(), None)
    assert b"pdfuaid:part" in pdf
    assert b"/Lang (de)" in pdf or b"/Lang(de)" in pdf
    assert b"/Title" in pdf


def test_decorative_image_and_formula_pass_pdf_ua() -> None:
    """An image without alt text is an artifact, and a formula has its source as alt text.

    § NF/accessibility/documents/000524
    """
    image_id = "0b7c6f0e-3a51-4c3e-9b8e-6f1d2a3b4c5d"
    name = f"img-{image_id}.png"
    source = (
        f"---\ngremium: StuPa\n---\n\n# Bericht\n\n![](/api/media/images/{image_id})\n\n$a^2$\n"
    )
    doc = build_document(source, variant="protocol-stupa", assets=[name])
    assert asyncio.run(default_compiler().compile(doc, {name: _png()})).startswith(b"%PDF")


def test_skipped_heading_level_keeps_the_top_numbers(tmp_path: Path) -> None:
    """A `###` after `#` passes PDF/UA-1 and leaves the next TOP number as it was.

    § NF/accessibility/documents/000524
    """
    source = "---\ngremium: StuPa\n---\n\n# Eins\n\n### Unter\n\nText.\n\n## Zwei\n\nText.\n"
    lines = _lines(_render(source, None), tmp_path)
    assert any(line[3].startswith("TOP 1.1") and "Zwei" in line[3] for line in lines)
    assert not any(line[3].startswith("TOP") and "Unter" in line[3] for line in lines)


def test_time_notes_print_centered_above_the_top(tmp_path: Path) -> None:
    """§000871 and §000872: the time of a TOP is a centered line right above its heading."""
    source = (
        "---\ntitle: T\n---\n\n"
        "> [!anmerkung 18:30]\n\n# Begrüßung\n\nText.\n\n"
        "> [!anmerkung 18:47] %%Max%% verlässt die Sitzung.\n\n"
        "> [!anmerkung 18:52]\n\n# Haushalt\n\nText.\n"
    )
    lines = _lines(_render(source, None), tmp_path)
    time_page, time_x, time_y = _find(lines, "18:30 Uhr")
    top_page, _, top_y = _find(lines, "TOP 1")
    assert time_page == top_page
    assert 0 < top_y - time_y < 30
    assert time_x > 250
    assert any(line[3] == "18:47 Uhr · Max verlässt die Sitzung." for line in lines)
    _, _, second_y = _find(lines, "18:52 Uhr")
    _, _, top2_y = _find(lines, "TOP 2")
    assert 0 < top2_y - second_y < 30


def test_embedded_pdfs_become_watermarked_anlagen_with_linked_references(tmp_path: Path) -> None:
    """§000864, §000865 and §000866: the Anlagen follow the protocol, each page has the
    watermark, and the reference prints the page of the Anlage and links to it."""
    from pypdf import PdfReader

    from typst_service.app import _appendix_of, _document_sizes
    from typst_service.appendix import document_assets, merge_appendix

    from .test_appendix import A, B, make_pdf

    source = (
        '---\ntitle: "GV"\ndatum: "2026-06-15"\n---\n\n# Haushalt\n\n'
        f"Siehe [Haushaltsplan.pdf](/api/media/documents/{A}) und "
        f"[Angebot.pdf](/api/media/documents/{B}).\n"
    )
    assets = {
        f"doc-{A}.pdf": make_pdf((595, 842), (595, 842)),
        f"doc-{B}.pdf": make_pdf((842, 595)),
    }
    documents = document_assets(assets)
    sizes = _document_sizes(documents)
    doc = build_document(source, variant=None, assets=assets.keys(), documents=sizes)
    compiled = asyncio.run(default_compiler().compile(doc, assets))
    pdf = merge_appendix(compiled, _appendix_of(doc, sizes), documents)
    reader = PdfReader(io.BytesIO(pdf))
    pages = len(reader.pages)
    lines = _lines(pdf, tmp_path)
    text = " ".join(line[3] for line in lines)
    assert "Anlage 1: Haushaltsplan.pdf (Seite 2)" in text
    assert "Anlage 2: Angebot.pdf (Seite 4)" in text
    tail = [reader.pages[i] for i in range(pages - 3, pages)]
    assert [round(float(p.mediabox.width)) for p in tail] == [595, 595, 842]
    marks = [p.extract_text() for p in tail]
    assert all("zum Protokoll GV vom 15.06.2026" in m for m in marks)
    assert "Anlage 1" in marks[0] and "Quelle 1" in marks[0]
    assert "Anlage 2" in marks[2] and "Quelle 1" in marks[2]
    index = {page.indirect_reference.idnum: i for i, page in enumerate(reader.pages)}  # pyright: ignore[reportOptionalMemberAccess]
    targets = [
        index[annot.get_object()["/Dest"][0].idnum]
        for annot in reader.pages[1].get("/Annots", [])
        if "/Dest" in annot.get_object()
    ]
    assert targets == [pages - 3, pages - 1]


def _gray_page(pdf: bytes, tmp_path: Path, page: int, dpi: int) -> tuple[int, bytes]:
    """Render one page as an 8-bit gray PGM and return its width and pixels."""
    path = tmp_path / "bar.pdf"
    path.write_bytes(pdf)
    pgm = subprocess.run(
        ["pdftoppm", "-gray", "-r", str(dpi), "-f", str(page), "-l", str(page), str(path)],
        capture_output=True,
        check=True,
    ).stdout
    head = pgm.split(b"\n", 3)
    width = int(head[1].split()[0])
    return width, head[3]


def _dark_rows(pixels: bytes, width: int, x0: int, x1: int) -> list[int]:
    """The rows with a dark pixel between the columns x0 and x1."""
    rows = len(pixels) // width
    return [y for y in range(rows) if any(pixels[y * width + x] < 100 for x in range(x0, x1))]


def test_a_black_bar_sits_on_the_baseline(tmp_path: Path) -> None:
    """§000887: the bar reaches from just under the baseline to the cap height."""
    pdf = _render("---\ntitle: T\n---\n\nHalli %%%% HHH\n", None)
    lines = _lines(pdf, tmp_path)
    page, x, y = _find(lines, "Halli")
    dpi = 144
    scale = dpi / 72
    width, pixels = _gray_page(pdf, tmp_path, page, dpi)
    top = round((y - 2) * scale)
    band = pixels[top * width : (top + round(24 * scale)) * width]
    letters = _dark_rows(band, width, round(x * scale), round((x + 4) * scale))
    bar = _dark_rows(band, width, round((x + 40) * scale), round((x + 50) * scale))
    baseline, cap = letters[-1], letters[0]
    assert 0 <= bar[-1] - baseline <= round(2 * scale)
    assert abs(bar[0] - cap) <= round(1.5 * scale)
