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
* An `unterschriften` list closes the document with one signature line per
  role.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Final

from .frontmatter import Meta, split_frontmatter
from .markdown import ConversionError, Node, convert_body

__all__ = [
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
    ("Entschuldigt", ("entschuldigt",)),
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
    for key in keys:
        value = options.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _items(options: Mapping[str, object], *keys: str) -> list[str]:
    for key in keys:
        value = options.get(key)
        if isinstance(value, list) and value:
            return [str(v) for v in value if str(v).strip()]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        if isinstance(value, str) and value.strip():
            return [v.strip() for v in value.split(",") if v.strip()]
    return []


def _title(options: Mapping[str, object]) -> str:
    title = _scalar(options, "title", "titel")
    if title:
        return title
    gremium = _scalar(options, "gremium")
    datum = _scalar(options, "datum", "date")
    if gremium and datum:
        return f"Protokoll der Sitzung des {gremium} vom {format_date(datum.split()[0])}"
    if gremium:
        return f"Protokoll der Sitzung des {gremium}"
    return "Sitzungsprotokoll"


def _data_lines(options: Mapping[str, object]) -> list[list[str]]:
    rows: list[list[str]] = []
    datum = _scalar(options, "datum", "date")
    if datum:
        rows.append(["Datum", format_date(datum)])
    span = " – ".join(  # noqa: RUF001 - an en dash between start and end
        t for t in (_scalar(options, "beginn", "start"), _scalar(options, "ende", "end")) if t
    )
    if span:
        rows.append(["Zeit", span])
    for label, keys in _SCALAR_ROWS:
        value = _scalar(options, *keys)
        if value:
            rows.append([label, value])
    # A free `Label: Wert` line, for example the head counts of the public
    # variant. A line without a colon prints as a value without a label.
    for line in _items(options, "datalines"):
        label, sep, value = line.partition(":")
        rows.append([label.strip(), value.strip()] if sep else ["", line.strip()])
    for label, keys in _LIST_ROWS:
        people = _items(options, *keys)
        if people:
            rows.append([f"{label} ({len(people)})", ", ".join(people)])
    return rows


def _signers(options: Mapping[str, object]) -> list[list[str]]:
    signers: list[list[str]] = []
    for role in _items(options, "unterschriften"):
        keys = _SIGNER_KEYS.get(role.strip().lower(), (role.strip().lower(),))
        signers.append([role.strip(), _scalar(options, *keys)])
    return signers


def _logo(entry: str, assets: Collection[str]) -> dict[str, str]:
    if entry in assets:
        return {"asset": entry}
    if entry in VENDORED_LOGOS:
        return {"name": entry}
    raise ConversionError(f"unknown logo {entry!r}: neither a vendored logo nor an uploaded asset")


def _logo_list(options: Mapping[str, object], key: str) -> list[str] | None:
    value = options.get(key)
    if isinstance(value, list):
        return [str(v) for v in value]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(value, str) and value:
        return [value]
    return None


def build_document(
    source: str,
    *,
    variant: str | None,
    config: Mapping[str, object] | None = None,
    assets: Collection[str] = (),
) -> dict[str, object]:
    """Turn protocol Markdown into the document data of the template.

    Args:
        source: The Markdown with its YAML frontmatter.
        variant: `protocol-stupa`, `protocol-asta`, `protocol`, or `None`. The
            last two read the default logos from the `gremium` key.
        config: Keys that override the frontmatter, for example `logos`.
        assets: The file names of the uploaded assets.

    Raises:
        ConversionError: The variant or a logo is unknown, or the Markdown
            nests too deep.
        FrontmatterError: The frontmatter is not valid YAML.
    """
    if variant is not None and variant not in PROTOCOL_VARIANTS:
        allowed = ", ".join(sorted(PROTOCOL_VARIANTS))
        raise ConversionError(f"unknown variant {variant!r}; allowed: {allowed}")
    meta: Meta
    meta, body = split_frontmatter(source)
    options: dict[str, object] = {**meta, **(config or {})}

    defaults = PROTOCOL_VARIANTS.get(variant) if variant else None
    if defaults is None:
        defaults = _GREMIUM_LOGOS.get(_scalar(options, "gremium").lower(), ("STUPA",))
    title_names = _logo_list(options, "logos")
    if title_names is None:
        title_names = list(defaults)
    footer_names = _logo_list(options, "footer_logos")
    if footer_names is None:
        # pytex falls back to the footer set of the variant here, not to a
        # custom title-page set.
        footer_names = [_FOOTER_SWAP.get(n, n) for n in defaults]

    blocks: list[Node] = convert_body(body, meta)
    signers = _signers(options)
    if signers:
        blocks.append({"t": "signatures", "signers": signers})
    return {
        "title": _title(options),
        "logos": [_logo(n, assets) for n in title_names],
        "footer_logos": [_logo(n, assets) for n in footer_names],
        "data": _data_lines(options),
        "body": blocks,
    }
