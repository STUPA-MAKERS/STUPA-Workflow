"""Application data that the mail engine needs: the bound recipients and the language.

The mail engine (`app.modules.notifications`) reads no application. A sender that mails
about an application gives the engine `application_specs` as the expander of the
recipient resolver, and reads the mail language with `resolve_application_lang`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Applicant, Application
from app.modules.budget.decision import effective_decision_gremium
from app.modules.gremien.models import Gremium
from app.settings import Settings


async def application_specs(
    session: AsyncSession, kind: str, application_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Turn a recipient kind that needs an application into plain recipient specs.

    ``applicant`` gives the applicant address; an anonymized application has none any
    more. ``voteGremium`` gives the Gremium that decides the current vote of the
    application. ``budgetGremium`` gives the effective deciding Gremium of its cost
    center. Every other kind gives no spec.
    """
    if kind == "applicant":
        email = await session.scalar(
            select(Applicant.email).where(
                Applicant.application_id == application_id,
                Applicant.anonymized_at.is_(None),
            )
        )
        return [{"kind": "email", "ref": email}] if email else []
    gremium_id = await _deciding_gremium(session, kind, application_id)
    return [{"kind": "gremium", "ref": str(gremium_id)}] if gremium_id is not None else []


async def _deciding_gremium(
    session: AsyncSession, kind: str, application_id: uuid.UUID
) -> uuid.UUID | None:
    """Return the Gremium of ``voteGremium`` or ``budgetGremium``; another kind has none."""
    match kind:
        case "voteGremium":
            return await session.scalar(
                select(Application.vote_gremium_id).where(Application.id == application_id)
            )
        case "budgetGremium":
            budget_id = await session.scalar(
                select(Application.budget_id).where(Application.id == application_id)
            )
            return await effective_decision_gremium(session, budget_id)
        case _:
            return None


async def resolve_application_lang(
    session: AsyncSession, *, application_id: uuid.UUID | None, settings: Settings
) -> str:
    """Return the mail language of an application.

    The order is: the language of the application, then the default language of its
    gremium, then the configured default language. The applicant sets the first one at
    submit time, so every mail to that applicant must follow it. Without an application
    (a magic link asked for by mail address alone) the function returns the default.
    """
    if application_id is None:
        return settings.mail_default_lang
    row = (
        await session.execute(
            select(Application.lang, Application.gremium_id).where(Application.id == application_id)
        )
    ).first()
    if row is None:
        return settings.mail_default_lang
    lang, gremium_id = row
    if lang:
        return str(lang)
    if gremium_id is not None:
        gremium_lang = await session.scalar(
            select(Gremium.default_lang).where(Gremium.id == gremium_id)
        )
        if gremium_lang:
            return str(gremium_lang)
    return settings.mail_default_lang
