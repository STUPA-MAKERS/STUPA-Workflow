"""Integration: the feature switches end to end (real Postgres).

§F/administration/admin/000756: the switches and their default.
§F/administration/admin/000757: a feature that is off is closed on the server.
§F/administration/admin/000758: the search and the public config follow the switches.
§F/administration/admin/000759: a switch keeps the data.
§F/administration/admin/000760: `Rechnungen` needs `Budget`.
§F/administration/admin/000761: a feature in use cannot go off.
§F/administration/admin/000762: the page needs ``admin.features``, and a save is a
version with an audit entry that a revert sets back.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.application_types.models import ApplicationType
from app.modules.audit.models import AuditEntry
from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium
from app.modules.site_config.features import Feature
from app.modules.site_config.models import SiteConfigVersion
from tests._support.guest_apps import seed_guest_flow
from tests.integration.modules.tickets.conftest import ADMIN, Api, add_principal

pytestmark = pytest.mark.integration

ALL_ON = {feature.value: True for feature in Feature}
SITE_ONLY = Principal(sub="site-sub", email="site@example.org", permissions={"admin.site"})
REVERT_ONLY = Principal(
    sub="rev-sub", email="rev@example.org", permissions={"audit.revert", "admin.site"}
)

#: One read route and one write route of each feature.
ROUTES: dict[Feature, tuple[tuple[str, str], ...]] = {
    Feature.TODOS: (("GET", "/api/todos/boards"), ("POST", "/api/todos/cards")),
    Feature.CALENDAR: (
        ("GET", "/api/calendar/entries"),
        ("POST", "/api/calendar/appointments"),
        ("GET", "/api/public/calendar/entries"),
        ("GET", "/api/admin/calendars"),
    ),
    Feature.MEETINGS: (
        ("GET", "/api/meetings"),
        ("POST", "/api/meetings"),
        ("GET", "/api/public/protocols"),
        ("GET", "/api/delegations"),
    ),
    Feature.VOTING: (
        ("GET", "/api/votes"),
        ("POST", f"/api/votes/{uuid.uuid4()}/ballot"),
        ("POST", f"/api/applications/{uuid.uuid4()}/votes"),
        ("GET", f"/api/committees/{uuid.uuid4()}/decisions"),
    ),
    Feature.BUDGET: (
        ("GET", "/api/budgets"),
        ("POST", "/api/budgets"),
        ("GET", "/api/expenses"),
    ),
    Feature.INVOICES: (("GET", "/api/invoices"), ("POST", "/api/invoices/parse")),
    Feature.TICKETS: (("GET", "/api/tickets"), ("POST", "/api/tickets")),
}


def _save(client: TestClient, **switches: bool) -> None:
    resp = client.put("/api/admin/features", json={**ALL_ON, **switches})
    assert resp.status_code == 200, resp.text


def _disabled(client: TestClient, method: str, path: str) -> bool:
    resp = client.request(method, path)
    return resp.status_code == 404 and resp.json()["code"] == "feature_disabled"


async def _admin(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    await add_principal(maker, sub=ADMIN.sub, email=ADMIN.email, role="admin")
    api.login(ADMIN)


async def test_each_feature_is_on_without_a_configuration(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    with TestClient(api.app) as client:
        assert client.get("/api/admin/features").json() == ALL_ON
        assert client.get("/api/site-config").json()["features"] == ALL_ON
        assert "features" not in client.get("/api/site-config").json()["branding"]


async def test_an_unknown_feature_key_is_refused(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    with TestClient(api.app) as client:
        resp = client.put("/api/admin/features", json={**ALL_ON, "wiki": False})
    assert resp.status_code == 422


async def test_the_switches_need_their_own_permission(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await add_principal(maker, sub=SITE_ONLY.sub, email=SITE_ONLY.email)
    with TestClient(api.app) as client:
        assert client.get("/api/admin/features").status_code == 401
        api.login(SITE_ONLY)
        assert client.get("/api/admin/features").status_code == 403
        assert client.put("/api/admin/features", json=ALL_ON).status_code == 403


@pytest.mark.parametrize("feature", list(Feature))
async def test_a_feature_that_is_off_answers_feature_disabled_to_the_admin(
    api: Api, maker: async_sessionmaker[AsyncSession], feature: Feature
) -> None:
    await _admin(api, maker)
    with TestClient(api.app) as client:
        assert not any(_disabled(client, method, path) for method, path in ROUTES[feature])
        _save(client, **{feature.value: False})
        assert all(_disabled(client, method, path) for method, path in ROUTES[feature])
        others = [route for other in Feature if other != feature for route in ROUTES[other]]
        still_open = [route for route in others if not _disabled(client, *route)]
        closed_with_it = {Feature.BUDGET: len(ROUTES[Feature.INVOICES])}.get(feature, 0)
        assert len(still_open) == len(others) - closed_with_it
        api.login(None)
        assert all(_disabled(client, method, path) for method, path in ROUTES[feature])


async def test_a_vote_in_a_meeting_needs_both_features(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    path = f"/api/meetings/{uuid.uuid4()}/votes"
    with TestClient(api.app) as client:
        _save(client, meetings=False)
        assert _disabled(client, "POST", path)
        _save(client, voting=False)
        assert _disabled(client, "POST", path)
        assert not _disabled(client, "GET", "/api/meetings")


async def test_invoices_go_off_with_budget_and_return_to_their_state(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    with TestClient(api.app) as client:
        _save(client, budget=False)
        assert _disabled(client, "GET", "/api/invoices")
        assert client.get("/api/admin/features").json()["invoices"] is True
        public = client.get("/api/site-config").json()["features"]
        assert (public["budget"], public["invoices"]) == (False, False)
        _save(client)
        assert not _disabled(client, "GET", "/api/invoices")
        _save(client, invoices=False)
        assert _disabled(client, "GET", "/api/invoices")
        assert not _disabled(client, "GET", "/api/budgets")


async def test_a_switch_keeps_the_records_and_the_search_follows_it(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    with TestClient(api.app) as client:
        created = client.post(
            "/api/tickets", json={"kind": "bug", "title": "Schalterprobe", "body": "Text."}
        )
        assert created.status_code == 201, created.text

        def hits() -> list[str]:
            found = client.get("/api/search", params={"q": "Schalterprobe"}).json()
            assert found["failed"] == []
            return [hit["kind"] for hit in found["hits"]]

        def link_targets() -> list[str]:
            found = client.get("/api/todos/link-targets", params={"q": "Schalterprobe"})
            assert found.status_code == 200, found.text
            return [target["kind"] for target in found.json()]

        assert hits() == ["ticket"]
        assert link_targets() == ["ticket"]
        _save(client, tickets=False)
        assert hits() == []
        assert link_targets() == []
        _save(client)
        assert hits() == ["ticket"]
        listed = client.get("/api/tickets").json()
    assert [item["title"] for item in listed["items"]] == ["Schalterprobe"]


async def test_a_save_writes_a_version_and_an_audit_entry_that_a_revert_sets_back(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    await add_principal(maker, sub=REVERT_ONLY.sub, email=REVERT_ONLY.email)
    with TestClient(api.app) as client:
        _save(client)
        _save(client, todos=False)
        async with maker() as session:
            versions = (
                await session.scalars(
                    select(SiteConfigVersion).order_by(SiteConfigVersion.version)
                )
            ).all()
            entry = (
                await session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()))
            ).first()
        assert [(v.version, v.active, v.branding["features"]["todos"]) for v in versions] == [
            (1, False, True),
            (2, True, False),
        ]
        assert entry is not None
        assert entry.data["section"] == "features"
        assert entry.data["siteConfigVersion"] == 2

        api.login(REVERT_ONLY)
        refused = client.post(f"/api/admin/audit/{entry.id}/revert")
        assert refused.status_code == 403
        assert "admin.features" in refused.json()["detail"]

        api.login(ADMIN)
        assert client.post(f"/api/admin/audit/{entry.id}/revert").status_code == 200
        assert client.get("/api/admin/features").json() == ALL_ON
        assert not _disabled(client, "GET", "/api/todos/boards")


async def test_a_branding_save_and_its_revert_keep_the_switches(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    with TestClient(api.app) as client:
        _save(client, calendar=False)
        stale = {"appName": "Neu", "features": ALL_ON}
        assert client.put("/api/admin/site-config", json=stale).status_code == 200
        assert client.get("/api/admin/features").json()["calendar"] is False
        _save(client)
        assert client.put("/api/admin/site-config", json={"appName": "X"}).status_code == 200
        async with maker() as session:
            entry = (
                await session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()))
            ).first()
        assert entry is not None
        assert client.post(f"/api/admin/audit/{entry.id}/revert").status_code == 200
        assert client.get("/api/admin/features").json() == ALL_ON
        assert client.get("/api/admin/site-config").json()["branding"]["appName"] == "Neu"


def _vote_graph(gremium_id: uuid.UUID, *, to_meeting: bool) -> dict[str, object]:
    actions = [{"type": "addToNextSession"}] if to_meeting else []
    return {
        "graph": {
            "states": [
                {"key": "eingang", "label": {"de": "Eingang"}, "isInitial": True},
                {
                    "key": "abstimmung",
                    "label": {"de": "Abstimmung"},
                    "kind": "vote",
                    "config": {"gremiumId": str(gremium_id)},
                },
                {"key": "ja", "label": {"de": "Angenommen"}, "isApproved": True},
                {"key": "nein", "label": {"de": "Abgelehnt"}, "isDenied": True},
            ],
            "transitions": [
                {"from": "eingang", "to": "abstimmung", "actions": actions},
                {"from": "abstimmung", "to": "ja", "branch": "pass"},
                {"from": "abstimmung", "to": "nein", "branch": "fail"},
            ],
        }
    }


async def _gremium(maker: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with maker() as session:
        row = Gremium(name="Parlament", slug=f"p-{uuid.uuid4().hex[:8]}")
        session.add(row)
        await session.commit()
        return row.id


async def test_a_feature_in_use_by_the_flow_cannot_go_off(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    gremium_id = await _gremium(maker)
    with TestClient(api.app) as client:
        saved = client.post(
            "/api/admin/flow-versions/global", json=_vote_graph(gremium_id, to_meeting=True)
        )
        assert saved.status_code == 201, saved.text
        refused = client.put(
            "/api/admin/features", json={**ALL_ON, "voting": False, "meetings": False}
        )
        assert refused.status_code == 409
        body = refused.json()
        assert body["code"] == "feature_in_use"
        assert body["errors"] == [
            {"field": "voting", "msg": "state:Abstimmung"},
            {"field": "meetings", "msg": "transition:Eingang → Abstimmung"},
        ]
        assert client.get("/api/admin/features").json() == ALL_ON
        _save(client, todos=False, budget=False)


async def test_a_flow_cannot_start_to_use_a_feature_that_is_off(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    gremium_id = await _gremium(maker)
    with TestClient(api.app) as client:
        _save(client, voting=False)
        refused = client.post(
            "/api/admin/flow-versions/global", json=_vote_graph(gremium_id, to_meeting=False)
        )
        assert refused.status_code == 422
        assert refused.json()["errors"] == [{"field": "voting", "msg": "state:Abstimmung"}]
        _save(client)
        assert (
            client.post(
                "/api/admin/flow-versions/global",
                json=_vote_graph(gremium_id, to_meeting=False),
            ).status_code
            == 201
        )


async def test_a_revert_cannot_switch_off_a_feature_in_use(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    gremium_id = await _gremium(maker)
    with TestClient(api.app) as client:
        _save(client, voting=False)
        _save(client)
        async with maker() as session:
            entry = (
                await session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()))
            ).first()
        assert entry is not None
        graph = _vote_graph(gremium_id, to_meeting=False)
        assert client.post("/api/admin/flow-versions/global", json=graph).status_code == 201
        refused = client.post(f"/api/admin/audit/{entry.id}/revert")
        assert (refused.status_code, refused.json()["code"]) == (409, "feature_in_use")


async def test_budget_is_in_use_while_an_antragsart_has_a_budget(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    await _admin(api, maker)
    seed = await seed_guest_flow(maker)
    new_type = {"key": f"fin-{uuid.uuid4().hex[:6]}", "nameI18n": {"de": "Finanzantrag"}}
    with TestClient(api.app) as client:
        _save(client, budget=False)
        with_budget = client.post(
            "/api/admin/application-types", json={**new_type, "hasBudget": True}
        )
        assert with_budget.status_code == 422
        assert with_budget.json()["errors"] == [
            {"field": "hasBudget", "msg": "feature_disabled"}
        ]
        patched = client.patch(
            f"/api/admin/application-types/{seed.type_id}", json={"hasBudget": True}
        )
        assert patched.status_code == 422
        created = client.post("/api/admin/application-types", json=new_type)
        assert created.status_code == 201, created.text

        _save(client)
        type_id = created.json()["id"]
        assert (
            client.patch(
                f"/api/admin/application-types/{type_id}", json={"hasBudget": True}
            ).status_code
            == 200
        )
        refused = client.put("/api/admin/features", json={**ALL_ON, "budget": False})
        assert refused.status_code == 409
        assert refused.json()["errors"] == [{"field": "budget", "msg": "type:Finanzantrag"}]
        # A type that keeps its budget saves other fields while the feature is on.
        assert (
            client.patch(
                f"/api/admin/application-types/{type_id}", json={"hasBudget": True}
            ).status_code
            == 200
        )
    async with maker() as session:
        await session.execute(text("DELETE FROM application_type"))
        assert (await session.scalars(select(ApplicationType))).first() is None
        await session.commit()
