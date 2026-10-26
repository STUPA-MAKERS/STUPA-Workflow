"""The UI text catalog of the frontend: every key with its built-in DE and EN text.

The texts live only in `frontend/src/app/core/i18n/catalog/de.json` and `en.json`.
The api container mounts that directory read-only at `/opt/ui-catalog` and sets
`UI_CATALOG_DIR` (`Settings.ui_catalog_dir`, see `deploy/docker-compose.yml`), because
the image builds from `backend/` only. A checkout without the variable reads them from
the frontend directory of the repository. The server uses the catalog to
refuse an override for an unknown key and an override whose placeholders differ from
the DE text, because a lost `{count}` hides the number and an unknown placeholder
shows literally. It also serves the built-in texts to an admin who translates.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.settings import get_settings

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

#: The catalog directory in a checkout: `<repo>/frontend/src/app/core/i18n/catalog`.
_REPO_DIR = (
    Path(__file__).resolve().parents[4] / "frontend" / "src" / "app" / "core" / "i18n" / "catalog"
)


@dataclass(frozen=True, slots=True)
class BuiltinText:
    """The built-in texts of one key. `en` is None where EN shows the DE text."""

    de: str
    en: str | None


def catalog_dir() -> Path:
    """Return the directory that holds `de.json` and `en.json`."""
    configured = get_settings().ui_catalog_dir
    return Path(configured) if configured else _REPO_DIR


def _read(locale: str) -> dict[str, str]:
    data: dict[str, str] = json.loads((catalog_dir() / f"{locale}.json").read_text("utf-8"))
    return data


@cache
def builtin_texts() -> dict[str, BuiltinText]:
    """Return every key with its built-in texts, sorted by key."""
    de = _read("de")
    en = _read("en")
    return {key: BuiltinText(de=de[key], en=en.get(key)) for key in sorted(de)}


@cache
def catalog() -> dict[str, tuple[str, ...]]:
    """Return every key with the sorted placeholder names of its DE text."""
    return {key: placeholders_of(text.de) for key, text in builtin_texts().items()}


def placeholders_of(text: str) -> tuple[str, ...]:
    """Return the placeholder names of `text`, sorted and without repeats."""
    return tuple(sorted(set(_PLACEHOLDER.findall(text))))
