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
a `..` path, except the canonical path of an uploaded image
(`/api/media/images/<id>`). Normal Markdown survives. A stored body thus stays free of the
known escape forms, whatever renderer reads it later.

Variant per gremium: the render service knows the protocol variants
`protocol-stupa` and `protocol-asta`, which pick the default logos. The
`cd_variant` value of the gremium selects one of them. For any other value
the variant stays `None`, and the service reads the logos from the `gremium`
frontmatter key.
"""

from __future__ import annotations

import operator
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date as _date
from datetime import datetime
from datetime import time as _time
from functools import partial, reduce
from itertools import accumulate
from zoneinfo import ZoneInfo

from app.modules.media.refs import is_image_path

try:
    import marko as _marko  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - primary regex protection works without marko
    _marko = None


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

    The pytex renderer ran `eval(EXPR)` for a definition that CommonMark parsed with
    `label == "//"` AND `dest == "#"`, and the definition stayed invisible in the PDF.
    The typst renderer has no such escape. The strip stays as RCE defense in depth, so
    no stored body carries the trigger.

    A line-oriented regex such as `^[ \t]*[...]: #` is NOT reliable, because a link
    reference definition is a CommonMark block. It can span several lines
    (`[//]:\n#\n"EXPR"`), nest in a container (`> [//]: # "EXPR"` or `- [//]: # "EXPR"`)
    and carry whitespace or newlines in the label (`[ // ]`). The pattern therefore
    removes the ENTIRE definition: the head `[label] : #` with a bare `#` target, never
    a `#fragment`, plus the optional title (`"…"`, `'…'` or `(…)`). It accepts
    whitespace and newlines wherever CommonMark allows them. A real reference link
    (`[foo]: #section`), an inline link, an image and the vote callout (`>
    [!abstimmung]`) stay untouched.
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


_PYTEX_IFFALSE_RE = re.compile(
    r"\\iffalse\s*\{?\s*pytex\s*\(.*?\)\s*\}?\s*\\fi",
    re.DOTALL | re.IGNORECASE,
)
_UNSAFE_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*(?P<path>[^)\s]+)[^)]*\)",
)


def _is_unsafe_image_path(path: str) -> bool:
    """Return True for an absolute-root or `..` traversal image path.

    An absolute path is a POSIX, UNC or Windows drive path. A `../` anywhere, also
    URL-encoded as `%2e%2e`, is traversal.
    """
    if path.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:[\\/]", path):
        return True
    normalized = path.replace("\\", "/").lower()
    return "../" in normalized or "%2e%2e" in normalized


def _neutralize_unsafe_image(match: re.Match[str]) -> str:
    r"""Replace an unsafe image path with a plain-text placeholder.

    An absolute path or a `../` path could reach a container file through
    `\includegraphics` and leak a readable image from outside the render directory, so
    the path is never passed through. A harmless relative path stays unchanged. The
    canonical path of an uploaded image (`/api/media/images/<id>`) stays too: it is
    absolute but no file path, because the render service maps it to an uploaded asset
    and never reads a file for it.
    """
    path = match.group("path")
    if is_image_path(path) or not _is_unsafe_image_path(path):
        return match.group(0)
    alt = match.group("alt").strip() or "Bild"
    return f"*[{_md_escape(alt)} (Bild entfernt)]*"


def _strip_until_clean(markdown: str, rounds: int) -> str:
    """Strip again while marko still finds an eval trigger, at most `rounds` more times."""
    clean = rounds == 0 or not _has_eval_refdef(markdown)
    return markdown if clean else _strip_until_clean(_strip_eval_refdefs(markdown), rounds - 1)


def sanitize_user_markdown(markdown: str) -> str:
    r"""Strip the former pytex `eval` escapes and path-traversal images from user Markdown.

    The function removes the RCE vectors: the `[//]: # "…"` comment eval in
    every CommonMark form, and `\iffalse{pytex(…)}\fi`. It also neutralizes
    an image with an absolute path or a `..` path. Normal Markdown survives in
    full: headings, lists, emphasis, real links, images with relative paths or
    the canonical path of an uploaded image, and vote callouts. The marko parse
    verifies the eval trigger structurally. While an eval-capable `LinkRefDef` survives, the strip
    repeats. The body therefore leaves without an eval vector.

    The strip runs again at most three times, as a structural backstop, because an
    eval-capable `LinkRefDef` can survive the regex, for example with a future marko
    version.

    The pytex marker `\iffalse{pytex(...)}\fi` holds the evaluated expression. An editor
    body never needs it, and the pattern also matches a multi-line marker.
    """
    stripped = _strip_eval_refdefs(_PYTEX_IFFALSE_RE.sub("", markdown))
    return _UNSAFE_IMAGE_RE.sub(_neutralize_unsafe_image, _strip_until_clean(stripped, 3))

#: Gremium `cd_variant` values that select a protocol render variant.
_PROTOCOL_VARIANTS = frozenset({"stupa", "asta"})


def protocol_variant_for(cd_variant: str | None) -> str | None:
    """Map `cd_variant` to the render variant `protocol-<cd>`, or `None` for auto."""
    return f"protocol-{cd_variant}" if cd_variant in _PROTOCOL_VARIANTS else None


@dataclass(slots=True, frozen=True)
class KeeperLine:
    """One period of a protocol keeper for the header.

    The times are local `HH:MM` values. The TOP numbers are the 1-based numbers in
    the current agenda order, or `None` when the period has no agenda item there or
    the item no longer exists. The renderer then shows the time.
    """

    name: str
    from_time: str | None = None
    to_time: str | None = None
    from_top: int | None = None
    to_top: int | None = None


@dataclass(frozen=True, slots=True)
class ProtocolDoc:
    """All header data of a protocol, filled from the database by the service.

    Attributes:
        end_time: The meeting end in local time, from `meeting.closed_at`. With the start it
            forms the "Zeit: Start – Ende" title-page line, which the renderer builds from
            `beginn` and `ende`.
        protokollant: The single keeper name. It is the fallback for a render service that
            does not know `keepers`, and for a meeting without keeper periods.
        keepers: Every period of a protocol keeper, in time order. The renderer lists them in
            the header and adds a handover line at the agenda item where a later period
            starts. Only the internal variant carries them.
        excused: The excused members, a group of their own.
        started_at: The real start in local time (`YYYY-MM-DD HH:MM`), or the planned start
            when the meeting has no recorded start.
        quorate: The quorum from the present members against the active members. `None`
            means no statement.
    """

    title: str
    gremium_name: str | None
    cd_variant: str | None
    date: _date | None
    markdown: str
    start_time: _time | None = None
    end_time: _time | None = None
    protokollant: str | None = None
    keepers: Sequence[KeeperLine] = ()
    present: Sequence[str] = ()
    excused: Sequence[str] = ()
    absent: Sequence[str] = ()
    started_at: str | None = None
    datalines: Sequence[str] = ()
    quorate: bool | None = None


#: Signature block of the renderer (`unterschriften`). The frontmatter
#: supplies the name of the secretary. The board line stays a blank
#: line for a hand signature.
_SIGNATURES = ("Schriftführung", "Vorstand")


def _yaml_list(key: str, items: Sequence[str]) -> list[str]:
    """Build a YAML block list with quoted values, or nothing for an empty list."""
    return [f"{key}:", *(f"  - {_yaml_scalar(i)}" for i in items)] if items else []


def _yaml_entry(key: str, value: str | None) -> list[str]:
    """Build one `key: "value"` line, or nothing for an empty or absent value."""
    return [f"{key}: {_yaml_scalar(value)}"] if value else []


def _yaml_keeper(keeper: KeeperLine) -> list[str]:
    """Build the lines of one keeper mapping: the set fields, the first one with the dash."""
    fields = (
        ("name", keeper.name),
        ("from", keeper.from_time),
        ("to", keeper.to_time),
        ("from_top", None if keeper.from_top is None else str(keeper.from_top)),
        ("to_top", None if keeper.to_top is None else str(keeper.to_top)),
    )
    present = [(k, v) for k, v in fields if v]
    return [
        f"{'  - ' if n == 0 else '    '}{key}: {_yaml_scalar(value)}"
        for n, (key, value) in enumerate(present)
    ]


def _yaml_keepers(keepers: Sequence[KeeperLine]) -> list[str]:
    """Build the `keepers` block list of mappings, with quoted values only."""
    lines = [line for keeper in keepers for line in _yaml_keeper(keeper)]
    return ["keepers:", *lines] if keepers else []


def _hhmm(value: _time | None) -> str | None:
    """Format a time as `HH:MM`, or `None` for no time."""
    return None if value is None else value.strftime("%H:%M")


def _datum(doc: ProtocolDoc) -> str | None:
    """Return the `datum` value: the date, with the start time when it is known."""
    day = None if doc.date is None else doc.date.isoformat()
    start = _hhmm(doc.start_time)
    return day if day is None or start is None else f"{day} {start}"


def _frontmatter(doc: ProtocolDoc) -> list[str]:
    """Build the YAML frontmatter lines of the protocol document.

    `datum` fills the protocol header with date and time, and `date` fills the report
    title page. The renderer sets `beginn` and `ende` into the "Zeit: Start – Ende" data
    line. The quorum is a title-page data line. The renderer sets one signature line per
    entry of `unterschriften`.
    """
    quorate = None if doc.quorate is None else ("Gegeben" if doc.quorate else "Nicht gegeben")
    return [
        "---",
        f"title: {_yaml_scalar(doc.title)}",
        "typ: protokoll",
        *_yaml_entry("gremium", doc.gremium_name),
        *_yaml_entry("cd", doc.cd_variant),
        *_yaml_entry("datum", _datum(doc)),
        *_yaml_entry("date", None if doc.date is None else doc.date.isoformat()),
        *_yaml_entry("beginn", _hhmm(doc.start_time)),
        *_yaml_entry("ende", _hhmm(doc.end_time)),
        *_yaml_entry("started_at", doc.started_at),
        *_yaml_entry("protokoll", doc.protokollant),
        *_yaml_keepers(doc.keepers),
        *_yaml_list("anwesend", doc.present),
        *_yaml_list("entschuldigt", doc.excused),
        *_yaml_list("abwesend", doc.absent),
        *_yaml_entry("beschlussfaehigkeit", quorate),
        *_yaml_list("datalines", doc.datalines),
        *_yaml_list("unterschriften", _SIGNATURES),
        "---",
    ]


def build_protocol_document(doc: ProtocolDoc) -> str:
    r"""Combine the frontmatter and the editor body into the final Markdown.

    The output is deterministic. `sanitize_user_markdown` cleans the
    user-written body of the former pytex `eval` escapes and of path-traversal
    images, as defense in depth. Normal Markdown stays verbatim. Frontmatter
    scalars stay YAML-quoted.
    """
    body = sanitize_user_markdown(doc.markdown).strip("\n")
    return "\n".join([*_frontmatter(doc), "", *([body] if body else [])]).rstrip() + "\n"


def guest_vote_note(
    present_members: int | None, present_guests: int | None, cast: int
) -> str:
    """Describe the base of a vote with guests, as counts and never as names.

    Such a vote has no quorum; the majority of the cast ballots decides. The line
    names the attendance when the close fixed it.
    """
    known = present_members is not None and present_guests is not None
    attendance = f"{present_members} Mitglieder + {present_guests} Gäste anwesend"
    return " · ".join(
        [*([attendance] if known else []), f"Abgegeben {cast}", "Mehrheit der abgegebenen Stimmen"]
    )


def build_vote_snippet(
    title: str,
    counts: Mapping[str, int] | None,
    question: str | None = None,
    note: str | None = None,
    conditions: Sequence[str] | None = None,
) -> str:
    """Render a vote as a protocol callout (`> [!abstimmung]`).

    The counts line holds `yes/no/abstain` or `ja/nein/enthaltung`, and the
    renderer turns it into the built-in tally box of the PDF. The function escapes all
    values and sets the title in bold. There is no separate result line,
    because the result reads from the tally box. The snippet stays part of the
    editable Markdown as a blockquote callout. `conditions` are the conditions of
    the decision: one plain body line `Auflage n: text` each.

    The renderer detects the tally line by two or more of ja/nein/enthaltung, and the
    ballot options carry exactly these keys. A condition or the note is a plain body
    line, because the callout body of the renderer has no list. The renderer keeps the
    note below the tally box.
    """
    head = question.strip() if question and question.strip() else title
    tally = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in (counts or {}).items())
    return "\n".join(
        [
            f"> [!abstimmung] **{_md_escape(head)}**",
            *([f"> {tally}"] if counts else []),
            *(
                f"> Auflage {index}: {_md_escape(condition)}"
                for index, condition in enumerate(conditions or (), start=1)
            ),
            *([f"> {_md_escape(note)}"] if note else []),
        ]
    )


@dataclass(frozen=True, slots=True)
class ElectionLine:
    """One candidate of an election snippet: name, votes and the outcome."""

    name: str
    votes: int
    elected: bool = False


@dataclass(frozen=True, slots=True)
class ElectionSnippet:
    """The protocol view of one election, built from its stored result."""

    question: str
    seats: int
    round: int = 1
    candidates: Sequence[ElectionLine] = ()
    abstentions: int = 0
    #: The single-candidate ballot (Ja/Nein/Enthaltung).
    yes: int | None = None
    no: int | None = None
    by_lot: bool = False
    lot_pending: bool = False
    runoff_names: Sequence[str] = ()
    runoff_seats: int = 0
    closed: bool = True
    #: The number of a repeat ("erneut abstimmen"); 1 for an election that repeats nothing.
    attempt: int = 1


def _election_head(view: ElectionSnippet) -> str:
    """Return the escaped question, with the number of the ballot from the second one on."""
    number = view.round + view.attempt - 1
    head = _md_escape(view.question)
    return f"{head} ({number}. Wahlgang)" if number > 1 else head


def _election_ballot(view: ElectionSnippet) -> list[str]:
    """Return the vote lines of the internal snippet of a closed election."""
    match (view.yes, view.no):
        case (int() as yes, int() as no):
            name = view.candidates[0].name if view.candidates else ""
            return [
                f"> Kandidatur: {_md_escape(name)}",
                f"> ja: {yes}, nein: {no}, enthaltung: {view.abstentions}",
            ]
        case _:
            votes = " · ".join(f"{_md_escape(c.name)}: {c.votes}" for c in view.candidates)
            return [f"> {votes} · Enthaltungen: {view.abstentions}"]


def _election_outcome(view: ElectionSnippet, *, public: bool) -> list[str]:
    """Return the outcome lines of a closed election: elected, lot and runoff notes."""
    elected = [c.name for c in view.candidates if c.elected]
    names = ", ".join(_md_escape(n) for n in elected) if elected else "niemand"
    others = len(view.candidates) - len(elected)
    who = ", ".join(_md_escape(n) for n in view.runoff_names)
    target = who if not public else f"{len(view.runoff_names)} Kandidierende"
    runoff = f"> Stichwahl ({view.round + 1}. Wahlgang) um {view.runoff_seats} Posten: {target}"
    return [
        f"> Gewählt: {names}",
        *([f"> {others} weitere Kandidierende"] if public and others > 0 else []),
        *(["> Durch Los entschieden."] if view.by_lot else []),
        *(["> Gleichstand: das Los steht aus."] if view.lot_pending else []),
        *([runoff] if view.runoff_seats else []),
    ]


def build_election_snippet(view: ElectionSnippet, *, public: bool = False) -> str:
    """Render an election as a protocol callout (`> [!abstimmung]`).

    The internal snippet holds the ballot, the seats, the votes per candidate, the
    abstentions, the elected candidates and the notes „durch Los entschieden“ or
    „Stichwahl (n. Wahlgang)“. The public snippet (`public=True`) names only the
    elected candidates; the others appear as a count, and no vote count travels. The
    single-candidate ballot writes its Ja/Nein/Enthaltung line, which the renderer
    turns into the tally box (internal only).

    A runoff copies the question of its election, so its head line names the round
    („Frage (2. Wahlgang)“). A repeat of an election counts on in the same way
    (`attempt`), but its kind line names no runoff. Each round then has its own head line,
    which `replace_vote_blocks` and `votes_in_body` match on.
    """
    runoff = f" · Stichwahl ({view.round}. Wahlgang)" if view.round > 1 else ""
    ballot = _election_ballot(view) if view.closed and not public else []
    outcome = _election_outcome(view, public=public) if view.closed else []
    return "\n".join(
        [
            f"> [!abstimmung] **{_election_head(view)}**",
            f"> Wahl · {view.seats} Posten{runoff}",
            *ballot,
            *outcome,
        ]
    )


@dataclass(frozen=True, slots=True)
class PollLine:
    """One option of a poll snippet: its label, its votes and the top mark.

    A date poll counts the Ja answers in ``count`` and the Vielleicht answers in
    ``maybe``.
    """

    label: str
    count: int
    maybe: int | None = None
    top: bool = False


@dataclass(frozen=True, slots=True)
class PollSnippet:
    """The protocol view of one poll, built from its config and its stored result."""

    question: str
    #: "Umfrage · Einzelwahl", "Umfrage · Mehrfachwahl, höchstens 2", "Terminumfrage".
    meta: str
    lines: Sequence[PollLine] = ()
    #: None for a date poll: it has no abstention.
    abstentions: int | None = 0
    ballots: int = 0
    date: bool = False
    closed: bool = True


def _poll_result(view: PollSnippet) -> list[str]:
    """Return the result lines of a closed poll: the votes per option, the top and the answers."""
    top = [_md_escape(line.label) for line in view.lines if line.top]
    lead = "Bester Termin" if view.date else "Meiste Stimmen"
    answers = "Antwort" if view.ballots == 1 else "Antworten"
    return [
        *(
            f"> {_md_escape(line.label)}: "
            + (f"{line.count} (+{line.maybe})" if line.maybe is not None else str(line.count))
            for line in view.lines
        ),
        *([f"> Enthaltungen: {view.abstentions}"] if view.abstentions is not None else []),
        *(["> Zahl = Ja, (+n) = Vielleicht"] if view.date else []),
        *([f"> {lead}: {', '.join(top)}"] if top else []),
        f"> {view.ballots} {answers}",
    ]


def build_poll_snippet(view: PollSnippet) -> str:
    """Render a poll as a protocol callout (`> [!abstimmung]`).

    The snippet holds the question, the kind of the poll and, once closed, one line
    per option with its votes (highest first; a date poll as „3 (+2)“ = Ja and
    Vielleicht), the abstentions, the options with the most votes and the number of
    answers. Each option has its own line, so a label such as „Ja“ never forms the
    Ja/Nein/Enthaltung line that the renderer turns into a tally box. A poll lists
    counts only, never a name, in both variants.
    """
    result = _poll_result(view) if view.closed else []
    return "\n".join(
        [f"> [!abstimmung] **{_md_escape(view.question)}**", f"> {view.meta}", *result]
    )


def _is_quote(line: str) -> bool:
    """Return True for a blockquote line."""
    return line.lstrip().startswith(">")


def _continues(line: str) -> bool:
    """Return True for a `>` line that continues a callout, so no `> [!` marker line."""
    return _is_quote(line) and not line.lstrip().startswith("> [!")


def _block_end(lines: Sequence[str], start: int) -> int:
    """Return the index after the callout that starts at `start`."""
    return next((j for j in range(start + 1, len(lines)) if not _continues(lines[j])), len(lines))


def _quote_blocks(lines: Sequence[str]) -> tuple[tuple[int, int], ...]:
    """Return the (start, stop) range of every `>` block, split at each `> [!` marker line.

    A `>` line starts a block unless it continues the block of the line above it.
    """
    starts = (
        k
        for k, line in enumerate(lines)
        if _is_quote(line) and not (k > 0 and _is_quote(lines[k - 1]) and _continues(line))
    )
    return tuple((start, _block_end(lines, start)) for start in starts)


def _stripped_lines(text: str) -> tuple[str, ...]:
    """Split a text into its lines without the outer whitespace."""
    return tuple(line.strip() for line in text.split("\n"))


def _whole(lines: tuple[str, ...]) -> object:
    """Match key of a block on its whole text."""
    return lines


def _head(lines: tuple[str, ...]) -> object:
    """Match key of a block on its head line."""
    return lines[0]


def _claim(
    key: Callable[[tuple[str, ...]], object],
    texts: Sequence[tuple[str, ...]],
    assigned: Mapping[int, int],
    item: tuple[int, str],
) -> Mapping[int, int]:
    """Give the vote `item` the first free block whose `key` equals the key of its snippet.

    `assigned` maps a block index to a vote index; a vote without a free block changes
    nothing.
    """
    n, snippet = item
    want = key(_stripped_lines(snippet))
    free = (k for k, text in enumerate(texts) if k not in assigned and key(text) == want)
    k = next(free, None)
    return assigned if k is None else {**assigned, k: n}


def _assign_blocks(
    texts: Sequence[tuple[str, ...]], snippets: Sequence[str]
) -> Mapping[int, int]:
    """Assign each block to at most one vote: the exact text first, then the head line."""
    empty: Mapping[int, int] = {}
    exact = reduce(partial(_claim, _whole, texts), enumerate(snippets), empty)
    done = frozenset(exact.values())
    pending = ((n, snippet) for n, snippet in enumerate(snippets) if n not in done)
    return reduce(partial(_claim, _head, texts), pending, exact)


def replace_vote_blocks(body: str, pairs: Sequence[tuple[str, str]]) -> str:
    """Replace the callout of each vote in `body` with its other form.

    Each pair is (the snippet of the text, the replacement). The public protocol uses
    this to swap an internal election callout that the protokollant put into the text
    for its public form. Two votes can share a question and so a head line, so
    each block goes to one vote only, as in `votes_in_body`: a block whose whole text
    equals a snippet belongs to that vote first, and the other blocks with the head
    go to the remaining votes in the given order. A block runs over `>` lines and
    ends before the next `> [!` marker line. A vote without a block changes nothing.
    """
    lines = body.split("\n")
    blocks = _quote_blocks(lines)
    texts = tuple(tuple(line.strip() for line in lines[start:stop]) for start, stop in blocks)
    assigned = _assign_blocks(texts, [match for match, _ in pairs])
    replaced = {blocks[k][0]: pairs[n][1].split("\n") for k, n in assigned.items()}
    hidden = frozenset(i for k in assigned for i in range(blocks[k][0] + 1, blocks[k][1]))
    return "\n".join(
        out for i, line in enumerate(lines) if i not in hidden for out in replaced.get(i, [line])
    )


def _mark_from(lines: tuple[str, ...], head: str, marked: str, start: int) -> tuple[str, ...]:
    """Add `marked` below the first block from `start` on that starts with `head` and lacks it."""
    match next((k for k in range(start, len(lines)) if lines[k].strip() == head), None):
        case None:
            return lines
        case i:
            j = _block_end(lines, i)
            done = any(line.strip() == marked for line in lines[i:j])
            return _mark_from(lines, head, marked, j) if done else (*lines[:j], marked, *lines[j:])


def _mark_one(lines: tuple[str, ...], pair: tuple[str, str]) -> tuple[str, ...]:
    """Add the mark of one (snippet, line) pair to the block of its vote."""
    snippet, mark = pair
    return _mark_from(lines, snippet.split("\n", 1)[0].strip(), f"> {_md_escape(mark)}", 0)


def mark_vote_blocks(body: str, marks: Sequence[tuple[str, str]]) -> str:
    """Add a mark line to the callout of each vote in `body`.

    Each pair is (the snippet of the vote, the line). The block of a vote is the
    first block that starts with the head line of its snippet and has no mark yet. The
    line goes below the last `>` line of that block, so a text that the protokollant
    changed inside the callout stays. A block that already holds the line stays as it
    is, and a vote without a block changes nothing.
    """
    return "\n".join(reduce(_mark_one, marks, tuple(body.split("\n"))))


def _head_line(snippet: str) -> str:
    """Return the head line of a snippet without the outer whitespace."""
    return snippet.split("\n", 1)[0].strip()


@dataclass(frozen=True, slots=True)
class _Found:
    """The state of the match in `votes_in_body`: the unclaimed lines and the result so far.

    Attributes:
        heads: How many times each stripped line of the body is still unclaimed.
        exact: How many times each snippet text is still unclaimed in the body.
        found: One flag per snippet visited so far.
    """

    heads: Mapping[str, int]
    exact: Mapping[str, int]
    found: tuple[bool, ...] = ()


def _less(counts: Mapping[str, int], key: str) -> Mapping[str, int]:
    """Return `counts` with one less of `key`."""
    return {**counts, key: counts[key] - 1}


def _found_exact(state: _Found, snippet: str) -> _Found:
    """Claim the text of `snippet` and its head line when both are still in the body."""
    head = _head_line(snippet)
    hit = state.exact[snippet] > 0 and state.heads.get(head, 0) > 0
    return (
        _Found(_less(state.heads, head), _less(state.exact, snippet), (*state.found, True))
        if hit
        else replace(state, found=(*state.found, False))
    )


def _found_head(state: _Found, item: tuple[str, bool]) -> _Found:
    """Claim the head line of a snippet that has no exact match yet, when one is left."""
    snippet, done = item
    head = _head_line(snippet)
    hit = not done and state.heads.get(head, 0) > 0
    heads = _less(state.heads, head) if hit else state.heads
    return replace(state, heads=heads, found=(*state.found, done or hit))


def votes_in_body(body: str, snippets: Sequence[str]) -> list[bool]:
    """Report for each snippet whether its vote is in the body.

    Two votes can share a question and then share the head line, so a head line
    counts for one vote only. A callout whose whole text equals a snippet belongs to
    that vote first. The other head lines go to the remaining votes in the given
    order (oldest first). The editor matches the same way (`votesInText`).
    """
    heads = Counter(line.strip() for line in body.split("\n"))
    exact = {snippet: body.count(snippet) for snippet in snippets}
    first = reduce(_found_exact, snippets, _Found(heads=heads, exact=exact))
    second = reduce(
        _found_head, zip(snippets, first.found, strict=True), _Found(first.heads, first.exact)
    )
    return list(second.found)


def _demoted(line: str) -> str:
    """Demote an ATX heading of level 1 to 5 by one level; any other line stays."""
    stripped = line.lstrip()
    hashes = len(stripped) - len(stripped.lstrip("#"))
    heading = 1 <= hashes <= 5 and stripped[hashes : hashes + 1] in (" ", "\t")
    return line.replace("#", "##", 1) if heading else line


def _is_fence(line: str) -> bool:
    """Return True for a line that opens or closes a code fence."""
    return line.lstrip().startswith(("```", "~~~"))


def demote_headings(markdown: str) -> str:
    """Demote all ATX headings in an agenda-item body by one level.

    The agenda-item heading is the only top-level `#`, and the renderer numbers
    it as "TOP n". Without the demotion, the renderer would number every `#` heading of the
    body as a separate agenda item. Code fences stay untouched. Level 6 stays
    at level 6.
    """
    lines = markdown.split("\n")
    fences = tuple(_is_fence(line) for line in lines)
    inside = accumulate(fences, operator.xor, initial=False)
    return "\n".join(
        line if fence or fenced else _demoted(line)
        for line, fence, fenced in zip(lines, fences, inside, strict=False)
    )


_YAML_ESCAPES: Mapping[str, str] = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _yaml_char(ch: str) -> str:
    """Escape one character of a double-quoted YAML scalar."""
    return _YAML_ESCAPES.get(ch, f"\\x{ord(ch):02x}" if ord(ch) < 0x20 else ch)


def _yaml_scalar(value: str) -> str:
    """Quote a string as a safe double-quoted YAML scalar that cannot inject a directive."""
    return '"' + "".join(_yaml_char(ch) for ch in value) + '"'


def _md_escape(text: str) -> str:
    """Minimal escape for inline Markdown text (newline → space)."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def top_time_note(started_at: datetime | None, tz: ZoneInfo) -> str:
    """Return the empty time note in front of a TOP heading, or "" without a time.

    The note `> [!anmerkung HH:MM]` shows the local time at which the meeting
    moved to the TOP. The typst template draws it grey and centered above the
    heading.
    """
    return f"> [!anmerkung {started_at.astimezone(tz):%H:%M}]" if started_at is not None else ""
