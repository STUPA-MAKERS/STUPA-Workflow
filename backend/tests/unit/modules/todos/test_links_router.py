"""The links routes (``/api/links``, spec 001409) with a fake ``LinkService``."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.deps import get_current_principal
from app.main import create_app
from app.modules.auth.principal import Principal
from app.modules.todos.links_router import get_link_service
from app.modules.todos.schemas import (
    LinkRow,
    LinksOut,
    TodoLinkDetail,
    TodoLinkTarget,
    TodoLinkView,
)

USER = Principal(sub="me-sub", permissions={"todo.write"})
AID = uuid.uuid4()
BID = uuid.uuid4()
LID = uuid.uuid4()
NOW = datetime(2026, 11, 19, tzinfo=UTC)
ROW = LinkRow(id=LID, kind="invoice", target_id=BID, accessible=True, title="R-1", created_at=NOW)


class _Tx:
    """The commit of the route; ``clash`` lets it meet a parallel equal link."""

    def __init__(self) -> None:
        self.clash = False
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        if self.clash:
            raise IntegrityError("INSERT", {}, Exception("uq_link_ends"))
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeLinks:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.session = _Tx()
        self.paperless_down = False

    async def of(self, *args: Any) -> LinksOut:
        self.calls.append(("of", args, {}))
        return LinksOut(can_link=True, links=[ROW])

    async def add(self, *args: Any) -> None:
        self.calls.append(("add", args, {}))

    async def remove(self, *args: Any) -> None:
        self.calls.append(("remove", args, {}))

    async def view(self, *args: Any) -> TodoLinkView:
        self.calls.append(("view", args, {}))
        return TodoLinkView(kind="vote", title="Abstimmung", detail=TodoLinkDetail())

    async def targets(self, *args: Any, **kw: Any) -> list[TodoLinkTarget]:
        self.calls.append(("targets", args, kw))
        return [TodoLinkTarget(kind="ticket", target_id=BID, title="T")]


@pytest.fixture
def fake() -> Iterator[tuple[TestClient, _FakeLinks]]:
    app = create_app()
    links = _FakeLinks()

    def _session() -> Iterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_link_service] = lambda: links
    app.dependency_overrides[get_current_principal] = lambda: USER
    yield TestClient(app), links


def test_every_route_needs_a_session() -> None:
    app = create_app()
    app.dependency_overrides[get_current_principal] = lambda: None
    assert TestClient(app).get(f"/api/links?kind=invoice&id={AID}").status_code == 401


def test_list_add_remove_and_view(fake: tuple[TestClient, _FakeLinks]) -> None:
    """§F/collaboration/links/001409: the routes call the service with the two ends."""
    client, links = fake
    got = client.get(f"/api/links?kind=application&id={AID}")
    assert got.json()["canLink"] is True
    assert got.json()["links"][0]["targetId"] == str(BID)
    assert links.calls[-1] == ("of", ("application", AID, USER), {})
    body = {"a": {"kind": "application", "id": str(AID)}, "b": {"kind": "invoice", "id": str(BID)}}
    added = client.post("/api/links", json=body)
    assert added.status_code == 201 and added.json()["links"][0]["id"] == str(LID)
    assert links.calls[-2][1][:2] == (("application", AID), ("invoice", BID))
    assert links.calls[-1] == ("of", ("application", AID, USER), {})
    bad = {**body, "b": {"kind": "cost_centre", "id": str(BID)}}
    assert client.post("/api/links", json=bad).status_code == 422
    assert client.delete(f"/api/links/{LID}").status_code == 204
    assert links.calls[-1] == ("remove", (LID, USER), {})
    assert links.session.commits == 2
    assert client.get(f"/api/links/{LID}/view").json()["title"] == "Abstimmung"
    assert client.get(f"/api/links?kind=nope&id={AID}").status_code == 422


def test_a_parallel_equal_link_is_link_exists(fake: tuple[TestClient, _FakeLinks]) -> None:
    """§F/collaboration/links/001400: at most one link per pair, also under a race."""
    client, links = fake
    links.session.clash = True
    body = {"a": {"kind": "application", "id": str(AID)}, "b": {"kind": "invoice", "id": str(BID)}}
    answer = client.post("/api/links", json=body)
    assert answer.status_code == 409 and answer.json()["code"] == "link_exists"
    assert links.session.rollbacks == 1


def test_targets_pass_the_excluded_element(fake: tuple[TestClient, _FakeLinks]) -> None:
    """§F/collaboration/links/001408: the search leaves out the element and its links."""
    client, links = fake
    hits = client.get(f"/api/links/targets?q=ab&kind=ticket&excludeKind=invoice&excludeId={BID}")
    assert hits.json()[0]["targetId"] == str(BID)
    assert links.calls[-1] == ("targets", ("ab", "ticket", USER), {"exclude": ("invoice", BID)})
    client.get("/api/links/targets?kind=todo")
    assert links.calls[-1] == ("targets", ("", "todo", USER), {"exclude": None})


def test_targets_without_the_scope_are_empty(fake: tuple[TestClient, _FakeLinks]) -> None:
    client, links = fake
    client.app.dependency_overrides[get_current_principal] = lambda: Principal(  # type: ignore[attr-defined]
        sub="t", scope_permissions=frozenset({"vote.cast"})
    )
    assert client.get("/api/links/targets?q=ab").json() == []
    assert links.calls == []
