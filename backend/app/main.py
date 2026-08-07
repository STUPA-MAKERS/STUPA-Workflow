"""FastAPI app factory.

`create_app()` wires settings, logging, middleware (trace id + security headers,
CORS off), the problem+json error contract, and all module routers under `/api`.
The uvicorn entrypoint runs with `--proxy-headers`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request

from app.db import dispose_engine, get_sessionmaker
from app.logging_config import configure_logging
from app.middleware import (
    CsrfMiddleware,
    DefaultWriteRateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.modules.admin.router import authed_router as gremien_authed_router
from app.modules.admin.router import public_router as site_config_public_router
from app.modules.admin.router import router as admin_router
from app.modules.antiabuse.router import router as antiabuse_router
from app.modules.application_types.router import router as application_types_router
from app.modules.applications.router import router as applications_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.mcp_router import router as mcp_router
from app.modules.auth.oauth_admin_router import router as oauth_admin_router
from app.modules.auth.oauth_router import router as oauth_router
from app.modules.auth.oauth_router import well_known_router as oauth_well_known_router
from app.modules.auth.router import router as auth_router
from app.modules.budget.tree_router import router as budget_tree_router
from app.modules.calendar.router import router as calendar_router
from app.modules.config_revision.router import router as config_revision_router
from app.modules.deadlines.router import router as deadline_policies_router
from app.modules.delegations.router import router as delegations_router
from app.modules.files.router import router as files_router
from app.modules.files.storage import build_object_storage
from app.modules.flow.dispatch import ActionDispatcher
from app.modules.flow.extras_dispatcher import build_flow_extras_dispatcher
from app.modules.flow.router import get_action_dispatcher
from app.modules.flow.router import router as flow_router
from app.modules.forms.router import router as forms_router
from app.modules.livevote.broker import RedisBroker
from app.modules.livevote.locks import RedisLocker
from app.modules.livevote.router import router as livevote_router
from app.modules.livevote.service import BrokerPublisher
from app.modules.notifications.action_dispatcher import build_notify_dispatcher
from app.modules.notifications.provider import close_mail_pool, create_mail_pool
from app.modules.notifications.router import (
    admin_router as notification_settings_router,
)
from app.modules.notifications.router import router as notifications_router
from app.modules.notifications.router import (
    templates_router as mail_templates_router,
)
from app.modules.pdf.action_dispatcher import ChainActionDispatcher
from app.modules.pdf.router import router as pdf_router
from app.modules.privacy.router import router as privacy_router
from app.modules.protocol.router import router as protocol_router
from app.modules.voting.router import router as voting_router
from app.modules.webhooks.action_dispatcher import build_webhook_dispatcher
from app.settings import Settings, get_settings
from app.shared.errors import register_exception_handlers, use_problem_json_contract

api_router = APIRouter(prefix="/api")


@api_router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    """Liveness endpoint (container healthcheck)."""
    return {"status": "ok"}


# This module includes the routers once at import time. Repeated `create_app()`
# calls in the tests then do not register them twice.
api_router.include_router(auth_router)
api_router.include_router(oauth_router)
# Admin view over the grants of every principal (kill switch for a leaked agent token).
api_router.include_router(oauth_admin_router)
api_router.include_router(mcp_router)
# Mirror OAuth discovery under /api. The RFC location is the root, but /api always
# stays reachable through the edge proxy and gives MCP clients a fallback.
api_router.include_router(oauth_well_known_router)
api_router.include_router(forms_router)
api_router.include_router(application_types_router)
api_router.include_router(applications_router)
api_router.include_router(flow_router)
api_router.include_router(voting_router)
api_router.include_router(livevote_router)
api_router.include_router(protocol_router)
api_router.include_router(notifications_router)
api_router.include_router(notification_settings_router)
api_router.include_router(mail_templates_router)
api_router.include_router(budget_tree_router)
api_router.include_router(calendar_router)
api_router.include_router(antiabuse_router)
api_router.include_router(files_router)
api_router.include_router(pdf_router)
api_router.include_router(audit_router)
api_router.include_router(config_revision_router)
api_router.include_router(admin_router)
api_router.include_router(deadline_policies_router)
api_router.include_router(delegations_router)
api_router.include_router(privacy_router)
api_router.include_router(gremien_authed_router)
api_router.include_router(site_config_public_router)


async def _bootstrap_admins_on_startup(settings: Settings) -> None:  # pragma: no cover
    """Grant the admin role to matched existing principals on startup.

    The sweep is best effort. Without bootstrap config, which is the normal case, it
    touches no database. It logs an error and never raises it, because app startup
    must not fail here.
    """
    if not (settings.bootstrap_admin_subject_set or settings.bootstrap_admin_email_set):
        return
    from app.modules.auth.bootstrap import ensure_bootstrap_admins

    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as db:
            await ensure_bootstrap_admins(db, settings)
            await db.commit()
    except Exception:  # noqa: BLE001 — startup must never fail on bootstrap
        logging.getLogger("app.auth.bootstrap").warning(
            "bootstrap admin startup sweep skipped (db unavailable?)", exc_info=True
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Open the arq pool best effort for mail and scan jobs. Without Redis it is None.
    app.state.arq_pool = await create_mail_pool(settings.redis_url)
    # Build the object storage best effort. Without MinIO it is None and uploads 503.
    app.state.object_storage = build_object_storage(settings)
    # The Redis client connects lazily on the first PUBLISH or SUBSCRIBE, so this
    # call is cheap.
    import redis.asyncio as aioredis

    livevote_redis = aioredis.from_url(settings.redis_url)
    app.state._livevote_redis = livevote_redis
    app.state.broker = RedisBroker(livevote_redis)
    app.state.locker = RedisLocker(livevote_redis)
    app.state.meeting_publisher = BrokerPublisher(app.state.broker)
    await _bootstrap_admins_on_startup(settings)
    try:
        yield
    finally:
        await dispose_engine()
        await close_mail_pool(getattr(app.state, "arq_pool", None))
        state = getattr(app, "state", None)
        redis_client = (
            getattr(state, "_antiabuse_redis", None) if state is not None else None
        )
        if redis_client is not None:
            await redis_client.aclose()
        await livevote_redis.aclose()


def _flow_action_dispatcher(request: Request) -> ActionDispatcher:
    """Build the flow action dispatcher: notify, webhook, addToNextSession, assignBudget.

    The dispatcher reads the arq pool from the app state. Without a pool it logs the
    notify mails and the webhook deliveries and keeps them pending. The API never
    blocks.
    """
    pool = getattr(request.app.state, "arq_pool", None)
    return ChainActionDispatcher(
        [
            build_notify_dispatcher(pool),
            build_webhook_dispatcher(pool),
            build_flow_extras_dispatcher(pool),
        ]
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    # CORS stays unregistered on purpose: no cross-origin access. The last middleware
    # added becomes the outermost one. SecurityHeaders is outermost, so its headers
    # also reach the CSRF and 429 responses. Next come the trace id, then CSRF, and
    # innermost the default write rate limit. All of them are BaseHTTPMiddleware, so
    # a WebSocket scope passes through untouched.
    app.add_middleware(DefaultWriteRateLimitMiddleware, settings=settings)
    app.add_middleware(CsrfMiddleware, settings=settings)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    register_exception_handlers(app)

    app.dependency_overrides[get_action_dispatcher] = _flow_action_dispatcher

    app.include_router(api_router)
    # OAuth discovery (RFC 8414/9728) at the root, per well-known convention.
    app.include_router(oauth_well_known_router)
    use_problem_json_contract(app)
    return app


# Module-level app for uvicorn (`app.main:app`).
app = create_app()
