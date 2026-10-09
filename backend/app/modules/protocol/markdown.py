"""Protocol Markdown: frontmatter, editor body and vote snippets.

The code here is pure and needs no database, so unit tests cover it directly.
`build_protocol_document` puts the YAML frontmatter in front of the Markdown
body that the editor supplies. The frontmatter carries `typ: protokoll` plus
the `gremium` name of the title page. `build_vote_snippet`
renders one vote as a Markdown section. The embed step appends that section to
the body.

Injection hardening: the result reaches the typst client as an HTTP body, and
no shell runs. Frontmatter scalars stay YAML-quoted. Snippet text stays
Markdown-escaped.

The typst render service turns the Markdown into data before Typst sees it,
so no part of the body runs as code there. The editor body is user-written
all the same, and `sanitize_user_markdown` stays as defense in depth. It
strips the `[//]: # "EXPR"` eval escape of the former pytex renderer in EVERY
CommonMark form: one line, several lines, nested in a container, and with
whitespace in the label. It also neutralizes an image with an absolute path or
a `..` path. Normal Markdown survives. A stored body thus stays free of the
known escape forms, whatever renderer reads it later.

Variant per gremium: the render service knows the protocol variants
`protocol-stupa` and `protocol-asta`, which pick the default logos. The
`cd_variant` value of the gremium selects one of them. For any other value
the variant stays `None`, and the service reads the logos from the `gremium`
frontmatter key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import time as _time

try:  # marko is optional here. The primary regex protection works without it.
    import marko as _marko  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - primary regex protection works without marko
    _marko = None  # type: ignore[assignment]


# RCE defense in depth.
# The former pytex renderer had a Markdown `eval` escape in its `trusted` mode. A
# link reference definition of the form `[//]: # "EXPR"` stayed invisible in the
# PDF and ran `eval(EXPR)` inside the render container. It fired ONLY when
# CommonMark parsed the definition with `label == "//"` AND `dest == "#"`. The
# typst renderer has no such escape. The strip stays, so no stored body carries
# the trigger.
#
# A line-oriented regex such as `^[ \t]*[...]: #` is NOT reliable. A link
# reference definition is a CommonMark block. It may span several lines
# (`[//]:\n#\n"EXPR"`), nest inside a container (`> [//]: # "EXPR"` or
# `- [//]: # "EXPR"`) and carry whitespace or newlines inside the label
# (`[ // ]`). Every one of those forms escapes a simple per-line regex. The
# pattern below therefore removes the ENTIRE eval-capable definition: the head
# `[label] : #` with a bare `#` target, never a `#fragment`, plus the
# optional title (`"…"`, `'…'` or `(…)`). It tolerates whitespace and newlines
# wherever CommonMark allows them. A real reference link (`[foo]: #section`), an
# inline link, an image and the vote callout (`> [!abstimmung]`) stay untouched.
_EVAL_REFDEF_RE = re.compile(
    # The label excludes BOTH brackets (`[^\][]`, not `[^\]]`). A CommonMark
    # reference definition never carries an unescaped `[` in its label, and without
    # that exclusion a long run of `[` without a `]` rescans the label from EVERY `[`
    # position, which is O(N**2) backtracking (ReDoS).
    r"\[[^\][]*\]\s*:\s*#"  # definition head, target exactly `#`
    r"(?=[ \t\r\n\"'(]|$)"  # bare `#`: whitespace, a title delimiter or the line end follows
    r"[ \t]*"  # whitespace before the optional title
    r"(?:\r?\n[ \t]*)?"  # multi-line form may put the title on the next line
    r"""(?:"[^"]*"|'[^']*'|\([^)]*\)|[^\r\n]*)?""",  # optional title / rest of line
    re.DOTALL,
)


def _strip_eval_refdefs(markdown: str) -> str:
    r"""Remove every eval-capable `[label]: # "EXPR"` definition.

    The function strips the head and the expression of every bare-`#` link
    reference definition, in any CommonMark form. The eval trigger of pytex
    therefore never reaches the Markdown tree. Normal Markdown stays untouched.
    """
    return _EVAL_REFDEF_RE.sub("", markdown)


