"""Integration: the team routes under ``/api/teams`` (real Postgres).

Covers the inherent team of a Gremium (specs 003060/003061), the sub-teams (003062),
the members of a free team (003063), the create right (003065), the manager of an
inherent team (003066) and the list and the detail (003074).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from tests.integration.modules.todos.conftest import (
    Api,
    add_gremium,
    add_member,
    add_person,
    team_of,
)

pytestmark = pytest.mark.integration


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


def _problem(resp: Any, status: int, code: str | None = None) -> None:
    assert resp.status_code == status, resp.text
    if code is not None:
        assert resp.json()["code"] == code


def _with(principal: Principal, *permissions: str) -> Principal:
    return Principal(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        permissions=set(permissions),
    )


async def test_the_inherent_team_follows_its_gremium(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """A Gremium has its team: members from the Gremium, managers by team.manage."""
    boss, boss_id = await add_person(maker, "Berta")
    member, member_id = await add_person(maker, "Moritz")
    outsider, _ = await add_person(maker, "Olga")
    gid, board_id = await add_gremium(maker, "AStA")
    tid = await team_of(maker, gid)
    await add_member(maker, gid, boss_id, "team.manage")
    await add_member(maker, gid, member_id)
    with TestClient(api.app) as client:
        api.login(None)
        _problem(client.get("/api/teams"), 401)
        api.login(member)
        rows = {t["id"]: t for t in _ok(client.get("/api/teams"))}
        team = rows[str(tid)]
        assert team["name"] == "AStA" and team["gremiumId"] == str(gid)
        assert team["boardId"] == str(board_id)
        assert team["isMember"] is True and team["canManage"] is False
        detail = _ok(client.get(f"/api/teams/{tid}"))
        names = [m["displayName"] for m in detail["members"]]
        assert names == ["Berta", "Moritz"]
        assert all(m["role"] is None for m in detail["members"])
        api.login(outsider)
        detail = _ok(client.get(f"/api/teams/{tid}"))
        assert detail["members"] == [] and detail["team"]["isMember"] is False
        api.login(boss)
        assert _ok(client.get(f"/api/teams/{tid}"))["team"]["canManage"] is True
        _problem(client.patch(f"/api/teams/{tid}", json={"name": "X"}), 409, "inherent_team")
        _problem(client.delete(f"/api/teams/{tid}"), 409, "inherent_team")
        _problem(
            client.put(f"/api/teams/{tid}/members/{member_id}", json={"role": "member"}),
            409,
            "inherent_team",
        )
        api.login(member)
        _problem(client.delete(f"/api/teams/{tid}"), 403, "team_manage_required")
        _problem(client.get(f"/api/teams/{gid}"), 404)


async def test_a_free_team_with_sub_teams_and_members(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Create, rename, move and delete a free team; the members and the last manager."""
    creator, creator_id = await add_person(maker, "Clara")
    plain, plain_id = await add_person(maker, "Paul")
    with TestClient(api.app) as client:
        api.login(plain)
        _problem(client.post("/api/teams", json={"name": "Ersti"}), 403, "team_create_required")
        api.login(_with(creator, "team.create"))
        top = _ok(client.post("/api/teams", json={"name": " Ersti "}), 201)
        top_id = top["team"]["id"]
        assert top["team"]["name"] == "Ersti" and top["team"]["canManage"] is True
        assert top["team"]["boardId"] is not None
        assert top["team"]["memberCount"] == 1
        assert top["members"] == [
            {"principalId": str(creator_id), "displayName": "Clara", "role": "manager"}
        ]
        sub = _ok(client.post("/api/teams", json={"name": "Party", "parentId": top_id}), 201)
        sub_id = sub["team"]["id"]
        assert sub["team"]["parentName"] == "Ersti"
        detail = _ok(client.get(f"/api/teams/{top_id}"))
        assert [t["id"] for t in detail["subTeams"]] == [sub_id]
        _problem(client.patch(f"/api/teams/{top_id}", json={"parentId": sub_id}), 422, "team_cycle")
        _problem(client.delete(f"/api/teams/{top_id}"), 409, "team_has_sub_teams")
        renamed = _ok(client.patch(f"/api/teams/{sub_id}", json={"name": "Feier"}))
        assert renamed["team"]["name"] == "Feier"
        moved = _ok(client.patch(f"/api/teams/{sub_id}", json={"parentId": None}))
        assert moved["team"]["parentId"] is None
        _problem(client.post("/api/teams", json={"name": "X", "parentId": str(creator_id)}), 404)

        added = _ok(client.put(f"/api/teams/{top_id}/members/{plain_id}", json={}))
        assert {m["displayName"]: m["role"] for m in added["members"]} == {
            "Clara": "manager",
            "Paul": "member",
        }
        _problem(
            client.put(f"/api/teams/{top_id}/members/{creator_id}", json={"role": "member"}),
            409,
            "last_manager",
        )
        _problem(client.delete(f"/api/teams/{top_id}/members/{creator_id}"), 409, "last_manager")
        _problem(
            client.put(f"/api/teams/{top_id}/members/{top_id}", json={}),
            422,
            "team_member_unknown",
        )
        _ok(client.put(f"/api/teams/{top_id}/members/{plain_id}", json={"role": "manager"}))
        api.login(plain)
        assert _ok(client.get(f"/api/teams/{top_id}"))["team"]["canManage"] is True
        left = _ok(client.delete(f"/api/teams/{top_id}/members/{creator_id}"))
        assert [m["displayName"] for m in left["members"]] == ["Paul"]
        _problem(client.delete(f"/api/teams/{top_id}/members/{creator_id}"), 404)
        _problem(client.delete(f"/api/teams/{sub_id}"), 403, "team_manage_required")
        api.login(creator)
        _ok(client.delete(f"/api/teams/{sub_id}"), 204)
        _problem(client.get(f"/api/teams/{sub_id}"), 404)


async def test_a_team_with_cards_stays(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    """A free team whose board holds cards is not deleted; an empty one goes."""
    creator, _ = await add_person(maker, "Clara")
    with TestClient(api.app) as client:
        api.login(_with(creator, "team.create"))
        team = _ok(client.post("/api/teams", json={"name": "Ersti"}), 201)["team"]
        _ok(
            client.post("/api/todos/cards", json={"boardId": team["boardId"], "title": "Karte"}),
            201,
        )
        _problem(client.delete(f"/api/teams/{team['id']}"), 409, "team_board_not_empty")
        empty = _ok(client.post("/api/teams", json={"name": "Leer"}), 201)["team"]
        _ok(client.delete(f"/api/teams/{empty['id']}"), 204)
    async with maker() as session:
        left = (
            await session.execute(
                text("SELECT count(*) FROM team WHERE id = :t"), {"t": empty["id"]}
            )
        ).scalar_one()
        assert left == 0
