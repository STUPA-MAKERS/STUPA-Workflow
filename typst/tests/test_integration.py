"""Real `typst compile` runs. They need the typst CLI and poppler on PATH.

The layout checks pin the geometry that reproduces the pytex protocol: a
template change that moves the running head, the first agenda item or a box
fails here. The positions come from `pdftotext -bbox` of the pytex 1.2.0
output of the same fixtures.
"""

from __future__ import annotations

import asyncio
import html
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


def test_invalid_math_is_a_compile_error() -> None:
    from typst_service.compiler import CompileError

    with pytest.raises(CompileError):
        _render("Formel $\\frac{a}{$ und $\\begin{x}$", None)
