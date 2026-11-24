"""Integration tests of the Bereiche of the tickets (real Postgres).

They cover the admin routes, the work right of a Gremium role and the move of a ticket
(specs 002701 to 002707, 002715, 002719).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium, GremiumMembership, GremiumRole
from app.modules.tickets.access import works_on_tickets
from app.modules.tickets.models import PLATFORM_AREA_ID, Ticket, TicketArea
from tests.integration.modules.tickets.conftest import ADMIN, MANAGER, Api, add_principal

pytestmark = pytest.mark.integration

_REPORT = {"kind": "bug", "title": "Drucker", "body": "Der Drucker druckt nicht."}


def _clear_areas(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM ticket"))
        conn.execute(text("DELETE FROM ticket_area WHERE NOT platform"))
        conn.execute(text("DELETE FROM gremium WHERE slug LIKE 'tickets-area-%'"))
        conn.execute(text("UPDATE ticket_area SET notify_new = true WHERE platform"))


@pytest.fixture
def areas(clean: Engine) -> Iterator[Engine]:
    """Remove the Bereiche and the Gremien of a test; ``Plattform`` stays."""
    _clear_areas(clean)
    try:
        yield clean
    finally:
        _clear_areas(clean)


async def _gremium_worker(
    maker: async_sessionmaker[AsyncSession], tag: str, *perms: str
) -> tuple[uuid.UUID, Principal, uuid.UUID]:
    """Create a Gremium and a member whose role grants ``perms``.

    Returns:
        The Gremium id, the request principal of the member and its account id.
    """
    async with maker() as session:
        gremium = Gremium(name=f"Gremium {tag}", slug=f"tickets-area-{tag}")
        row = PrincipalRow(sub=f"worker-{tag}", display_name=f"Worker {tag}", email=f"{tag}@x.org")
        session.add_all([gremium, row])
        await session.flush()
        role = GremiumRole(
            gremium_id=gremium.id, key=f"desk-{tag}", name_i18n={"de": "Desk"}, permissions=[*perms]
        )
        session.add(role)
        await session.flush()
        session.add(
            GremiumMembership(principal_id=row.id, gremium_id=gremium.id, gremium_role_id=role.id)
        )
        await session.commit()
        return gremium.id, Principal(sub=row.sub, email=row.email), row.id


async def test_the_migration_seeds_plattform_and_every_report_lands_there(
    api: Api, maker: async_sessionmaker[AsyncSession], areas: Engine
) -> None:
    await add_principal(maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia")
    api.login(MANAGER)
    with TestClient(api.app) as client:
        assert client.post("/api/tickets", json=_REPORT).status_code == 201
        listed = client.get("/api/tickets/areas").json()
        assert [(a["id"], a["name"], a["platform"], a["mine"]) for a in listed] == [
            (str(PLATFORM_AREA_ID), "Plattform", True, True)
        ]
        (item,) = client.get("/api/tickets").json()["items"]
        assert (item["areaId"], item["kind"], item["categoryId"]) == (
            str(PLATFORM_AREA_ID),
            "bug",
            None,
        )
    async with maker() as session:
        assert await works_on_tickets(session, MANAGER) is True


async def test_an_admin_keeps_the_bereiche(
    api: Api, maker: async_sessionmaker[AsyncSession], areas: Engine
) -> None:
    gremium_id, _worker, _account = await _gremium_worker(maker, "adm", "ticket.work")
    await add_principal(maker, sub=ADMIN.sub, email=ADMIN.email, name="Admin", role="admin")
    api.login(ADMIN)
    with TestClient(api.app) as client:
        body = {
            "name": "Finanzen",
            "gremiumId": str(gremium_id),
            "categories": [{"name": "Rechnung"}, {"name": "Erstattung"}],
        }
        created = client.post("/api/admin/ticket-areas", json=body)
        assert created.status_code == 201, created.text
        area = created.json()
        assert [c["name"] for c in area["categories"]] == ["Rechnung", "Erstattung"]
        again = client.post("/api/admin/ticket-areas", json={"name": "finanzen"})
        assert again.status_code == 409
        assert again.json()["code"] == "ticket_area_name_taken"
        first, second = area["categories"]
        swapped = client.patch(
            f"/api/admin/ticket-areas/{area['id']}",
            json={
                "name": "Kasse",
                "categories": [
                    {"id": second["id"], "name": "Rechnung"},
                    {"id": first["id"], "name": "Erstattung"},
                    {"name": "Sonstiges"},
                ],
            },
        )
        assert swapped.status_code == 200, swapped.text
        assert [
            (c["id"] in (first["id"], second["id"]), c["name"])
            for c in swapped.json()["categories"]
        ] == [(True, "Rechnung"), (True, "Erstattung"), (False, "Sonstiges")]
        assert swapped.json()["gremiumId"] == str(gremium_id)
        platform = f"/api/admin/ticket-areas/{PLATFORM_AREA_ID}"
        fixed = client.patch(platform, json={"categories": [{"name": "Fehlerchen"}]})
        assert fixed.status_code == 409
        assert fixed.json()["code"] == "ticket_area_platform_fixed"
        assert client.patch(platform, json={"notifyNew": False}).json()["notifyNew"] is False
        assert client.delete(platform).status_code == 409
        names = [a["name"] for a in client.get("/api/admin/ticket-areas").json()]
        assert names == ["Plattform", "Kasse"]
        assert client.post("/api/tickets", json=_REPORT).status_code == 201
        (ticket,) = client.get("/api/tickets").json()["items"]
        moved = client.patch(f"/api/tickets/{ticket['id']}", json={"areaId": area["id"]})
        assert moved.status_code == 200, moved.text
        held = client.delete(f"/api/admin/ticket-areas/{area['id']}")
        assert held.status_code == 409
        assert held.json()["code"] == "ticket_area_has_tickets"
        back = client.patch(f"/api/tickets/{ticket['id']}", json={"areaId": str(PLATFORM_AREA_ID)})
        assert back.status_code == 200
        assert client.delete(f"/api/admin/ticket-areas/{area['id']}").status_code == 204
    async with maker() as session:
        assert (await session.scalars(select(TicketArea.name))).all() == ["Plattform"]


async def test_a_gremium_role_works_only_in_the_bereiche_of_its_gremium(
    api: Api, maker: async_sessionmaker[AsyncSession], areas: Engine
) -> None:
    """Specs 002703, 002704, 002707 and 002715."""
    gremium_a, worker_a, account_a = await _gremium_worker(maker, "a", "ticket.work")
    gremium_b, worker_b, account_b = await _gremium_worker(maker, "b", "ticket.work")
    _gremium_c, plain, _account_c = await _gremium_worker(maker, "c", "todo.write")
    manager_id = await add_principal(
        maker, sub=MANAGER.sub, email=MANAGER.email, name="Mia", role="admin"
    )
    async with maker() as session:
        assert await works_on_tickets(session, plain) is False
        assert await works_on_tickets(session, worker_a) is False
        area_a = TicketArea(name="Bereich A", gremium_id=gremium_a)
        area_b = TicketArea(name="Bereich B", gremium_id=gremium_b)
        session.add_all([area_a, area_b])
        await session.flush()
        assert await works_on_tickets(session, worker_a) is True
        in_a = Ticket(
            number="AAAAAAA2", area_id=area_a.id, title="A", body="a", reporter_email="r@x.org"
        )
        in_platform = Ticket(
            number="AAAAAAA3", kind="bug", title="P", body="p", reporter_email="r@x.org"
        )
        session.add_all([in_a, in_platform])
        await session.commit()
        a_id, b_id, ticket_a, ticket_p = area_a.id, area_b.id, in_a.id, in_platform.id
    with TestClient(api.app) as client:
        api.login(plain)
        assert client.get("/api/tickets").status_code == 403
        api.login(worker_b)
        assert client.get("/api/tickets").json()["items"] == []
        assert client.get(f"/api/tickets/{ticket_a}").status_code == 404
        assert client.patch(f"/api/tickets/{ticket_a}", json={"status": "done"}).status_code == 404
        assert client.get("/api/tickets/assignees", params={"area": str(a_id)}).status_code == 404
        api.login(worker_a)
        assert [t["id"] for t in client.get("/api/tickets").json()["items"]] == [str(ticket_a)]
        assert client.get("/api/tickets/counts").json()["new"] == 1
        assert client.get(f"/api/tickets/{ticket_p}").status_code == 404
        mine = {a["name"]: a["mine"] for a in client.get("/api/tickets/areas").json()}
        assert mine == {"Plattform": False, "Bereich A": True, "Bereich B": False}
        people = client.get("/api/tickets/assignees", params={"area": str(a_id)}).json()
        assert {p["principalId"] for p in people} == {str(account_a), str(manager_id)}
        foreign = client.patch(f"/api/tickets/{ticket_a}", json={"assigneeId": str(account_b)})
        assert foreign.status_code == 422
        assert foreign.json()["code"] == "assignee_not_allowed"
        own = client.patch(f"/api/tickets/{ticket_a}", json={"assigneeId": str(account_a)})
        assert own.status_code == 200, own.text
        note = client.post(
            f"/api/tickets/{ticket_a}/notes", json={"body": "x", "mentions": [str(account_b)]}
        )
        assert note.status_code == 422
        moved = client.patch(f"/api/tickets/{ticket_a}", json={"areaId": str(b_id)})
        assert moved.status_code == 200, moved.text
        assert (moved.json()["areaId"], moved.json()["assignee"]) == (str(b_id), None)
        assert moved.json()["events"][-1]["kind"] == "area"
        assert moved.json()["events"][-1]["payload"]["toName"] == "Bereich B"
        assert client.get(f"/api/tickets/{ticket_a}").status_code == 404
        api.login(worker_b)
        assert client.get(f"/api/tickets/{ticket_a}").status_code == 200
        api.login(MANAGER)
        both = client.get("/api/tickets").json()
        assert both["total"] == 2
        only_b = client.get("/api/tickets", params={"area": str(b_id)}).json()["items"]
        assert [t["id"] for t in only_b] == [str(ticket_a)]
