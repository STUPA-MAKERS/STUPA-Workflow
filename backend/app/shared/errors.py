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
from collections.abc import Mapping, Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from app.shared.schemas import FrozenModel

logger = logging.getLogger("app.error")

PROBLEM_CONTENT_TYPE = "application/problem+json"

#: HTTPException(400) details of a body that fails to parse but is not invalid JSON,
#: mainly a broken multipart/form-data. FastAPI raises the first for an unknown parser
#: error; Starlette 1.7 and later raises the second for a multipart parser error.
#: Invalid JSON goes through RequestValidationError to 422. The handler lifts these
#: cases to 422 too, so an unparseable body gives the same documented status app-wide
#: instead of an undocumented per-endpoint 400.
_BODY_PARSE_ERROR_DETAILS: frozenset[str] = frozenset(
    {"There was an error parsing the body", "Invalid multipart data."}
)

#: HTTP status to stable error code.
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

#: HTTP status to the default title when an AppError sets none.
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


class FieldError(FrozenModel, frozen=True):
    """Validation error of one field in a problem response."""
    field: str
    msg: str


class ProblemDetail(FrozenModel, frozen=True):
    """Error body of every 4xx and 5xx response (RFC 9457 problem+json)."""
    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    errors: tuple[FieldError, ...] | None = None
    traceId: str | None = None


def code_for(status: int) -> str:
    """Return the stable error code of an HTTP status."""
    return STATUS_CODE_MAP.get(status, "error")


def title_for(status: int) -> str:
    """Return the default title of an HTTP status."""
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
        """Build the error.

        Args:
            detail: Human-readable detail.
            code: Stable error code; defaults to the code of the status.
            title: Title; defaults to the title of the status.
            errors: Field errors, as models or as ``{field, msg}`` dicts.
            headers: Extra response headers, for example ``Retry-After`` on a 429.
        """
        self.status = type(self).status
        self.code = code or code_for(self.status)
        self.title = title or title_for(self.status)
        self.detail = detail
        self.errors: tuple[FieldError, ...] | None = (
            tuple(e if isinstance(e, FieldError) else FieldError(**e) for e in errors)
            if errors is not None
            else None
        )
        self.headers: dict[str, str] | None = headers
        super().__init__(self.detail or self.title)

    def to_problem(self, trace_id: str | None) -> ProblemDetail:
        """Return the problem body of this error."""
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
    """400 - malformed request."""
    status = 400


class UnauthorizedError(AppError):
    """401 - no valid login."""
    status = 401


class ForbiddenError(AppError):
    """403 - the caller lacks the right."""
    status = 403


class NotFoundError(AppError):
    """404 - unknown or not readable resource."""
    status = 404


class ConflictError(AppError):
    """409 - conflict with the current state."""
    status = 409


class GoneError(AppError):
    """410 - the resource no longer exists."""
    status = 410


class PayloadTooLargeError(AppError):
    """413 - the body exceeds its cap."""
    status = 413


class UnsupportedMediaTypeError(AppError):
    """415 - file type not allowed or MIME sniff != extension."""

    status = 415


class ValidationProblem(AppError):
    """422 - validation against form/config. Named to avoid a Pydantic collision."""

    status = 422


class RateLimitedError(AppError):
    """429 - rate limit hit; ``retry_after`` sets the ``Retry-After`` header."""

    status = 429

    def __init__(
        self,
        detail: str | None = None,
        *,
        retry_after: int | None = None,
        code: str | None = None,
        title: str | None = None,
    ) -> None:
        """Build the error; a ``retry_after`` in seconds sets the ``Retry-After`` header."""
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
    trace = {"X-Trace-Id": problem.traceId} if problem.traceId else {}
    headers = {**trace, **(extra_headers or {})}
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(exclude_none=True),
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers or None,
    )


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return _problem_response(exc.to_problem(_trace_id(request)), exc.headers)


def _validation_problem(
    request: Request, *, detail: str, errors: Sequence[FieldError]
) -> JSONResponse:
    """Uniform 422 problem+json for any body/parameter validation."""
    problem = ProblemDetail(
        type="app://error/validation_error",
        title=title_for(422),
        status=422,
        code="validation_error",
        detail=detail,
        errors=tuple(errors),
        traceId=_trace_id(request),
    )
    return _problem_response(problem)


async def _validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = tuple(
        FieldError(field=".".join(str(p) for p in e["loc"]), msg=e["msg"])
        for e in exc.errors()
    )
    return _validation_problem(request, detail="Request validation failed.", errors=errors)


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Map an HTTPException onto problem+json.

    A body-parse error (see ``_BODY_PARSE_ERROR_DETAILS``) becomes 422 instead of the
    endpoint-specific, undocumented 400 of FastAPI.
    """
    if (
        exc.status_code == 400
        and isinstance(exc.detail, str)
        and exc.detail in _BODY_PARSE_ERROR_DETAILS
    ):
        return _validation_problem(
            request,
            detail="Request body could not be parsed.",
            errors=(FieldError(field="body", msg="Request body could not be parsed."),),
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


#: Prefix of every public route without login (the same as in ``app.middleware``).
PUBLIC_API_PREFIX = "/api/public/"


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log an unhandled exception and answer a bare 500.

    The log holds the full detail; the answer leaks nothing (no path, no stack trace).
    The handler of ``Exception`` runs outside the middleware stack, so the security
    middleware never sees this answer, and a public route sets its noindex here.
    """
    logger.exception("Unhandled exception", exc_info=exc)
    problem = ProblemDetail(
        type="app://error/internal_error",
        title=title_for(500),
        status=500,
        code="internal_error",
        detail="An internal error occurred.",
        traceId=_trace_id(request),
    )
    extra = (
        {"X-Robots-Tag": "noindex"}
        if request.url.path.startswith(PUBLIC_API_PREFIX)
        else None
    )
    return _problem_response(problem, extra)