def _has_eval_refdef(markdown: str) -> bool:
    """Parse `markdown` with marko and report a remaining eval trigger.

    This is the structural check. A `LinkRefDef` node with `label == "//"` and
    `dest == "#"` fires the pytex eval, anywhere in the tree or in
    `document.link_ref_defs`. Without marko the primary regex protection
    applies alone, and the body counts as clean.
    """
    if _marko is None:  # pragma: no cover - primary regex protection covers all vectors
        return False
    document = _marko.Markdown().parse(markdown)
    refs = getattr(document, "link_ref_defs", {}) or {}
    if refs.get("//", (None,))[0] == "#":
        return True

    def _walk(node: object) -> bool:
        if (
            type(node).__name__ == "LinkRefDef"
            and getattr(node, "label", None) == "//"
            and getattr(node, "dest", None) == "#"
        ):
            return True
        children = getattr(node, "children", None)
        if isinstance(children, list):
            return any(_walk(c) for c in children if not isinstance(c, str))
        return False

    return _walk(document)


# Internal pytex marker for the evaluated expression: `\iffalse{pytex(...)}\fi`.
# An editor body never needs it. The pattern also matches a multi-line marker.
_PYTEX_IFFALSE_RE = re.compile(
    r"\\iffalse\s*\{?\s*pytex\s*\(.*?\)\s*\}?\s*\\fi",
    re.DOTALL | re.IGNORECASE,
)
# Image path traversal: a Markdown image `![alt](PATH)` with an absolute path
# (`/...`) or a `../` path could reach a container file through
# `\includegraphics` and leak a readable image from outside the render
# directory. The code replaces such a path with a plain-text placeholder. A
# relative in-repo path stays untouched.
_UNSAFE_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*(?P<path>[^)\s]+)[^)]*\)",
)


def _is_unsafe_image_path(path: str) -> bool:
    """Return True for an absolute-root or `..` traversal image path."""
    if path.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:[\\/]", path):
        return True  # absolute: POSIX, UNC or a Windows drive
    # A `../` anywhere, also URL-encoded as `%2e%2e`, is traversal.
    normalized = path.replace("\\", "/").lower()
    return "../" in normalized or "%2e%2e" in normalized


def _neutralize_unsafe_image(match: re.Match[str]) -> str:
    path = match.group("path")
    if not _is_unsafe_image_path(path):
        return match.group(0)  # a harmless relative path stays unchanged
    alt = match.group("alt").strip() or "Bild"
    # Do NOT pass the path through. Replace it with a plain-text placeholder.
    return f"*[{_md_escape(alt)} (Bild entfernt)]*"


def sanitize_user_markdown(markdown: str) -> str:
    r"""Strip the former pytex `eval` escapes and path-traversal images from user Markdown.

    The function removes the RCE vectors: the `[//]: # "…"` comment eval in
    every CommonMark form, and `\iffalse{pytex(…)}\fi`. It also neutralizes
    an image with an absolute path or a `..` path. Normal Markdown survives in
    full: headings, lists, emphasis, real links and images with relative
    paths, and vote callouts. The marko parse verifies the eval trigger
    structurally. While an eval-capable `LinkRefDef` survives, the strip
    repeats. The body therefore leaves without an eval vector.
    """
    cleaned = _PYTEX_IFFALSE_RE.sub("", markdown)
    cleaned = _strip_eval_refdefs(cleaned)
    # Structural backstop: an eval-capable LinkRefDef may survive, for example
    # with a future marko version. The loop strips again until none remains.
    for _ in range(3):
        if not _has_eval_refdef(cleaned):
            break
        cleaned = _strip_eval_refdefs(cleaned)
    cleaned = _UNSAFE_IMAGE_RE.sub(_neutralize_unsafe_image, cleaned)
    return cleaned

# Gremium `cd_variant` values that select a protocol render variant.
_PROTOCOL_VARIANTS = {"stupa", "asta"}


def protocol_variant_for(cd_variant: str | None) -> str | None:
    """Map `cd_variant` to the render variant `protocol-<cd>`, or `None` for auto."""
    if cd_variant in _PROTOCOL_VARIANTS:
        return f"protocol-{cd_variant}"
    return None


