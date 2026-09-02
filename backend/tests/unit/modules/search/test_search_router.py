"""Router tests for the global search: auth, the query floor and the shape."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_session
from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.search import service as search_service
from app.modules.search.schemas import SearchHit, SearchResults


class _FakeSession:
    async def commit(self) -> None: ...


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    application = create_app()

    def _session() -> Iterator[_FakeSession]:
        yield _FakeSession()

    application.dependency_overrides[get_session] = _session

    class _FakeService:
        def __init__(self, _session: object) -> None: ...

        async def search(
            self, q: str, principal: Principal, *, lang: str = "de"
        ) -> SearchResults:
            return SearchResults(
                hits=[
                    SearchHit(
                        kind="application",
                        id="a-1",
                        title=f"{q}/{lang}/{principal.sub}",
                        url="/applications/a-1",
                    )
                ]
            )

    monkeypatch.setattr(search_service, "SearchService", _FakeService)
    monkeypatch.setattr("app.modules.search.router.SearchService", _FakeService)
    return application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _principal(app: FastAPI) -> None:
    app.dependency_overrides[get_current_principal] = lambda: Principal(sub="me")


def test_search_requires_authentication_401(client: TestClient) -> None:
    assert client.get("/api/search?q=abc").status_code == 401


def test_search_returns_hits_for_a_principal(app: FastAPI, client: TestClient) -> None:
    _principal(app)
    r = client.get("/api/search", params={"q": "abc"})
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    assert body["hits"][0]["kind"] == "application"
    assert body["hits"][0]["url"] == "/applications/a-1"
    # The query, the language default and the caller all reach the service.
    assert body["hits"][0]["title"] == "abc/de/me"


def test_search_passes_the_requested_language(app: FastAPI, client: TestClient) -> None:
    _principal(app)
    r = client.get("/api/search", params={"q": "abc", "lang": "en"})
    assert r.json()["hits"][0]["title"] == "abc/en/me"


def test_search_without_a_query_is_not_an_error(app: FastAPI, client: TestClient) -> None:
    # The palette calls this on every keystroke, including the first.
    _principal(app)
    assert client.get("/api/search").status_code == 200


def test_an_overlong_query_is_rejected_rather_than_scanned(
    app: FastAPI, client: TestClient
) -> None:
    # A DoS bound, not a validation rule: a trigram scan over a very long string costs
    # more than any real query needs.
    _principal(app)
    assert client.get("/api/search", params={"q": "x" * 201}).status_code == 422
