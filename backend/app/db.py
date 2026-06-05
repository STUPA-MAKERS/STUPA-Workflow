"""Async DB-Engine + Session-Lifecycle + Metadata-Registry (SQLAlchemy 2.0 async).

Engine/Sessionmaker lazy + gecacht (kein Connect beim Import). `get_session` ist
die FastAPI-Dependency (yield → close je Request). `Base` ist die deklarative
Registry: alle Modul-Modelle (T-06) hängen ihre Tabellen in `Base.metadata` ein;
Alembic (`migrations/`) und die Tests nutzen diese Metadata als Single Source.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime
from functools import lru_cache

from sqlalchemy import DateTime, MetaData, Uuid, func, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.settings import get_settings

# Deterministische Constraint-/Index-Namen → stabile, reviewbare Migrationen.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Gemeinsame deklarative Basis aller Modelle (Metadata-Registry)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPkMixin:
    """`id uuid PK DEFAULT gen_random_uuid()` (pgcrypto, data-model §0)."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )


class CreatedAtMixin:
    """`created_at timestamptz DEFAULT now()`."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    """`created_at` + `updated_at` (auto-touch via `onupdate`)."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        expire_on_commit=False,
        autoflush=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Request-scoped Session; bei Fehler Rollback, immer Close."""
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Engine-Pool schließen (Shutdown/Lifespan)."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
