"""Integration: a card links a Termin (§F/collaboration/todos/000735).

The link picker finds only the Termine that the person reads. A person who reads the
card but not the Termin reads its title, its start, its end and its place, and never
its description, its invitations or its answers. The Termin knows the cards that link
it, and a deleted Termin takes its links with it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.modules.calendar.conftest import CalendarApi
from tests.integration.modules.todos.conftest import add_gremium, add_member, add_person

pytestmark = pytest.mark.integration

TERMIN = {
    "title": "Klausurtagung",
    "startsOn": "2031-05-05",
    "endsOn": "2031-05-06",
    "startTime": "14:00:00",
    "endTime": "16:00:00",
    "place": "Raum 1",
    "description": "Vertraulich",
}


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _targets(client: TestClient, q: str) -> list[dict[str, Any]]:
    return _ok(client.get("/api/todos/link-targets", params={"q": q, "kind": "appointment"}))


async def test_card_links_a_termin(
    api: CalendarApi, maker: async_sessionmaker[AsyncSession]
) -> None:
    """The picker, the link check, the granted read, the back-reference and the delete."""
    gid, board = await add_gremium(maker, "Kultur")
    anna, anna_id = await add_person(maker, "Anna")
    bert, bert_id = await add_person(maker, "Bert")
    await add_member(maker, gid, anna_id, "todo.write")
    await add_member(maker, gid, bert_id, "todo.write")

    api.login(anna)
    with TestClient(api.app) as client:
        termin = _ok(
            client.post(
                "/api/calendar/appointments", json={**TERMIN, "principalIds": [str(anna_id)]}
            ),
            201,
        )
        found = _targets(client, "klausur")
        assert [(t["kind"], t["targetId"], t["title"]) for t in found] == [
            ("appointment", termin["id"], "Klausurtagung")
        ]
        assert found[0]["detail"]["date"] == "2031-05-05"
        card = _ok(
            client.post(
                "/api/todos/cards",
                json={
                    "boardId": str(board),
                    "title": "Raum buchen",
                    "links": [{"kind": "appointment", "targetId": termin["id"]}],
                },
            ),
            201,
        )
        own = card["links"][0]
        assert own["accessible"] and not own["granted"]
        assert own["url"] == f"/calendar?appointment={termin['id']}"
        back = _ok(
            client.get(
                "/api/todos/linked", params={"kind": "appointment", "targetId": termin["id"]}
            )
        )
        assert [c["title"] for c in back] == ["Raum buchen"]

    api.login(bert)
    with TestClient(api.app) as client:
        assert _targets(client, "klausur") == []
        _ok(client.get(f"/api/calendar/appointments/{termin['id']}"), 404)
        link = _ok(client.get(f"/api/todos/cards/{card['id']}"))["links"][0]
        assert link["accessible"] and link["granted"] and link["url"] is None
        assert link["title"] == "Klausurtagung"
        assert link["detail"] == {
            **{key: None for key in link["detail"]},
            "date": "2031-05-05",
            "endDate": "2031-05-06",
            "startTime": "14:00:00",
            "endTime": "16:00:00",
            "place": "Raum 1",
        }
        view = _ok(client.get(f"/api/todos/cards/{card['id']}/links/{link['id']}/view"))
        assert {fact["key"]: fact["value"] for fact in view["facts"]} == {
            "date": "2031-05-05",
            "endDate": "2031-05-06",
            "startTime": "14:00",
            "endTime": "16:00",
            "place": "Raum 1",
        }
        assert view["rows"] == [] and "Vertraulich" not in str(view)
        other = _ok(
            client.post("/api/todos/cards", json={"boardId": str(board), "title": "Plakate"}), 201
        )
        refused = client.post(
            f"/api/todos/cards/{other['id']}/links",
            json={"kind": "appointment", "targetId": termin["id"]},
        )
        assert _ok(refused, 422)["code"] == "link_target_not_found"

    api.login(anna)
    with TestClient(api.app) as client:
        _ok(client.delete(f"/api/calendar/appointments/{termin['id']}"), 204)
        assert _ok(client.get(f"/api/todos/cards/{card['id']}"))["links"] == []
