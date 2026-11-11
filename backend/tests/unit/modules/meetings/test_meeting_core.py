"""The meeting core is in the module `meetings` (§S/backend/python/000652)."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[4] / "pyproject.toml"
_LOWER = ("app.modules.voting.", "app.modules.flow.", "app.modules.applications.")


def test_import_contract_has_no_exception_for_voting_flow_or_applications() -> None:
    """§S/backend/python/000652: `voting`, `flow` and `applications` import no higher module."""
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    assert [
        entry
        for contract in contracts
        for entry in contract.get("ignore_imports", [])
        if entry.startswith(_LOWER)
    ] == []
