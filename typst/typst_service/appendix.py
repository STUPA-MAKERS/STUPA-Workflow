"""The embedded PDFs of a protocol: the Anlagen at the end of the protocol PDF.

A protocol text refers to an uploaded PDF as `[name](/api/media/documents/<uuid>)`.
The caller sends the bytes as the asset `doc-<uuid>.pdf`. The service makes each
referenced PDF an Anlage in three steps:

1. `page_sizes` reads the size of each page with pypdf. A PDF that pypdf cannot
   read, or that is encrypted, has no size and is no Anlage.
2. `number_documents` numbers the PDFs in the order of their first reference and
   keeps them within the budget (`MAX_APPENDICES`, `MAX_APPENDIX_PAGES`). A
   reference to a PDF that is no Anlage becomes a `docmiss` node, which prints
   "Anlage nicht eingebunden". The template prints one empty page with the
   watermark per Anlage page, in the size of that page, at the end of the PDF.
   The reference links to the first of these pages and prints its number.
3. `merge_appendix` puts each page of each PDF under its empty page, after the
   compile. typst refuses an embedded PDF in a PDF/UA-1 document, and a
   conversion to SVG blows the size up by two orders of magnitude, so the pages
   go in after the compile. A page goes in as a form XObject inside an
   `/Artifact` marked-content sequence: the PDF/UA tags of the protocol stay
   valid, and a screen reader reads the alt text of the empty page. The links,
   forms and scripts of the source page do not come along, because only the
   content stream and its resources are copied.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    IndirectObject,
    NameObject,
    PdfObject,
    StreamObject,
)

__all__ = [
    "DOCUMENT_ASSET_RE",
    "DOCUMENT_PATH_RE",
    "MAX_APPENDICES",
    "MAX_APPENDIX_PAGES",
    "Appendix",
    "Size",
    "document_assets",
    "merge_appendix",
    "number_documents",
    "page_sizes",
]

_UUID: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
#: The canonical path of an uploaded PDF (the backend media module).
DOCUMENT_PATH_RE: Final[re.Pattern[str]] = re.compile(rf"^/api/media/documents/({_UUID})$")
#: The asset name of an uploaded PDF: `doc-<uuid>.pdf`.
DOCUMENT_ASSET_RE: Final[re.Pattern[str]] = re.compile(rf"^doc-({_UUID})\.pdf$")

#: The most Anlagen of one protocol PDF (spec 000868).
MAX_APPENDICES: Final[int] = 20
#: The most Anlage pages of one protocol PDF (spec 000868).
MAX_APPENDIX_PAGES: Final[int] = 300

type Size = tuple[float, float]
type Node = dict[str, object]


@dataclass(frozen=True, slots=True)
class Appendix:
    """One Anlage: its number, its PDF, its file name and the size of each page."""

    number: int
    doc: str
    name: str
    pages: tuple[Size, ...]


def document_assets(assets: Mapping[str, bytes]) -> dict[str, bytes]:
    """Map the uuid of each uploaded PDF asset to its bytes."""
    matches = ((DOCUMENT_ASSET_RE.fullmatch(name), data) for name, data in assets.items())
    return {match.group(1): data for match, data in matches if match is not None}


def _rotation(page: PageObject) -> int:
    return int(page.rotation) % 360


def _box(page: PageObject) -> tuple[float, float, float, float]:
    box = page.cropbox
    return (float(box.left), float(box.bottom), float(box.right), float(box.top))


def _shown_size(page: PageObject) -> Size:
    """The size of a page as a viewer shows it: the crop box, turned by `/Rotate`."""
    x0, y0, x1, y1 = _box(page)
    width, height = abs(x1 - x0), abs(y1 - y0)
    return (height, width) if _rotation(page) in (90, 270) else (width, height)


def page_sizes(data: bytes) -> tuple[Size, ...] | None:
    """Return the shown size of each page in pt, or None for a PDF that is no Anlage.

    An encrypted PDF, a PDF that pypdf cannot read and a PDF without pages give None.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return None
        sizes = tuple(_shown_size(page) for page in reader.pages)
    except (PyPdfError, ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError):
        return None
    return sizes if sizes and all(w > 0 and h > 0 for w, h in sizes) else None


def _walk(value: object) -> list[Node]:
    """Return every node of a tree in document order."""
    if isinstance(value, list):
        return [node for item in cast("list[object]", value) for node in _walk(item)]
    if isinstance(value, dict):
        node = cast("Node", value)
        return [node, *(n for item in node.values() for n in _walk(item))]
    return []


def _rewrite(value: object, numbers: Mapping[str, int], names: Mapping[str, str]) -> object:
    """Give each `docref` its number and the name of its Anlage, or make it a `docmiss`."""
    if isinstance(value, list):
        return [_rewrite(item, numbers, names) for item in cast("list[object]", value)]
    if not isinstance(value, dict):
        return value
    node = cast("Node", value)
    if node.get("t") == "docref":
        doc = str(node["doc"])
        return (
            {**node, "n": numbers[doc], "name": names.get(doc, node["name"])}
            if doc in numbers
            else {"t": "docmiss", "name": node["name"]}
        )
    return {key: _rewrite(item, numbers, names) for key, item in node.items()}


