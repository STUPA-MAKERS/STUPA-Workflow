"""The modules `auth` and `audit` import no higher module (§S/backend/python/000649)."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"


def test_import_contract_has_no_exception_for_auth_or_audit() -> None:
    """§S/backend/python/000649: no import exception starts in `auth` or in `audit`."""
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    assert [
        entry
        for contract in contracts
        for entry in contract.get("ignore_imports", [])
        if entry.startswith(("app.modules.auth.", "app.modules.audit."))
    ] == []
