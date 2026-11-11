"""The module `notifications` holds the mail engine only (§S/backend/python/000648)."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"


def test_import_contract_has_no_exception_for_notifications() -> None:
    """§S/backend/python/000648: no import exception starts in `notifications`."""
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    assert [
        entry
        for contract in contracts
        for entry in contract.get("ignore_imports", [])
        if entry.startswith("app.modules.notifications")
    ] == []
