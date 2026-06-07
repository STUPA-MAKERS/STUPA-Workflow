"""TDD: einheitlicher Fehler-Contract (api.md §2).

Problem-JSON: type/title/status/code/detail/errors/traceId.
Status→Code-Mapping 400/401/403/404/409/410/413/422/429/500.
Keine Stacktraces/Pfade nach außen.
"""

import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import RequestContextMiddleware
from app.shared.errors import STATUS_CODE_MAP, ProblemDetail, register_exception_handlers

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


# --------------------------------------------------------------------------- #
# Unparsebarer Request-Body → app-weit EIN dokumentierter 422 (nicht der
# endpunktspezifische, undokumentierte FastAPI-400 bei kaputtem multipart). T-13/PR.
# --------------------------------------------------------------------------- #
_MALFORMED_MULTIPART = b"--ff\r\nFalse--ff--\r\n"
_MULTIPART_HEADERS = {"content-type": "multipart/form-data; boundary=xxx"}


def _upload_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    @app.post("/upload")
    async def upload(file: UploadFile) -> dict[str, str]:  # pragma: no cover - Parse failt davor
        return {"name": file.filename or ""}

    return TestClient(app)


def test_malformed_multipart_body_is_422_problem_json() -> None:
    resp = _upload_app().post(
        "/upload", content=_MALFORMED_MULTIPART, headers=_MULTIPART_HEADERS
    )
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    _assert_problem_shape(body, 422, "validation_error")
    assert body["errors"][0]["field"] == "body"


def test_malformed_json_body_is_422() -> None:
    # JSON-Decode-Fehler laufen schon über RequestValidationError → 422; hier nur
    # festhalten, dass beide Body-Parse-Pfade DENSELBEN Status liefern.
    resp = create_app_client().post(
        "/api/auth/magic-link", content=b"not json{", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422


def create_app_client() -> TestClient:
    return TestClient(create_app())


def test_attachments_route_documents_422_problem_json() -> None:
    schema = create_app().openapi()
    op = schema["paths"]["/api/applications/{application_id}/attachments"]["post"]
    assert "422" in op["responses"]
    assert (
        op["responses"]["422"]["content"]["application/problem+json"]["schema"]["$ref"]
        == "#/components/schemas/ProblemDetail"
    )


def test_all_body_endpoints_document_422() -> None:
    # Globale Garantie: jeder Body-annehmende Endpunkt dokumentiert 422 (sonst wäre ein
    # unparsebarer Body endpunktweise ein undokumentierter Status → be-contract rot).
    schema = create_app().openapi()
    missing: list[str] = []
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            if not isinstance(op, dict) or "requestBody" not in op:
                continue
            if "422" not in op.get("responses", {}):
                missing.append(f"{method.upper()} {path}")
    assert not missing, f"Body-Endpunkte ohne dokumentierten 422: {missing}"


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
