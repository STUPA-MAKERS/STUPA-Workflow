"""Pytest-Fixtures (T-02).

Setzt Pflicht-Env **vor** App-Import (Settings würde sonst beim Import fehlschlagen)
und stellt TestClients bereit.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:pw@localhost/antrag_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("MAGIC_LINK_SECRET", "test-magic-link-secret")

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.middleware import RequestContextMiddleware
from app.shared.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    GoneError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    UnauthorizedError,
    ValidationProblem,
    register_exception_handlers,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def error_client() -> TestClient:
    """App mit Test-Routen, die jeden AppError-Typ + Unhandled werfen."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    router = APIRouter()

    errors: dict[str, AppError] = {
        "bad-request": BadRequestError(),
        "unauthorized": UnauthorizedError(),
        "forbidden": ForbiddenError(),
        "not-found": NotFoundError(),
        "conflict": ConflictError(),
        "gone": GoneError(),
        "payload-too-large": PayloadTooLargeError(),
        "validation": ValidationProblem(errors=[{"field": "data.title", "msg": "required"}]),
        "rate-limited": RateLimitedError(),
    }

    def make(err: AppError):
        def raise_it() -> None:
            raise err

        return raise_it

    for path, err in errors.items():
        router.add_api_route(f"/raise/{path}", make(err), methods=["GET"])

    def boom() -> None:
        raise RuntimeError("secret internal detail /etc/passwd")

    router.add_api_route("/raise/unhandled", boom, methods=["GET"])
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)
