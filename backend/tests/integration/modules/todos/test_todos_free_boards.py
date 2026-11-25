"""Integration: free boards and the member entries of a board (real Postgres).

Covers the create right (spec 001061), the roles of the entries (001062), the live
gremium entry (001063), the last manager (001064), the assignees (001065), the global
keys (001066), the archive and the delete (001068), the agenda (001069), the mail of a
person entry (001071), the transfer (001075), the entries of a gremium board (001077)
and the rights of a gremium board (001078).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.gremien.models import GremiumMembership
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


def _problem(resp: Any, status: int, code: str) -> None:
    assert resp.status_code == status, resp.text
    assert resp.json()["code"] == code


def _creator(principal: Principal) -> Principal:
    return Principal(
        sub=principal.sub,
        email=principal.email,
        display_name=principal.display_name,
        permissions={"todo.create_board"},
    )


async def test_only_the_permission_creates_a_free_board(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Create a free board with the permission; the creator manages it (spec 001061)."""
    plain, _ = await add_person(maker, "Paul")
    maker_p, maker_id = await add_person(maker, "Mara")
    other, other_id = await add_person(maker, "Otto")
    gid, _ = await add_gremium(maker, "AStA")
    tid = await team_of(maker, gid)
    with TestClient(api.app) as client:
        api.login(plain)
        _problem(client.post("/api/todos/boards", json={"name": "X"}), 403, "board_create_required")
        api.login(_creator(maker_p))
        board = _ok(
            client.post(
                "/api/todos/boards",
                json={
                    "name": "Ersti-Woche",
                    "entries": [
                        {"teamId": str(tid), "role": "read"},
                        {"principalId": str(other_id), "role": "edit"},
                    ],
                },
            ),
            201,
        )
        assert board["kind"] == "free" and board["canConfigure"] is True
        assert [c["isDone"] for c in board["columns"]] == [False, False, False, True]
        assert board["agendaGremiumIds"] == [str(gid)]
        entries = _ok(client.get(f"/api/todos/boards/{board['id']}/entries"))
        assert [(e["kind"], e["name"], e["role"]) for e in entries] == [
            ("team", "AStA", "read"),
            ("person", "Mara", "manage"),
            ("person", "Otto", "edit"),
        ]
        assert [(m.kind, m.recipients, m.role) for m in api.mails] == [
            ("board_added", (other_id,), "edit")
        ]
        twice = client.post(
            "/api/todos/boards",
            json={"name": "Y", "entries": [{"teamId": str(tid)}, {"teamId": str(tid)}]},
        )
        _problem(twice, 422, "entry_duplicate")
        both = client.post(
            "/api/todos/boards",
            json={"name": "Y", "entries": [{"teamId": str(tid), "principalId": str(maker_id)}]},
        )
        _problem(both, 422, "entry_target")
        api.login(other)
        summary = [b for b in _ok(client.get("/api/todos/boards")) if b["kind"] == "free"]
        assert [(b["name"], b["canWrite"], b["canConfigure"]) for b in summary] == [
            ("Ersti-Woche", True, False)
        ]


