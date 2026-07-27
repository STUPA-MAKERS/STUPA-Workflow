"""Protocol Markdown: frontmatter, editor body and vote snippets.

The code here is pure and needs no database, so unit tests cover it directly.
`build_protocol_document` puts the YAML frontmatter in front of the Markdown
body that the editor supplies. The frontmatter carries `typ: protokoll` plus
the `gremium` name that selects the pytex variant. `build_vote_snippet`
renders one vote as a Markdown section. The embed step appends that section to
the body.

Injection hardening: the result reaches the pytex client as an HTTP body, and
no shell runs. Frontmatter scalars stay YAML-quoted. Snippet text stays
Markdown-escaped. Both helpers come from `app.modules.pdf.markdown`.

The editor body is user-written. `sanitize_user_markdown` strips the pytex
`eval` escape `[//]: # "EXPR"`, which runs arbitrary code in the container.
It strips that escape in EVERY CommonMark form: one line, several lines,
nested in a container, and with whitespace in the label. It also neutralizes
an image with an absolute path or a `..` path. Normal Markdown survives.

This sanitizer IS the protection against remote code execution. The service
renders the body as `trusted`, the client default, because the protocol
variant needs the pytex template machinery. The `untrusted` level blocks that
machinery and fails every render with 400.

Variant per gremium: pytex knows the protocol variants `protocol-stupa` and
`protocol-asta`. The `cd_variant` value of the gremium selects one of them.
For any other value the variant stays `None`, and pytex reads the variant from
the `typ: protokoll` frontmatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import time as _time

try:  # marko ships with the render path (pytex_markdown). Hardening is optional.
    import marko as _marko  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - primary regex protection works without marko
    _marko = None  # type: ignore[assignment]

from app.modules.pdf.markdown import _md_escape, _yaml_scalar

# RCE defense in depth.
# In `trusted` mode pytex has a Markdown `eval` escape. A link reference definition
# of the form `[//]: # "EXPR"` stays invisible in the PDF and runs
# `eval(EXPR, pytex_namespace())` inside the pytex container. That is an RCE.
# pytex fires the eval ONLY when CommonMark parses the definition with
# `label == "//"` AND `dest == "#"`. The body is user-written, and the
# protocol variant must render as `trusted`. So THIS sanitizer is the RCE guard.
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
    r"\[[^\]]*\]\s*:\s*#"  # definition head, target exactly `#`
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
    r"""Strip pytex `eval` escapes and path-traversal images from user Markdown.

    The function removes the RCE vectors: the `[//]: # "…"` comment eval in
    every CommonMark form, and `\iffalse{pytex(…)}\fi`. It also neutralizes
    an image with an absolute path or a `..` path. Normal Markdown survives in
    full: headings, lists, emphasis, real links and images with relative
    paths, and vote callouts. The marko parse verifies the eval trigger
    structurally. While an eval-capable `LinkRefDef` survives, the strip
    repeats. The body therefore reaches pytex without an eval vector.
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

# Gremium `cd_variant` values that select a pytex protocol variant.
_PROTOCOL_VARIANTS = {"stupa", "asta"}


def protocol_variant_for(cd_variant: str | None) -> str | None:
    """Map `cd_variant` to the pytex variant `protocol-<cd>`, or `None` for auto."""
    if cd_variant in _PROTOCOL_VARIANTS:
        return f"protocol-{cd_variant}"
    return None


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
    # start it forms the "Zeit: Start – Ende" title-page line, which pytex
    # builds from `beginn` and `ende`.
    end_time: _time | None = None
    protokollant: str | None = None
    present: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    datalines: list[str] = field(default_factory=list)
    # Quorum from the present members against the active members. `None` means
    # no statement.
    quorate: bool | None = None


# Signature block for the pytex helper `signature_block_from_meta`. The
# frontmatter supplies the name of the secretary. The board line stays a blank
# line for a hand signature.
_SIGNATURES = ["Schriftführung", "Vorstand"]


def _yaml_list(key: str, items: list[str]) -> list[str]:
    """Build a YAML block list with quoted values, or nothing for an empty list."""
    if not items:
        return []
    return [f"{key}:", *(f"  - {_yaml_scalar(i)}" for i in items)]


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
    # pytex renders start and end into the "Zeit: Start – Ende" data line.
    if doc.start_time is not None:
        lines.append(f"beginn: {_yaml_scalar(doc.start_time.strftime('%H:%M'))}")
    if doc.end_time is not None:
        lines.append(f"ende: {_yaml_scalar(doc.end_time.strftime('%H:%M'))}")
    if doc.protokollant:
        lines.append(f"protokoll: {_yaml_scalar(doc.protokollant)}")
    lines += _yaml_list("anwesend", doc.present)
    lines += _yaml_list("abwesend", doc.absent)
    if doc.quorate is not None:
        # Quorum as a title-page data line. The pytex wrapper registers the key.
        quorate = "Gegeben" if doc.quorate else "Nicht gegeben"
        lines.append(f"beschlussfaehigkeit: {_yaml_scalar(quorate)}")
    lines += _yaml_list("datalines", doc.datalines)
    # Signature page: pytex renders the signature lines from this list.
    lines += _yaml_list("unterschriften", _SIGNATURES)
    lines.append("---")
    return lines


def build_protocol_document(doc: ProtocolDoc) -> str:
    r"""Combine the frontmatter and the editor body into the final Markdown.

    The output is deterministic. `sanitize_user_markdown` cleans the
    user-written body of pytex `eval` escapes (RCE) and path-traversal images.
    Normal Markdown stays verbatim. Frontmatter scalars stay YAML-quoted. The
    eval escape is gone before pytex sees the body. The `\write18` shell
    escape does not apply under the tectonic engine anyway. The service renders
    this path as `trusted`, the client default, because the protocol variant
    needs the pytex template machinery, which `untrusted` blocks.
    """
    body = sanitize_user_markdown(doc.markdown).strip("\n")
    out = [*_frontmatter(doc), ""]
    if body:
        out.append(body)
    return "\n".join(out).rstrip() + "\n"


def build_vote_snippet(
    title: str,
    counts: dict[str, int] | None,
    question: str | None = None,
) -> str:
    """Render a vote as a pytex protocol callout (`> [!abstimmung]`).

    The counts line holds `yes/no/abstain` or `ja/nein/enthaltung`, and pytex
    turns it into the built-in tally box of the PDF. The function escapes all
    values and sets the title in bold. There is no separate result line,
    because the result reads from the tally box. The snippet stays part of the
    editable Markdown as a blockquote callout.
    """
    head = question.strip() if question and question.strip() else title
    lines = [f"> [!abstimmung] **{_md_escape(head)}**"]
    if counts:
        # pytex detects the tally line by two or more of ja/nein/enthaltung
        # (yes/no/abstain). The ballot options carry exactly these keys.
        tally = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in counts.items())
        lines.append(f"> {tally}")
    return "\n".join(lines)


def demote_headings(markdown: str) -> str:
    """Demote all ATX headings in an agenda-item body by one level.

    The agenda-item heading is the only top-level `#`, and pytex numbers it as
    "TOP n". Without the demotion, pytex would number every `#` heading of the
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