#: SQLSTATE `character_not_in_repertoire` and `untranslatable_character`: Postgres refuses
#: a NUL character in a text column and in a JSONB column.
_SQLSTATES_BAD_TEXT = frozenset({"22021", "22P05"})


async def _db_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Answer 422 for a text that the database cannot hold, else the bare 500.

    A NUL character passes the JSON parser and the length checks, and only Postgres
    refuses it: 22021 in a text column and 22P05 in a JSONB column, which the audit
    entry of a write is. That is an input error of the caller, not a fault of the server.
    """
    state = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    if state in _SQLSTATES_BAD_TEXT:
        return _validation_problem(
            request,
            detail="A text holds a character that cannot be stored.",
            errors=(FieldError(field="body", msg="A text holds a NUL character."),),
        )
    return await _unhandled_handler(request, exc)


def register_exception_handlers(app: FastAPI) -> None:
    """Bind all handlers to the app (order: specific -> generic)."""
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DBAPIError, _db_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_handler)


def _ensure_problem_components(schema: dict[str, object]) -> None:
    """Register ``ProblemDetail`` (+ ``FieldError``) in the components block (idempotent)."""
    schema.update(_with_problem_components(schema))


def _with_problem_components(schema: Mapping[str, object]) -> dict[str, object]:
    """Return ``schema`` with ``ProblemDetail`` (+ ``FieldError``) in its components block.

    A schema that holds ``ProblemDetail`` already keeps its components as they are. A
    component of the same name that the schema holds wins over the one of the model.
    """
    components = schema.get("components", {})
    assert isinstance(components, dict)
    schemas = components.get("schemas", {})
    assert isinstance(schemas, dict)
    return {
        **schema,
        "components": {**components, "schemas": _with_problem_schemas(schemas)},
    }


def _with_problem_schemas(schemas: Mapping[str, object]) -> dict[str, object]:
    """Return the component schemas with ``ProblemDetail`` and its ``$defs`` added."""
    if "ProblemDetail" in schemas:
        return dict(schemas)
    model = ProblemDetail.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions: dict[str, object] = model.get("$defs", {})
    body = {key: value for key, value in model.items() if key != "$defs"}
    added = {name: d for name, d in definitions.items() if name not in schemas}
    return {**schemas, **added, "ProblemDetail": body}


def _problem_operation(operation: object, problem_content: object) -> object:
    """Return an operation whose 4xx and 5xx responses document problem+json.

    An operation with ``x-error-contract: oauth`` stays as it is. An operation with a
    request body gets a 422, because an unparseable body can give one.
    """
    if not isinstance(operation, dict) or operation.get("x-error-contract") == "oauth":
        return operation
    responses = operation.get("responses", {})
    with_422 = (
        {**responses, "422": responses.get("422", {"description": "Validation Error"})}
        if "requestBody" in operation and isinstance(responses, dict)
        else responses
    )
    return {**operation, "responses": _problem_responses(with_422, problem_content)}


def _problem_responses(responses: object, problem_content: object) -> object:
    """Return the responses with the problem+json content on every 4xx and 5xx response."""
    if not isinstance(responses, dict):
        return responses
    return {
        code: (
            {**response, "content": problem_content}
            if str(code)[0] in {"4", "5"} and isinstance(response, dict)
            else response
        )
        for code, response in responses.items()
    }


def use_problem_json_contract(app: FastAPI) -> None:
    """Align OpenAPI with the error contract.

    FastAPI documents an error or 422 response as ``application/json``, but the handlers
    emit ``application/problem+json`` (RFC 9457-ish). This function rewrites every 4xx
    and 5xx response to ``application/problem+json`` with ``ProblemDetail``. The contract
    then stays consistent.

    An endpoint with ``x-error-contract: oauth`` documents its own responses (the RFC
    6749 token error uses OAuth JSON) and stays as it is. Every body-accepting endpoint
    gets a 422, because it can return one on an unparseable or invalid body, and FastAPI
    documents 422 only when validatable fields exist, so a multipart or File endpoint
    misses it and the contract would fail on an undocumented status.
    """
    generate = app.openapi

    def custom_openapi() -> dict[str, object]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = _with_problem_components(generate())
        problem_content = {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetail"}
            }
        }
        paths = schema.get("paths", {})
        assert isinstance(paths, dict)
        problem_paths = {
            path: {
                method: _problem_operation(operation, problem_content)
                for method, operation in operations.items()
            }
            for path, operations in paths.items()
        }
        contract = {**schema, "paths": problem_paths} if "paths" in schema else schema
        app.openapi_schema = contract
        return contract

    app.openapi = custom_openapi
