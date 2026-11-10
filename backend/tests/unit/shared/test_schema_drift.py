"""Unit tests for the schema compare (§000626, §000627) on an in-memory SQLite database."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Self

import pytest
from sqlalchemy import (
    CheckConstraint,
    Column,
    Connection,
    Engine,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    create_engine,
    text,
)

from app.shared import schema_drift
from app.shared.schema_drift import DriftException, is_excepted, schema_differences


def _models() -> MetaData:
    metadata = MetaData()
    Table(
        "thing",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", Text, nullable=False),
        Column("size", Integer),
        CheckConstraint("size >= 0", name="thing_size_positive"),
        Index("ix_thing_name", "name"),
    )
    return metadata


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite://")
    try:
        yield eng
    finally:
        eng.dispose()


def _differences(engine: Engine, ddl: tuple[str, ...]) -> tuple[str, ...]:
    with engine.begin() as conn:
        for statement in ddl:
            conn.execute(text(statement))
        return schema_differences(conn, _models(), ())


def test_equal_schema_gives_no_difference(engine: Engine) -> None:
    _models().create_all(engine)
    assert _differences(engine, ()) == ()


def test_each_kind_of_difference_is_named(engine: Engine) -> None:
    lines = _differences(
        engine,
        (
            "CREATE TABLE thing (id INTEGER NOT NULL PRIMARY KEY, name TEXT, size TEXT, "
            "extra TEXT, "
            "CONSTRAINT hand_made CHECK (extra <> ''))",
            "CREATE INDEX ix_thing_extra ON thing (extra)",
            "CREATE TABLE stray (id INTEGER PRIMARY KEY)",
        ),
    )
    assert set(lines) == {
        "database has table stray",
        "database has column thing.extra",
        "database has index thing.ix_thing_extra",
        "models have index thing.ix_thing_name",
        "column thing.name differs in nullable: database True, models False",
        "column thing.size differs in type: database TEXT(), models Integer()",
        "models have check constraint thing.thing_size_positive",
        "database has check constraint thing.hand_made",
    }


def test_missing_table_is_named(engine: Engine) -> None:
    assert _differences(engine, ()) == (
        "models have table thing",
        "models have index thing.ix_thing_name",
    )


def test_exception_list_removes_a_difference(engine: Engine) -> None:
    _models().create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE INDEX ix_trgm_thing_name ON thing (name)"))
        assert schema_differences(conn, _models(), ()) == (
            "database has index thing.ix_trgm_thing_name",
        )
        assert schema_differences(conn, _models()) == ()


def test_every_exception_gives_its_cause() -> None:
    assert all(entry.cause.strip() for entry in schema_drift.EXCEPTIONS)
    assert is_excepted("x", (DriftException("x", "cause"),))
    assert not is_excepted("database has index thing.other")


def test_unknown_entry_shapes_stay_readable() -> None:
    assert schema_drift._describe("odd") == ("'odd'",)
    assert schema_drift._describe(("add_sequence", object())) == (
        "models have sequence ?.<unnamed>",
    )


class _FakeAsyncConnection:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def run_sync[T](self, fn: Callable[[Connection], T]) -> T:
        return fn(self._connection)


class _FakeAsyncEngine:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def connect(self) -> _FakeAsyncConnection:
        return _FakeAsyncConnection(self._connection)

    async def dispose(self) -> None:
        return None


@pytest.fixture
def fake_database(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Connection]:
    monkeypatch.setattr(schema_drift.Base, "metadata", _models())
    with engine.connect() as conn:
        monkeypatch.setattr(
            schema_drift, "create_async_engine", lambda *_a, **_k: _FakeAsyncEngine(conn)
        )
        monkeypatch.setattr(
            schema_drift,
            "schema_differences",
            lambda c: schema_differences(c, _models(), ()),
        )
        monkeypatch.setattr(schema_drift, "_database_url", lambda: "sqlite://")
        yield conn


def test_main_logs_each_difference_as_error_and_does_not_stop(
    fake_database: Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.schema_drift")
    assert schema_drift.main(()) == 0
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r.getMessage() for r in errors] == [
        "schema differs from the models: models have table thing",
        "schema differs from the models: models have index thing.ix_thing_name",
    ]


def test_main_strict_fails_on_a_difference(fake_database: Connection) -> None:
    assert schema_drift.main(("--strict",)) == 1


def test_main_reports_an_equal_schema(
    fake_database: Connection, caplog: pytest.LogCaptureFixture
) -> None:
    _models().create_all(fake_database)
    caplog.set_level(logging.INFO, logger="app.schema_drift")
    assert schema_drift.main(("--strict",)) == 0
    assert "schema equals the models" in caplog.text


def test_database_url_prefers_the_migration_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Settings:
        db_migration_url = "postgresql+asyncpg://m/db"
        database_url = "postgresql+asyncpg://a/db"

    monkeypatch.setattr(schema_drift, "get_settings", _Settings)
    assert schema_drift._database_url() == "postgresql+asyncpg://m/db"


def test_main_logs_a_failed_compare_and_stops_only_when_strict(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom() -> str:
        raise RuntimeError("no database")

    monkeypatch.setattr(schema_drift, "_database_url", _boom)
    caplog.set_level(logging.ERROR, logger="app.schema_drift")
    assert schema_drift.main(()) == 0
    assert schema_drift.main(("--strict",)) == 1
    assert [r.getMessage() for r in caplog.records] == ["schema compare failed"] * 2
