"""Integration (real Postgres): the Gravatar proxy reads the principal and the switch.

The fetcher and the cache are fakes, so no test contacts gravatar.com. The tests
prove:
* the proxy hashes the stored e-mail of the requested principal (SHA-256, trimmed,
  lower case) and answers the image; ``me`` reads the own row by ``sub``;
* a principal without e-mail and an unknown id give 404 without a fetch;
* the switch ``gravatarEnabled`` of the ACTIVE site config turns the proxy off, a
  draft does not; the public site config carries the switch.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.branding import Branding
from app.modules.admin.site_config_service import SiteConfigService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.avatars.cache import CachedAvatar
from app.modules.avatars.gravatar import AvatarImage, FetchResult
from app.modules.avatars.router import get_avatar_cache, get_gravatar_fetcher
from tests._support.guest_apps import build_api, guest_settings
from tests._support.read_models import as_principal

pytestmark = pytest.mark.integration

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class _Cache:
    def __init__(self) -> None:
        self.entries: dict[tuple[str, int], CachedAvatar] = {}

    async def get(self, digest: str, size: int) -> CachedAvatar | None:
        return self.entries.get((digest, size))

    async def put(
        self, digest: str, size: int, image: AvatarImage | None, *, ttl_seconds: int
    ) -> None:
        self.entries[(digest, size)] = CachedAvatar(image)


class _Fetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, digest: str, size: int) -> FetchResult:
        self.calls.append((digest, size))
        return FetchResult("found", AvatarImage(mime="image/png", data=PNG))


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE site_config_version RESTART IDENTITY CASCADE"))
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE site_config_version RESTART IDENTITY CASCADE"))


async def _principal(
    maker: async_sessionmaker[AsyncSession], email: str | None
) -> PrincipalRow:
    async with maker() as session:
        row = PrincipalRow(sub=f"av-{uuid.uuid4()}", display_name="Mara Keller", email=email)
        session.add(row)
        await session.commit()
        return row


def _api(
    migrated: tuple[str, str], monkeypatch: pytest.MonkeyPatch, fetcher: _Fetcher
) -> TestClient:
    api = build_api(migrated[1], guest_settings(migrated[1]), monkeypatch)
    api.dependency_overrides[get_gravatar_fetcher] = lambda: fetcher
    cache = _Cache()
    api.dependency_overrides[get_avatar_cache] = lambda: cache
    as_principal(api, Principal(sub="viewer"))
    return TestClient(api)


async def test_proxy_hashes_the_stored_email(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = await _principal(maker, "  Mara.Keller@Example.org")
    fetcher = _Fetcher()
    client = _api(migrated, monkeypatch, fetcher)

    resp = client.get(f"/api/principals/{row.id}/avatar?s=80")
    assert resp.status_code == 200
    assert resp.content == PNG
    digest = hashlib.sha256(b"mara.keller@example.org").hexdigest()
    assert fetcher.calls == [(digest, 128)]
    assert digest not in str(dict(resp.headers))

    # `me` reads the own row by sub.
    as_principal(client.app, Principal(sub=row.sub))  # type: ignore[arg-type]
    assert client.get("/api/principals/me/avatar?s=64").status_code == 200
    assert fetcher.calls[-1] == (digest, 64)


async def test_no_email_and_unknown_id_give_404(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = await _principal(maker, None)
    fetcher = _Fetcher()
    client = _api(migrated, monkeypatch, fetcher)
    assert client.get(f"/api/principals/{row.id}/avatar").status_code == 404
    assert client.get(f"/api/principals/{uuid.uuid4()}/avatar").status_code == 404
    assert fetcher.calls == []


async def test_active_site_config_switches_the_proxy_off(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = await _principal(maker, "m@example.org")
    fetcher = _Fetcher()
    client = _api(migrated, monkeypatch, fetcher)

    # A draft with the switch off changes nothing until it is active.
    async with maker() as session:
        await SiteConfigService(session).put_draft(
            Branding.model_validate({"gravatarEnabled": False}), actor="admin"
        )
    assert client.get(f"/api/principals/{row.id}/avatar").status_code == 200

    async with maker() as session:
        out = await SiteConfigService(session).activate(actor="admin")
        assert out.active.gravatar_enabled is False
        public = await SiteConfigService(session).public()
    assert public.model_dump(by_alias=True)["branding"]["gravatarEnabled"] is False

    calls = len(fetcher.calls)
    resp = client.get(f"/api/principals/{row.id}/avatar")
    assert resp.status_code == 404
    assert resp.headers["cache-control"] == "private, max-age=300"
    assert len(fetcher.calls) == calls

    # The public endpoint carries the switch for the frontend.
    public_resp = client.get("/api/site-config")
    assert public_resp.json()["branding"]["gravatarEnabled"] is False
