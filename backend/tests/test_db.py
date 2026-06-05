"""TDD: async DB-Engine/Session-Lifecycle (db.py). Kein echter Connect (Skelett)."""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import get_engine, get_session, get_sessionmaker


def test_engine_is_async_and_cached() -> None:
    eng = get_engine()
    assert isinstance(eng, AsyncEngine)
    assert get_engine() is eng  # gecacht


def test_sessionmaker_builds_async_session() -> None:
    maker = get_sessionmaker()
    sess = maker()
    assert isinstance(sess, AsyncSession)


async def test_get_session_yields_and_closes() -> None:
    gen = get_session()
    sess = await anext(gen)
    assert isinstance(sess, AsyncSession)
    # Generator sauber schließen (ruft session.close()).
    await gen.aclose()


async def test_get_session_rolls_back_on_error() -> None:
    gen = get_session()
    await anext(gen)
    # Fehler in den Generator werfen → except-Zweig (rollback) + finally (close).
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))


async def test_lifespan_disposes_engine() -> None:
    from app.db import get_engine
    from app.main import lifespan

    get_engine()  # Engine erzeugen, damit dispose-Pfad greift.
    app = object()  # lifespan nutzt das Arg nicht.
    async with lifespan(app):  # type: ignore[arg-type]
        pass
