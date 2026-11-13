"""The embedded PDFs: page sizes, numbering, budget and the merge under the Anlage pages."""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from typst_service.appendix import (
    Appendix,
    document_assets,
    merge_appendix,
    number_documents,
    page_sizes,
)
from typst_service.markdown import convert_body

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"


def make_pdf(*sizes: tuple[float, float], rotate: int = 0, password: str | None = None) -> bytes:
    """A PDF with one line of text `Quelle <k>` on each page."""
    writer = PdfWriter()
    for k, (w, h) in enumerate(sizes, start=1):
        page = writer.add_blank_page(width=w, height=h)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        content = DecodedStreamObject()
        content.set_data(f"BT /F1 12 Tf 40 40 Td (Quelle {k}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)
        if rotate:
            page.rotate(rotate)
    if password is not None:
        writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_page_sizes_turn_a_rotated_page_and_refuse_a_bad_pdf() -> None:
    assert page_sizes(make_pdf((595, 842), (842, 595))) == ((595, 842), (842, 595))
    assert page_sizes(make_pdf((595, 842), rotate=90)) == ((842, 595),)
    assert page_sizes(make_pdf((595, 842), password="geheim")) is None
    assert page_sizes(b"%PDF-1.7 kaputt") is None
    assert page_sizes(b"no pdf") is None


def test_document_assets_take_only_pdf_assets() -> None:
    assets = {f"doc-{A}.pdf": b"a", f"img-{A}.png": b"b", "doc-x.pdf": b"c"}
    assert document_assets(assets) == {A: b"a"}


def _refs(markdown: str, *docs: str) -> list[dict[str, object]]:
    return convert_body(markdown, {}, [f"doc-{d}.pdf" for d in docs])


def test_number_documents_follows_the_first_reference() -> None:
    """§000864: one Anlage per PDF, numbered by its first reference, named by it."""
    blocks = _refs(
        f"[Zwei](/api/media/documents/{B}) und [Eins](/api/media/documents/{A}).\n\n"
        f"> [Zwei wieder](/api/media/documents/{B})",
        A,
        B,
    )
    sizes = {A: ((595.0, 842.0),), B: ((595.0, 842.0), (842.0, 595.0))}
    numbered, appendix = number_documents(blocks, sizes)
    assert [(a.number, a.doc, a.name, len(a.pages)) for a in appendix] == [
        (1, B, "Zwei", 2),
        (2, A, "Eins", 1),
    ]
    par = numbered[0]["c"]
    assert par[0] == {"t": "docref", "doc": B, "name": "Zwei", "n": 1}  # pyright: ignore[reportIndexIssue]
    quote = numbered[1]["c"][0]["c"][0]  # pyright: ignore[reportIndexIssue]
    assert quote == {"t": "docref", "doc": B, "name": "Zwei", "n": 1}


def test_a_missing_or_unreadable_pdf_or_one_past_the_budget_is_no_anlage() -> None:
    """§000868: such a reference prints "Anlage nicht eingebunden"."""
    blocks = _refs(
        f"[A](/api/media/documents/{A}) [B](/api/media/documents/{B}) "
        f"[C](/api/media/documents/{C}) [D](/api/media/documents/{C.replace('3', '4')})",
        A,
        B,
        C,
    )
    sizes = {A: ((1.0, 1.0),) * 2, C: ((1.0, 1.0),) * 2}
    numbered, appendix = number_documents(blocks, sizes, max_pages=3)
    assert [a.doc for a in appendix] == [A]
    inline = numbered[0]["c"]
    kinds = [n["t"] for n in inline if n["t"] != "text"]  # pyright: ignore[reportGeneralTypeIssues]
    assert kinds == ["docref", "docmiss", "docmiss", "docmiss"]
    _, by_count = number_documents(blocks, sizes, max_count=1)
    assert [a.doc for a in by_count] == [A]


def test_a_plain_link_and_a_bad_path_stay_what_they_are() -> None:
    (par,) = _refs(f"[x](https://example.org) [y](/api/media/documents/{A}/x)", A)
    assert [n["t"] for n in par["c"]] == ["link", "text", "text"]  # pyright: ignore[reportGeneralTypeIssues]


def _blank_target(*sizes: tuple[float, float]) -> bytes:
    writer = PdfWriter()
    for w, h in sizes:
        writer.add_blank_page(width=w, height=h)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_merge_puts_each_page_under_its_anlage_page_as_an_artifact() -> None:
    """§000864: the last pages get the pages of the PDFs, in the order of the Anlagen."""
    first = make_pdf((595, 842), (842, 595))
    second = make_pdf((595, 842), rotate=90)
    target = _blank_target((595, 842), (595, 842), (842, 595), (842, 595))
    appendix = (
        Appendix(number=1, doc=A, name="a", pages=((595, 842), (842, 595))),
        Appendix(number=2, doc=B, name="b", pages=((842, 595),)),
    )
    merged = PdfReader(io.BytesIO(merge_appendix(target, appendix, {A: first, B: second})))
    assert len(merged.pages) == 4
    texts = [page.extract_text() for page in merged.pages]
    assert texts == ["", "Quelle 1", "Quelle 2", "Quelle 1"]
    contents = merged.pages[1].get_contents()
    assert contents is not None
    assert contents.get_data().startswith(b"/Artifact BMC q /Anlage Do Q EMC")


def test_merge_without_anlagen_keeps_the_pdf_and_refuses_too_few_pages() -> None:
    target = _blank_target((595, 842))
    assert merge_appendix(target, (), {}) == target
    appendix = (Appendix(number=1, doc=A, name="a", pages=((1, 1), (1, 1))),)
    with pytest.raises(ValueError, match="fewer pages"):
        merge_appendix(target, appendix, {A: make_pdf((1, 1), (1, 1))})
