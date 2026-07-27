"""Async DB engine, session lifecycle, and metadata registry (SQLAlchemy 2.0).

The engine and the sessionmaker are lazy and cached, so no connection opens at
import time. `get_session` is the FastAPI dependency. Every module model registers
on `Base.metadata`, the single source for Alembic and for the tests.
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

# Deterministic constraint/index names keep migrations stable and reviewable.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Shared declarative base of all models (metadata registry)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPkMixin:
    """UUID primary key with a `gen_random_uuid()` server default (needs pgcrypto)."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )


class CreatedAtMixin:
    """Row creation timestamp, set by the database with `now()`."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    """Row creation and update timestamps.

    SQLAlchemy writes `updated_at` into every UPDATE it issues. A raw SQL update
    does not touch the column.
    """

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
    """Yield a request-scoped session that rolls back on an error and always closes."""
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Dispose the engine pool at lifespan shutdown."""
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
