"""Async DB-Engine + Session-Lifecycle (SQLAlchemy 2.0 async).

Engine/Sessionmaker lazy + gecacht (kein Connect beim Import). `get_session` ist
die FastAPI-Dependency (yield → close je Request). Migrationen/Modelle: T-06.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import get_settings


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
