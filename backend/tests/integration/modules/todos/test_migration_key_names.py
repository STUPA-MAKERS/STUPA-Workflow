"""Integration: the ticket and to-do migrations name their keys like ``create_all``.

A fresh database gets the tables from the baseline (``create_all``, naming convention
``pk_<table>``); an upgraded database gets them from the migration DDL. Both must give
the same constraint names, so a later migration can name a key.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

pytestmark = pytest.mark.integration

_TABLES = (
    "ticket",
    "ticket_note",
    "ticket_event",
    "todo_board",
    "todo_column",
    "todo_card",
    "todo_assignee",
    "todo_label",
    "todo_card_label",
    "todo_check_item",
    "todo_comment",
    "todo_event",
    "todo_link",
)


def _keys(engine: Engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                "WHERE contype = 'p' AND conrelid::regclass::text = ANY(:t)"
            ),
            {"t": list(_TABLES)},
        ).all()
    return {str(table): str(name) for table, name in rows}


def test_an_upgraded_database_has_the_key_names_of_a_fresh_one(
    alembic_cfg: Config, engine: Engine
) -> None:
    fresh = _keys(engine)
    assert fresh == {table: f"pk_{table}" for table in _TABLES}
    command.downgrade(alembic_cfg, "5d8e1b0c6f27")
    try:
        assert _keys(engine) == {}
    finally:
        command.upgrade(alembic_cfg, "head")
    assert _keys(engine) == fresh