@dataclass(slots=True, frozen=True)
class KeeperLine:
    """One period of a protocol keeper for the header (Z3).

    The times are local `HH:MM` values. The TOP numbers are the 1-based numbers in
    the current agenda order, or `None` when the period has no agenda item there or
    the item no longer exists. The renderer then shows the time.
    """

    name: str
    from_time: str | None = None
    to_time: str | None = None
    from_top: int | None = None
    to_top: int | None = None


@dataclass(slots=True)
class ProtocolDoc:
    """All header data of a protocol, filled from the database by the service."""

    title: str
    gremium_name: str | None
    cd_variant: str | None
    date: _date | None
    markdown: str
    start_time: _time | None = None
    # Meeting end in local time, from `meeting.closed_at`. Together with the
    # start it forms the "Zeit: Start – Ende" title-page line, which the
    # renderer builds from `beginn` and `ende`.
    end_time: _time | None = None
    # The legacy single name. It stays as the fallback of a render service that does
    # not know `keepers` yet, and for a meeting without keeper periods.
    protokollant: str | None = None
    # Z3: every period of a protocol keeper, in time order. The renderer lists them
    # in the header and adds a handover line at the agenda item where a later
    # period starts. Only the internal variant carries them.
    keepers: list[KeeperLine] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    # F17: the excused members are their own group.
    excused: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    # The real start in local time (`YYYY-MM-DD HH:MM`), or the planned start when
    # the meeting has no recorded start.
    started_at: str | None = None
    datalines: list[str] = field(default_factory=list)
    # Quorum from the present members against the active members. `None` means
    # no statement.
    quorate: bool | None = None


# Signature block of the renderer (`unterschriften`). The frontmatter
# supplies the name of the secretary. The board line stays a blank
# line for a hand signature.
_SIGNATURES = ["Schriftführung", "Vorstand"]


def _yaml_list(key: str, items: list[str]) -> list[str]:
    """Build a YAML block list with quoted values, or nothing for an empty list."""
    if not items:
        return []
    return [f"{key}:", *(f"  - {_yaml_scalar(i)}" for i in items)]


def _yaml_keepers(keepers: list[KeeperLine]) -> list[str]:
    """Build the `keepers` block list of mappings, with quoted values only."""
    if not keepers:
        return []
    lines = ["keepers:"]
    for keeper in keepers:
        fields = (
            ("name", keeper.name),
            ("from", keeper.from_time),
            ("to", keeper.to_time),
            ("from_top", None if keeper.from_top is None else str(keeper.from_top)),
            ("to_top", None if keeper.to_top is None else str(keeper.to_top)),
        )
        present = [(k, v) for k, v in fields if v]
        for n, (key, value) in enumerate(present):
            lead = "  - " if n == 0 else "    "
            lines.append(f"{lead}{key}: {_yaml_scalar(value)}")
    return lines


def _frontmatter(doc: ProtocolDoc) -> list[str]:
    lines = ["---", f"title: {_yaml_scalar(doc.title)}", "typ: protokoll"]
    if doc.gremium_name:
        lines.append(f"gremium: {_yaml_scalar(doc.gremium_name)}")
    if doc.cd_variant:
        lines.append(f"cd: {_yaml_scalar(doc.cd_variant)}")
    if doc.date is not None:
        # `datum` fills the protocol header with date and time. `date` fills
        # the report title page.
        datum = doc.date.isoformat()
        if doc.start_time is not None:
            datum = f"{datum} {doc.start_time.strftime('%H:%M')}"
        lines.append(f"datum: {_yaml_scalar(datum)}")
        lines.append(f"date: {_yaml_scalar(doc.date.isoformat())}")
    # The renderer sets start and end into the "Zeit: Start – Ende" data line.
    if doc.start_time is not None:
        lines.append(f"beginn: {_yaml_scalar(doc.start_time.strftime('%H:%M'))}")
    if doc.end_time is not None:
        lines.append(f"ende: {_yaml_scalar(doc.end_time.strftime('%H:%M'))}")
    if doc.started_at:
        lines.append(f"started_at: {_yaml_scalar(doc.started_at)}")
    if doc.protokollant:
        lines.append(f"protokoll: {_yaml_scalar(doc.protokollant)}")
    lines += _yaml_keepers(doc.keepers)
    lines += _yaml_list("anwesend", doc.present)
    lines += _yaml_list("entschuldigt", doc.excused)
    lines += _yaml_list("abwesend", doc.absent)
    if doc.quorate is not None:
        # Quorum as a title-page data line.
        quorate = "Gegeben" if doc.quorate else "Nicht gegeben"
        lines.append(f"beschlussfaehigkeit: {_yaml_scalar(quorate)}")
    lines += _yaml_list("datalines", doc.datalines)
    # Signature page: the renderer sets one signature line per entry.
    lines += _yaml_list("unterschriften", _SIGNATURES)
    lines.append("---")
    return lines


