"""OpenAPI error contract (api.md §2).

Error responses use the problem+json media type.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.errors import _ensure_problem_components


def test_error_responses_are_problem_json() -> None:
    spec = create_app().openapi()
    me = spec["paths"]["/api/auth/me"]["get"]["responses"]
    assert list(me["401"]["content"]) == ["application/problem+json"]
    assert me["401"]["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetail"
    }
    assert list(me["200"]["content"]) == ["application/json"]


def test_problem_detail_component_registered() -> None:
    spec = create_app().openapi()
    schemas = spec["components"]["schemas"]
    assert "ProblemDetail" in schemas
    assert "FieldError" in schemas


def test_openapi_served_and_cached() -> None:
    app = create_app()
    client = TestClient(app)
    first = client.get("/openapi.json")
    assert first.status_code == 200
    # The second call uses the cache because app.openapi_schema is set.
    assert client.get("/openapi.json").json() == first.json()


def test_ensure_problem_components_idempotent() -> None:
    schema: dict[str, object] = {}
    _ensure_problem_components(schema)
    _ensure_problem_components(schema)  # The second run returns early.
    schemas = schema["components"]["schemas"]  # type: ignore[index]
    assert "ProblemDetail" in schemas
