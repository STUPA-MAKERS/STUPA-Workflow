"""Pytest-Fixtures (T-02).

Setzt Pflicht-Env **vor** App-Import (Settings würde sonst beim Import fehlschlagen)
und stellt TestClients bereit.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:pw@localhost/antrag_test")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("MAGIC_LINK_SECRET", "test-magic-link-secret")
# Anti-Abuse standardmäßig aus für die Unit-Suite: Rate-Limiting würde sonst pro POST
# einen (scheiternden) Redis-Connect versuchen; Altcha bleibt ohne Secret ohnehin aus.
# Die Härtungs-Tests aktivieren beides gezielt via eigener Settings/Overrides.
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


# --------------------------------------------------------------------------- #
# Integration-Fixtures (testing.md §5): echte Backing-Services via testcontainers.
# Nur für `-m integration` (Docker nötig). Fehlt Docker, wird der Test geskippt
# statt zu erroren — die Unit-Suite (Default-addopts) berührt diese Fixtures nie.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Ephemerer Postgres; liefert async-DSN (`postgresql+asyncpg://…`)."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers nicht installiert")

    try:
        with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
            yield pg.get_connection_url()
    except Exception as exc:  # pragma: no cover — Docker fehlt/Runner ohne Daemon
        pytest.skip(f"Postgres-Container nicht startbar: {exc}")


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """Ephemerer Redis; liefert `redis://host:port/0`."""
    try:
        from testcontainers.redis import RedisContainer
    except ImportError:  # pragma: no cover
        pytest.skip("testcontainers nicht installiert")

    try:
        with RedisContainer("redis:7-alpine") as redis:
            host = redis.get_container_host_ip()
            port = redis.get_exposed_port(6379)
            yield f"redis://{host}:{port}/0"
    except Exception as exc:  # pragma: no cover — Docker fehlt/Runner ohne Daemon
        pytest.skip(f"Redis-Container nicht startbar: {exc}")
