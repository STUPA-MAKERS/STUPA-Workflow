"""TDD: einheitlicher Fehler-Contract (api.md §2).

Problem-JSON: type/title/status/code/detail/errors/traceId.
Status→Code-Mapping 400/401/403/404/409/410/413/422/429/500.
Keine Stacktraces/Pfade nach außen.
"""

import pytest
from fastapi.testclient import TestClient

from app.shared.errors import STATUS_CODE_MAP, ProblemDetail

# (Pfad-Suffix, erwarteter Status, erwarteter Code)
CASES = [
    ("bad-request", 400, "bad_request"),
    ("unauthorized", 401, "unauthorized"),
    ("forbidden", 403, "forbidden"),
    ("not-found", 404, "not_found"),
    ("conflict", 409, "conflict"),
    ("gone", 410, "gone"),
    ("payload-too-large", 413, "payload_too_large"),
    ("validation", 422, "validation_error"),
    ("rate-limited", 429, "rate_limited"),
]


def _assert_problem_shape(body: dict[str, object], status: int, code: str) -> None:
    assert body["status"] == status
    assert body["code"] == code
    assert isinstance(body["title"], str) and body["title"]
    assert isinstance(body["type"], str) and body["type"]
    assert isinstance(body["traceId"], str) and body["traceId"]


@pytest.mark.parametrize(("suffix", "status", "code"), CASES)
def test_app_errors_map_to_problem(
    error_client: TestClient, suffix: str, status: int, code: str
) -> None:
    resp = error_client.get(f"/raise/{suffix}")
    assert resp.status_code == status
    assert resp.headers["content-type"].startswith("application/problem+json")
    _assert_problem_shape(resp.json(), status, code)


def test_validation_carries_field_errors(error_client: TestClient) -> None:
    resp = error_client.get("/raise/validation")
    body = resp.json()
    assert body["errors"] == [{"field": "data.title", "msg": "required"}]


def test_unhandled_is_500_without_leak(error_client: TestClient) -> None:
    resp = error_client.get("/raise/unhandled")
    assert resp.status_code == 500
    body = resp.json()
    _assert_problem_shape(body, 500, "internal_error")
    # Kein Pfad/Stacktrace nach außen.
    dumped = resp.text
    assert "/etc/passwd" not in dumped
    assert "Traceback" not in dumped
    assert "RuntimeError" not in dumped


def test_unknown_route_yields_problem_json(client: TestClient) -> None:
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    _assert_problem_shape(resp.json(), 404, "not_found")


def test_status_code_map_complete() -> None:
    for status in (400, 401, 403, 404, 409, 410, 413, 422, 429, 500):
        assert status in STATUS_CODE_MAP


def test_problem_detail_serialization() -> None:
    p = ProblemDetail(
        type="app://error/conflict",
        title="Conflict",
        status=409,
        code="conflict",
        traceId="abc",
    )
    dumped = p.model_dump(exclude_none=True)
    assert dumped["traceId"] == "abc"
    assert "detail" not in dumped
    assert "errors" not in dumped
