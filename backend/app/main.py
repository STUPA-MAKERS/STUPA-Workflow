"""FastAPI App-Factory (T-02).

`create_app()` baut die App: Settings laden, Logging, Middleware (Trace-Id +
Security-Header, CORS aus), Fehler-Contract-Handler, API-Router-Mount unter `/api`.
Fachmodul-Router werden ab T-10 hier eingehängt. uvicorn-Entrypoint nutzt
`--proxy-headers` (Dockerfile/compose, security.md §3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.db import dispose_engine
from app.logging_config import configure_logging
from app.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.modules.auth.router import router as auth_router
from app.settings import Settings, get_settings
from app.shared.errors import register_exception_handlers, use_problem_json_contract

api_router = APIRouter(prefix="/api")


@api_router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness-Endpunkt (Container-Healthcheck)."""
    return {"status": "ok"}


api_router.include_router(auth_router)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Middleware (CORS bewusst nicht registriert → Cross-Origin aus).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(api_router)
    use_problem_json_contract(app)
    return app


# Modul-Level-App für uvicorn (`app.main:app`).
app = create_app()
