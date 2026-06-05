"""TDD: Security-Header + Trace-Id-Middleware (security.md §10, §3)."""

from fastapi.testclient import TestClient


def test_security_headers_present(client: TestClient) -> None:
    resp = client.get("/api/health")
    h = resp.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY"
    assert "permissions-policy" in h


def test_trace_id_header_and_unique(client: TestClient) -> None:
    r1 = client.get("/api/health")
    r2 = client.get("/api/health")
    assert r1.headers["x-trace-id"]
    assert r1.headers["x-trace-id"] != r2.headers["x-trace-id"]


def test_cors_off_no_acao_header(client: TestClient) -> None:
    resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_error_traceid_matches_header(error_client: TestClient) -> None:
    resp = error_client.get("/raise/not-found")
    assert resp.json()["traceId"] == resp.headers["x-trace-id"]
