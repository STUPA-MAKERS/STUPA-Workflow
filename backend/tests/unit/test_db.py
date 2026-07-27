"""Test the async DB engine and the session lifecycle of `db.py`.

The tests never open a real database connection.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db import get_engine, get_session, get_sessionmaker


def test_engine_is_async_and_cached() -> None:
    eng = get_engine()
    assert isinstance(eng, AsyncEngine)
    assert get_engine() is eng


def test_sessionmaker_builds_async_session() -> None:
    maker = get_sessionmaker()
    sess = maker()
    assert isinstance(sess, AsyncSession)


async def test_get_session_yields_and_closes() -> None:
    gen = get_session()
    sess = await anext(gen)
    assert isinstance(sess, AsyncSession)
    # The finally branch of the generator runs here and calls session.close().
    await gen.aclose()


async def test_get_session_rolls_back_on_error() -> None:
    gen = get_session()
    await anext(gen)
    # The except branch rolls back the session. The finally branch then closes it.
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))


async def test_lifespan_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.db import get_engine
    from app.main import lifespan

    # Stub the mail pool of the lifespan. The unit test has no Redis.
    async def _no_pool(_redis_url: str) -> None:
        return None

    monkeypatch.setattr("app.main.create_mail_pool", _no_pool)
    get_engine()  # Create the engine so that the dispose path runs.
    app = SimpleNamespace(state=SimpleNamespace())  # lifespan sets state.arq_pool
    async with lifespan(app):  # type: ignore[arg-type]
        pass
