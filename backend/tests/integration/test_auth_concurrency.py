"""Integration: atomare Single-Use-Einlösung des Magic-Links (security.md §1).

Zwei nebenläufige `verify_magic_link` mit demselben Token gegen echtes Postgres:
genau einer gewinnt (Applicant-Session), der andere bekommt 410 (Replay-Schutz).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.auth import service, tokens
from app.settings import load_settings
from app.shared.errors import GoneError

_SECRET = "x" * 16
_PEPPER = "magic-link-pepper-0"
_TOKEN = "concurrency-test-token"


def _seed_single_use_link(engine: Engine) -> None:
    digest = tokens.hash_token(_TOKEN, _PEPPER)
    expires = datetime.now(UTC) + timedelta(days=1)
    with engine.begin() as conn:
        type_id = conn.execute(
            text("INSERT INTO application_type (key) VALUES ('c') RETURNING id")
        ).scalar_one()
        fv = conn.execute(
            text(
                "INSERT INTO form_version (application_type_id, version) "
                "VALUES (:t,1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        flv = conn.execute(
            text(
                "INSERT INTO flow_version (application_type_id, version) "
                "VALUES (:t,1) RETURNING id"
            ),
            {"t": type_id},
        ).scalar_one()
        app_id = conn.execute(
            text(
                "INSERT INTO application (type_id, form_version_id, flow_version_id) "
                "VALUES (:t,:fv,:flv) RETURNING id"
            ),
            {"t": type_id, "fv": fv, "flv": flv},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO magic_link "
                "(application_id, token_hash, scope, expires_at, single_use) "
                "VALUES (:a, :h, 'view', :e, true)"
            ),
            {"a": app_id, "h": digest, "e": expires},
        )


async def test_concurrent_single_use_only_one_wins(
    migrated: tuple[str, str], engine: Engine
) -> None:
    _seed_single_use_link(engine)
    _, async_url = migrated
    settings = load_settings(
        database_url=async_url, session_secret=_SECRET, magic_link_secret=_PEPPER
    )
    aengine = create_async_engine(async_url)
    sessionmaker = async_sessionmaker(aengine, expire_on_commit=False)

    async def attempt() -> str:
        async with sessionmaker() as db:
            try:
                await service.verify_magic_link(db, settings, token=_TOKEN)
                await db.commit()
                return "ok"
            except GoneError:
                return "gone"

    try:
        outcomes = sorted(await asyncio.gather(attempt(), attempt()))
    finally:
        await aengine.dispose()

    assert outcomes == ["gone", "ok"]  # exakt einer gewinnt
