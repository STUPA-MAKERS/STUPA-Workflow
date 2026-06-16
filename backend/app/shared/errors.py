"""Einheitlicher Fehler-Contract (api.md §2, RFC-9457-nah).

Problem-JSON:
    {"type","title","status","code","detail","errors":[{"field","msg"}],"traceId"}

`AppError` + Subklassen tragen Status/Code/Title. `register_exception_handlers`
mappt AppError, FastAPI-Validierung, Starlette-HTTP (z.B. unbekannte Route) und
unbehandelte Exceptions auf das Problem-JSON. Nach außen **keine** Stacktraces/Pfade.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger("app.error")

PROBLEM_CONTENT_TYPE = "application/problem+json"

# FastAPI wirft GENAU diese `HTTPException(400)`, wenn das Parsen des Request-Bodys
# fehlschlägt, das kein JSON-Decode-Fehler ist — v.a. kaputtes `multipart/form-data`
# (fastapi/routing.py). Ungültiges JSON läuft dagegen über `RequestValidationError`
# → 422. Damit ein unparsebarer Body **app-weit** denselben dokumentierten
# problem+json-Status liefert (statt endpunktweise undokumentierter 400er — Contract
# `negative_data_rejection`/undocumented-status, Issue #23/T-13), heben wir diesen Fall
# auf 422 (validation_error) — denselben Status wie jede andere Body-Validierung.
_BODY_PARSE_ERROR_DETAIL = "There was an error parsing the body"

# Status → stabiler Fehlercode (api.md §2).
STATUS_CODE_MAP: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}

# Status → menschenlesbarer Titel (Default, falls AppError keinen setzt).
STATUS_TITLE_MAP: dict[int, str] = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    413: "Payload Too Large",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


class FieldError(BaseModel):
    field: str
    msg: str


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    errors: list[FieldError] | None = None
    traceId: str | None = None


def code_for(status: int) -> str:
    return STATUS_CODE_MAP.get(status, "error")


def title_for(status: int) -> str:
    return STATUS_TITLE_MAP.get(status, "Error")


class AppError(Exception):
    """Domänen-/HTTP-Fehler mit Mapping auf das Problem-JSON."""

    status: int = 500

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        title: str | None = None,
        errors: Sequence[FieldError | dict[str, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = type(self).status
        self.code = code or code_for(self.status)
        self.title = title or title_for(self.status)
        self.detail = detail
        self.errors: list[FieldError] | None = (
            [e if isinstance(e, FieldError) else FieldError(**e) for e in errors]
            if errors is not None
            else None
        )
        # Zusätzliche Antwort-Header (z.B. `Retry-After` bei 429).
        self.headers: dict[str, str] | None = headers
        super().__init__(self.detail or self.title)

    def to_problem(self, trace_id: str | None) -> ProblemDetail:
        return ProblemDetail(
            type=f"app://error/{self.code}",
            title=self.title,
            status=self.status,
            code=self.code,
            detail=self.detail,
            errors=self.errors,
            traceId=trace_id,
        )


class BadRequestError(AppError):
    status = 400


class UnauthorizedError(AppError):
    status = 401


class ForbiddenError(AppError):
    status = 403


class NotFoundError(AppError):
    status = 404


class ConflictError(AppError):
    status = 409


class GoneError(AppError):
    status = 410


class PayloadTooLargeError(AppError):
    status = 413


class UnsupportedMediaTypeError(AppError):
    """415 — Datei-Typ nicht erlaubt bzw. MIME-Sniff ≠ Endung (security.md §6)."""

    status = 415


class ValidationProblem(AppError):
    """422 — Validierung gegen Form/Config (api.md). Name vermeidet Pydantic-Kollision."""

    status = 422


class RateLimitedError(AppError):
    status = 429

    def __init__(
        self,
        detail: str | None = None,
        *,
        retry_after: int | None = None,
        code: str | None = None,
        title: str | None = None,
    ) -> None:
        headers = (
            {"Retry-After": str(max(0, retry_after))} if retry_after is not None else None
        )
        super().__init__(detail, code=code, title=title, headers=headers)


class ServiceUnavailableError(AppError):
    """503 — abhängiger Dienst nicht erreichbar (z. B. Object-Storage beim Upload)."""

    status = 503


def _trace_id(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _problem_response(
    problem: ProblemDetail, extra_headers: dict[str, str] | None = None
) -> JSONResponse:
    headers: dict[str, str] = {}
    if problem.traceId:
        headers["X-Trace-Id"] = problem.traceId
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers or None,
    )


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _problem_response(exc.to_problem(_trace_id(request)), exc.headers)


def _validation_problem(
    request: Request, *, detail: str, errors: list[FieldError]
) -> JSONResponse:
    """Einheitliches 422-problem+json für jede Body-/Parameter-Validierung."""
    problem = ProblemDetail(
        type="app://error/validation_error",
        title=title_for(422),
        status=422,
        code="validation_error",
        detail=detail,
        errors=errors,
        traceId=_trace_id(request),
    )
    return _problem_response(problem)


async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        FieldError(field=".".join(str(p) for p in e["loc"]), msg=e["msg"])
        for e in exc.errors()
    ]
    return _validation_problem(request, detail="Request validation failed.", errors=errors)


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    # Body-Parse-Fehler (kaputtes multipart o.Ä.) vereinheitlichen auf 422 — nicht der
    # endpunktspezifische, undokumentierte 400 von FastAPI (s. `_BODY_PARSE_ERROR_DETAIL`).
    if exc.status_code == 400 and exc.detail == _BODY_PARSE_ERROR_DETAIL:
        return _validation_problem(
            request,
            detail="Request body could not be parsed.",
            errors=[FieldError(field="body", msg="Request body could not be parsed.")],
        )
    status = exc.status_code
    detail = exc.detail if isinstance(exc.detail, str) else None
    problem = ProblemDetail(
        type=f"app://error/{code_for(status)}",
        title=title_for(status),
        status=status,
        code=code_for(status),
        detail=detail,
        traceId=_trace_id(request),
    )
    return _problem_response(problem)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    # Intern volle Info loggen, nach außen nichts leaken (keine Pfade/Stacktraces).
    logger.exception("Unhandled exception", exc_info=exc)
    problem = ProblemDetail(
        type="app://error/internal_error",
        title=title_for(500),
        status=500,
        code="internal_error",
        detail="An internal error occurred.",
        traceId=_trace_id(request),
    )
    return _problem_response(problem)


def register_exception_handlers(app: FastAPI) -> None:
    """Alle Handler an die App binden (Reihenfolge: spezifisch → generisch)."""
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)


def _ensure_problem_components(schema: dict[str, object]) -> None:
    """`ProblemDetail`(+`FieldError`) im components-Block registrieren (idempotent)."""
    components = schema.setdefault("components", {})
    assert isinstance(components, dict)
    schemas = components.setdefault("schemas", {})
    assert isinstance(schemas, dict)
    if "ProblemDetail" in schemas:
        return
    model = ProblemDetail.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    for name, definition in model.pop("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["ProblemDetail"] = model


def use_problem_json_contract(app: FastAPI) -> None:
    """OpenAPI an den Fehler-Contract angleichen (api.md §2).

    FastAPI dokumentiert Fehler-/422-Antworten als `application/json`; die Handler
    liefern jedoch `application/problem+json` (RFC-9457-nah). Diese Anpassung schreibt
    **alle** 4xx/5xx-Antworten auf `application/problem+json` + `ProblemDetail` um, damit
    der Contract (Schemathesis content/status/schema) konsistent ist."""
    generate = app.openapi

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = generate()
        _ensure_problem_components(schema)
        problem_content = {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"}
            }
        }
        paths = schema.get("paths", {})
        assert isinstance(paths, dict)
        for operations in paths.values():
            for operation in operations.values():
                if not isinstance(operation, dict):
                    continue
                # Opt-out: Endpunkte mit eigenem Fehler-Contract (z. B. RFC-6749-OAuth-
                # Token-Fehler in OAuth-JSON statt problem+json) dokumentieren ihre
                # Antworten selbst und werden hier NICHT umgeschrieben (s. oauth_router.token).
                if operation.get("x-error-contract") == "oauth":
                    continue
                responses = operation.setdefault("responses", {})
                # Jeder Body-annehmende Endpunkt kann bei unparsebarem/ungültigem Body
                # ein 422 liefern (RequestValidationError bzw. vereinheitlichter
                # Body-Parse-Fehler, s. `_http_exception_handler`). FastAPI dokumentiert
                # 422 nur, wenn validierbare Felder existieren — multipart/File-Endpunkte
                # bekommen es z.B. nicht zuverlässig. Darum hier global ergänzen, damit der
                # Contract nicht endpunktweise an einem undokumentierten Status scheitert.
                if "requestBody" in operation and isinstance(responses, dict):
                    responses.setdefault(
                        "422", {"description": "Validation Error"}
                    )
                for code, response in responses.items():
                    if str(code)[0] in {"4", "5"} and isinstance(response, dict):
                        response["content"] = problem_content
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
