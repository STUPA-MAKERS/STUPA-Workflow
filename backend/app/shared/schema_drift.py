"""Compare the schema of a database with the models (§000626, §000627).

`alembic upgrade head` builds a fresh database from the models of the same commit, so a
fresh database always agrees with them. A database that came through older migrations can
differ: a model changed without a migration, or a migration dropped a constraint by the
wrong name. `schema_differences` names each such difference.

The compare covers tables, columns, types, nullability, indexes, unique constraints and
foreign keys through the Alembic autogenerate compare, and check constraints by name,
because Alembic does not compare check constraints.

Run as a module after the upgrade: `python -m app.shared.schema_drift` writes each
difference to the log with the level `error` and exits 0, because a stop of the deploy
would keep a fix from production. `--strict` exits 1 on a difference, for CI.

A new accepted difference is a new entry in `EXCEPTIONS`, with its cause.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, Column, Connection, MetaData, Table, inspect
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  — fills Base.metadata
from app.db import Base
from app.logging_config import configure_logging
from app.settings import get_settings

_log = logging.getLogger("app.schema_drift")


@dataclass(frozen=True, slots=True)
class DriftException:
    """One accepted difference: a pattern over the difference text, and its cause."""

    pattern: str
    cause: str


EXCEPTIONS: tuple[DriftException, ...] = (
    DriftException(
        "database has index *.ix_trgm_*",
        "The trigram indexes of the global search are raw DDL in a migration, because "
        "they need the `gin_trgm_ops` operator class of the `pg_trgm` extension.",
    ),
    DriftException(
        "database has index budget.ix_budget_view_gremium_id",
        "The migration that adds `view_gremium_id` creates this index with raw DDL, "
        "and the model column carries no `index=True`.",
    ),
    DriftException(
        "database has check constraint budget.budget_fiscal_start_day",
        "A migration adds this constraint with raw DDL, and the model does not declare it.",
    ),
    DriftException(
        "database has check constraint budget.budget_fiscal_start_month",
        "A migration adds this constraint with raw DDL, and the model does not declare it.",
    ),
    DriftException(
        "database has check constraint budget_expense.budget_expense_payment_method_valid",
        "A migration adds this constraint with raw DDL, and the model does not declare it.",
    ),
)

_SIDES = {"add": "models have", "remove": "database has"}
_KINDS = {
    "table": "table",
    "column": "column",
    "index": "index",
    "constraint": "unique constraint",
    "fk": "foreign key",
}


def _object_name(obj: object) -> str:
    """Name a schema object as `<table>.<name>`, or `<table>` for a table."""
    if isinstance(obj, Table):
        return obj.name
    table = getattr(obj, "table", None)
    name = getattr(obj, "name", None)
    return f"{getattr(table, 'name', '?')}.{name or '<unnamed>'}"


def _describe_one(diff: Sequence[object]) -> str:
    """Render one Alembic difference tuple as one line."""
    verb, _, kind = str(diff[0]).partition("_")
    if verb == "modify":
        return (
            f"column {diff[2]}.{diff[3]} differs in {kind}: "
            f"database {diff[5]!r}, models {diff[6]!r}"
        )
    last = diff[-1]
    name = f"{diff[2]}.{last.name}" if isinstance(last, Column) else _object_name(last)
    return f"{_SIDES.get(verb, verb)} {_KINDS.get(kind, kind)} {name}"


def _describe(diff: object) -> tuple[str, ...]:
    """Render one Alembic entry, which is one tuple or a list of column changes."""
    if isinstance(diff, list):
        return tuple(_describe_one(inner) for inner in diff)
    if isinstance(diff, tuple):
        return (_describe_one(diff),)
    return (repr(diff),)


def _check_differences(connection: Connection, metadata: MetaData) -> tuple[str, ...]:
    """Name each check constraint that only the models or only the database have."""
    inspector = inspect(connection)
    present = frozenset(inspector.get_table_names())
    pairs = tuple(
        (
            table.name,
            frozenset(
                str(c.name)
                for c in table.constraints
                if isinstance(c, CheckConstraint) and c.name is not None
            ),
            frozenset(str(c["name"]) for c in inspector.get_check_constraints(table.name)),
        )
        for table in metadata.sorted_tables
        if table.name in present
    )
    return tuple(
        line
        for table, in_models, in_database in pairs
        for line in (
            *(
                f"models have check constraint {table}.{name}"
                for name in sorted(in_models - in_database)
            ),
            *(
                f"database has check constraint {table}.{name}"
                for name in sorted(in_database - in_models)
            ),
        )
    )


def is_excepted(line: str, exceptions: Sequence[DriftException] = EXCEPTIONS) -> bool:
    """Tell if an entry of the exception list accepts this difference."""
    return any(fnmatchcase(line, entry.pattern) for entry in exceptions)


def schema_differences(
    connection: Connection,
    metadata: MetaData = Base.metadata,
    exceptions: Sequence[DriftException] = EXCEPTIONS,
) -> tuple[str, ...]:
    """List each difference between the database and the models, exceptions left out.

    Args:
        connection: A sync connection to the migrated database.
        metadata: The metadata of the models.
        exceptions: The accepted differences.

    Returns:
        One line per difference. An empty tuple means the schema equals the models.
    """
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    lines = (
        *(line for diff in compare_metadata(context, metadata) for line in _describe(diff)),
        *_check_differences(connection, metadata),
    )
    return tuple(line for line in lines if not is_excepted(line, exceptions))


def _database_url() -> str:
    """Give the migration URL, with the app URL as the fallback, as the migrations do."""
    settings = get_settings()
    return settings.db_migration_url or settings.database_url


async def report(url: str) -> tuple[str, ...]:
    """Compare the database at `url` with the models and log each difference as an error."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            differences = await connection.run_sync(schema_differences)
    finally:
        await engine.dispose()
    for line in differences:
        _log.error("schema differs from the models: %s", line)
    if not differences:
        _log.info("schema equals the models")
    return differences


def main(argv: Sequence[str]) -> int:
    """Run the compare; exit 1 only with `--strict` and a difference or a failed compare.

    Without `--strict` a compare that fails is one more log line with the level `error`,
    because the upgrade is done at this point and the deploy must go on.
    """
    configure_logging()
    strict = "--strict" in argv
    try:
        differences = asyncio.run(report(_database_url()))
    except Exception:
        _log.exception("schema compare failed")
        return 1 if strict else 0
    return 1 if differences and strict else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
