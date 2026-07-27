"""Unified error contract (RFC 9457-ish).

Problem JSON:
    {"type","title","status","code","detail","errors":[{"field","msg"}],"traceId"}

``AppError`` and its subclasses carry the status, the code and the title.
``register_exception_handlers`` maps AppError, FastAPI validation, Starlette HTTP (for
example an unknown route) and unhandled exceptions onto the problem JSON. The handlers
leak no stack trace and no path outward.
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

# FastAPI raises exactly this HTTPException(400) when the body parsing fails in a way
# that is not a JSON decode error, mainly a broken multipart/form-data. Invalid JSON
# goes through RequestValidationError to 422. The handler lifts this case to 422
# (validation_error). An unparseable body then gives the same documented problem+json
# status app-wide, instead of an undocumented per-endpoint 400.
_BODY_PARSE_ERROR_DETAIL = "There was an error parsing the body"

# Status -> stable error code.
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

# Status -> human-readable title (default when AppError sets none).
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
    """Domain/HTTP error mapped onto the problem JSON."""

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
        # Extra response headers, for example ``Retry-After`` on a 429.
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
    """415 - file type not allowed or MIME sniff != extension."""

    status = 415


class ValidationProblem(AppError):
    """422 - validation against form/config. Named to avoid a Pydantic collision."""

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
    """503 - a dependent service is unreachable (e.g. object storage during upload)."""

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
    """Uniform 422 problem+json for any body/parameter validation."""
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
    # Unify the body-parse errors (broken multipart and similar) onto 422, instead of
    # the endpoint-specific, undocumented 400 of FastAPI. See
    # ``_BODY_PARSE_ERROR_DETAIL``.
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
    # Log the full detail internally. Leak nothing outward: no path, no stack trace.
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
    """Bind all handlers to the app (order: specific -> generic)."""
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)


def _ensure_problem_components(schema: dict[str, object]) -> None:
    """Register ``ProblemDetail`` (+ ``FieldError``) in the components block (idempotent)."""
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
    """Align OpenAPI with the error contract.

    FastAPI documents an error or 422 response as ``application/json``, but the handlers
    emit ``application/problem+json`` (RFC 9457-ish). This function rewrites every 4xx
    and 5xx response to ``application/problem+json`` with ``ProblemDetail``. The contract
    then stays consistent.
    """
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
                # Opt-out: an endpoint with its own error contract documents its own
                # responses. An example is the RFC 6749 OAuth token error, which uses
                # OAuth JSON instead of problem+json. This function does NOT rewrite it.
                if operation.get("x-error-contract") == "oauth":
                    continue
                responses = operation.setdefault("responses", {})
                # Any body-accepting endpoint can return 422 on an unparseable or
                # invalid body (RequestValidationError or the unified body-parse error).
                # FastAPI documents 422 only when validatable fields exist, so a
                # multipart or File endpoint misses it. Add it globally so the contract
                # does not fail on an undocumented status.
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
