"""Pytest fixtures (T-02).

This module sets the required environment variables before it imports the app. Settings
fails at import time without them. The module also provides the test clients.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:pw@localhost/antrag_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("MAGIC_LINK_SECRET", "test-magic-link-secret")
# The unit suite runs with anti-abuse off. Rate limiting would otherwise try one Redis
# connect per POST, and that connect fails. Altcha stays off anyway without a secret.
# The hardening tests turn both on through their own settings or overrides.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from collections.abc import Iterator

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
    """App with test routes that raise every AppError type plus an unhandled error."""
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


# Integration fixtures (testing.md §5). They start real backing services with
# testcontainers and run only under `-m integration`, which needs Docker. Without Docker
# the test skips instead of errors. The unit suite (default addopts) never touches them.


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Start an ephemeral Postgres and yield an async DSN (`postgresql+asyncpg://…`)."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers nicht installiert")

    try:
        with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
            yield pg.get_connection_url()
    except Exception as exc:  # pragma: no cover — no Docker, or a runner without a daemon
        pytest.skip(f"Postgres-Container nicht startbar: {exc}")


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """Start an ephemeral Redis and yield `redis://host:port/0`."""
    try:
        from testcontainers.redis import RedisContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers nicht installiert")

    try:
        with RedisContainer("redis:7-alpine") as redis:
            host = redis.get_container_host_ip()
            port = redis.get_exposed_port(6379)
            yield f"redis://{host}:{port}/0"
    except Exception as exc:  # pragma: no cover — no Docker, or a runner without a daemon
        pytest.skip(f"Redis-Container nicht startbar: {exc}")
