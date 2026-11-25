"""Kostenaufstellung: give each stored position a fixed id.

A Bestellung names a position of the Kostenaufstellung by its id. The stored positions have
none, so the upgrade writes an id into each position of each stored version and of the
current data of each Antrag. The same position in two versions of an Antrag gets the same
id: a position takes the id of the position at the same place with the same label in the
version before.

The step is idempotent: a position that has an id keeps it. The downgrade keeps the ids,
because a reader that does not know the key ignores it.

Revision ID: e7d870f703d5
Revises: 377af7322897
Create Date: 2026-11-24 19:10:00.000000
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e7d870f703d5"
down_revision: str | None = "377af7322897"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _positions(value: object) -> list[dict[str, Any]]:
    """Return the positions of one answer: the rows of a list of which one holds offers."""
    rows = [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []
    return rows if any("offers" in row for row in rows) else []


def _filled(rows: list[Any], before: list[dict[str, Any]]) -> list[Any]:
    """Return the rows of one field with an id at each position."""
    used = {str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")}
    out: list[Any] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or row.get("id"):
            out.append(row)
            continue
        same = before[index] if index < len(before) else None
        kept = (
            str(same["id"])
            if same is not None
            and same.get("id")
            and same.get("label") == row.get("label")
            and str(same["id"]) not in used
            else str(uuid.uuid4())
        )
        used.add(kept)
        out.append({**row, "id": kept})
    return out


def fill_position_ids(data: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    """Return the data with an id at each position; previous is the version before."""
    return {
        key: _filled(value, _positions(previous.get(key))) if _positions(value) else value
        for key, value in data.items()
    }


def upgrade() -> None:
    """Write the ids into the versions and the current data of each Antrag."""
    bind = op.get_bind()
    set_version = sa.text(
        "UPDATE submission_version SET data = CAST(:data AS jsonb) WHERE id = :id"
    )
    set_current = sa.text("UPDATE application SET data = CAST(:data AS jsonb) WHERE id = :id")
    apps = bind.execute(sa.text("SELECT id, data FROM application ORDER BY id")).all()
    for app_id, current in apps:
        previous: dict[str, Any] = {}
        versions = bind.execute(
            sa.text(
                "SELECT id, data FROM submission_version "
                "WHERE application_id = :app ORDER BY version"
            ),
            {"app": app_id},
        ).all()
        for version_id, data in versions:
            filled = fill_position_ids(data or {}, previous)
            if filled != (data or {}):
                bind.execute(set_version, {"data": json.dumps(filled), "id": version_id})
            previous = filled
        filled = fill_position_ids(current or {}, previous)
        if filled != (current or {}):
            bind.execute(set_current, {"data": json.dumps(filled), "id": app_id})


def downgrade() -> None:
    """Keep the ids: a reader that does not know the key ignores it."""
