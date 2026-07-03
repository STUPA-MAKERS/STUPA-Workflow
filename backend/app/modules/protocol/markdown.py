"""Protocol → Markdown + YAML frontmatter + vote snippets.

Pure, DB-free generation (unit-testable):

* :func:`build_protocol_document` puts the YAML frontmatter (``typ: protokoll``,
  ``gremium`` → pytex variant) before the editor-supplied Markdown body.
* :func:`build_vote_snippet` renders a vote as a Markdown section appended to
  the body when embedding.

Injection hardening: the result goes to the pytex client as an HTTP body (no
shell). Frontmatter scalars are YAML-quoted; snippet text is Markdown-escaped —
both reused from :mod:`app.modules.pdf.markdown`. The editor body is
user-written; :func:`sanitize_user_markdown` strips pytex's ``eval`` escape
(``[//]: # "EXPR"`` → RCE in the container) in EVERY CommonMark form
(single-/multi-line, container-nested, whitespace in the label) plus images
with absolute/``..`` paths. Normal Markdown survives. This sanitizer IS the RCE
protection: the service renders the body ``trusted`` (client default) because
the protocol variant needs pytex's template machinery — ``untrusted`` would
block it and fail every render with 400.

Variant per gremium: pytex knows the protocol variants ``protocol-stupa`` /
``protocol-asta``, selected by the gremium ``cd_variant``. For other values the
variant stays ``None`` → pytex detects it from the ``typ: protokoll`` frontmatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import time as _time

try:  # marko is present in the render path (via pytex_markdown); optional hardening.
    import marko as _marko  # pyright: ignore[reportMissingImports]
except ImportError:  # pragma: no cover - primary regex protection works without marko
    _marko = None  # type: ignore[assignment]

from app.modules.pdf.markdown import _md_escape, _yaml_scalar

# --- RCE defense in depth ----------------------------------------------------
# pytex in ``trusted`` mode has a Markdown ``eval`` escape: a link reference
# definition of the form ``[//]: # "EXPR"`` (invisible in the PDF) runs
# ``eval(EXPR, pytex_namespace())`` inside the pytex container → RCE. pytex
# fires the eval ONLY when CommonMark parses the definition with
# ``label == "//"`` AND ``dest == "#"``. The body is user-written, and the
# protocol variant must render ``trusted``, so THIS sanitizer is the RCE guard.
#
# A line-oriented regex (``^[ \t]*[...]: #``) is NOT reliable — a link
# reference definition is a CommonMark block that may span lines
# (``[//]:\n#\n"EXPR"``), nest in containers (``> [//]: # "EXPR"``,
# ``- [//]: # "EXPR"``) and carry whitespace/newlines inside the label
# (``[ // ]``), bypassing any simple per-line regex. We therefore remove the
# ENTIRE eval-capable definition: head ``[label] : #`` (bare ``#`` target — not
# ``#fragment``) plus optional title (``"…"``/``'…'``/``(…)``), tolerant of
# whitespace and newlines wherever CommonMark allows them. Real reference
# links (``[foo]: #section``), inline links/images and the vote callout
# (``> [!abstimmung]``) are untouched.
_EVAL_REFDEF_RE = re.compile(
    r"\[[^\]]*\]\s*:\s*#"  # definition head, target exactly ``#`` …
    r"(?=[ \t\r\n\"'(]|$)"  # … bare ``#`` (followed by WS/title delimiter/EOL)
    r"[ \t]*"  # whitespace before the optional title
    r"(?:\r?\n[ \t]*)?"  # multi-line form may put the title on the next line
    r"""(?:"[^"]*"|'[^']*'|\([^)]*\)|[^\r\n]*)?""",  # optional title / rest of line
    re.DOTALL,
)


def _strip_eval_refdefs(markdown: str) -> str:
    r"""Remove eval-capable ``[label]: # "EXPR"`` definitions entirely.

    Strips head and expression of every bare-``#`` link reference definition
    (in any CommonMark form) so pytex's eval trigger never reaches the
    Markdown tree. Normal Markdown is untouched."""
    return _EVAL_REFDEF_RE.sub("", markdown)


