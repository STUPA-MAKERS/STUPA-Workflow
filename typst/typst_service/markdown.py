"""Convert protocol Markdown into a JSON tree that the Typst template walks.

The converter never writes Typst code. Every node is plain data: a dict with a
type tag `t` and its fields. The template (`template/protocol.typ`) reads the
tree with `json()` and builds the content itself. Text from the Markdown
therefore stays text, whatever characters it holds. Typst markup, a `#` call
or a `$` formula in the source cannot run as code.

The Markdown dialect is the one of the protocol editor and of the backend
builder (`backend/app/modules/protocol/markdown.py`):

* CommonMark plus the GFM tables, strikethrough and autolinks.
* A `#` heading is an agenda item. The template numbers it "TOP n".
* Callouts: the GitHub kinds (`> [!NOTE]`, `> [!TIP]`, ...) and the protocol
  kinds `> [!beschluss]`, `> [!abstimmung]`, `> [!aufgabe]`, `> [!frist]`
  and `> [!unterschriften]`. A vote callout carries a tally line such as
  `ja: 12, nein: 3, enthaltung: 2`.
* Inline shortcodes: `{{time 18:30}}`, `{{vote ja=1 nein=2 enthaltung=0}}`,
  `{{count anwesend}}` and a bare frontmatter field such as `{{anwesend}}`.
* TeX math: `$...$` in a line, and a paragraph that is one `$$...$$` block.
  The formula body goes to the template as a string. The vendored mitex
  package converts it inside math mode.
* The editor block `:::antrag{#<id>}` ... `:::` only marks an application
  reference. The converter drops the two fence lines and keeps the content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

import marko

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from .frontmatter import Meta

__all__ = ["ConversionError", "Node", "convert_body", "strip_antrag_fences"]

type Node = dict[str, object]

_PARSER: Final = marko.Markdown(extensions=["gfm"])

# Deeper nesting than this is no protocol, it is an attack on the recursion of
# the converter and of the template. The render answers 400 instead.
MAX_DEPTH: Final[int] = 24


class ConversionError(ValueError):
    """The Markdown cannot become a document. The service answers 400."""


# -- callouts ---------------------------------------------------------------

CALLOUT_RE: Final[re.Pattern[str]] = re.compile(r"^\s*\[!(\w+)\]\s*", re.IGNORECASE)

# Marker -> (box kind, bold label). The label opens the box body.
_LABELLED: Final[dict[str, tuple[str, str | None]]] = {
    "NOTE": ("info", None),
    "INFO": ("info", None),
    "TIP": ("success", None),
    "HINT": ("success", None),
    "SUCCESS": ("success", None),
    "IMPORTANT": ("important", None),
    "WARNING": ("warning", None),
    "CAUTION": ("warning", None),
    "DANGER": ("warning", None),
    "ERROR": ("warning", None),
    "BESCHLUSS": ("decision", "Beschluss: "),
    "DECISION": ("decision", "Beschluss: "),
    "AUFGABE": ("task", "Aufgabe: "),
    "TODO": ("task", "Aufgabe: "),
    "ACTION": ("task", "Aufgabe: "),
    "FRIST": ("deadline", "Frist: "),
    "DEADLINE": ("deadline", "Frist: "),
}
_VOTE_MARKERS: Final[frozenset[str]] = frozenset({"ABSTIMMUNG", "VOTE"})
_SIGNATURE_MARKERS: Final[frozenset[str]] = frozenset({"UNTERSCHRIFTEN", "SIGNATURES"})

_TALLY_RE: Final[dict[str, re.Pattern[str]]] = {
    "yes": re.compile(r"(?:ja|yes)\s*[:=]?\s*(\d+)", re.IGNORECASE),
    "no": re.compile(r"(?:nein|no)\s*[:=]?\s*(\d+)", re.IGNORECASE),
    "abstain": re.compile(r"(?:enthaltung|enth\.?|abstain)\s*[:=]?\s*(\d+)", re.IGNORECASE),
}


def _tally(text: str, key: str) -> int:
    match = _TALLY_RE[key].search(text)
    return int(match.group(1)) if match else 0


def _is_tally_line(line: str) -> bool:
    """Test whether a line carries at least two of the three vote counts."""
    return sum(1 for rx in _TALLY_RE.values() if rx.search(line)) >= 2


# -- inline text: shortcodes, math, arrows ----------------------------------

SHORTCODE_RE: Final[re.Pattern[str]] = re.compile(r"\{\{\s*(.*?)\s*\}\}")

# The frontmatter keys that a shortcode may name. The value lists the aliases.
_FIELD_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "gremium": ("gremium",),
    "datum": ("datum", "date"),
    "beginn": ("beginn", "start"),
    "ende": ("ende", "end"),
    "ort": ("ort",),
    "sitzungsleitung": ("sitzungsleitung",),
    "protokoll": ("protokoll",),
    "anwesend": ("anwesend",),
    "abwesend": ("abwesend",),
    "entschuldigt": ("entschuldigt",),
    "gaeste": ("gaeste", "gäste"),
}
_LIST_FIELDS: Final[frozenset[str]] = frozenset({"anwesend", "abwesend", "entschuldigt", "gaeste"})

# TeX math, the syntax of KaTeX and pandoc. The opening `$` has no space behind
# it, the closing `$` no space in front of it and no digit behind it, so a
# price such as "$5 und $6" stays prose. `\$` is a dollar sign.
MATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<!\\)\$(?![\s$])((?:\\.|[^\\$\n])*?)(?<!\s)\$(?!\d)"
)
DISPLAY_MATH_RE: Final[re.Pattern[str]] = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)

# ASCII arrows and the symbols that pytex set from the math font. The template
# sets a `sym` node in math, so the glyphs match the formulas. `<=` is absent
# on purpose: in prose it means "less than or equal", not an arrow.
_ARROWS: Final[dict[str, str]] = {
    "<-->": "⟷",
    "<->": "↔",
    "<=>": "⇔",
    "-->": "⟶",
    "<--": "⟵",
    "->": "→",
    "<-": "←",
    "=>": "⇒",
}
_MATH_SYMBOLS: Final[frozenset[str]] = frozenset("→↔≤≥·←⇒⇔⟶⟵⟷")
_SYMBOL_SPLIT_RE: Final[re.Pattern[str]] = re.compile(
    "("
    + "|".join(re.escape(a) for a in sorted(_ARROWS, key=len, reverse=True))
    + "|["
    + "".join(sorted(_MATH_SYMBOLS))
    + "])"
)

# Only a link with a URL scheme or a protocol-relative `//` stays a link. A
# relative target points at nothing inside the PDF, so it keeps its text only.
EXTERNAL_URL_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[a-z][a-z0-9+.\-]*:|//)", re.IGNORECASE)

# The editor fences of an application reference.
_ANTRAG_OPEN_RE: Final[re.Pattern[str]] = re.compile(r"^\s*:::\s*antrag\b[^\n]*$", re.IGNORECASE)
_FENCE_CLOSE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*:::\s*$")
_CODE_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")


def _text(value: str) -> Node:
    return {"t": "text", "v": value}


def _prose(text: str) -> Iterator[Node]:
    """Split prose into text runs and math-font symbol nodes."""
    for index, piece in enumerate(_SYMBOL_SPLIT_RE.split(text)):
        if not piece:
            continue
        if index % 2:
            yield {"t": "sym", "v": _ARROWS.get(piece, piece)}
        else:
            yield _text(piece)


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [v.strip() for v in value.split(",") if v.strip()]


def _lookup(meta: Meta, name: str) -> str | list[str] | None:
    for key in _FIELD_ALIASES.get(name, (name,)):
        if key in meta:
            return meta[key]
    return None


def _count(args: Mapping[str, str], *keys: str) -> int:
    for key in keys:
        if key in args:
            try:
                return int(args[key])
            except ValueError:
                return 0
    return 0


def _shortcode(inner: str, meta: Meta) -> list[Node]:
    """Expand the body of one `{{...}}` marker.

    An unknown shortcode comes back as literal text, braces included, so a
    typo stays visible in the PDF.
    """
    name, _, rest = inner.strip().partition(" ")
    name = name.lower()
    rest = rest.strip()
    if name == "time" and rest:
        return [{"t": "time", "v": rest}]
    if name == "vote":
        args = dict(tok.split("=", 1) for tok in rest.split() if "=" in tok)
        return [
            {
                "t": "vote",
                "yes": _count(args, "ja", "yes"),
                "no": _count(args, "nein", "no"),
                "abstain": _count(args, "enthaltung", "enth", "abstain"),
            }
        ]
    if name == "count":
        return [_text(str(len(_as_list(_lookup(meta, rest.lower())))))]
    if name in _FIELD_ALIASES:
        value = _lookup(meta, name)
        if name in _LIST_FIELDS:
            return [_text(", ".join(_as_list(value)))]
        return [_text(value if isinstance(value, str) else "")]
    return [_text("{{" + inner + "}}")]


def _inline_text(text: str, meta: Meta) -> Iterator[Node]:
    """Expand the shortcodes of a text run and split the rest into prose."""
    for index, piece in enumerate(SHORTCODE_RE.split(text)):
        if index % 2:
            yield from _shortcode(piece, meta)
        elif piece:
            yield from _prose(piece)


# -- marko helpers ----------------------------------------------------------


def _kind(node: object) -> str:
    return type(node).__name__


def _children(node: object) -> list[object]:
    ch = getattr(node, "children", None)
    return cast("list[object]", ch) if isinstance(ch, list) else []


def _leaf(node: object) -> str | None:
    ch = getattr(node, "children", None)
    return ch if isinstance(ch, str) else None


def _source_text(node: object) -> str | None:
    """Return the Markdown source of one plain inline node, or `None`.

    marko drops the backslash of an escape. A formula body is LaTeX and needs
    it, so the function puts it back. A node with structure returns `None`,
    and a formula never crosses such a node.
    """
    kind = _kind(node)
    if kind == "RawText":
        return _leaf(node)
    if kind == "Literal":
        return "\\" + (_leaf(node) or "")
    if kind == "LineBreak":
        return "\n"
    return None


def strip_antrag_fences(markdown: str) -> str:
    """Drop the `:::antrag{...}` fence and its closing `:::`, outside code.

    Only a closing `:::` that belongs to an open application fence goes. Any
    other `:::` line stays text.
    """
    out: list[str] = []
    in_code = False
    open_fences = 0
    for line in markdown.split("\n"):
        if _CODE_FENCE_RE.match(line):
            in_code = not in_code
        elif not in_code and _ANTRAG_OPEN_RE.match(line):
            open_fences += 1
            continue
        elif not in_code and open_fences and _FENCE_CLOSE_RE.match(line):
            open_fences -= 1
            continue
        out.append(line)
    return "\n".join(out)


# -- the converter ----------------------------------------------------------


@dataclass(slots=True)
class _Converter:
    meta: Meta
    _depth: int = 0
    _ul: int = 0
    _ol: int = 0

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise ConversionError(f"the Markdown nests deeper than {MAX_DEPTH} levels")

    def _leave(self) -> None:
        self._depth -= 1

    # -- inline ------------------------------------------------------------

    def inline(self, node: object) -> list[Node]:
        kind = _kind(node)
        text = _leaf(node)
        if kind == "CodeSpan":
            return [{"t": "code", "v": text or ""}]
        if kind in ("RawText", "Literal"):
            return list(_inline_text(text or "", self.meta))
        if kind == "InlineHTML":
            return [_text(text or "")]
        if kind == "LineBreak":
            soft = bool(getattr(node, "soft", False))
            return [_text(" ")] if soft else [{"t": "br"}]
        self._enter()
        try:
            if kind == "StrongEmphasis":
                return [{"t": "strong", "c": self.inlines(node)}]
            if kind == "Emphasis":
                return [{"t": "emph", "c": self.inlines(node)}]
            if kind == "Strikethrough":
                return [{"t": "strike", "c": self.inlines(node)}]
            if kind in ("Link", "AutoLink", "Url"):
                dest = str(getattr(node, "dest", ""))
                if EXTERNAL_URL_RE.match(dest):
                    return [{"t": "link", "url": dest, "c": self.inlines(node)}]
                return self.inlines(node)
            if kind == "Image":
                # The render has no network and no file of the author, so an
                # image cannot load. Its alt text stands in for it.
                alt = "".join(_plain(c) for c in _children(node)).strip() or "Bild"
                return [{"t": "image", "alt": alt}]
            return self.inlines(node)
        finally:
            self._leave()

    def inlines(self, node: object) -> list[Node]:
        return self._inline_nodes(_children(node))

    def _inline_nodes(self, kids: list[object]) -> list[Node]:
        """Convert inline children and lift each `$...$` span into a formula.

        A formula can span several marko nodes, as soon as its body holds an
        escape. The method rebuilds the source of the plain children, finds
        the formulas in it and converts the rest the ordinary way.
        """
        spans: list[tuple[object, int, int]] = []
        source = ""
        for child in kids:
            text = _source_text(child)
            # A node with structure stands in the source as a newline. A
            # formula holds no newline, so it never spans such a node.
            plain = text if text is not None else "\n"
            end = len(source) + len(plain) if text is not None else -1
            spans.append((child, len(source), end))
            source += plain
        formulas = [(m.start(), m.end(), m.group(1)) for m in MATH_RE.finditer(source)]
        out: list[Node] = []
        if not formulas:
            for child in kids:
                out.extend(self.inline(child))
            return out
        for child, start, end in spans:
            if end < 0:
                out.extend(self.inline(child))
                continue
            cursor = start
            for first, last, tex in formulas:
                if last <= cursor or first >= end:
                    continue
                if first > cursor:
                    out.extend(_inline_text(source[cursor:first], self.meta))
                if first >= start:
                    out.append({"t": "math", "tex": tex})
                cursor = max(cursor, last)
            if cursor >= end:
                continue
            if cursor == start:
                out.extend(self.inline(child))
            else:
                out.extend(_inline_text(source[cursor:end], self.meta))
        return out

    # -- blocks ------------------------------------------------------------

    def block(self, node: object) -> list[Node]:
        kind = _kind(node)
        if kind in ("BlankLine", "LinkRefDef", "HTMLBlock"):
            # A link definition and raw HTML print nothing.
            return []
        self._enter()
        try:
            return self._block(node, kind)
        finally:
            self._leave()

    def _block(self, node: object, kind: str) -> list[Node]:
        if kind in ("Heading", "SetextHeading"):
            level = int(getattr(node, "level", 1))
            return [{"t": "heading", "level": level, "c": self.inlines(node)}]
        if kind == "Paragraph":
            display = self._display_math(node)
            if display is not None:
                return [display]
            return [{"t": "par", "c": _trim(self.inlines(node))}]
        if kind == "List":
            # LaTeX counts the itemize and the enumerate depth apart: a bullet
            # list inside a numbered list still takes the first bullet.
            ordered = bool(getattr(node, "ordered", False))
            level = self._ol if ordered else self._ul
            if ordered:
                self._ol += 1
            else:
                self._ul += 1
            try:
                items = [
                    self.blocks(_children(c)) for c in _children(node) if _kind(c) == "ListItem"
                ]
            finally:
                if ordered:
                    self._ol -= 1
                else:
                    self._ul -= 1
            return [
                {
                    "t": "list",
                    "ordered": ordered,
                    "start": int(getattr(node, "start", 1) or 1),
                    "olevel" if ordered else "ulevel": level,
                    "items": items,
                }
            ]
        if kind == "Quote":
            return self._quote(node)
        if kind in ("FencedCode", "CodeBlock"):
            text = _leaf(node)
            if text is None:
                kids = _children(node)
                text = _leaf(kids[0]) if kids else ""
            return [{"t": "codeblock", "v": (text or "").rstrip("\n")}]
        if kind == "ThematicBreak":
            return [{"t": "rule"}]
        if kind == "Table":
            return self._table(node)
        return self.blocks(_children(node))

    def blocks(self, nodes: list[object]) -> list[Node]:
        out: list[Node] = []
        for node in nodes:
            out.extend(self.block(node))
        return out

    def _display_math(self, node: object) -> Node | None:
        parts = [_source_text(c) for c in _children(node)]
        if not parts or any(p is None for p in parts):
            return None
        match = DISPLAY_MATH_RE.fullmatch("".join(cast("list[str]", parts)).strip())
        if match is None or not match.group(1).strip():
            return None
        return {"t": "mathblock", "tex": match.group(1).strip()}

    def _table(self, node: object) -> list[Node]:
        rows = [r for r in _children(node) if _kind(r) == "TableRow"]
        if not rows:
            return []
        head, *body = rows
        align = [
            str(getattr(c, "align", None) or "left")
            for c in _children(head)
            if _kind(c) == "TableCell"
        ]
        return [
            {
                "t": "table",
                "align": align,
                "head": self._row(head),
                "rows": [self._row(r) for r in body],
            }
        ]

    def _row(self, row: object) -> list[list[Node]]:
        return [self.inlines(c) for c in _children(row) if _kind(c) == "TableCell"]

    # -- callouts ----------------------------------------------------------

    def _quote(self, node: object) -> list[Node]:
        kids = _children(node)
        marker = self._marker(kids)
        if marker is None:
            return [{"t": "quote", "c": self.blocks(kids)}]
        name, rest = marker
        if name in _VOTE_MARKERS:
            return [self._vote(kids)]
        if name in _SIGNATURE_MARKERS:
            return [self._signature_callout(kids)]
        box, label = _LABELLED[name]
        first = cast("list[object]", _children(kids[0]))
        head: list[Node] = [{"t": "strong", "c": [_text(label)]}] if label else []
        head.extend(_inline_text(rest, self.meta))
        head.extend(self._inline_nodes(first[1:]))
        return [
            {"t": "callout", "kind": box, "c": [{"t": "par", "c": head}, *self.blocks(kids[1:])]}
        ]

    def _marker(self, kids: list[object]) -> tuple[str, str] | None:
        """Read the callout marker of a quote: `(NAME, rest of the first text)`."""
        if not kids or _kind(kids[0]) != "Paragraph":
            return None
        inner = _children(kids[0])
        first = _leaf(inner[0]) if inner else None
        if first is None or _kind(inner[0]) != "RawText":
            return None
        match = CALLOUT_RE.match(first)
        if match is None:
            return None
        name = match.group(1).upper()
        if name not in _LABELLED and name not in _VOTE_MARKERS and name not in _SIGNATURE_MARKERS:
            return None
        return name, first[match.end() :]

    def _callout_lines(self, kids: list[object]) -> list[list[object]]:
        """Split the paragraphs of a callout into its source lines of inline nodes.

        The first line loses the callout marker. A line break and a paragraph
        boundary both end a line.
        """
        lines: list[list[object]] = [[]]
        for kid in kids:
            if _kind(kid) != "Paragraph":
                continue
            if lines[-1]:
                lines.append([])
            for inline in _children(kid):
                if _kind(inline) == "LineBreak":
                    lines.append([])
                else:
                    lines[-1].append(inline)
        return [line for line in lines if line]

    def _vote(self, kids: list[object]) -> Node:
        """Build a tally box. The tally line gives the counts, the rest is the body."""
        lines = self._callout_lines(kids)
        texts = ["".join(_plain(n) for n in line) for line in lines]
        if texts:
            texts[0] = CALLOUT_RE.sub("", texts[0], count=1)
        tally = next((t.strip() for t in texts if _is_tally_line(t)), "")
        body: list[list[Node]] = []
        for index, (line, text) in enumerate(zip(lines, texts, strict=True)):
            if not text.strip() or _is_tally_line(text):
                continue
            if index == 0:
                marker_text = CALLOUT_RE.sub("", _leaf(line[0]) or "", count=1)
                nodes = [*_inline_text(marker_text, self.meta), *self._inline_nodes(line[1:])]
            else:
                nodes = self._inline_nodes(line)
            body.append(_trim(nodes))
        return {
            "t": "tally",
            "yes": _tally(tally, "yes"),
            "no": _tally(tally, "no"),
            "abstain": _tally(tally, "abstain"),
            "lines": body,
        }

    def _signature_callout(self, kids: list[object]) -> Node:
        """Build a signature block from its `Rolle: Name` lines."""
        lines = ["".join(_plain(n) for n in line) for line in self._callout_lines(kids)]
        if lines:
            lines[0] = CALLOUT_RE.sub("", lines[0], count=1)
        signers: list[list[str]] = []
        for entry in lines:
            line = entry.strip()
            if line:
                role, _, person = line.partition(":")
                signers.append([role.strip(), person.strip()])
        return {"t": "signatures", "signers": signers}


def _plain(node: object) -> str:
    """Return the plain text under a node, formatting dropped."""
    text = _leaf(node)
    if text is not None:
        return " " if _kind(node) == "LineBreak" else text
    return "".join(_plain(c) for c in _children(node))


def _trim(nodes: list[Node]) -> list[Node]:
    """Strip the leading and the trailing whitespace of an inline run."""
    out = list(nodes)
    if out and out[0].get("t") == "text":
        value = str(out[0]["v"]).lstrip()
        out[0] = _text(value) if value else {"t": "text", "v": ""}
    if out and out[-1].get("t") == "text":
        out[-1] = _text(str(out[-1]["v"]).rstrip())
    return [n for n in out if not (n.get("t") == "text" and n.get("v") == "")]


def convert_body(markdown: str, meta: Meta) -> list[Node]:
    """Convert the Markdown body of a protocol into block nodes.

    Raises:
        ConversionError: The Markdown nests too deep.
    """
    tree = _PARSER.parse(strip_antrag_fences(markdown))
    converter = _Converter(meta=meta)
    try:
        blocks = converter.blocks(_children(tree))
    except RecursionError:
        raise ConversionError("the Markdown nests too deep") from None
    return blocks
