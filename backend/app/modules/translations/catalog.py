"""The key catalog of the frontend: every UI text key with its built-in texts.

`catalog.json` is a copy of the DE and the EN catalog of the frontend
(`frontend/src/app/core/i18n/translations.ts`, `translations.en.ts`). A frontend spec
fails when the copy is stale and regenerates it with `UPDATE_I18N_CATALOG=1`. The
server uses it to refuse an override for an unknown key and an override whose
placeholders differ from the DE text, because a lost `{count}` hides the number and
an unknown placeholder shows literally. It also serves the built-in texts to an admin
who translates, because the server has no other copy of them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True, slots=True)
class BuiltinText:
    """The built-in texts of one key. `en` is None where EN shows the DE text."""

    de: str
    en: str | None


@cache
def builtin_texts() -> dict[str, BuiltinText]:
    """Return every key with its built-in texts, sorted by key."""
    raw = resources.files(__package__).joinpath("catalog.json").read_text("utf-8")
    data: dict[str, dict[str, str]] = json.loads(raw)
    return {key: BuiltinText(de=entry["de"], en=entry.get("en")) for key, entry in data.items()}


@cache
def catalog() -> dict[str, tuple[str, ...]]:
    """Return every key with the sorted placeholder names of its DE text."""
    return {key: placeholders_of(text.de) for key, text in builtin_texts().items()}


def placeholders_of(text: str) -> tuple[str, ...]:
    """Return the placeholder names of `text`, sorted and without repeats."""
    return tuple(sorted(set(_PLACEHOLDER.findall(text))))
