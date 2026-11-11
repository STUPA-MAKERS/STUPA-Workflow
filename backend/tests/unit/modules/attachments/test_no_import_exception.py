"""The import contract has no exception (§S/backend/python/000651)."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"


def test_import_contract_has_no_entry_in_ignore_imports() -> None:
    """§S/backend/python/000651: no contract has an entry in `ignore_imports`."""
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    assert contracts
    assert [
        entry for contract in contracts for entry in contract.get("ignore_imports", [])
    ] == []
