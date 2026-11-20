"""Router tests of the graph: the permission, the query and the shape (specs 001421, 001431)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.graph.build import Filters
from app.modules.graph.schemas import GraphEdge, GraphNode, GraphPage, GraphRef

A = uuid.UUID(int=1)
B = uuid.UUID(int=2)


class _FakeService:
    seen: tuple[Principal, Filters, str | None] | None = None

    def __init__(self, _session: object) -> None: ...

    async def page(
        self, principal: Principal, filters: Filters, cursor: str | None = None
    ) -> GraphPage:
        type(self).seen = (principal, filters, cursor)
        return GraphPage(
            nodes=(
                GraphNode(
                    kind="application",
                    id=A,
                    accessible=True,
                    title="Antrag",
                    date=date(2026, 5, 1),
                    url=f"/applications/{A}",
                ),
                GraphNode(kind="invoice", id=B, accessible=False),
            ),
            edges=(
                GraphEdge(
                    a=GraphRef(kind="application", id=A),
                    b=GraphRef(kind="invoice", id=B),
                    source="link",
                ),
            ),
            nextCursor="60",
        )


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    application = create_app()

    def _session() -> Iterator[AsyncMock]:
        yield AsyncMock()

    application.dependency_overrides[get_session] = _session
    _FakeService.seen = None
    monkeypatch.setattr("app.modules.graph.router.GraphService", _FakeService)
    return application


def _login(app: FastAPI, *permissions: str) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="me", permissions=set(permissions)
    )


def test_the_graph_needs_a_session_and_its_permission(app: FastAPI) -> None:
    """Spec 001421: 401 without a session, 403 without ``graph.view``."""
    app.dependency_overrides[get_current_principal] = lambda: None
    with TestClient(app) as client:
        assert client.get("/api/graph").status_code == 401
    _login(app, "application.read", "budget.view")
    with TestClient(app) as client:
        resp = client.get("/api/graph")
        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("application/problem+json")
    assert _FakeService.seen is None


def test_the_graph_answers_a_page_in_camel_case(app: FastAPI) -> None:
    """Spec 001431: nodes, edges and the cursor."""
    _login(app, "graph.view")
    with TestClient(app) as client:
        resp = client.get("/api/graph")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nextCursor"] == "60"
    assert body["nodes"][0] == {
        "kind": "application",
        "id": str(A),
        "accessible": True,
        "title": "Antrag",
        "date": "2026-05-01",
        "url": f"/applications/{A}",
        "granted": False,
        "detail": None,
    }
    assert body["nodes"][1]["title"] is None
    assert body["edges"] == [
        {
            "a": {"kind": "application", "id": str(A)},
            "b": {"kind": "invoice", "id": str(B)},
            "source": "link",
        }
    ]
    assert _FakeService.seen is not None
    assert _FakeService.seen[1] == Filters(depth=2)
    assert _FakeService.seen[2] is None


def test_the_query_becomes_the_filters(app: FastAPI) -> None:
    """Spec 001431: every filter of the page is a query parameter."""
    _login(app, "graph.view")
    with TestClient(app) as client:
        resp = client.get(
            "/api/graph",
            params={
                "kinds": ["meeting", "todo"],
                "from": "2026-01-01",
                "to": "2026-12-31",
                "relations": "links",
                "q": "party",
                "depth": "4",
                "single": "true",
                "noAccess": "true",
                "cursor": "60",
            },
        )
    assert resp.status_code == 200
    assert _FakeService.seen is not None
    assert _FakeService.seen[1] == Filters(
        kinds=frozenset({"meeting", "todo"}),
        start=date(2026, 1, 1),
        end=date(2026, 12, 31),
        relations="links",
        q="party",
        single=True,
        no_access=True,
        depth=4,
    )
    assert _FakeService.seen[2] == "60"


@pytest.mark.parametrize(
    "params",
    [
        {"kinds": "wiki"},
        {"relations": "none"},
        {"from": "gestern"},
        {"depth": "-1"},
        {"depth": "6"},
    ],
)
def test_a_wrong_query_is_a_problem(app: FastAPI, params: dict[str, str]) -> None:
    _login(app, "graph.view")
    with TestClient(app) as client:
        resp = client.get("/api/graph", params=params)
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