def build_protocol_document(doc: ProtocolDoc) -> str:
    r"""Combine the frontmatter and the editor body into the final Markdown.

    The output is deterministic. `sanitize_user_markdown` cleans the
    user-written body of the former pytex `eval` escapes and of path-traversal
    images, as defense in depth. Normal Markdown stays verbatim. Frontmatter
    scalars stay YAML-quoted.
    """
    body = sanitize_user_markdown(doc.markdown).strip("\n")
    out = [*_frontmatter(doc), ""]
    if body:
        out.append(body)
    return "\n".join(out).rstrip() + "\n"


def guest_vote_note(
    present_members: int | None, present_guests: int | None, cast: int
) -> str:
    """Describe the base of a vote with guests (#17), as counts and never as names.

    Such a vote has no quorum; the majority of the cast ballots decides. The line
    names the attendance when the close fixed it.
    """
    parts: list[str] = []
    if present_members is not None and present_guests is not None:
        parts.append(f"{present_members} Mitglieder + {present_guests} Gäste anwesend")
    parts.append(f"Abgegeben {cast}")
    parts.append("Mehrheit der abgegebenen Stimmen")
    return " · ".join(parts)


def build_vote_snippet(
    title: str,
    counts: dict[str, int] | None,
    question: str | None = None,
    note: str | None = None,
    conditions: list[str] | None = None,
) -> str:
    """Render a vote as a protocol callout (`> [!abstimmung]`).

    The counts line holds `yes/no/abstain` or `ja/nein/enthaltung`, and the
    renderer turns it into the built-in tally box of the PDF. The function escapes all
    values and sets the title in bold. There is no separate result line,
    because the result reads from the tally box. The snippet stays part of the
    editable Markdown as a blockquote callout. `conditions` are the conditions of
    the decision (F1): one plain body line `Auflage n: text` each.
    """
    head = question.strip() if question and question.strip() else title
    lines = [f"> [!abstimmung] **{_md_escape(head)}**"]
    if counts:
        # The renderer detects the tally line by two or more of ja/nein/enthaltung
        # (yes/no/abstain). The ballot options carry exactly these keys.
        tally = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in counts.items())
        lines.append(f"> {tally}")
    for index, condition in enumerate(conditions or [], start=1):
        # A plain body line: the callout body of the renderer has no list.
        lines.append(f"> Auflage {index}: {_md_escape(condition)}")
    if note:
        # A plain body line of the callout: the renderer keeps it below the tally box.
        lines.append(f"> {_md_escape(note)}")
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ElectionLine:
    """One candidate of an election snippet (F2): name, votes and the outcome."""

    name: str
    votes: int
    elected: bool = False


@dataclass(frozen=True, slots=True)
class ElectionSnippet:
    """The protocol view of one election (F2), built from its stored result."""

    question: str
    seats: int
    round: int = 1
    candidates: list[ElectionLine] = field(default_factory=list)
    abstentions: int = 0
    # The single-candidate ballot (Ja/Nein/Enthaltung).
    yes: int | None = None
    no: int | None = None
    by_lot: bool = False
    lot_pending: bool = False
    runoff_names: list[str] = field(default_factory=list)
    runoff_seats: int = 0
    closed: bool = True


