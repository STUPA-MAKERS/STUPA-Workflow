"""A11/O17: the applicant reads the version metadata, without values (real Postgres).

The magic-link applicant and the logged-in creator without a read permission get the
number, the time, the changed keys and the editor of every version. `data` and `diff`
stay null. A principal with `application.read` still gets the full history.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.principal import Principal
from tests._support.read_models import (
    GREMIUM_NAME,
    IBAN,
    OWNER_NAME,
    as_applicant,
    as_principal,
    build_read_api,
    create_app,
    get_json,
    patch,
    seed_read_world,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def test_applicant_reads_version_metadata_only(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor="applicant")
    # v2 by a member, v3 by the applicant through the magic link.
    await patch(
        maker,
        app_id,
        {"title": "Antrag", "iban": IBAN, "note": "vom Gremium"},
        changed_by=seed.member_sub,
    )
    await patch(
        maker,
        app_id,
        {"title": "Antrag neu", "iban": IBAN, "note": "vom Gremium"},
        changed_by="applicant",
    )

    api = build_read_api(migrated[1], monkeypatch)
    as_applicant(api, app_id)
    versions = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(versions, list)
    assert [v["version"] for v in versions] == [1, 2, 3]
    assert all(v["data"] is None and v["diff"] is None for v in versions)
    assert all(v["at"] for v in versions)
    assert [v["changedKeys"] for v in versions] == [[], ["note"], ["title"]]
    # A12: the member edit names the Gremium, the own edits stay the applicant.
    assert [v["changedBy"] for v in versions] == ["applicant", GREMIUM_NAME, "applicant"]

    as_principal(api, Principal(sub="reader", permissions={"application.read"}))
    full = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(full, list)
    assert full[1]["data"]["note"] == "vom Gremium"
    assert full[1]["diff"]["changed"]["note"] == {"old": "erste Notiz", "new": "vom Gremium"}
    assert full[1]["changedKeys"] == ["note"]
    assert full[1]["changedBy"] == "Max Mitglied"


async def test_logged_in_creator_reads_version_metadata(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor=seed.owner_sub)
    await patch(
        maker,
        app_id,
        {"title": "Antrag", "iban": IBAN, "note": "zweite"},
        changed_by=seed.owner_sub,
    )

    api = build_read_api(migrated[1], monkeypatch)
    # The creator without any permission: before A11 this route answered 403.
    as_principal(api, Principal(sub=seed.owner_sub, display_name=OWNER_NAME))
    versions = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(versions, list)
    assert [v["changedKeys"] for v in versions] == [[], ["note"]]
    assert [v["changedBy"] for v in versions] == [OWNER_NAME, OWNER_NAME]
    assert all(v["data"] is None and v["diff"] is None for v in versions)


async def test_foreign_principal_cannot_read_versions(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor=seed.owner_sub, in_read_scope=False)
    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="stranger"))
    with TestClient(api) as client:
        resp = client.get(f"/api/applications/{app_id}/versions")
    assert resp.status_code == 403
