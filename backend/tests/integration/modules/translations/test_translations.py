"""UI text overrides and extra UI languages: the admin routes and the public bundle.

* `admin.translations` gates every admin route; the public bundle needs no login.
* A save sets and clears overrides, refuses unknown keys and lost placeholders as a
  whole, and writes a `config_change` audit entry with the keys only.
* The built-in texts come by key with the override of a locale, and `untranslated`
  keeps the keys without one.
* An extra language starts inactive and shows in the bundle only while active. Its
  fallback chain is the language, then EN, then DE. A delete removes its overrides.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.deps import get_current_principal
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.translations.models import UiTranslation
from app.settings import Settings
from tests._support.guest_apps import build_api, guest_settings

pytestmark = pytest.mark.integration

_ADMIN = Principal(sub="text-admin", roles=[], permissions={"admin.translations"})
_OTHER = Principal(sub="site-admin", roles=[], permissions={"admin.site"})


@pytest.fixture
async def maker(
    migrated: tuple[str, str], engine: Engine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = create_async_engine(migrated[1])
    yield async_sessionmaker(eng, expire_on_commit=False)
    await eng.dispose()


@pytest.fixture
def settings(migrated: tuple[str, str]) -> Settings:
    return guest_settings(migrated[1])


def _client(
    migrated: tuple[str, str],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    principal: Principal | None,
) -> TestClient:
    api = build_api(migrated[1], settings, monkeypatch)
    api.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(api)


async def test_save_sets_clears_and_audits(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        assert client.get("/api/admin/translations/texts/de").json() == {
            "locale": "de",
            "overrides": {},
        }
        put = client.put(
            "/api/admin/translations/texts/de",
            json={
                "changes": {
                    "meetings.overview.open": "Ansehen",
                    "shell.nav.tasksOpen": "{count} zu tun",
                }
            },
        )
        assert put.status_code == 200, put.text
        assert put.json()["overrides"] == {
            "meetings.overview.open": "Ansehen",
            "shell.nav.tasksOpen": "{count} zu tun",
        }
        cleared = client.put(
            "/api/admin/translations/texts/de",
            json={"changes": {"meetings.overview.open": None, "shell.nav.tasksOpen": "  "}},
        )
        assert cleared.json()["overrides"] == {}
        again = client.put(
            "/api/admin/translations/texts/de",
            json={"changes": {"meetings.overview.open": "Ansehen"}},
        )
        assert again.status_code == 200
        bundle = client.get("/api/i18n", params={"locale": "de"})
        assert bundle.headers["cache-control"] == "no-cache"
        assert bundle.json() == {
            "locale": "de",
            "languages": [],
            "overrides": {"de": {"meetings.overview.open": "Ansehen"}},
        }

    async with maker() as session:
        entries = (
            await session.scalars(
                select(AuditEntry)
                .where(AuditEntry.target_type == "ui_translation")
                .order_by(AuditEntry.id)
            )
        ).all()
        rows = (await session.scalars(select(UiTranslation))).all()
    assert [e.data["set"] for e in entries] == [2, 0, 1]
    assert entries[1].data == {
        "set": 0,
        "cleared": 2,
        "keys": ["meetings.overview.open", "shell.nav.tasksOpen"],
    }
    assert all(e.actor == "text-admin" and e.target_id == "de" for e in entries)
    assert [(r.locale, r.key, r.value) for r in rows] == [
        ("de", "meetings.overview.open", "Ansehen")
    ]


async def test_save_refuses_unknown_keys_and_lost_placeholders(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        unknown = client.put(
            "/api/admin/translations/texts/en",
            json={"changes": {"no.such.key": "x", "meetings.overview.open": "View"}},
        )
        assert unknown.status_code == 422
        assert unknown.json()["code"] == "unknown_key"
        assert unknown.json()["errors"] == [{"field": "no.such.key", "msg": "unknown key"}]
        lost = client.put(
            "/api/admin/translations/texts/en",
            json={"changes": {"shell.nav.tasksOpen": "open", "meetings.overview.open": "View"}},
        )
        assert lost.status_code == 422
        assert lost.json()["code"] == "placeholder_mismatch"
        assert lost.json()["errors"] == [
            {"field": "shell.nav.tasksOpen", "msg": "expected {count}"}
        ]
        extra = client.put(
            "/api/admin/translations/texts/en",
            json={"changes": {"meetings.overview.open": "View {x}"}},
        )
        assert extra.json()["code"] == "placeholder_mismatch"
        assert (
            client.put("/api/admin/translations/texts/xx", json={"changes": {}}).status_code == 404
        )
        assert client.get("/api/admin/translations/texts/xx").status_code == 404

    async with maker() as session:
        assert (await session.scalars(select(UiTranslation))).all() == []


async def test_extra_language_lifecycle(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        made = client.post(
            "/api/admin/translations/languages", json={"code": "fr", "name": "Français"}
        )
        assert made.status_code == 201, made.text
        assert made.json()["active"] is False
        assert (
            client.post(
                "/api/admin/translations/languages", json={"code": "fr", "name": "x"}
            ).json()["code"]
            == "language_exists"
        )
        assert (
            client.post(
                "/api/admin/translations/languages", json={"code": "en", "name": "x"}
            ).json()["code"]
            == "language_builtin"
        )
        assert (
            client.post(
                "/api/admin/translations/languages", json={"code": "French", "name": "x"}
            ).status_code
            == 422
        )

        client.put(
            "/api/admin/translations/texts/fr", json={"changes": {"meetings.overview.open": "Voir"}}
        )
        client.put("/api/admin/translations/texts/en", json={"changes": {"nav.tasks": "To do"}})
        assert client.get("/api/i18n", params={"locale": "fr"}).json() == {
            "locale": "de",
            "languages": [],
            "overrides": {"de": {}},
        }

        on = client.patch(
            "/api/admin/translations/languages/fr", json={"active": True, "name": "Français"}
        )
        assert on.status_code == 200
        assert on.json()["active"] is True
        assert client.get("/api/i18n", params={"locale": "fr"}).json() == {
            "locale": "fr",
            "languages": [{"code": "fr", "name": "Français"}],
            "overrides": {
                "fr": {"meetings.overview.open": "Voir"},
                "en": {"nav.tasks": "To do"},
                "de": {},
            },
        }
        assert client.get("/api/i18n").json()["locale"] == "de"
        assert [
            lang["code"] for lang in client.get("/api/admin/translations/languages").json()
        ] == ["fr"]

        assert client.delete("/api/admin/translations/languages/fr").status_code == 204
        assert client.delete("/api/admin/translations/languages/fr").status_code == 404
        assert (
            client.patch("/api/admin/translations/languages/fr", json={"active": True}).status_code
            == 404
        )

    async with maker() as session:
        rows = (await session.scalars(select(UiTranslation))).all()
        entries = (
            await session.scalars(
                select(AuditEntry)
                .where(AuditEntry.target_type == "ui_language")
                .order_by(AuditEntry.id)
            )
        ).all()
    assert [(r.locale, r.key) for r in rows] == [("en", "nav.tasks")]
    assert [e.data for e in entries] == [
        {"created": True, "name": "Français", "active": False},
        {"active": {"from": False, "to": True}},
        {"deleted": True, "overrides": 1},
    ]


def test_routes_need_the_permission(
    migrated: tuple[str, str], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _client(migrated, settings, monkeypatch, _OTHER) as client:
        assert client.get("/api/admin/translations/languages").status_code == 403
        assert client.get("/api/admin/translations/texts/de").status_code == 403
        assert client.get("/api/admin/translations/builtin").status_code == 403
        assert (
            client.put("/api/admin/translations/texts/de", json={"changes": {}}).status_code == 403
        )
        assert (
            client.post(
                "/api/admin/translations/languages", json={"code": "fr", "name": "F"}
            ).status_code
            == 403
        )
        assert client.get("/api/i18n").status_code == 200
    with _client(migrated, settings, monkeypatch, None) as client:
        assert client.get("/api/admin/translations/languages").status_code == 401
        assert client.get("/api/i18n").json()["locale"] == "de"


async def test_builtin_texts_with_the_own_text(
    migrated: tuple[str, str],
    settings: Settings,
    maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(migrated, settings, monkeypatch, _ADMIN) as client:
        everything = client.get("/api/admin/translations/builtin").json()
        assert everything["locale"] is None
        assert len(everything["texts"]) > 1000
        assert all(row["own"] is None for row in everything["texts"])
        keys = [row["key"] for row in everything["texts"]]
        assert keys == sorted(keys)

        prefix = "meetings.overview."
        rows = client.get("/api/admin/translations/builtin", params={"prefix": prefix}).json()
        assert rows["texts"]
        assert all(row["key"].startswith(prefix) for row in rows["texts"])
        open_row = next(row for row in rows["texts"] if row["key"] == "meetings.overview.open")
        assert open_row == {
            "key": "meetings.overview.open",
            "de": "Details",
            "en": "Details",
            "own": None,
        }

        client.post("/api/admin/translations/languages", json={"code": "fr", "name": "Français"})
        client.put(
            "/api/admin/translations/texts/fr", json={"changes": {"meetings.overview.open": "Voir"}}
        )
        mine = client.get(
            "/api/admin/translations/builtin", params={"prefix": prefix, "locale": "fr"}
        ).json()
        assert mine["locale"] == "fr"
        assert (
            next(r for r in mine["texts"] if r["key"] == "meetings.overview.open")["own"] == "Voir"
        )
        open_work = client.get(
            "/api/admin/translations/builtin",
            params={"prefix": prefix, "locale": "fr", "untranslated": "true"},
        ).json()
        assert "meetings.overview.open" not in {row["key"] for row in open_work["texts"]}
        assert len(open_work["texts"]) == len(mine["texts"]) - 1

        assert (
            client.get("/api/admin/translations/builtin", params={"untranslated": "true"}).json()[
                "code"
            ]
            == "locale_required"
        )
        assert (
            client.get("/api/admin/translations/builtin", params={"locale": "xx"}).status_code
            == 404
        )
