"""The canonical Markdown reference of an image and the helpers that find it.

A Markdown text refers to an uploaded image only as ``![alt](/api/media/images/<id>)``
with the lowercase canonical uuid. Every renderer (the SPA, the typst service) shows
this path only. Every other image destination renders as its alt text, so no
renderer loads an external image and the PDF renderer never fetches a file.
"""

from __future__ import annotations

import re
from typing import Final
from uuid import UUID

_UUID: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

#: The whole canonical path, for one image destination.
IMAGE_PATH_RE: Final[re.Pattern[str]] = re.compile(rf"^/api/media/images/({_UUID})$")

# The destination of a Markdown image or link: `](` + the path + an optional title
# + `)`. The angle-bracket form `](<path>)` is CommonMark too.
_REF_RE: Final[re.Pattern[str]] = re.compile(
    rf"\]\(\s*<?/api/media/images/({_UUID})>?\s*(?:\"[^\"\n]*\"\s*|'[^'\n]*'\s*)?\)"
)


def image_path(image_id: UUID) -> str:
    """Return the canonical Markdown path of an image."""
    return f"/api/media/images/{image_id}"


def is_image_path(path: str) -> bool:
    """Tell whether ``path`` is exactly the canonical path of an image."""
    return IMAGE_PATH_RE.fullmatch(path) is not None


def image_ids_in(*texts: str | None) -> list[UUID]:
    """Return the image ids that the texts refer to.

    The order is the order of the first appearance, and every id comes once.
    """
    seen: dict[UUID, None] = {}
    for text in texts:
        if not text:
            continue
        for match in _REF_RE.finditer(text):
            seen.setdefault(UUID(match.group(1)), None)
    return list(seen)