async def test_the_roles_of_the_entries_and_the_live_gremium(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Read with a gremium entry while a member, and lose it at once (specs 001062, 001063)."""
    owner, _ = await add_person(maker, "Mara")
    reader, reader_id = await add_person(maker, "Rita")
    gid, _ = await add_gremium(maker, "Fachschaft")
    tid = await team_of(maker, gid)
    await add_member(maker, gid, reader_id, "vote.cast")
    with TestClient(api.app) as client:
        api.login(_creator(owner))
        bid = _ok(
            client.post(
                "/api/todos/boards",
                json={"name": "Projekt", "entries": [{"teamId": str(tid), "role": "read"}]},
            ),
            201,
        )["id"]
        card = _ok(client.post("/api/todos/cards", json={"boardId": bid, "title": "A"}), 201)
        api.login(reader)
        assert _ok(client.get(f"/api/todos/boards/{bid}"))["canWrite"] is False
        _problem(
            client.post("/api/todos/cards", json={"boardId": bid, "title": "B"}),
            403,
            "todo_write_required",
        )
        _problem(
            client.patch(f"/api/todos/boards/{bid}", json={"name": "X"}),
            403,
            "todo_configure_required",
        )
        api.login(_creator(owner))
        bad = client.post(
            f"/api/todos/cards/{card['id']}/assignees", json={"principalId": str(reader_id)}
        )
        _problem(bad, 422, "assignee_not_allowed")
        async with maker() as session:
            await session.execute(
                delete(GremiumMembership).where(GremiumMembership.principal_id == reader_id)
            )
            await session.commit()
        api.login(reader)
        assert client.get(f"/api/todos/boards/{bid}").status_code == 404


async def test_the_last_manager_stays(api: Api, maker: async_sessionmaker[AsyncSession]) -> None:
    """Refuse to remove or lower the last manager of a free board (spec 001064)."""
    owner, _ = await add_person(maker, "Mara")
    _, helper_id = await add_person(maker, "Hans")
    with TestClient(api.app) as client:
        api.login(_creator(owner))
        bid = _ok(client.post("/api/todos/boards", json={"name": "P"}), 201)["id"]
        mine = _ok(client.get(f"/api/todos/boards/{bid}/entries"))[0]
        _problem(
            client.delete(f"/api/todos/boards/{bid}/entries/{mine['id']}"), 409, "last_manager"
        )
        _problem(
            client.patch(f"/api/todos/boards/{bid}/entries/{mine['id']}", json={"role": "edit"}),
            409,
            "last_manager",
        )
        added = _ok(
            client.post(
                f"/api/todos/boards/{bid}/entries",
                json={"principalId": str(helper_id), "role": "manage"},
            ),
            201,
        )
        _problem(
            client.post(f"/api/todos/boards/{bid}/entries", json={"principalId": str(helper_id)}),
            409,
            "entry_exists",
        )
        helper = next(e for e in added if e["name"] == "Hans")
        _ok(client.patch(f"/api/todos/boards/{bid}/entries/{helper['id']}", json={"role": "read"}))
        _problem(
            client.delete(f"/api/todos/boards/{bid}/entries/{mine['id']}"), 409, "last_manager"
        )
        _ok(
            client.patch(f"/api/todos/boards/{bid}/entries/{helper['id']}", json={"role": "manage"})
        )
        left = _ok(client.delete(f"/api/todos/boards/{bid}/entries/{mine['id']}"))
        assert [e["name"] for e in left] == ["Hans"]


async def test_archive_restore_and_delete(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Archive and restore as a manager; only an admin deletes (spec 001068)."""
    owner, _ = await add_person(maker, "Mara")
    admin, _ = await add_person(maker, "Admin")
    with TestClient(api.app) as client:
        api.login(_creator(owner))
        bid = _ok(client.post("/api/todos/boards", json={"name": "Alt"}), 201)["id"]
        _ok(client.post("/api/todos/cards", json={"boardId": bid, "title": "A"}), 201)
        _problem(client.delete(f"/api/todos/boards/{bid}"), 403, "board_delete_admin_only")
        assert _ok(client.post(f"/api/todos/boards/{bid}/archive"))["archived"] is True
        assert bid not in [b["id"] for b in _ok(client.get("/api/todos/boards"))]
        assert [b["id"] for b in _ok(client.get("/api/todos/boards?archived=true"))] == [bid]
        assert _ok(client.get(f"/api/todos/boards/{bid}"))["archived"] is True
        _problem(
            client.post("/api/todos/cards", json={"boardId": bid, "title": "B"}),
            409,
            "board_archived",
        )
        assert _ok(client.post(f"/api/todos/boards/{bid}/restore"))["archived"] is False
        assert bid in [b["id"] for b in _ok(client.get("/api/todos/boards"))]
        api.login(Principal(sub=admin.sub, roles=["admin"]))
        _problem(client.delete(f"/api/todos/boards/{bid}"), 409, "board_not_archived")
        _ok(client.post(f"/api/todos/boards/{bid}/archive"))
        assert client.delete(f"/api/todos/boards/{bid}").status_code == 204
        assert client.get(f"/api/todos/boards/{bid}").status_code == 404


async def test_a_global_key_reads_a_free_board(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Read a free board with ``todo.read_all`` as a non-member (spec 001066)."""
    owner, _ = await add_person(maker, "Mara")
    auditor, _ = await add_person(maker, "Ida")
    with TestClient(api.app) as client:
        api.login(_creator(owner))
        bid = _ok(client.post("/api/todos/boards", json={"name": "P"}), 201)["id"]
        api.login(Principal(sub=auditor.sub, permissions={"todo.read_all"}))
        board = _ok(client.get(f"/api/todos/boards/{bid}"))
        assert board["canWrite"] is False and board["canConfigure"] is False
        api.login(Principal(sub=auditor.sub, permissions={"todo.all"}))
        _ok(client.post("/api/todos/cards", json={"boardId": bid, "title": "A"}), 201)


async def test_a_team_board_takes_entries_and_every_member_edits(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Edit as a member, manage with team.manage, add a guest (specs 001077, 001078, 003066)."""
    gid, bid = await add_gremium(maker, "StuPa")
    member, member_id = await add_person(maker, "Mia")
    lead, lead_id = await add_person(maker, "Lena")
    guest, guest_id = await add_person(maker, "Gast")
    await add_member(maker, gid, member_id, "vote.cast")
    await add_member(maker, gid, lead_id, "todo.configure", "team.manage")
    with TestClient(api.app) as client:
        api.login(member)
        _ok(client.post("/api/todos/cards", json={"boardId": str(bid), "title": "A"}), 201)
        _problem(
            client.post(f"/api/todos/boards/{bid}/entries", json={"principalId": str(guest_id)}),
            403,
            "todo_configure_required",
        )
        api.login(lead)
        own = _ok(client.get(f"/api/todos/boards/{bid}/entries"))
        assert [(e["name"], e["fixed"], e["id"]) for e in own] == [("StuPa", True, None)]
        _problem(
            client.post(
                f"/api/todos/boards/{bid}/entries", json={"teamId": str(await team_of(maker, gid))}
            ),
            409,
            "own_team_entry",
        )
        _ok(
            client.post(
                f"/api/todos/boards/{bid}/entries",
                json={"principalId": str(guest_id), "role": "edit"},
            ),
            201,
        )
        api.login(guest)
        _ok(client.post("/api/todos/cards", json={"boardId": str(bid), "title": "B"}), 201)
        members = {m["displayName"] for m in _ok(client.get(f"/api/todos/boards/{bid}/members"))}
        assert members == {"Mia", "Lena", "Gast"}


async def test_a_card_of_a_free_board_goes_on_the_agenda_of_its_gremien(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Put a card on a meeting of an entry gremium; another gremium is refused (001069)."""
    from app.modules.meetings.models import Meeting

    on_board, _ = await add_gremium(maker, "AStA")
    elsewhere, _ = await add_gremium(maker, "Senat")
    admin, _ = await add_person(maker, "Admin")
    async with maker() as session:
        soon = date.today() + timedelta(days=3)
        good = Meeting(gremium_id=on_board, title="GV", date=soon, status="planned")
        bad = Meeting(gremium_id=elsewhere, title="Senat", date=soon, status="planned")
        session.add_all([good, bad])
        await session.commit()
    with TestClient(api.app) as client:
        api.login(Principal(sub=admin.sub, roles=["admin"]))
        bid = _ok(
            client.post(
                "/api/todos/boards",
                json={
                    "name": "P",
                    "entries": [{"teamId": str(await team_of(maker, on_board)), "role": "read"}],
                },
            ),
            201,
        )["id"]
        card = _ok(client.post("/api/todos/cards", json={"boardId": bid, "title": "TOP"}), 201)
        _problem(
            client.post(f"/api/meetings/{bad.id}/agenda", json={"todoId": card["id"]}),
            422,
            "todo_wrong_board",
        )
        items = _ok(client.post(f"/api/meetings/{good.id}/agenda", json={"todoId": card["id"]}))
        assert [i["todoId"] for i in items] == [card["id"]]


async def test_a_card_moves_between_a_free_board_and_a_gremium_board(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Transfer a card both ways between shared boards (spec 001075)."""
    gid, gboard = await add_gremium(maker, "StuPa")
    owner, owner_id = await add_person(maker, "Mara")
    await add_member(maker, gid, owner_id, "vote.cast")
    with TestClient(api.app) as client:
        api.login(_creator(owner))
        bid = _ok(client.post("/api/todos/boards", json={"name": "P"}), 201)["id"]
        card = _ok(client.post("/api/todos/cards", json={"boardId": bid, "title": "A"}), 201)
        there = _ok(
            client.post(f"/api/todos/cards/{card['id']}/transfer", json={"boardId": str(gboard)})
        )
        assert there["boardId"] == str(gboard)
        back = _ok(client.post(f"/api/todos/cards/{card['id']}/transfer", json={"boardId": bid}))
        assert back["boardId"] == bid


async def test_the_picker_finds_teams_and_persons(
    api: Api, maker: async_sessionmaker[AsyncSession]
) -> None:
    """Find teams by name and persons from two characters on (specs 001074, 003071)."""
    tag = f"Zq{uuid.uuid4().hex[:8]}"
    me, _ = await add_person(maker, "Mara")
    await add_person(maker, f"{tag} Astrid")
    gid, _ = await add_gremium(maker, f"{tag} AStA")
    await add_gremium(maker, "Fachschaft")
    with TestClient(api.app) as client:
        api.login(me)
        every = _ok(client.get("/api/todos/entry-options"))
        assert {g["name"] for g in every["teams"]} >= {f"{tag} AStA", "Fachschaft"}
        assert every["persons"] == []
        hits = _ok(client.get("/api/todos/entry-options", params={"q": tag.lower()}))
        assert [(g["gremiumId"], g["logoUrl"]) for g in hits["teams"]] == [(str(gid), None)]
        assert [p["name"] for p in hits["persons"]] == [f"{tag} Astrid"]
        assert "email" not in hits["persons"][0]
