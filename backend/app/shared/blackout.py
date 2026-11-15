r"""Blackout marks in protocol Markdown (specs 000685-000691, 000965-000967).

A keeper marks a segment, mainly a name, as `%%Name%%`. A whole block of lines is
marked with two fence lines that hold only `%%`:

    %%
    Text, lists, images and embedded PDFs
    %%

The internal views show the content. Every public answer gets the empty form
instead: `%%%%` for a segment, which the frontend and the typst template draw as
a black bar of one fixed width, and the empty block `%%` + newline + `%%` for a
block, which they draw as one bar of the full text width. The server replaces
the content before the public snapshot, the public typst input and the guest
view, so the text never leaves the server in a public answer. An image or a PDF
in a block leaves with the block: the public lists of images and Anlagen read
the public Markdown, so they never see it (000966).

A `\%%` is a literal `%%` and starts no marker. An open marker (a `%%` without
its closing pair, or a fence line without its closing fence line) blacks out
nothing, so the finalize refuses it.
"""

from __future__ import annotations

import re
from typing import Final

#: A closed marker. Group 1 is the marked text, which is empty for a bar.
BLACKOUT_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\\)%%([^%\n]*)%%")

#: A closed block: a fence line, the content, the next fence line. Group 1 is the
#: content with its line ends, empty for the bar of a block.
BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r"^[ \t]*%%[ \t]*\r?\n(.*?)^[ \t]*%%[ \t]*\r?$", re.MULTILINE | re.DOTALL
)

#: A marker start that no backslash escapes.
_OPEN_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\\)%%")

#: The empty marker: the black bar of a segment in the public variants.
BAR: Final = "%%%%"

#: The empty block: the black bar of a block in the public variants.
BLOCK_BAR: Final = "%%\n%%"


def black_out(text: str) -> str:
    """Replace each closed block with the empty block, then each segment with `%%%%`."""
    return BLACKOUT_RE.sub(BAR, BLOCK_RE.sub(BLOCK_BAR, text))


def has_open_marker(text: str | None) -> bool:
    """Return True if the text has a `%%` that no closed block or marker holds."""
    if not text:
        return False
    rest = BLACKOUT_RE.sub("", BLOCK_RE.sub("", text))
    return _OPEN_RE.search(rest) is not None
