"""Links to Paperless documents on a real Postgres, against a fake Paperless instance.

§ F/integrations/paperless/002763 a Paperless document is a link end, stored once, and
two documents do not link. § 002764 the link needs `paperless.use`. § 002765 the link
keeps the title of the moment of the link. § 002766 the link search asks Paperless and
keeps the other kinds in an outage. § 002767 the switch of the links. § 002768 the
graph shows the document only with the permission.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.principal import Principal
from app.modules.paperless import links as paperless_links
from app.modules.paperless.connection import ConnectionService
from app.modules.paperless.links import document_number, document_ref
from app.modules.paperless.models import PaperlessDocument
from app.modules.paperless.schemas import ConnectionIn
from app.settings import Settings
from tests._support.paperless_fakes import BASE_URL, HOST, TOKEN, FakePaperless
from tests.integration.modules.todos.conftest import Api, add_gremium, add_member, add_person

pytestmark = pytest.mark.integration

Maker = async_sessionmaker[AsyncSession]


def _ok(resp: Any, status: int = 200) -> Any:
    assert resp.status_code == status, resp.text
    return resp.json() if resp.content else None


@pytest.fixture
def fake(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FakePaperless:
    """A fake Paperless with two documents, which the links part speaks to."""
    instance = FakePaperless()
    for number, title in ((41, "Angebot Beamer"), (42, "Bescheid Kulturamt")):
        instance.documents[number] = {
            "id": number,
            "title": title,
            "created": "2026-10-30",
            "document_type": None,
            "tags": [],
            "custom_fields": [],
        }
    allowed = settings.model_copy(update={"paperless_host_allowlist": [HOST]})
    monkeypatch.setattr(
        paperless_links,
        "connection_of",
        lambda session: ConnectionService(session, allowed, instance.client),
    )
    return instance


async def _switch(maker: Maker, settings: Settings, *, on: bool) -> None:
    allowed = settings.model_copy(update={"paperless_host_allowlist": [HOST]})
    async with maker() as session:
        await ConnectionService(session, allowed).save(
            ConnectionIn.model_validate({"baseUrl": BASE_URL, "token": TOKEN, "linkEnabled": on}),
            actor="admin-sub",
            now=datetime.now(UTC),
        )
        await session.commit()


async def _people(maker: Maker) -> tuple[uuid.UUID, Principal, Principal]:
    """A board with a writer who uses Paperless and a writer who does not."""
    gid, board = await add_gremium(maker, "Kultur")
    user, uid = await add_person(maker, "Ada")
    other, oid = await add_person(maker, "Bea")
    await add_member(maker, gid, uid, "todo.write")
    await add_member(maker, gid, oid, "todo.write")
    return (
        board,
        replace(user, permissions={"paperless.use", "graph.view"}),
        replace(other, permissions={"graph.view"}),
    )


def _card(client: TestClient, board: uuid.UUID, title: str) -> str:
    made = _ok(client.post("/api/todos/cards", json={"boardId": str(board), "title": title}), 201)
    return made["id"]


def _link(client: TestClient, card: str, document: int) -> Any:
    return client.post(
        "/api/links",
        json={
            "a": {"kind": "todo", "id": card},
            "b": {"kind": "paperless", "id": str(document_ref(document))},
        },
    )


def test_the_row_id_names_the_document_number() -> None:
    """§ 002763: the id of the row comes from the number and gives it back."""
    assert document_number(document_ref(41)) == 41
    assert document_ref(41) != document_ref(42)
    assert document_number(uuid.uuid4()) is None
    assert document_number(uuid.UUID(int=41)) is None


async def test_a_card_links_a_document_and_the_document_is_stored_once(
    api: Api, maker: Maker, settings: Settings, fake: FakePaperless
) -> None:
    """§ 002763, 002765: the link, the stored values and the refusals."""
    await _switch(maker, settings, on=True)
    board, user, _other = await _people(maker)
    api.login(user)
    with TestClient(api.app) as client:
        first, second = _card(client, board, "Beamer kaufen"), _card(client, board, "Rechnung")
        newest = _ok(client.get("/api/links/targets", params={"kind": "paperless"}))
        assert [(h["kind"], h["title"]) for h in newest] == [
            ("paperless", "Bescheid Kulturamt"),
            ("paperless", "Angebot Beamer"),
        ]
        found = _ok(client.get("/api/links/targets", params={"kind": "paperless", "q": "beamer"}))
        assert [h["targetId"] for h in found] == [str(document_ref(41))]
        assert found[0]["detail"]["date"] == "2026-10-30"

        (row,) = _ok(_link(client, first, 41), 201)["links"]
        assert (row["kind"], row["title"], row["accessible"]) == (
            "paperless",
            "Angebot Beamer",
            True,
        )
        assert row["url"] == f"{BASE_URL}/documents/41/details"
        assert row["removable"] is True

        fake.documents[41]["title"] = "Angebot Beamer (neu)"
        _ok(_link(client, second, 41), 201)
        (again,) = _ok(client.get("/api/links", params={"kind": "todo", "id": first}))["links"]
        assert again["title"] == "Angebot Beamer (neu)"

        assert _link(client, first, 41).status_code == 409
        missing = _link(client, first, 999)
        assert (missing.status_code, missing.json()["code"]) == (422, "link_target_not_found")
        pair = client.post(
            "/api/links",
            json={
                "a": {"kind": "paperless", "id": str(document_ref(41))},
                "b": {"kind": "paperless", "id": str(document_ref(42))},
            },
        )
        assert (pair.status_code, pair.json()["code"]) == (422, "link_paperless_pair")
        left = _ok(
            client.get(
                "/api/links/targets",
                params={"kind": "paperless", "excludeKind": "todo", "excludeId": first},
            )
        )
        assert [h["title"] for h in left] == ["Bescheid Kulturamt"]
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(PaperlessDocument)) == 1


async def test_a_link_needs_the_permission(
    api: Api, maker: Maker, settings: Settings, fake: FakePaperless
) -> None:
    """§ 002764: without `paperless.use` no link, no hit and no title."""
    await _switch(maker, settings, on=True)
    board, user, other = await _people(maker)
    api.login(user)
    with TestClient(api.app) as client:
        card = _card(client, board, "Beamer kaufen")
        (row,) = _ok(_link(client, card, 41), 201)["links"]
    api.login(other)
    with TestClient(api.app) as client:
        (hidden,) = _ok(client.get("/api/links", params={"kind": "todo", "id": card}))["links"]
        assert (hidden["kind"], hidden["accessible"]) == ("paperless", False)
        assert (hidden["title"], hidden["url"], hidden["detail"]) == (None, None, None)
        assert hidden["removable"] is False
        refused = _link(client, card, 42)
        assert (refused.status_code, refused.json()["code"]) == (403, "link_forbidden")
        gone = client.delete(f"/api/links/{row['id']}")
        assert (gone.status_code, gone.json()["code"]) == (403, "link_forbidden")
        assert _ok(client.get("/api/links/targets", params={"kind": "paperless"})) == []
        both = _ok(client.get("/api/links/targets", params={"q": "Beamer"}))
        assert [h["kind"] for h in both] == ["todo"]
        made = client.post(
            "/api/todos/cards",
            json={
                "boardId": str(board),
                "title": "Mit Dokument",
                "links": [{"kind": "paperless", "targetId": str(document_ref(42))}],
            },
        )
        assert (made.status_code, made.json()["code"]) == (422, "link_target_not_found")
    assert [r for r in fake.requests if "id__in=42" in str(r.url)] == []


async def test_an_outage_keeps_the_stored_title_and_the_other_hits(
    api: Api, maker: Maker, settings: Settings, fake: FakePaperless
) -> None:
    """§ 002765, 002766: no read calls Paperless, and the search tells the outage."""
    await _switch(maker, settings, on=True)
    board, user, _other = await _people(maker)
    api.login(user)
    with TestClient(api.app) as client:
        card = _card(client, board, "Beamer kaufen")
        _ok(_link(client, card, 41), 201)
        every = client.get("/api/links/targets", params={"q": "Beamer"})
        assert [h["kind"] for h in _ok(every)] == ["todo", "paperless"]
        assert "x-paperless-unavailable" not in every.headers

        fake.down = True
        calls = len(fake.requests)
        (row,) = _ok(client.get("/api/links", params={"kind": "todo", "id": card}))["links"]
        assert row["title"] == "Angebot Beamer"
        assert len(fake.requests) == calls

        every = client.get("/api/links/targets", params={"q": "Beamer"})
        assert [h["kind"] for h in _ok(every)] == ["todo"]
        assert every.headers["x-paperless-unavailable"] == "1"
        only = client.get("/api/links/targets", params={"kind": "paperless", "q": "Beamer"})
        assert (only.status_code, only.json()["code"]) == (503, "paperless_unavailable")
        late = _link(client, card, 42)
        assert (late.status_code, late.json()["code"]) == (503, "paperless_unavailable")
        assert TOKEN not in only.text + late.text


async def test_the_switch_hides_the_links_and_keeps_them(
    api: Api, maker: Maker, settings: Settings, fake: FakePaperless
) -> None:
    """§ 002767: off shows no Paperless link and offers no kind; on shows it again."""
    await _switch(maker, settings, on=True)
    board, user, _other = await _people(maker)
    api.login(user)
    with TestClient(api.app) as client:
        card = _card(client, board, "Beamer kaufen")
        _ok(_link(client, card, 41), 201)

        await _switch(maker, settings, on=False)
        assert _ok(client.get("/api/links", params={"kind": "todo", "id": card}))["links"] == []
        assert _ok(client.get("/api/links/targets", params={"kind": "paperless"})) == []
        off = _link(client, card, 42)
        assert (off.status_code, off.json()["code"]) == (422, "link_target_not_found")
        nodes = _ok(client.get("/api/graph", params={"kinds": ["todo"], "depth": 1}))["nodes"]
        assert [n["kind"] for n in nodes] == []

        await _switch(maker, settings, on=True)
        (row,) = _ok(client.get("/api/links", params={"kind": "todo", "id": card}))["links"]
        assert row["title"] == "Angebot Beamer"


async def test_the_graph_shows_the_document_only_with_the_permission(
    api: Api, maker: Maker, settings: Settings, fake: FakePaperless
) -> None:
    """§ 002768: the node and its line show with `paperless.use`, else neither."""
    await _switch(maker, settings, on=True)
    board, user, other = await _people(maker)
    api.login(user)
    with TestClient(api.app) as client:
        card = _card(client, board, "Beamer kaufen")
        _ok(_link(client, card, 41), 201)
        page = _ok(client.get("/api/graph", params={"relations": "links"}))
        kinds = {n["kind"]: n for n in page["nodes"]}
        assert kinds["paperless"]["title"] == "Angebot Beamer"
        assert kinds["paperless"]["date"] == "2026-10-30"
        assert kinds["paperless"]["url"] == f"{BASE_URL}/documents/41/details"
        assert len(page["edges"]) == 1
        only = _ok(client.get("/api/graph", params={"kinds": ["paperless"], "depth": 0}))
        assert [n["kind"] for n in only["nodes"]] == []
    api.login(other)
    with TestClient(api.app) as client:
        page = _ok(client.get("/api/graph", params={"relations": "links", "noAccess": True}))
        assert (page["nodes"], page["edges"]) == ([], [])