def _has_eval_refdef(markdown: str) -> bool:
    """Parse ``markdown`` with marko and report a remaining eval trigger.

    Structural verification: a ``LinkRefDef`` node with ``label == "//"`` and
    ``dest == "#"`` anywhere in the tree (or in ``document.link_ref_defs``)
    would fire pytex's eval. Without marko installed only the primary regex
    protection applies and the body counts as clean."""
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


# pytex's internal marker for the evaluated expression: ``\iffalse{pytex(...)}\fi``.
# It has no business in an editor body → remove (multi-line too, non-greedy).
_PYTEX_IFFALSE_RE = re.compile(
    r"\\iffalse\s*\{?\s*pytex\s*\(.*?\)\s*\}?\s*\\fi",
    re.DOTALL | re.IGNORECASE,
)
# Image path traversal: Markdown images ``![alt](PATH)`` with an absolute
# (``/...``) or ``../`` traversal path could reference a container file via
# ``\includegraphics`` and exfiltrate a readable image outside the render dir.
# Such paths are neutralized to a plain-text placeholder; relative in-repo
# paths stay untouched.
_UNSAFE_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(\s*(?P<path>[^)\s]+)[^)]*\)",
)


def _is_unsafe_image_path(path: str) -> bool:
    """Return True for absolute-root or ``..`` traversal image paths."""
    if path.startswith(("/", "\\")) or re.match(r"^[a-zA-Z]:[\\/]", path):
        return True  # absolute (POSIX/UNC/Windows drive)
    # ``../`` anywhere (also URL-encoded ``%2e%2e``) is traversal.
    normalized = path.replace("\\", "/").lower()
    return "../" in normalized or "%2e%2e" in normalized


def _neutralize_unsafe_image(match: re.Match[str]) -> str:
    path = match.group("path")
    if not _is_unsafe_image_path(path):
        return match.group(0)  # harmless relative path → unchanged
    alt = match.group("alt").strip() or "Bild"
    # Do NOT pass the path through — neutralize to a plain-text placeholder.
    return f"*[{_md_escape(alt)} (Bild entfernt)]*"


def sanitize_user_markdown(markdown: str) -> str:
    """Strip pytex ``eval`` escapes (+ path-traversal images) from user Markdown.

    Removes the RCE vectors (``[//]: # "…"`` comment eval in every CommonMark
    form, and ``\\iffalse{pytex(…)}\\fi``) and neutralizes images with
    absolute/``..`` paths. Normal Markdown (headings, lists, emphasis, real
    links/images with relative paths, vote callouts) is fully preserved. The
    eval trigger is verified structurally via the marko parse: as long as an
    eval-capable ``LinkRefDef`` survives, stripping repeats — the body is
    guaranteed to reach pytex without an eval vector."""
    cleaned = _PYTEX_IFFALSE_RE.sub("", markdown)
    cleaned = _strip_eval_refdefs(cleaned)
    # Structural backstop: should an eval-capable LinkRefDef survive (e.g. via a
    # future marko version), strip again until none remains. Bounded loop.
    for _ in range(3):
        if not _has_eval_refdef(cleaned):
            break
        cleaned = _strip_eval_refdefs(cleaned)
    cleaned = _UNSAFE_IMAGE_RE.sub(_neutralize_unsafe_image, cleaned)
    return cleaned

# Gremium ``cd_variant`` → pytex protocol variant.
_PROTOCOL_VARIANTS = {"stupa", "asta"}


def protocol_variant_for(cd_variant: str | None) -> str | None:
    """Map ``cd_variant`` to a pytex ``variant`` (``protocol-<cd>``) or ``None`` (auto)."""
    if cd_variant in _PROTOCOL_VARIANTS:
        return f"protocol-{cd_variant}"
    return None


