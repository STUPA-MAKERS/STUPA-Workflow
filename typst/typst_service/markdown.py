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
  `ja: 12, nein: 3, enthaltung: 2`. A vote callout without a tally line can
  hold a personnel election or a poll (Umfrage), which the template draws as a
  ranking.
* Inline shortcodes: `{{time 18:30}}`, `{{vote ja=1 nein=2 enthaltung=0}}`,
  `{{count anwesend}}` and a bare frontmatter field such as `{{anwesend}}`.
* TeX math: `$...$` in a line, and a paragraph that is one `$$...$$` block.
  The formula body goes to the template as a string. The vendored mitex
  package converts it inside math mode.
* The editor block `:::antrag{#<id>}` ... `:::` only marks an application
  reference. The converter drops the two fence lines and keeps the content.
* Images: only the canonical path of an uploaded image,
  `![alt](/api/media/images/<uuid>)`, shows an image, and only when the
  caller uploaded its bytes as the asset `img-<uuid>.<ext>`. Every other image
  (a URL, a relative path, a missing asset) keeps its alt text. The node names
  the asset only; the template loads it from `/assets/`. A paragraph that holds
  only an image becomes a block image (`figure`).
"""

from __future__ import annotations

import functools
import itertools
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, cast

import marko

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping, Sequence

    from .frontmatter import Meta

__all__ = ["ConversionError", "Node", "convert_body", "image_assets", "strip_antrag_fences"]

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


_ELECTION_META_RE: Final = re.compile(r"^(?:Wahl|Stichwahl)\b.*·\s*\d+\s+Posten")
_ELECTION_VOTES_RE: Final = re.compile(r"^.+:\s*\d+(?:\s+·\s+.+:\s*\d+)*$")
_ELECTION_PART_RE: Final = re.compile(r"^(.*):\s*(\d+)$")
_ELECTION_OTHERS_RE: Final = re.compile(r"^(\d+) weitere Kandidierende$")


@dataclass(frozen=True, slots=True)
class _ElectionScan:
    """What the lines of an election have said so far."""

    rows: tuple[tuple[str, int], ...] = ()
    abstentions: int | None = None
    elected_raw: str | None = None
    others: int = 0
    lot: str | None = None
    notes: tuple[str, ...] = ()


def _election_votes(scan: _ElectionScan, line: str) -> _ElectionScan:
    """Read the votes per candidate (`Anna: 5 · Ben: 3 · Enthaltungen: 1`)."""
    parts = (_ELECTION_PART_RE.match(part) for part in re.split(r"\s+·\s+", line))
    matches = [match for match in parts if match is not None]
    abstained = [int(m.group(2)) for m in matches if m.group(1) == "Enthaltungen"]
    return replace(
        scan,
        rows=tuple((m.group(1), int(m.group(2))) for m in matches if m.group(1) != "Enthaltungen"),
        abstentions=abstained[-1] if abstained else scan.abstentions,
    )


def _election_line(scan: _ElectionScan, line: str) -> _ElectionScan:
    """Read one line of an election after the seat line."""
    others = _ELECTION_OTHERS_RE.match(line)
    match line:
        case _ if line.startswith("Gewählt:"):
            return replace(scan, elected_raw=line.removeprefix("Gewählt:").strip())
        case _ if others:
            return replace(scan, others=int(others.group(1)))
        case "Durch Los entschieden.":
            return replace(scan, lot="drawn")
        case _ if line.rstrip(".") == "Gleichstand: das Los steht aus":
            return replace(scan, lot="pending")
        case _ if not scan.rows and _ELECTION_VOTES_RE.match(line):
            return _election_votes(scan, line)
        case _:
            return replace(scan, notes=(*scan.notes, line))


def _pick_elected(raw: str, names: Sequence[str]) -> list[str]:
    """Find the known names in the `Gewählt:` text.

    The longer name goes first, so a name with ", " stays whole.
    """

    def pick(found: tuple[tuple[str, ...], str], name: str) -> tuple[tuple[str, ...], str]:
        picked, rest = found
        return ((*picked, name), rest.replace(name, "", 1)) if name in rest else found

    longest_first = sorted(names, key=lambda name: -len(name))
    return list(functools.reduce(pick, longest_first, ((), raw))[0])


def _elected(raw: str | None, names: Sequence[str]) -> list[str]:
    """Read the elected people: the known candidates, else the comma list of the public form."""
    match raw:
        case None | "niemand":
            return []
        case _ if names:
            return _pick_elected(raw, names)
        case _:
            return [name.strip() for name in raw.split(",") if name.strip()]


def _election(lines: list[str]) -> Node | None:
    """Read a personnel election from the lines after the question.

    The backend writes `Wahl · 2 Posten`, the votes per candidate
    (`Anna: 5 · Ben: 3 · Enthaltungen: 1`), `Gewählt: …` and the notes of the lot;
    the public form writes the elected people and `n weitere Kandidierende`. The
    editor reads the same lines (`parseElection` of the ui-kit). A callout without
    the seat line, or with a single candidate (its Ja/Nein line), is no ranking.
    Only the first line of votes counts; a later one is a note.
    """
    meta = next((line for line in lines if _ELECTION_META_RE.match(line)), None)
    if meta is None or any(line.startswith("Kandidatur:") for line in lines):
        return None
    rest = [line for line in lines if line is not meta]
    scan = functools.reduce(_election_line, rest, _ElectionScan())
    elected = _elected(scan.elected_raw, [name for name, _ in scan.rows])
    rows = [{"name": name, "votes": votes, "elected": name in elected} for name, votes in scan.rows]
    return {
        "meta": meta,
        "rows": sorted(rows, key=lambda r: (-cast("int", r["votes"]), not r["elected"])),
        "abstentions": scan.abstentions,
        "elected": [] if rows else elected,
        "others": scan.others,
        "lot": scan.lot,
        "notes": list(scan.notes),
    }


_POLL_META_RE: Final = re.compile(r"^(?:Umfrage\s+·\s+.+|Terminumfrage)$")
_POLL_ROW_RE: Final = re.compile(r"^(.*\S):\s*(\d+)(?:\s*\(\+(\d+)\))?$")
_POLL_TOP_RE: Final = re.compile(r"^(?:Meiste Stimmen|Bester Termin):\s*(.*)$")
_POLL_BALLOTS_RE: Final = re.compile(r"^(\d+) Antwort(?:en)?\b")
_POLL_LEGEND: Final = "Zahl = Ja, (+n) = Vielleicht"


def _top_labels(top: str, labels: list[str]) -> set[str]:
    """Split the list `top` (`A, B`) into the option labels that it names.

    A label can hold ", " itself (a date such as `Di, 3.11. · 18:00–20:00`), so a
    split at every comma is wrong. The function finds a sequence of known labels
    that joins to `top`, and tries the longer label first at each place.
    """
    ordered = sorted(set(labels), key=len, reverse=True)

    def attempt(label: str, rest: str) -> tuple[str, ...] | None:
        tail = split(rest[len(label) + 2 :]) if rest.startswith(label + ", ") else None
        return (label,) if rest == label else (None if tail is None else (label, *tail))

    # The cache keeps the search linear in the places of `top`, whatever the labels.
    @functools.cache
    def split(rest: str) -> tuple[str, ...] | None:
        attempts = (attempt(label, rest) for label in ordered)
        return next((found for found in attempts if found is not None), None)

    return set(split(top) or ()) if top else set()


@dataclass(frozen=True, slots=True)
class _PollScan:
    """What the lines of a poll have said so far."""

    rows: tuple[tuple[str, int, int | None], ...] = ()
    abstentions: int | None = None
    top: str = ""
    footer: str | None = None
    notes: tuple[str, ...] = ()


def _poll_line(scan: _PollScan, line: str, *, date: bool) -> _PollScan:
    """Read one line of a poll after the kind line."""
    top = _POLL_TOP_RE.match(line)
    row = _POLL_ROW_RE.match(line)
    ballots = _POLL_BALLOTS_RE.match(line) if row is None else None
    match line:
        case _ if top:
            return replace(scan, top=top.group(1).strip())
        case _ if ballots:
            # The footer comes from the number, so the rest of an old stored line drops.
            n = int(ballots.group(1))
            return replace(scan, footer=f"{n} {'Antwort' if n == 1 else 'Antworten'}")
        case _ if line == _POLL_LEGEND:
            return scan
        case _ if row and row.group(1) == "Enthaltungen" and not row.group(3):
            return replace(scan, abstentions=int(row.group(2)))
        case _ if row and (row.group(3) is not None) == date:
            maybe = row.group(3)
            entry = (row.group(1), int(row.group(2)), int(maybe) if maybe is not None else None)
            return replace(scan, rows=(*scan.rows, entry))
        case _:
            return replace(scan, notes=(*scan.notes, line))


def _poll(lines: list[str]) -> Node | None:
    """Read a poll (Umfrage) from the lines after the question.

    The backend (`build_poll_snippet`) writes the kind (`Umfrage · Einzelwahl`,
    `Umfrage · Mehrfachwahl, höchstens 2` or `Terminumfrage`) and, once the poll is
    closed, one `Label: n` line per option, highest first. A date poll writes
    `Label: n (+m)`, where n counts Ja and m counts Vielleicht, and the legend line
    for that. Then come `Enthaltungen: n`, the options with the most votes
    (`Meiste Stimmen: …` or `Bester Termin: …`) and `n Antworten` (`1 Antwort`). An open poll
    has the kind line only. The editor reads the same lines (`parsePoll` of the
    ui-kit).
    """
    if not lines or _POLL_META_RE.match(lines[0]) is None:
        return None
    meta = lines[0]
    date = meta == "Terminumfrage"
    scan = functools.reduce(
        lambda acc, line: _poll_line(acc, line, date=date), lines[1:], _PollScan()
    )
    best = _top_labels(scan.top, [label for label, _, _ in scan.rows])
    return {
        "kind": "date" if date else "multi" if "Mehrfachwahl" in meta else "single",
        "meta": meta,
        "rows": [
            {"label": label, "count": count, "maybe": maybe, "top": label in best}
            for label, count, maybe in scan.rows
        ],
        "abstentions": scan.abstentions,
        "footer": scan.footer,
        "notes": list(scan.notes),
    }


# -- images -----------------------------------------------------------------

_UUID: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# The canonical path of an uploaded image (the backend media module).
IMAGE_PATH_RE: Final[re.Pattern[str]] = re.compile(rf"^/api/media/images/({_UUID})$")
# The asset name of an uploaded image: `img-<uuid>.<ext>`.
IMAGE_ASSET_RE: Final[re.Pattern[str]] = re.compile(rf"^img-({_UUID})\.(?:png|jpg|gif|webp)$")


def image_assets(assets: Collection[str]) -> dict[str, str]:
    """Map the uuid of each uploaded image asset to its asset name."""
    matches = (IMAGE_ASSET_RE.fullmatch(name) for name in assets)
    return {match.group(1): match.group(0) for match in matches if match is not None}


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
    return (
        {"t": "sym", "v": _ARROWS.get(piece, piece)} if index % 2 else _text(piece)
        for index, piece in enumerate(_SYMBOL_SPLIT_RE.split(text))
        if piece
    )


def _as_list(value: str | list[str] | None) -> list[str]:
    match value:
        case None:
            return []
        case list():
            return value
        case str():
            return [v.strip() for v in value.split(",") if v.strip()]


def _lookup(meta: Meta, name: str) -> str | list[str] | None:
    return next((meta[key] for key in _FIELD_ALIASES.get(name, (name,)) if key in meta), None)


def _count(args: Mapping[str, str], *keys: str) -> int:
    key = next((key for key in keys if key in args), None)
    if key is None:
        return 0
    try:
        return int(args[key])
    except ValueError:
        return 0


def _vote_shortcode(rest: str) -> Node:
    """Build the tally of a `{{vote ja=1 nein=2 enthaltung=0}}` marker."""
    args = dict(tok.split("=", 1) for tok in rest.split() if "=" in tok)
    return {
        "t": "vote",
        "yes": _count(args, "ja", "yes"),
        "no": _count(args, "nein", "no"),
        "abstain": _count(args, "enthaltung", "enth", "abstain"),
    }


def _shortcode(inner: str, meta: Meta) -> list[Node]:
    """Expand the body of one `{{...}}` marker.

    An unknown shortcode comes back as literal text, braces included, so a
    typo stays visible in the PDF.
    """
    head, _, tail = inner.strip().partition(" ")
    name = head.lower()
    rest = tail.strip()
    match name:
        case "time" if rest:
            return [{"t": "time", "v": rest}]
        case "vote":
            return [_vote_shortcode(rest)]
        case "count":
            return [_text(str(len(_as_list(_lookup(meta, rest.lower())))))]
        case _ if name in _LIST_FIELDS:
            return [_text(", ".join(_as_list(_lookup(meta, name))))]
        case _ if name in _FIELD_ALIASES:
            value = _lookup(meta, name)
            return [_text(value if isinstance(value, str) else "")]
        case _:
            return [_text("{{" + inner + "}}")]


def _inline_text(text: str, meta: Meta) -> Iterator[Node]:
    """Expand the shortcodes of a text run and split the rest into prose."""
    return (
        node
        for index, piece in enumerate(SHORTCODE_RE.split(text))
        for node in (_shortcode(piece, meta) if index % 2 else _prose(piece))
    )


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
    match _kind(node):
        case "RawText":
            return _leaf(node)
        case "Literal":
            return "\\" + (_leaf(node) or "")
        case "LineBreak":
            return "\n"
        case _:
            return None


@dataclass(frozen=True, slots=True)
class _FenceScan:
    """The fence state after one line, and whether that line stays."""

    in_code: bool = False
    open_fences: int = 0
    keep: bool = True


def _fence_line(scan: _FenceScan, line: str) -> _FenceScan:
    """Advance the fence state over one line."""
    match line:
        case _ if _CODE_FENCE_RE.match(line):
            return replace(scan, in_code=not scan.in_code, keep=True)
        case _ if not scan.in_code and _ANTRAG_OPEN_RE.match(line):
            return replace(scan, open_fences=scan.open_fences + 1, keep=False)
        case _ if not scan.in_code and scan.open_fences and _FENCE_CLOSE_RE.match(line):
            return replace(scan, open_fences=scan.open_fences - 1, keep=False)
        case _:
            return replace(scan, keep=True)


def strip_antrag_fences(markdown: str) -> str:
    """Drop the `:::antrag{...}` fence and its closing `:::`, outside code.

    Only a closing `:::` that belongs to an open application fence goes. Any
    other `:::` line stays text.
    """
    lines = markdown.split("\n")
    scans = itertools.accumulate(lines, _fence_line, initial=_FenceScan())
    kept = zip(lines, itertools.islice(scans, 1, None), strict=True)
    return "\n".join(line for line, scan in kept if scan.keep)


# -- the converter ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Converter:
    """Convert marko nodes at one nesting depth and list level.

    The converter is a value: a nested node gets a copy one level deeper, so
    the depth and the list levels need no bookkeeping on the way back up.
    """

    meta: Meta
    # uuid -> asset name of the uploaded images.
    images: Mapping[str, str]
    depth: int = 0
    ul: int = 0
    ol: int = 0

    def _enter(self) -> _Converter:
        """Return the converter one nesting level deeper.

        Raises:
            ConversionError: The Markdown nests deeper than `MAX_DEPTH`.
        """
        if self.depth + 1 > MAX_DEPTH:
            raise ConversionError(f"the Markdown nests deeper than {MAX_DEPTH} levels")
        return replace(self, depth=self.depth + 1)

    # -- inline ------------------------------------------------------------

    def inline(self, node: object) -> list[Node]:
        kind = _kind(node)
        text = _leaf(node)
        match kind:
            case "CodeSpan":
                return [{"t": "code", "v": text or ""}]
            case "RawText" | "Literal":
                return list(_inline_text(text or "", self.meta))
            case "InlineHTML":
                return [_text(text or "")]
            case "LineBreak":
                soft = bool(getattr(node, "soft", False))
                return [_text(" ")] if soft else [{"t": "br"}]
            case _:
                return self._enter()._nested_inline(node, kind)

    def _nested_inline(self, node: object, kind: str) -> list[Node]:
        """Convert an inline node that holds other inline nodes."""
        match kind:
            case "StrongEmphasis":
                return [{"t": "strong", "c": self.inlines(node)}]
            case "Emphasis":
                return [{"t": "emph", "c": self.inlines(node)}]
            case "Strikethrough":
                return [{"t": "strike", "c": self.inlines(node)}]
            case "Link" | "AutoLink" | "Url":
                dest = str(getattr(node, "dest", ""))
                external = EXTERNAL_URL_RE.match(dest)
                return (
                    [{"t": "link", "url": dest, "c": self.inlines(node)}]
                    if external
                    else self.inlines(node)
                )
            case "Image":
                return [self._image(node)]
            case _:
                return self.inlines(node)

    def _image(self, node: object) -> Node:
        """Build an image node: the uploaded asset, else the alt text only.

        The render has no network and reads no file of the author. Only the
        canonical path of an uploaded image whose bytes came with the request
        names an asset; every other image keeps its alt text.
        """
        alt = "".join(_plain(c) for c in _children(node)).strip() or "Bild"
        match = IMAGE_PATH_RE.fullmatch(str(getattr(node, "dest", "")))
        asset = self.images.get(match.group(1)) if match is not None else None
        if asset is None:
            return {"t": "image", "alt": alt}
        return {"t": "image", "asset": asset, "alt": alt}

    def inlines(self, node: object) -> list[Node]:
        return self._inline_nodes(_children(node))

    def _inline_nodes(self, kids: list[object]) -> list[Node]:
        """Convert inline children and lift each `$...$` span into a formula.

        A formula can span several marko nodes, as soon as its body holds an
        escape. The method rebuilds the source of the plain children, finds
        the formulas in it and converts the rest the ordinary way. A node with
        structure stands in the source as a newline. A formula holds no
        newline, so it never spans such a node; its span ends at -1.
        """
        texts = [_source_text(child) for child in kids]
        plains = ["\n" if text is None else text for text in texts]
        starts = itertools.accumulate((len(plain) for plain in plains), initial=0)
        spans = [
            (child, start, start + len(plain) if text is not None else -1)
            for child, text, plain, start in zip(kids, texts, plains, starts, strict=False)
        ]
        source = "".join(plains)
        formulas = [(m.start(), m.end(), m.group(1)) for m in MATH_RE.finditer(source)]
        if not formulas:
            return [out for child in kids for out in self.inline(child)]
        return [
            out
            for child, start, end in spans
            for out in self._span_nodes(child, start, end, source, formulas)
        ]

    def _span_nodes(
        self,
        child: object,
        start: int,
        end: int,
        source: str,
        formulas: Sequence[tuple[int, int, str]],
    ) -> list[Node]:
        """Convert one inline child whose source is `source[start:end]`.

        A formula that overlaps the child becomes a math node in the child where
        it starts. The text between the formulas stays prose. A child that no
        formula touches converts the ordinary way.
        """
        if end < 0:
            return self.inline(child)
        hits = [(first, last, tex) for first, last, tex in formulas if last > start and first < end]
        # The formulas do not overlap, so the prose before each one starts where the last ended.
        cursors = [start, *(last for _, last, _ in hits)]
        pieces = [
            out
            for (first, _, tex), cursor in zip(hits, cursors, strict=False)
            for out in self._formula_nodes(source[cursor:first], tex, first >= start)
        ]
        cursor = cursors[-1]
        tail = (
            []
            if cursor >= end
            else self.inline(child)
            if cursor == start
            else list(_inline_text(source[cursor:end], self.meta))
        )
        return [*pieces, *tail]

    def _formula_nodes(self, before: str, tex: str, starts_here: bool) -> list[Node]:
        """Convert the prose in front of a formula, then the formula if it starts here."""
        return [
            *_inline_text(before, self.meta),
            *([{"t": "math", "tex": tex}] if starts_here else []),
        ]

    # -- blocks ------------------------------------------------------------

    def block(self, node: object) -> list[Node]:
        kind = _kind(node)
        if kind in ("BlankLine", "LinkRefDef", "HTMLBlock"):
            # A link definition and raw HTML print nothing.
            return []
        return self._enter()._block(node, kind)

    def _block(self, node: object, kind: str) -> list[Node]:
        match kind:
            case "Heading" | "SetextHeading":
                level = int(getattr(node, "level", 1))
                return [{"t": "heading", "level": level, "c": self.inlines(node)}]
            case "Paragraph":
                return [self._paragraph(node)]
            case "List":
                return [self._list(node)]
            case "Quote":
                return self._quote(node)
            case "FencedCode" | "CodeBlock":
                return [self._codeblock(node)]
            case "ThematicBreak":
                return [{"t": "rule"}]
            case "Table":
                return self._table(node)
            case _:
                return self.blocks(_children(node))

    def _paragraph(self, node: object) -> Node:
        """Build a paragraph: a display formula, a block image, or a run of inline nodes."""
        display = self._display_math(node)
        if display is not None:
            return display
        content = _trim(self.inlines(node))
        if len(content) == 1 and content[0].get("t") == "image" and "asset" in content[0]:
            # A paragraph of one image is a block image, centered and scaled.
            return {"t": "figure", "asset": content[0]["asset"], "alt": content[0]["alt"]}
        return {"t": "par", "c": content}

    def _list(self, node: object) -> Node:
        """Build a bullet or a numbered list.

        LaTeX counts the itemize and the enumerate depth apart: a bullet list
        inside a numbered list still takes the first bullet.
        """
        ordered = bool(getattr(node, "ordered", False))
        level = self.ol if ordered else self.ul
        nested = replace(self, ol=self.ol + 1) if ordered else replace(self, ul=self.ul + 1)
        items = [nested.blocks(_children(c)) for c in _children(node) if _kind(c) == "ListItem"]
        return {
            "t": "list",
            "ordered": ordered,
            "start": int(getattr(node, "start", 1) or 1),
            "olevel" if ordered else "ulevel": level,
            "items": items,
        }

    def _codeblock(self, node: object) -> Node:
        """Build a code block from the text of a fenced or an indented block."""
        kids = _children(node)
        leaf = _leaf(node)
        text = leaf if leaf is not None else (_leaf(kids[0]) if kids else "")
        return {"t": "codeblock", "v": (text or "").rstrip("\n")}

    def blocks(self, nodes: list[object]) -> list[Node]:
        return [out for node in nodes for out in self.block(node)]

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
        match self._marker(kids):
            case None:
                return [{"t": "quote", "c": self.blocks(kids)}]
            case (name, _) if name in _VOTE_MARKERS:
                return [self._vote(kids)]
            case (name, _) if name in _SIGNATURE_MARKERS:
                return [self._signature_callout(kids)]
            case (name, rest):
                return [self._labelled(kids, name, rest)]

    def _labelled(self, kids: list[object], name: str, rest: str) -> Node:
        """Build a callout box. Its bold label and the rest of the marker line open the body."""
        box, label = _LABELLED[name]
        first = cast("list[object]", _children(kids[0]))
        head: list[Node] = [
            *([{"t": "strong", "c": [_text(label)]}] if label else []),
            *_inline_text(rest, self.meta),
            *self._inline_nodes(first[1:]),
        ]
        return {"t": "callout", "kind": box, "c": [{"t": "par", "c": head}, *self.blocks(kids[1:])]}

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
        return [
            line
            for kid in kids
            if _kind(kid) == "Paragraph"
            for line in _split_at_breaks(_children(kid))
            if line
        ]

    def _vote_line(self, index: int, line: list[object]) -> list[Node]:
        """Convert one body line of a tally box. The first line drops the callout marker."""
        if index == 0:
            marker_text = CALLOUT_RE.sub("", _leaf(line[0]) or "", count=1)
            return [*_inline_text(marker_text, self.meta), *self._inline_nodes(line[1:])]
        return self._inline_nodes(line)

    def _vote(self, kids: list[object]) -> Node:
        """Build a tally box. The tally line gives the counts, the rest is the body.

        A callout without a tally line, such as the election of several candidates,
        has no Ja/Nein/Enthaltung counts. `counts` is then false, and the template
        draws the body without the three boxes. An election also gets `election`
        (see `_election`), and the template draws its ranking. A poll gets `poll`
        (see `_poll`), and the template draws its options the same way. The template
        draws the ranking of both, so only the question stays a body line.
        """
        lines = self._callout_lines(kids)
        texts = _unmarked(["".join(_plain(n) for n in line) for line in lines])
        tally = next((t.strip() for t in texts if _is_tally_line(t)), "")
        body = [
            _trim(self._vote_line(index, line))
            for index, (line, text) in enumerate(zip(lines, texts, strict=True))
            if text.strip() and not _is_tally_line(text)
        ]
        rest = [t.strip() for t in texts[1:] if t.strip()]
        election = None if tally else _election(rest)
        poll = None if tally or election is not None else _poll(rest)
        ranking: Node = (
            {"election": election}
            if election is not None
            else {"poll": poll}
            if poll is not None
            else {}
        )
        return {
            "t": "tally",
            "yes": _tally(tally, "yes"),
            "no": _tally(tally, "no"),
            "abstain": _tally(tally, "abstain"),
            "counts": bool(tally),
            "lines": body[:1] if ranking else body,
            **ranking,
        }

    def _signature_callout(self, kids: list[object]) -> Node:
        """Build a signature block from its `Rolle: Name` lines."""
        lines = _unmarked(["".join(_plain(n) for n in line) for line in self._callout_lines(kids)])
        entries = (entry.strip() for entry in lines)
        parts = (line.partition(":") for line in entries if line)
        return {
            "t": "signatures",
            "signers": [[role.strip(), person.strip()] for role, _, person in parts],
        }


def _split_at_breaks(inlines: list[object]) -> list[list[object]]:
    """Split a run of inline nodes at each line break; the breaks drop."""
    breaks = [index for index, node in enumerate(inlines) if _kind(node) == "LineBreak"]
    bounds = zip([-1, *breaks], [*breaks, len(inlines)], strict=True)
    return [inlines[after + 1 : until] for after, until in bounds]


def _unmarked(texts: list[str]) -> list[str]:
    """Drop the callout marker from the first of the plain text lines."""
    return [
        CALLOUT_RE.sub("", text, count=1) if index == 0 else text
        for index, text in enumerate(texts)
    ]


def _plain(node: object) -> str:
    """Return the plain text under a node, formatting dropped."""
    text = _leaf(node)
    if text is not None:
        return " " if _kind(node) == "LineBreak" else text
    return "".join(_plain(c) for c in _children(node))


def _trim_text(node: Node, *, first: bool, last: bool) -> Node:
    """Strip the outer whitespace of a text node at the start or the end of a run."""
    if node.get("t") != "text" or not (first or last):
        return node
    value = str(node["v"])
    left = value.lstrip() if first else value
    return _text(left.rstrip() if last else left)


def _trim(nodes: list[Node]) -> list[Node]:
    """Strip the leading and the trailing whitespace of an inline run."""
    trimmed = (
        _trim_text(node, first=index == 0, last=index == len(nodes) - 1)
        for index, node in enumerate(nodes)
    )
    return [n for n in trimmed if not (n.get("t") == "text" and n.get("v") == "")]


def convert_body(markdown: str, meta: Meta, assets: Collection[str] = ()) -> list[Node]:
    """Convert the Markdown body of a protocol into block nodes.

    `assets` holds the names of the uploaded assets. An `img-<uuid>.<ext>` among
    them lets the image `/api/media/images/<uuid>` show.

    Raises:
        ConversionError: The Markdown nests too deep.
    """
    tree = _PARSER.parse(strip_antrag_fences(markdown))
    converter = _Converter(meta=meta, images=image_assets(assets))
    try:
        blocks = converter.blocks(_children(tree))
    except RecursionError:
        raise ConversionError("the Markdown nests too deep") from None
    return blocks
