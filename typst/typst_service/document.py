"""Build the document data of one protocol: title page, logos, body and signatures.

The result is one JSON-ready dict. The Typst template reads it and lays out the
pages. The rules here follow the pytex protocol variant (`protocol-stupa`,
`protocol-asta`), so the platform gets the same document:

* The title is the `title` frontmatter key. Without it the title reads
  "Protokoll der Sitzung des <Gremium> vom <Datum>".
* The title page lists the meeting data: Datum, Zeit, Ort, Sitzungsleitung,
  Protokoll, Gremium, Beschlussfähigkeit, the `datalines`, and the attendance
  lists with their head count.
* The variant selects the default logos. A `logos` or `footer_logos` config
  key replaces them. An entry is a vendored logo name or the file name of an
  uploaded asset.
* A `footer_graphic` config key names the graphic at the foot of each page: a
  vendored name or an asset. An empty value means no graphic. Without the key
  the page carries the Skyline.
* An `unterschriften` list closes the document with one signature line per
  role.
* A `keepers` list names every period of a protocol keeper. It replaces the
  single `protokoll` name on the title page and on the signature page, and it
  adds a handover line below the heading of the agenda item where a later period
  starts. Without `keepers` the `protokoll` name stays in use.
* `started_at` (`YYYY-MM-DD HH:MM`) is the real start. It fills the date and the
  start time when `datum` or `beginn` is missing.
* `typ: antrag` marks an Antrag. Its headings are the sections of the form, so they
  get no "TOP n" number.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Final, cast

from .appendix import Appendix, Size, number_documents
from .frontmatter import Meta, Records, parse_frontmatter
from .markdown import ConversionError, Node, convert_body

__all__ = [
    "PLAN_VARIANT",
    "PROTOCOL_VARIANTS",
    "VENDORED_LOGOS",
    "build_document",
    "format_date",
]

# The logo names that the template ships. They match the logo names that
# pytex shipped, so a stored CD variant keeps working.
VENDORED_LOGOS: Final[frozenset[str]] = frozenset(
    {"HSRT", "INF", "ASTA", "STUPA", "ECHO", "MAKERS", "MAKERS-RAlign", "MAKERS-Icon", "Skyline"}
)

# Variant -> the default title-page logos. `None` reads the `gremium` key.
PROTOCOL_VARIANTS: Final[dict[str, tuple[str, ...] | None]] = {
    "protocol": None,
    "protocol-stupa": ("STUPA",),
    "protocol-asta": ("ASTA",),
}
# The variant of a Haushaltsplan. Its table comes in the `plan` config key.
PLAN_VARIANT: Final[str] = "plan"
_PLAN_ROW_KINDS: Final[frozenset[str]] = frozenset({"group", "line", "sum", "balance"})
_GREMIUM_LOGOS: Final[dict[str, tuple[str, ...]]] = {
    "stupa": ("STUPA",),
    "asta": ("ASTA",),
    "echo": ("ECHO",),
}
# A MAKERS design puts the icon into the page corner, so its footer takes the
# right-aligned logo.
_FOOTER_SWAP: Final[dict[str, str]] = {"MAKERS": "MAKERS-RAlign"}

_SCALAR_ROWS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("Ort", ("ort",)),
    ("Sitzungsleitung", ("sitzungsleitung",)),
    ("Protokoll", ("protokoll",)),
    ("Gremium", ("gremium",)),
    ("Beschlussfähigkeit", ("beschlussfaehigkeit", "beschlussfähigkeit")),
)
_LIST_ROWS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("Anwesend", ("anwesend",)),
    ("Entschuldigt", ("entschuldigt", "excused")),
    ("Abwesend", ("abwesend",)),
    ("Gäste", ("gaeste", "gäste")),
)
_SIGNER_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "sitzungsleitung": ("sitzungsleitung",),
    "schriftführung": ("protokoll", "schriftführung", "schriftfuehrung"),
    "schriftfuehrung": ("protokoll", "schriftfuehrung"),
    "protokoll": ("protokoll",),
    "vorstand": ("vorstand",),
}

_DATE_RE: Final[re.Pattern[str]] = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}:\d{2}))?")
# The document types whose headings are sections, not agenda items: they get no
# "TOP n" number.
_UNNUMBERED_TYPES: Final[frozenset[str]] = frozenset({"antrag"})
# The document types without a title page: each page starts with the title.
_COVERLESS_TYPES: Final[frozenset[str]] = frozenset({"antrag"})
# The signature roles that the protocol keepers sign.
_KEEPER_ROLES: Final[frozenset[str]] = frozenset({"schriftführung", "schriftfuehrung", "protokoll"})


def _keepers(records: Records) -> list[dict[str, str]]:
    """Return the keeper records that carry a name."""
    return [
        {k: v.strip() for k, v in r.items()}
        for r in records.get("keepers", [])
        if r.get("name", "").strip()
    ]


def _keeper_names(keepers: list[dict[str, str]]) -> list[str]:
    """Return each keeper name once, in the order of the periods."""
    return list(dict.fromkeys(k["name"] for k in keepers))


def _span(keeper: Mapping[str, str]) -> str:
    """Write the period of one keeper: the TOP numbers, else the times."""
    start = f"TOP {keeper['from_top']}" if keeper.get("from_top") else keeper.get("from", "")
    end = f"TOP {keeper['to_top']}" if keeper.get("to_top") else keeper.get("to", "")
    match (start, end):
        case ("", ""):
            return ""
        case (_, ""):
            return f"ab {start}"
        case ("", _):
            return f"bis {end}"
        case _:
            return f"{start} – {end}"  # an en dash between start and end


def _keeper_label(keeper: Mapping[str, str]) -> str:
    """Write one keeper of the `Protokoll` row: the name, with the period if it has one."""
    span = _span(keeper)
    return f"{keeper['name']} ({span})" if span else keeper["name"]


def _keeper_row(keepers: list[dict[str, str]]) -> str:
    """Write the `Protokoll` row: one name, or every period with its span."""
    return (
        keepers[0]["name"]
        if len(keepers) == 1
        else ", ".join(_keeper_label(keeper) for keeper in keepers)
    )


def _handover(keeper: Mapping[str, str]) -> Node:
    """Build the handover line of one keeper: who takes over, and when."""
    at = f" um {keeper['from']} Uhr" if keeper.get("from") else ""
    text = f"Die Protokollführung übernimmt {keeper['name']}{at}."
    return {"t": "par", "c": [{"t": "emph", "c": [{"t": "text", "v": text}]}]}


def _is_agenda_item(block: Node) -> bool:
    """Test whether a block is the `#` heading of an agenda item."""
    return block.get("t") == "heading" and block.get("level") == 1


def _handover_lines(blocks: list[Node], keepers: list[dict[str, str]]) -> list[Node]:
    """Add a handover line below the agenda item where a later period starts.

    The first period starts with the meeting and gets no line. A period without a
    TOP number, or with a number that the body does not have, gets no line; the
    title page still names it with its time.
    """
    pairs = [
        (int(keeper["from_top"]), _handover(keeper))
        for keeper in keepers[1:]
        if keeper.get("from_top", "").isdigit()
    ]
    if not pairs:
        return blocks
    lines = {top: [node for at, node in pairs if at == top] for top, _ in pairs}
    tops = itertools.accumulate(int(_is_agenda_item(block)) for block in blocks)
    return [
        node
        for block, top in zip(blocks, tops, strict=True)
        for node in ([block, *lines.get(top, [])] if _is_agenda_item(block) else [block])
    ]


def format_date(value: str) -> str:
    """Write an ISO date, with an optional time, the German way.

    `2026-06-15` becomes `15.06.2026`, and `2026-06-15 18:30` becomes
    `15.06.2026, 18:30`. Any other value stays unchanged.
    """
    match = _DATE_RE.fullmatch(value.strip())
    if match is None:
        return value
    day = f"{match[3]}.{match[2]}.{match[1]}"
    return f"{day}, {match[4]}" if match[4] else day


def _scalar(options: Mapping[str, object], *keys: str) -> str:
    values = (options.get(key) for key in keys)
    return next((v.strip() for v in values if isinstance(v, str) and v.strip()), "")


def _filled(value: object) -> bool:
    """Test whether a config value is a non-empty list or a non-blank string."""
    return (isinstance(value, list) and bool(value)) or (
        isinstance(value, str) and bool(value.strip())
    )


def _items(options: Mapping[str, object], *keys: str) -> list[str]:
    values = (options.get(key) for key in keys)
    match next((v for v in values if _filled(v)), None):
        case list() as items:
            return [str(v) for v in cast("list[object]", items) if str(v).strip()]
        case str() as text:
            return [v.strip() for v in text.split(",") if v.strip()]
        case _:
            return []


def _title(options: Mapping[str, object]) -> str:
    title = _scalar(options, "title", "titel")
    gremium = _scalar(options, "gremium")
    datum = _scalar(options, "datum", "date")
    match (title, gremium, datum):
        case ("", "", _):
            return "Sitzungsprotokoll"
        case ("", _, ""):
            return f"Protokoll der Sitzung des {gremium}"
        case ("", _, _):
            return f"Protokoll der Sitzung des {gremium} vom {format_date(datum.split()[0])}"
        case _:
            return title


def _started(options: Mapping[str, object]) -> tuple[str, str]:
    """Split `started_at` into the date and the time, or two empty strings."""
    match = _DATE_RE.fullmatch(_scalar(options, "started_at"))
    if match is None:
        return "", ""
    return f"{match[1]}-{match[2]}-{match[3]}", match[4] or ""


def _scalar_rows(options: Mapping[str, object], keepers: list[dict[str, str]]) -> list[list[str]]:
    """Write the rows of the single values. The keepers replace the `protokoll` name."""
    keeper_row = _keeper_row(keepers) if keepers else ""
    values = (
        (label, (keeper_row if label == "Protokoll" else "") or _scalar(options, *keys))
        for label, keys in _SCALAR_ROWS
    )
    return [[label, value] for label, value in values if value]


def _free_row(line: str) -> list[str]:
    """Split a free `Label: Wert` line. A line without a colon is a value without a label."""
    label, sep, value = line.partition(":")
    return [label.strip(), value.strip()] if sep else ["", line.strip()]


def _list_rows(options: Mapping[str, object]) -> list[list[str]]:
    """Write the attendance rows with their head count."""
    lists = ((label, _items(options, *keys)) for label, keys in _LIST_ROWS)
    return [[f"{label} ({len(people)})", ", ".join(people)] for label, people in lists if people]


def _data_lines(options: Mapping[str, object], keepers: list[dict[str, str]]) -> list[list[str]]:
    started_date, started_time = _started(options)
    datum = _scalar(options, "datum", "date") or (
        f"{started_date} {started_time}".strip() if started_date else ""
    )
    beginn = _scalar(options, "beginn", "start") or started_time
    span = " – ".join(  # an en dash between start and end
        t for t in (beginn, _scalar(options, "ende", "end")) if t
    )
    return [
        *([["Datum", format_date(datum)]] if datum else []),
        *([["Zeit", span]] if span else []),
        *_scalar_rows(options, keepers),
        # A free `Label: Wert` line, for example the head counts of the public variant.
        *(_free_row(line) for line in _items(options, "datalines")),
        *_list_rows(options),
    ]


def _role_signers(
    role: str, options: Mapping[str, object], keepers: list[dict[str, str]]
) -> list[list[str]]:
    """Write the signature lines of one role.

    Every protocol keeper signs the part of the minutes they kept, so a keeper
    role gets one line per keeper.
    """
    key = role.strip().lower()
    return (
        [[role.strip(), name] for name in _keeper_names(keepers)]
        if keepers and key in _KEEPER_ROLES
        else [[role.strip(), _scalar(options, *_SIGNER_KEYS.get(key, (key,)))]]
    )


def _signers(options: Mapping[str, object], keepers: list[dict[str, str]]) -> list[list[str]]:
    return [
        signer
        for role in _items(options, "unterschriften")
        for signer in _role_signers(role, options, keepers)
    ]


def _logo(entry: str, assets: Collection[str]) -> dict[str, str]:
    if entry in assets:
        return {"asset": entry}
    if entry in VENDORED_LOGOS:
        return {"name": entry}
    raise ConversionError(f"unknown logo {entry!r}: neither a vendored logo nor an uploaded asset")


def _footer_graphic(
    options: Mapping[str, object], assets: Collection[str]
) -> dict[str, str] | None:
    """Return the footer graphic of each page: the key, else the Skyline; empty is none."""
    match options.get("footer_graphic", "Skyline"):
        case str() as name if name:
            return _logo(name, assets)
        case None | "":
            return None
        case _:
            raise ConversionError("footer_graphic must be a name or empty")


def _logo_list(options: Mapping[str, object], key: str) -> list[str] | None:
    match options.get(key):
        case list() as items:
            return [str(v) for v in cast("list[object]", items)]
        case str() as name if name:
            return [name]
        case _:
            return None


def _default_logos(variant: str | None, options: Mapping[str, object]) -> tuple[str, ...]:
    """Return the default logos of the variant, else of the `gremium` key."""
    logos = PROTOCOL_VARIANTS.get(variant) if variant else None
    return (
        _GREMIUM_LOGOS.get(_scalar(options, "gremium").lower(), ("STUPA",))
        if logos is None
        else logos
    )


def _watermark(options: Mapping[str, object], number: int) -> str:
    """The watermark of an Anlage: `Anlage <N> zum Protokoll <Sitzungstitel> vom <Datum>`."""
    title = _scalar(options, "title", "titel") or _scalar(options, "gremium")
    started_date, _ = _started(options)
    datum = (_scalar(options, "datum", "date") or started_date).split(" ")[0]
    return " ".join(
        part
        for part in (
            f"Anlage {number} zum Protokoll",
            title,
            f"vom {format_date(datum)}" if datum else "",
        )
        if part
    )


def _appendix_data(options: Mapping[str, object], appendix: Sequence[Appendix]) -> list[Node]:
    return [
        {
            "n": item.number,
            "doc": item.doc,
            "name": item.name,
            "pages": [[w, h] for w, h in item.pages],
            "watermark": _watermark(options, item.number),
        }
        for item in appendix
    ]


def _texts(value: object, what: str) -> list[str]:
    """Return a list of texts of the plan config.

    Raises:
        ConversionError: The value is not a list of strings.
    """
    if not isinstance(value, list) or not all(
        isinstance(v, str) for v in cast("list[object]", value)
    ):
        raise ConversionError(f"plan {what} must be a list of texts")
    return cast("list[str]", value)


def _plan_row(row: object, cols: int) -> dict[str, object]:
    """Check one row of the plan table: its kind, its depth and one cell per column."""
    item = cast("dict[str, object]", row) if isinstance(row, dict) else {}
    kind, depth = item.get("kind"), item.get("depth", 0)
    cells = _texts(item.get("cells"), "row cells")
    if kind not in _PLAN_ROW_KINDS or not isinstance(depth, int) or len(cells) != cols:
        raise ConversionError("plan row needs a known kind, a depth and one cell per column")
    return {"kind": kind, "depth": max(0, min(depth, 12)), "cells": cells}


def _plan(options: Mapping[str, object]) -> dict[str, object]:
    """Check the `plan` config key and return the data of the plan layout.

    Raises:
        ConversionError: The key is missing or it does not have the shape of a plan.
    """
    raw = options.get("plan")
    if not isinstance(raw, dict):
        raise ConversionError("the plan variant needs a `plan` config object")
    plan = cast("dict[str, object]", raw)
    headers = _texts(plan.get("headers"), "headers")
    rows, head, money = plan.get("rows"), plan.get("head"), plan.get("money")
    if len(headers) < 2 or not isinstance(rows, list) or not isinstance(head, list):
        raise ConversionError("plan needs at least two headers, a head and rows")
    if not isinstance(money, list) or not all(
        isinstance(i, int) for i in cast("list[object]", money)
    ):
        raise ConversionError("plan money must be a list of column places")
    pairs = [_texts(pair, "head pair") for pair in cast("list[object]", head)]
    if any(len(pair) != 2 for pair in pairs):
        raise ConversionError("plan head pair needs a label and a value")
    return {
        "title": str(plan.get("title") or _title(options)),
        "mark": str(plan.get("mark") or ""),
        "head": pairs,
        "headers": headers,
        "money": money,
        "rows": [_plan_row(row, len(headers)) for row in cast("list[object]", rows)],
    }


def _plan_document(options: Mapping[str, object], assets: Collection[str]) -> dict[str, object]:
    """Build the document data of a Haushaltsplan. The default logo is that of the StuPa."""
    title_logos = _logo_list(options, "logos")
    footer_logos = _logo_list(options, "footer_logos")
    return {
        "layout": "plan",
        "logos": [_logo(n, assets) for n in (("STUPA",) if title_logos is None else title_logos)],
        "footer_logos": [_logo(n, assets) for n in (footer_logos or ())],
        "plan": _plan(options),
    }


def build_document(
    source: str,
    *,
    variant: str | None,
    config: Mapping[str, object] | None = None,
    assets: Collection[str] = (),
    documents: Mapping[str, tuple[Size, ...]] | None = None,
) -> dict[str, object]:
    """Turn protocol Markdown into the document data of the template.

    Args:
        source: The Markdown with its YAML frontmatter.
        variant: `protocol-stupa`, `protocol-asta`, `protocol`, `plan`, or `None`.
            `protocol` and `None` read the default logos from the `gremium` key.
            `plan` builds a Haushaltsplan from the `plan` config key and reads no
            Markdown body.
        config: Keys that override the frontmatter, for example `logos`.
        assets: The file names of the uploaded assets.
        documents: The page sizes of each uploaded PDF, by uuid (`appendix.page_sizes`).
            Only a PDF with sizes becomes an Anlage.

    Raises:
        ConversionError: The variant or a logo is unknown, or the Markdown
            nests too deep.
        FrontmatterError: The frontmatter is not valid YAML.
    """
    if variant == PLAN_VARIANT:
        plan_meta, _records, _body = parse_frontmatter(source)
        return _plan_document({**plan_meta, **(config or {})}, assets)
    if variant is not None and variant not in PROTOCOL_VARIANTS:
        allowed = ", ".join(sorted({*PROTOCOL_VARIANTS, PLAN_VARIANT}))
        raise ConversionError(f"unknown variant {variant!r}; allowed: {allowed}")
    meta: Meta
    records: Records
    meta, records, body = parse_frontmatter(source)
    options: dict[str, object] = {**meta, **(config or {})}
    keepers = _keepers(records)
    defaults = _default_logos(variant, options)
    title_logos = _logo_list(options, "logos")
    footer_logos = _logo_list(options, "footer_logos")
    title_names = list(defaults) if title_logos is None else title_logos
    # pytex falls back to the footer set of the variant here, not to a custom
    # title-page set.
    footer_names = (
        [_FOOTER_SWAP.get(n, n) for n in defaults] if footer_logos is None else footer_logos
    )
    converted = _handover_lines(convert_body(body, meta, assets), keepers)
    signers = _signers(options, keepers)
    signed = [*converted, {"t": "signatures", "signers": signers}] if signers else converted
    blocks, appendix = number_documents(signed, documents or {})
    return {
        "appendix": _appendix_data(options, appendix),
        "title": _title(options),
        "logos": [_logo(n, assets) for n in title_names],
        "footer_logos": [_logo(n, assets) for n in footer_names],
        "footer_graphic": _footer_graphic(options, assets),
        "data": _data_lines(options, keepers),
        "body": blocks,
        "numbered": _scalar(options, "typ").lower() not in _UNNUMBERED_TYPES,
        "cover": _scalar(options, "typ").lower() not in _COVERLESS_TYPES,
    }