@dataclass(slots=True)
class ProtocolDoc:
    """All header data of a protocol (filled from the DB by the service)."""

    title: str
    gremium_name: str | None
    cd_variant: str | None
    date: _date | None
    markdown: str
    start_time: _time | None = None
    # Meeting end (local time) from ``meeting.closed_at``; with start this forms
    # the "Zeit: Start – Ende" title-page line (pytex ``beginn``/``ende``).
    end_time: _time | None = None
    protokollant: str | None = None
    present: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    datalines: list[str] = field(default_factory=list)
    # Quorum (present vs. active members); None = no statement.
    quorate: bool | None = None


# Signature block (pytex ``signature_block_from_meta``): the secretary's name
# comes from the frontmatter, the board stays a blank line for hand-signing.
_SIGNATURES = ["Schriftführung", "Vorstand"]


def _yaml_list(key: str, items: list[str]) -> list[str]:
    """Build a YAML block list (empty list ⇒ nothing) with quoted/escaped values."""
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
        # ``datum`` fills the protocol header (date + time), ``date`` the
        # report title page.
        datum = doc.date.isoformat()
        if doc.start_time is not None:
            datum = f"{datum} {doc.start_time.strftime('%H:%M')}"
        lines.append(f"datum: {_yaml_scalar(datum)}")
        lines.append(f"date: {_yaml_scalar(doc.date.isoformat())}")
    # pytex renders start/end into the "Zeit: Start – Ende" data line.
    if doc.start_time is not None:
        lines.append(f"beginn: {_yaml_scalar(doc.start_time.strftime('%H:%M'))}")
    if doc.end_time is not None:
        lines.append(f"ende: {_yaml_scalar(doc.end_time.strftime('%H:%M'))}")
    if doc.protokollant:
        lines.append(f"protokoll: {_yaml_scalar(doc.protokollant)}")
    lines += _yaml_list("anwesend", doc.present)
    lines += _yaml_list("abwesend", doc.absent)
    if doc.quorate is not None:
        # Quorum as a title-page data line; the pytex wrapper registers the key.
        quorate = "Gegeben" if doc.quorate else "Nicht gegeben"
        lines.append(f"beschlussfaehigkeit: {_yaml_scalar(quorate)}")
    lines += _yaml_list("datalines", doc.datalines)
    # Signature page (pytex renders the signature lines from this list).
    lines += _yaml_list("unterschriften", _SIGNATURES)
    lines.append("---")
    return lines


def build_protocol_document(doc: ProtocolDoc) -> str:
    """Combine frontmatter + editor body into the final Markdown (deterministic).

    The user-written body is cleaned of pytex ``eval`` escapes (RCE) and
    path-traversal images via :func:`sanitize_user_markdown`; normal Markdown
    stays verbatim. Frontmatter scalars stay YAML-quoted. The eval escape is
    gone before pytex sees the body; ``\\write18`` shell escape does not apply
    under the tectonic engine anyway. The service renders this path ``trusted``
    (client default) — the protocol variant needs pytex's template machinery,
    which ``untrusted`` blocks."""
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
    """Render a vote as a pytex protocol callout (``> [!abstimmung]``).

    pytex turns the counts line (``yes/no/abstain`` resp. ``ja/nein/enthaltung``)
    into the built-in tally box in the PDF. All values are escaped; the title is
    bold. No separate result line — the result reads from the tally box.
    Remains part of the editable Markdown (blockquote callout)."""
    head = question.strip() if question and question.strip() else title
    lines = [f"> [!abstimmung] **{_md_escape(head)}**"]
    if counts:
        # pytex detects the tally line by ≥2 of ja/nein/enthaltung (yes/no/abstain) —
        # the ballot options carry exactly these keys.
        tally = ", ".join(f"{_md_escape(opt)}: {n}" for opt, n in counts.items())
        lines.append(f"> {tally}")
    return "\n".join(lines)


def demote_headings(markdown: str) -> str:
    """Demote all ATX headings in an agenda-item body by one level.

    The agenda-item heading itself is the only top-level ``#`` (pytex numbers
    it as "TOP n"); ``#`` headings written by the secretary in the body would
    otherwise be numbered as separate TOPs. Code fences are untouched; level 6
    stays 6."""
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
