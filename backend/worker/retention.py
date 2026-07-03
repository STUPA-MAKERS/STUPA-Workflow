"""GDPR retention cron (daily sweep).

Terminal applications past their retention window are anonymized; expired sessions
and used/expired magic links are purged. Retention =
``COALESCE(application_type.retention_months, privacy_settings.default_retention_months)``.

Budget/money data (``budget*``/``expense``/``invoice``) is NEVER touched: financial
records outside this GDPR scope. Idempotent, with per-row try/except so one bad row
never aborts the run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import get_sessionmaker
from app.modules.admin.models import ApplicationType
from app.modules.applications.models import Applicant, Application, MagicLink
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import AuthSession
from app.modules.files.service import FilesService
from app.modules.files.storage import ObjectStorage, build_object_storage
from app.modules.flow.models import State
from app.modules.privacy.models import PrivacySettings
from app.settings import Settings, load_settings

logger = logging.getLogger("worker.retention")

_RETENTION_ACTOR = "system:retention"


def _sessionmaker(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    """DB sessionmaker (injectable in tests via ``ctx['retention_sessionmaker']``)."""
    maker = ctx.get("retention_sessionmaker")
    return maker if maker is not None else get_sessionmaker()


def _now() -> datetime:
    """Timezone-aware now (UTC); freezegun-controllable in tests."""
    return datetime.now(UTC)


async def _due_application_ids(
    maker: async_sessionmaker[AsyncSession],
) -> list[UUID]:
    """IDs of terminal, not-yet-anonymized applications past their retention window."""
    async with maker() as session:
        default_months = (
            await session.scalar(select(PrivacySettings.default_retention_months))
        ) or 24
        retention = func.coalesce(ApplicationType.retention_months, default_months)
        # Per-row threshold: updated_at older than (now - retention) is due.
        cutoff = func.now() - func.make_interval(0, retention)
        stmt = (
            select(Application.id)
            .join(State, State.id == Application.current_state_id)
            .join(ApplicationType, ApplicationType.id == Application.type_id)
            .join(Applicant, Applicant.application_id == Application.id)
            .where(
                State.is_terminal.is_(True),
                Applicant.anonymized_at.is_(None),
                Application.updated_at < cutoff,
            )
        )
        return list((await session.scalars(stmt)).all())


async def _anonymize_due(
    maker: async_sessionmaker[AsyncSession],
    storage: ObjectStorage | None,
) -> int:
    ids = await _due_application_ids(maker)
    count = 0
    for application_id in ids:
        try:
            async with maker() as session:
                files = FilesService(session, storage=storage)
                await ApplicationsService(session).anonymize(
                    application_id,
                    files=files,
                    actor=_RETENTION_ACTOR,
                    commit=False,
                )
                await audit_record(
                    session,
                    actor=_RETENTION_ACTOR,
                    action=AuditAction.RETENTION_ANONYMIZE,
                    target_type="application",
                    target_id=str(application_id),
                )
                await session.commit()
            count += 1
        except Exception:  # noqa: BLE001 - a bad single row must not abort the run
            logger.exception("retention anonymize failed (app=%s)", application_id)
    return count


async def _purge_expired(
    maker: async_sessionmaker[AsyncSession], now: datetime
) -> tuple[int, int]:
    """Delete expired sessions and used/expired magic links.

    Auth artifacts only: budget/``expense``/``invoice`` rows are financial records
    and are NEVER deleted here.
    """
    async with maker() as session:
        sessions = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(AuthSession).where(AuthSession.expires_at < now)
            ),
        )
        links = cast(
            "CursorResult[Any]",
            await session.execute(
                delete(MagicLink).where(
                    or_(MagicLink.used_at.is_not(None), MagicLink.expires_at < now)
                )
            ),
        )
        await session.commit()
        return sessions.rowcount or 0, links.rowcount or 0


async def process_retention(ctx: dict[str, Any]) -> str:
    """Entry point (arq cron): anonymize + purge.

    Returns a run summary; arq logs the return value for cron visibility.
    """
    settings: Settings = ctx.get("settings") or load_settings()
    maker = _sessionmaker(ctx)
    now = _now()
    storage = build_object_storage(settings)
    anonymized = await _anonymize_due(maker, storage)
    purged_sessions, purged_links = await _purge_expired(maker, now)
    return (
        f"anonymized={anonymized} sessions_purged={purged_sessions} "
        f"links_purged={purged_links}"
    )
