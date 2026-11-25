"""Every key of the permission catalogue has a German and an English name.

Rule: §F/administration/admin/003017. The names are the UI texts `admin.perm.<key>` of the
built-in frontend catalogue, so the page "Übersetzungen" can change them.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.shared.permissions import PERMISSION_CATALOGUE

#: From tests/unit/, parents[3] is the repo root.
_CATALOG = Path(__file__).resolve().parents[3] / "frontend/src/app/core/i18n/catalog"


def _texts(locale: str) -> dict[str, str]:
    data: dict[str, str] = json.loads((_CATALOG / f"{locale}.json").read_text("utf-8"))
    return data


def test_every_permission_has_a_name() -> None:
    """A key without a non-empty name in de.json or en.json fails the test."""
    missing = [
        f"{locale}: admin.perm.{key}"
        for locale in ("de", "en")
        for key in PERMISSION_CATALOGUE
        if not _texts(locale).get(f"admin.perm.{key}", "").strip()
    ]
    assert missing == []


def test_no_name_without_a_permission() -> None:
    """A name for a key that the catalogue no longer has fails the test."""
    keys = {f"admin.perm.{key}" for key in PERMISSION_CATALOGUE}
    for locale in ("de", "en"):
        stale = [k for k in _texts(locale) if k.startswith("admin.perm.") and k not in keys]
        assert stale == [], locale
