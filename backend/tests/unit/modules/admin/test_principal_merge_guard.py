"""Guard: every column that references a principal has a rule in the account merge.

A new column that stores a principal id or `sub` and is not in a list of
`principal_merge.py` would stay on the old account after a merge. The test scans the
whole model metadata and fails for such a column.
"""

from __future__ import annotations

import re

from sqlalchemy import Column, Table

import app.models  # noqa: F401 - registers every model in Base.metadata
from app.db import Base
from app.modules.admin import principal_merge as merge

# Text columns that store a principal `sub` by convention.
_SUB_NAME = re.compile(r"(_by|^actor|^author|^voter_sub|^handed_over_by)$")


def _key(column: Column[object]) -> str:
    table = column.table
    assert isinstance(table, Table)
    return f"{table.name}.{column.name}"


def _references_principal(column: Column[object]) -> bool:
    if any(fk.column.table.name == "principal" for fk in column.foreign_keys):
        return True
    return bool(_SUB_NAME.search(column.name))


def _handled() -> set[str]:
    cols = [c for _, c in merge.SUB_COLUMNS]
    cols += [c for _, c in merge.ID_COLUMNS]
    cols += [c for _, c in merge.REMOVED_ROWS]
    cols += list(merge.COMBINED_COLUMNS)
    keys = {f"{c.class_.__tablename__}.{c.key}" for c in cols}
    return keys | set(merge.EXCLUDED_COLUMNS)


def test_every_principal_column_has_a_merge_rule() -> None:
    found = {
        _key(column)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if _references_principal(column)
    }
    missing = sorted(found - _handled())
    assert missing == [], f"principal columns without a merge rule: {missing}"


def test_the_lists_name_real_columns_only() -> None:
    every = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
    }
    assert _handled() <= every


def test_the_scan_sees_known_columns() -> None:
    found = {
        _key(column)
        for table in Base.metadata.tables.values()
        for column in table.columns
        if _references_principal(column)
    }
    # FK columns, sub columns and the merge reference itself.
    assert {"ballot.voter_sub", "meeting.protokollant_id", "audit_entry.actor"} <= found
    assert "principal.merged_into" in found
