"""Split the YAML frontmatter off a protocol Markdown document.

The parser uses `yaml.BaseLoader`. That loader resolves no implicit types, so
every scalar stays the string of the source: `18:30` does not become the
sexagesimal number 1110, and `2026-06-15` does not become a date. A value is a
string or a list of strings. A mapping or a nested list is not part of the
protocol shape, and the parser drops it.

One exception: a list of flat mappings is a list of records, for example the
`keepers` of a protocol. `parse_frontmatter` returns the records apart from the
plain values. A record keeps its string values only.
"""

from __future__ import annotations

from typing import cast

import yaml

__all__ = ["FrontmatterError", "Meta", "Records", "parse_frontmatter", "split_frontmatter"]

type Meta = dict[str, str | list[str]]
type Records = dict[str, list[dict[str, str]]]


class FrontmatterError(ValueError):
    """The frontmatter is not valid YAML. The service answers 400."""


def _record(item: object) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    fields = cast("dict[object, object]", item).items()
    return {str(k): v for k, v in fields if isinstance(v, str)}


def _coerce(raw: object) -> tuple[Meta, Records]:
    if not isinstance(raw, dict):
        return {}, {}
    meta: Meta = {}
    records: Records = {}
    for key, value in cast("dict[object, object]", raw).items():
        if isinstance(value, str):
            meta[str(key)] = value
        elif isinstance(value, list):
            items = cast("list[object]", value)
            rows = [r for r in (_record(item) for item in items) if r is not None]
            if rows:
                records[str(key)] = rows
            else:
                meta[str(key)] = [item for item in items if isinstance(item, str)]
    return meta, records


def parse_frontmatter(text: str) -> tuple[Meta, Records, str]:
    """Split `text` into the plain values, the records and the Markdown body.

    Returns:
        The plain values, the lists of records, and the body. A text without an
        opening `---` fence, or without a closing one, comes back whole with
        empty mappings.

    Raises:
        FrontmatterError: The fenced block is not valid YAML.
    """
    stripped = text.lstrip("﻿").lstrip("\n")
    lines = stripped.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if end is None:
        return {}, {}, text
    try:
        raw: object = yaml.load("\n".join(lines[1:end]), Loader=yaml.BaseLoader)  # noqa: S506
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"the frontmatter is not valid YAML: {exc}") from None
    meta, records = _coerce(raw)
    return meta, records, "\n".join(lines[end + 1 :]).lstrip("\n")


def split_frontmatter(text: str) -> tuple[Meta, str]:
    """Split `text` into the plain frontmatter values and the Markdown body.

    The records (lists of mappings) are left out. See `parse_frontmatter`.

    Raises:
        FrontmatterError: The fenced block is not valid YAML.
    """
    meta, _, body = parse_frontmatter(text)
    return meta, body
