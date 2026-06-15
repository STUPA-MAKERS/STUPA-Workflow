"""Kalender-Feed: Token-Verwaltung + Sitzungs-Datenzugriff (#ics).

Der Feed-Token (``principal.calendar_token``) authentifiziert die ``.ics``-URL
ohne Session/OIDC. Er wird über ``/calendar/me/rotate`` erzeugt/rotiert (alte URL
wird ungültig). Klartext-Speicherung ist hier vertretbar: der Token exponiert
ausschließlich Sitzungstitel/-zeiten der eigenen Gremien (low-sensitivity).

Alle Funktionen sind an ``principal.sub`` gebunden (der aufgelöste ``Principal``
trägt nur ``sub``, nicht die DB-``id``) und committen **nicht** selbst.
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import gremium_member_ids
from app.modules.admin.models import Gremium
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.models import Meeting

# 32 Byte → ~43 Zeichen URL-safe; nicht erratbar, kein Rate-Limit nötig.
_TOKEN_BYTES = 32


def generate_calendar_token() -> str:
    """Neuen, nicht erratbaren Feed-Token erzeugen (URL-safe, ohne ``.``/``/``)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


async def _row_by_sub(db: AsyncSession, sub: str) -> PrincipalRow | None:
    return (
        await db.execute(select(PrincipalRow).where(PrincipalRow.sub == sub))
    ).scalar_one_or_none()


async def get_calendar_token(db: AsyncSession, sub: str) -> str | None:
    """Aktuellen Feed-Token des Principals lesen (``None`` = noch keiner erzeugt)."""
    row = await _row_by_sub(db, sub)
    return row.calendar_token if row is not None else None


async def rotate_calendar_token(db: AsyncSession, sub: str) -> str | None:
    """Feed-Token neu erzeugen (alte Subscription-URL wird ungültig). Committet nicht.

    ``None`` nur, wenn der Principal nicht (mehr) existiert.
    """
    row = await _row_by_sub(db, sub)
    if row is None:
        return None
    row.calendar_token = generate_calendar_token()
    await db.flush()
    return row.calendar_token


async def principal_by_calendar_token(
    db: AsyncSession, token: str
) -> PrincipalRow | None:
    """Aktiven Principal zu einem Feed-Token auflösen (oder ``None``).

    Leerer Token bzw. deaktivierter/​unbekannter Principal ⇒ ``None`` (der Feed
    antwortet dann 404, ohne »falscher Token« von »deaktiviert« zu unterscheiden).
    """
    if not token:
        return None
    return (
        await db.execute(
            select(PrincipalRow).where(
                PrincipalRow.calendar_token == token,
                PrincipalRow.active.is_(True),
            )
        )
    ).scalar_one_or_none()


async def member_meetings(db: AsyncSession, sub: str) -> list[tuple[Meeting, str]]:
    """Datierte Sitzungen der Gremien, in denen ``sub`` Mitglied ist.

    Liefert ``(Meeting, gremium_name)``-Paare nach Datum/Startzeit sortiert. Sitzungen
    ohne Datum werden ausgelassen (nicht im Kalender platzierbar).
    """
    gremium_ids = await gremium_member_ids(db, sub)
    if not gremium_ids:
        return []
    rows = (
        await db.execute(
            select(Meeting, Gremium.name)
            .join(Gremium, Gremium.id == Meeting.gremium_id)
            .where(
                Meeting.gremium_id.in_(gremium_ids),
                Meeting.date.isnot(None),
            )
            .order_by(Meeting.date, Meeting.start_time)
        )
    ).all()
    return [(meeting, name) for meeting, name in rows]
