r"""Blackout marks in protocol Markdown: `%%Name%%` (specs 000685-000691).

A keeper marks a segment, mainly a name, as `%%Name%%`. The internal views show the
text. Every public answer gets the empty marker `%%%%` instead, which the frontend
and the typst template draw as a black bar of one fixed width. The server replaces
the text before the public snapshot, the public typst input and the guest view, so
the name never leaves the server in a public answer.

A `\%%` is a literal `%%` and starts no marker. An open marker (a `%%` without its
closing pair) blacks out nothing, so the finalize refuses it.
"""

from __future__ import annotations

import re
from typing import Final

#: A closed marker. Group 1 is the marked text, which is empty for a bar.
BLACKOUT_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\\)%%([^%\n]*)%%")

#: A marker start that no backslash escapes.
_OPEN_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\\)%%")

#: The empty marker: the black bar of the public variants.
BAR: Final = "%%%%"


def black_out(text: str) -> str:
    """Replace the text of every closed marker with the empty marker `%%%%`."""
    return BLACKOUT_RE.sub(BAR, text)


def has_open_marker(text: str | None) -> bool:
    """Return True if the text has a `%%` that no closed marker holds."""
    return bool(text) and _OPEN_RE.search(BLACKOUT_RE.sub("", text or "")) is not None