def _within_budget(
    order: Sequence[str], sizes: Mapping[str, tuple[Size, ...]], max_count: int, max_pages: int
) -> tuple[str, ...]:
    """Keep the PDFs in order while the count and the page sum stay within the budget."""
    if not order or max_count <= 0:
        return ()
    first, rest = order[0], order[1:]
    pages = len(sizes[first])
    return (
        (first, *_within_budget(rest, sizes, max_count - 1, max_pages - pages))
        if pages <= max_pages
        else _within_budget(rest, sizes, max_count, max_pages)
    )


def number_documents(
    blocks: list[Node],
    sizes: Mapping[str, tuple[Size, ...]],
    *,
    max_count: int = MAX_APPENDICES,
    max_pages: int = MAX_APPENDIX_PAGES,
) -> tuple[list[Node], tuple[Appendix, ...]]:
    """Number the referenced PDFs and return the blocks with their Anlagen.

    The numbers follow the first reference. The name of an Anlage is the label of
    its first reference. A PDF without sizes, or one past the budget, is no Anlage.
    """
    refs = [node for node in _walk(blocks) if node.get("t") == "docref"]
    names = {str(node["doc"]): str(node["name"]) for node in reversed(refs)}
    order = tuple(dict.fromkeys(str(node["doc"]) for node in refs if str(node["doc"]) in sizes))
    kept = _within_budget(order, sizes, max_count, max_pages)
    numbers = {doc: number for number, doc in enumerate(kept, start=1)}
    appendix = tuple(
        Appendix(number=numbers[doc], doc=doc, name=names[doc], pages=sizes[doc]) for doc in kept
    )
    return cast("list[Node]", _rewrite(blocks, numbers, names)), appendix


# -- merge ------------------------------------------------------------------


def _matrix(page: PageObject) -> list[float]:
    """The form matrix that moves the crop box of a page to the origin and turns it."""
    x0, y0, x1, y1 = _box(page)
    width, height = abs(x1 - x0), abs(y1 - y0)
    match _rotation(page):
        case 90:
            return [0, -1, 1, 0, -y0, x0 + width]
        case 180:
            return [-1, 0, 0, -1, x0 + width, y0 + height]
        case 270:
            return [0, 1, -1, 0, y0 + height, -x0]
        case _:
            return [1, 0, 0, 1, -x0, -y0]


def _put(target: DictionaryObject, key: str, value: PdfObject) -> DictionaryObject:
    """Set one entry of a pypdf dictionary and return the dictionary."""
    target.update({NameObject(key): value})
    return target


def _filled(stream: StreamObject, data: bytes, entries: Mapping[str, PdfObject]) -> StreamObject:
    """Give a pypdf stream its data and its entries and return the stream."""
    stream.set_data(data)
    stream.update({NameObject(key): value for key, value in entries.items()})
    return stream


def _form(writer: PdfWriter, page: PageObject) -> IndirectObject:
    """Copy the content and the resources of a page into a form XObject of `writer`."""
    contents = page.get_contents()
    resources = page.get("/Resources")
    x0, y0, x1, y1 = _box(page)
    form = _filled(
        DecodedStreamObject(),
        contents.get_data() if contents is not None else b"",
        {
            "/Type": NameObject("/XObject"),
            "/Subtype": NameObject("/Form"),
            "/BBox": ArrayObject([FloatObject(v) for v in (x0, y0, x1, y1)]),
            "/Matrix": ArrayObject([FloatObject(v) for v in _matrix(page)]),
            "/Resources": (
                resources.get_object().clone(writer)
                if resources is not None
                else DictionaryObject()
            ),
        },
    )
    return writer._add_object(form)


def _underlay(writer: PdfWriter, target: PageObject, form: IndirectObject) -> None:
    """Draw `form` under the content of `target`, marked as an artifact."""
    resources = cast("DictionaryObject", target[NameObject("/Resources")].get_object())
    xobjects = cast(
        "DictionaryObject",
        resources.get(NameObject("/XObject"), DictionaryObject()).get_object(),
    )
    _put(resources, "/XObject", _put(xobjects, "/Anlage", form))
    under = _filled(StreamObject(), b"/Artifact BMC q /Anlage Do Q EMC\n", {})
    existing = target.get("/Contents")
    current = existing.get_object() if existing is not None else ArrayObject()
    parts = list(current) if isinstance(current, ArrayObject) else [existing]
    _put(target, "/Contents", ArrayObject([writer._add_object(under), *parts]))


def merge_appendix(
    pdf: bytes, appendix: Sequence[Appendix], documents: Mapping[str, bytes]
) -> bytes:
    """Put the pages of each Anlage under its empty pages at the end of `pdf`.

    The template prints the empty pages last, in the order of the Anlagen, so the
    last pages of the compiled PDF are the targets.

    Raises:
        ValueError: The PDF has fewer pages than the Anlagen.
    """
    total = sum(len(item.pages) for item in appendix)
    if total == 0:
        return pdf
    reader = PdfReader(io.BytesIO(pdf))
    writer = PdfWriter(clone_from=reader)
    first = len(writer.pages) - total
    if first < 0:
        raise ValueError("the PDF holds fewer pages than its Anlagen")
    sources = [
        page for item in appendix for page in PdfReader(io.BytesIO(documents[item.doc])).pages
    ]
    for offset, source in enumerate(sources):
        _underlay(writer, writer.pages[first + offset], _form(writer, source))
    return _written(writer, reader.pdf_header)


def _written(writer: PdfWriter, header: str) -> bytes:
    """Return the bytes of the PDF of `writer`, with the version header of the source."""
    writer.pdf_header = header
    with io.BytesIO() as out:
        writer.write(out)
        return out.getvalue()
