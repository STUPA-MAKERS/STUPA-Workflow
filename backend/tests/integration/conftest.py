"""Integration-Fixtures: echte Postgres-16 via testcontainers + Alembic-Upgrade.

Übersprungen, wenn keine Docker-Runtime erreichbar ist (lokal ohne Docker); in der
CI-Integration-Stage (T-04) läuft Docker → Tests greifen. data-model §4 / testing.md §5.
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
    """Startet Postgres-16-Container; gibt (sync_url, async_url). Skip ohne Docker."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers nicht installiert")

    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # pragma: no cover - Umgebung ohne Docker
        pytest.skip(f"keine Docker-Runtime: {exc}")

    sync_url = container.get_connection_url()  # postgresql+psycopg://…
    async_url = sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    try:
        yield sync_url, async_url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated(_pg_urls: tuple[str, str]) -> tuple[str, str]:
    """Schema auf `head` migriert (idempotent). Gibt (sync_url, async_url)."""
    sync_url, async_url = _pg_urls
    command.upgrade(_make_alembic_config(async_url), "head")
    return sync_url, async_url


@pytest.fixture
def alembic_cfg(migrated: tuple[str, str]) -> Config:
    return _make_alembic_config(migrated[1])


@pytest.fixture
def engine(migrated: tuple[str, str]) -> Iterator[Engine]:
    """Sync-Engine (psycopg) für Assertions/Inserts; säubert Test-Daten je Test."""
    eng = create_engine(migrated[0])
    _truncate(eng)
    try:
        yield eng
    finally:
        _truncate(eng)
        eng.dispose()


_DATA_TABLES = (
    "applicant",
    "application",
    "state",
    "transition",
    "flow_version",
    "form_field",
    "form_version",
    "application_type",
)


def _truncate(eng: Engine) -> None:
    with eng.begin() as conn:
        # `audit_entry` ist per Trigger append-only (auch gegen TRUNCATE, T-23). Für die
        # Test-Isolation wird der Schutz nur in dieser Wartungs-Transaktion umgangen
        # (`session_replication_role = replica` deaktiviert User-Trigger) — der Trigger
        # selbst bleibt bestehen; ein eigener Test beweist die Ablehnung im Normalbetrieb.
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text("TRUNCATE audit_entry RESTART IDENTITY"))
        conn.execute(text("SET LOCAL session_replication_role = origin"))
        conn.execute(
            text("TRUNCATE " + ", ".join(_DATA_TABLES) + " RESTART IDENTITY CASCADE")
        )