def build_election_snippet(view: ElectionSnippet, *, public: bool = False) -> str:
    """Render an election as a protocol callout (`> [!abstimmung]`, F2).

    The internal snippet holds the ballot, the seats, the votes per candidate, the
    abstentions, the elected candidates and the notes „durch Los entschieden“ or
    „Stichwahl (n. Wahlgang)“. The public snippet (`public=True`) names only the
    elected candidates; the others appear as a count, and no vote count travels. The
    single-candidate ballot writes its Ja/Nein/Enthaltung line, which the renderer
    turns into the tally box (internal only).

    A runoff copies the question of its election, so its head line names the round
    („Frage (2. Wahlgang)“). Each round then has its own head line, which
    `replace_vote_block` and `vote_in_body` match on.
    """
    head = _md_escape(view.question)
    if view.round > 1:
        head += f" ({view.round}. Wahlgang)"
    lines = [f"> [!abstimmung] **{head}**"]
    meta = f"Wahl · {view.seats} Posten"
    if view.round > 1:
        meta += f" · Stichwahl ({view.round}. Wahlgang)"
    lines.append(f"> {meta}")
    elected = [c.name for c in view.candidates if c.elected]
    if not public and view.closed:
        if view.yes is not None and view.no is not None:
            name = view.candidates[0].name if view.candidates else ""
            lines.append(f"> Kandidatur: {_md_escape(name)}")
            lines.append(f"> ja: {view.yes}, nein: {view.no}, enthaltung: {view.abstentions}")
        else:
            votes = " · ".join(f"{_md_escape(c.name)}: {c.votes}" for c in view.candidates)
            lines.append(f"> {votes} · Enthaltungen: {view.abstentions}")
    if view.closed:
        names = ", ".join(_md_escape(n) for n in elected) if elected else "niemand"
        lines.append(f"> Gewählt: {names}")
        if public:
            others = len(view.candidates) - len(elected)
            if others > 0:
                lines.append(f"> {others} weitere Kandidierende")
        if view.by_lot:
            lines.append("> Durch Los entschieden.")
        if view.lot_pending:
            lines.append("> Gleichstand: das Los steht aus.")
        if view.runoff_seats:
            who = ", ".join(_md_escape(n) for n in view.runoff_names)
            target = who if not public else f"{len(view.runoff_names)} Kandidierende"
            lines.append(
                f"> Stichwahl ({view.round + 1}. Wahlgang) um {view.runoff_seats} Posten: {target}"
            )
    return "\n".join(lines)


def replace_vote_block(body: str, snippet: str) -> str:
    """Replace the callout of a vote in `body` with `snippet`.

    The head line of `snippet` (marker and bold question) finds the block; the block
    runs over the following `>` lines. The public protocol uses this to swap an
    internal election callout that the protokollant put into the text for its public
    form (F2). A body without the head stays as it is.
    """
    head = snippet.split("\n", 1)[0].strip()
    lines = body.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == head:
            out.extend(snippet.split("\n"))
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def vote_in_body(body: str, snippet: str) -> bool:
    """Report whether the body already carries the vote of `snippet`.

    The protokollant inserts the same callout from the editor. The marker line with
    the bold question identifies it, so the tally can differ (a re-count) and the
    box still counts as present.
    """
    head = snippet.split("\n", 1)[0].strip()
    return any(line.strip() == head for line in body.split("\n"))


def demote_headings(markdown: str) -> str:
    """Demote all ATX headings in an agenda-item body by one level.

    The agenda-item heading is the only top-level `#`, and the renderer numbers
    it as "TOP n". Without the demotion, the renderer would number every `#` heading of the
    body as a separate agenda item. Code fences stay untouched. Level 6 stays
    at level 6.
    """
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        elif not in_fence and stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            if 1 <= hashes <= 5 and stripped[hashes : hashes + 1] in (" ", "\t"):
                line = line.replace("#", "##", 1)
        out.append(line)
    return "\n".join(out)


def _yaml_scalar(value: str) -> str:
    """Quote a string as a safe double-quoted YAML scalar that cannot inject a directive."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _md_escape(text: str) -> str:
    """Minimal escape for inline Markdown text (newline → space)."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
