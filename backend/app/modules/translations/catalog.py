"""The key catalog of the frontend: every UI text key with its placeholders.

`catalog.json` is a copy of the DE catalog of the frontend
(`frontend/src/app/core/i18n/translations.ts`) without the texts. A frontend spec
fails when the copy is stale and regenerates it with `UPDATE_I18N_CATALOG=1`. The
server uses it to refuse an override for an unknown key and an override whose
placeholders differ from the built-in text, because a lost `{count}` hides the
number and an unknown placeholder shows literally.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@cache
def catalog() -> dict[str, tuple[str, ...]]:
    """Return every key with its sorted placeholder names."""
    raw = resources.files(__package__).joinpath("catalog.json").read_text("utf-8")
    data: dict[str, list[str]] = json.loads(raw)
    return {key: tuple(names) for key, names in data.items()}


def placeholders_of(text: str) -> tuple[str, ...]:
    """Return the placeholder names of `text`, sorted and without repeats."""
    return tuple(sorted(set(_PLACEHOLDER.findall(text))))
