"""O21: the `isPII` fields reach only a reader with the PII right (real Postgres).

The right is `application.read`, `application.read_all` or admin. The applicant
(magic link) and the logged-in creator read the own data. A member who reads only
through the Gremium read scope gets the detail and the version history without the
`isPII` fields and without the applicant block. An editor with `application.manage`
alone cannot see them either, so the patch keeps their stored values. The XLSX export
holds no form field value at all.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from tests._support.read_models import (
    IBAN,
    MEMBER_NAME,
    OWNER_NAME,
    ReadSeed,
    as_applicant,
    as_principal,
    build_read_api,
    create_app,
    get_json,
    patch,
    seed_read_world,
    staff,
)

pytestmark = pytest.mark.integration

_NEW_IBAN = "DE89370400440532013000"


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


async def _world(
    maker: async_sessionmaker[AsyncSession],
) -> tuple[ReadSeed, uuid.UUID]:
    """An application by the creator, with a second version that changes the IBAN."""
    seed = await seed_read_world(maker)
    app_id = await create_app(maker, seed, actor=seed.owner_sub)
    await patch(
        maker,
        app_id,
        {"title": "Antrag", "iban": _NEW_IBAN, "note": "zweite"},
        changed_by=seed.owner_sub,
    )
    return seed, app_id


def _detail(api: FastAPI, app_id: uuid.UUID) -> dict:
    body = get_json(api, f"/api/applications/{app_id}")
    assert isinstance(body, dict)
    return body


def _versions(api: FastAPI, app_id: uuid.UUID) -> list:
    body = get_json(api, f"/api/applications/{app_id}/versions")
    assert isinstance(body, list)
    return body


@pytest.mark.parametrize(
    "principal",
    [
        Principal(sub="reader", permissions={"application.read"}),
        Principal(sub="global", permissions={"application.read_all"}),
        Principal(sub="root", roles=["admin"]),
    ],
    ids=["read", "read_all", "admin"],
)
async def test_reader_with_the_right_sees_pii(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal,
) -> None:
    _, app_id = await _world(maker)
    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, principal)

    detail = _detail(api, app_id)
    assert detail["data"]["iban"] == _NEW_IBAN
    assert detail["applicant"]["email"] == "antrag@example.org"

    versions = _versions(api, app_id)
    assert versions[0]["data"]["iban"] == IBAN
    assert versions[1]["diff"]["changed"]["iban"] == {"old": IBAN, "new": _NEW_IBAN}
    assert versions[1]["changedKeys"] == ["iban", "note"]


async def test_committee_reader_gets_no_pii(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, app_id = await _world(maker)
    api = build_read_api(migrated[1], monkeypatch)
    # Gremium member without a global permission: reads through the view cost centre.
    as_principal(api, Principal(sub=seed.member_sub, display_name=MEMBER_NAME))

    detail = _detail(api, app_id)
    assert "iban" not in detail["data"]
    assert detail["data"]["note"] == "zweite"
    assert detail["applicant"] is None

    versions = _versions(api, app_id)
    assert [v["version"] for v in versions] == [1, 2]
    assert all("iban" not in v["data"] for v in versions)
    assert "iban" not in versions[1]["diff"]["changed"]
    assert versions[1]["diff"]["changed"]["note"] == {"old": "erste Notiz", "new": "zweite"}
    assert versions[1]["changedKeys"] == ["note"]
    assert versions[1]["changedBy"] == OWNER_NAME
    assert IBAN not in str(versions) and _NEW_IBAN not in str(versions)


async def test_applicant_and_creator_read_the_own_pii(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, app_id = await _world(maker)
    api = build_read_api(migrated[1], monkeypatch)

    as_applicant(api, app_id)
    assert _detail(api, app_id)["data"]["iban"] == _NEW_IBAN

    as_principal(api, Principal(sub=seed.owner_sub, display_name=OWNER_NAME))
    detail = _detail(api, app_id)
    assert detail["data"]["iban"] == _NEW_IBAN
    assert detail["applicant"]["name"] == "Anna Antrag"
    assert detail["isOwner"] is True


async def test_editor_without_read_keeps_the_stored_pii(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, app_id = await _world(maker)
    api = build_read_api(migrated[1], monkeypatch)
    # `application.manage` without `application.read`: the editor reads no IBAN and
    # sends the form back without it, or with a value it never saw.
    as_principal(api, staff(seed))
    with TestClient(api) as client:
        without = client.patch(
            f"/api/applications/{app_id}",
            json={"data": {"title": "Antrag", "note": "dritte"}},
        )
        forged = client.patch(
            f"/api/applications/{app_id}",
            json={"data": {"title": "Antrag", "iban": "DE00", "note": "vierte"}},
        )
    assert without.status_code == 200, without.text
    assert "iban" not in without.json()["data"]
    assert forged.status_code == 200, forged.text
    assert "iban" not in forged.json()["data"]

    async with maker() as session:
        row = await session.get(Application, app_id)
        assert row is not None
        assert row.data["iban"] == _NEW_IBAN
        assert row.data["note"] == "vierte"


async def test_archive_response_strips_pii_without_read(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, app_id = await _world(maker)
    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="archivar", permissions={"application.archive"}))
    with TestClient(api) as client:
        archived = client.post(f"/api/applications/{app_id}/archive")
        restored = client.delete(f"/api/applications/{app_id}/archive")
    assert archived.status_code == 200, archived.text
    assert "iban" not in archived.json()["data"]
    assert "iban" not in restored.json()["data"]


async def test_xlsx_export_holds_no_pii(
    migrated: tuple[str, str],
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, app_id = await _world(maker)
    api = build_read_api(migrated[1], monkeypatch)
    as_principal(api, Principal(sub="export", permissions={"application.export"}))
    with TestClient(api) as client:
        resp = client.get("/api/applications/export.xlsx")
    assert resp.status_code == 200, resp.text
    sheet = load_workbook(io.BytesIO(resp.content)).active
    assert sheet is not None
    cells = [str(c) for row in sheet.iter_rows(values_only=True) for c in row if c]
    assert "Antrag" in cells
    assert "Status seit" in cells
    assert not any(IBAN in c or _NEW_IBAN in c for c in cells)
    assert not any("antrag@example.org" in c for c in cells)
    assert str(app_id) not in cells
