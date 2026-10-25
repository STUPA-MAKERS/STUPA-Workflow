"""Integration fixtures: a real Postgres 16 from testcontainers plus an Alembic upgrade.

The tests skip when no Docker runtime is reachable, for example on a local machine
without Docker. The CI integration stage runs Docker, so the tests run there.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text


def _make_alembic_config(async_url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", async_url)
    return cfg


@pytest.fixture(scope="session")
def _pg_urls() -> Iterator[tuple[str, str]]:
    """Start a Postgres 16 container.

    The fixture skips the test when no Docker runtime is available.

    Yields:
        The sync URL first and the async URL second.
    """
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers nicht installiert")

    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - Umgebung ohne Docker
        pytest.skip(f"keine Docker-Runtime: {exc}")

    sync_url = container.get_connection_url()
    async_url = sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    try:
        yield sync_url, async_url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated(_pg_urls: tuple[str, str]) -> tuple[str, str]:
    """Migrate the schema to `head`.

    The upgrade is idempotent.

    Returns:
        The sync URL first and the async URL second.
    """
    sync_url, async_url = _pg_urls
    command.upgrade(_make_alembic_config(async_url), "head")
    return sync_url, async_url


@pytest.fixture
def alembic_cfg(migrated: tuple[str, str]) -> Config:
    return _make_alembic_config(migrated[1])


@pytest.fixture
def engine(migrated: tuple[str, str]) -> Iterator[Engine]:
    """Give a sync psycopg engine for assertions and inserts.

    The fixture clears the test data before and after each test.
    """
    eng = create_engine(migrated[0])
    _truncate(eng)
    try:
        yield eng
    finally:
        _truncate(eng)
        eng.dispose()


#: Tables that the ``engine`` fixture truncates after each test. The meeting and vote
#: tables are listed, because the ``application`` CASCADE does not reach them, and they
#: would leak between tests (``uq_flow_version_version``, vote or ballot collisions);
#: their CASCADE clears the children. The single-row settings fall back to the defaults
#: after the truncate, so a changed setting does not leak. ``attachment_draft_token``,
#: ``audit_verification`` and ``ticket_sender_block`` have no FK that a CASCADE follows.
#: ``ticket`` and ``todo_board`` clear their child rows by CASCADE; a test creates the
#: boards it needs (``ensure_gremium_board``, ``GET /todos/boards``).
_DATA_TABLES = (
    "applicant",
    "application",
    "state",
    "transition",
    "flow_version",
    "form_field",
    "form_version",
    "application_type",
    "meeting",
    "vote",
    "ballot",
    "protocol",
    "task_reminder_log",
    "guest_application_settings",
    "meeting_settings",
    "login_settings",
    "attachment_draft_token",
    "audit_verification",
    "ticket",
    "ticket_sender_block",
    "todo_board",
)


def clear_privacy_tables(eng: Engine) -> None:
    """Clear the privacy and auth base tables for test isolation of the DSGVO suite.

    The `engine` fixture clears only the application and flow tables. Without this
    helper, `principal`, `auth_session`, `erasure_request` and `privacy_settings` stay
    for the whole session and leak between tests. One example is a login subject that
    keeps the mail address of an applicant. This helper restores the clean start state.
    A trigger protects `audit_entry`, so the `engine` fixture clears it separately.
    """
    with eng.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE erasure_request, auth_session, principal, privacy_settings "
                "RESTART IDENTITY CASCADE"
            )
        )


def _truncate(eng: Engine) -> None:
    """Truncate the data tables and the audit log.

    A trigger keeps ``audit_entry`` append-only, also against TRUNCATE. This maintenance
    transaction is the only place that bypasses it, because ``session_replication_role =
    replica`` turns off the user triggers; the trigger itself stays. A separate test proves
    that normal operation rejects the write.
    """
    with eng.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("TRUNCATE audit_entry RESTART IDENTITY"))
        conn.execute(text("SET LOCAL session_replication_role = origin"))
        conn.execute(
            text("TRUNCATE " + ", ".join(_DATA_TABLES) + " RESTART IDENTITY CASCADE")
        )
