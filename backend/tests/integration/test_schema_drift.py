"""Integration tests for the schema compare on a real Postgres 16 (§000626, §000627)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy import Engine, text

from app.shared.schema_drift import report, schema_differences

pytestmark = pytest.mark.integration


def test_migrated_database_equals_the_models(engine: Engine) -> None:
    """§000626: after `alembic upgrade head` the schema has no difference to the models."""
    with engine.connect() as conn:
        assert schema_differences(conn) == ()


def test_hand_made_check_constraint_is_logged_as_error(
    migrated: tuple[str, str],
    engine: Engine,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§000627: the compare of the `migrate` service logs a difference and does not raise.

    The Alembic upgrade of the fixture loads `alembic.ini`, which disables every logger
    that exists at that time, so the test enables the logger of the compare again.
    """
    monkeypatch.setattr(logging.getLogger("app.schema_drift"), "disabled", False)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE gremium ADD CONSTRAINT hand_made CHECK (name <> '')"))
    caplog.set_level(logging.ERROR, logger="app.schema_drift")
    try:
        differences = asyncio.run(report(migrated[1]))
    finally:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE gremium DROP CONSTRAINT hand_made"))
    assert differences == ("database has check constraint gremium.hand_made",)
    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [
        (
            logging.ERROR,
            "schema differs from the models: database has check constraint gremium.hand_made",
        )
    ]
