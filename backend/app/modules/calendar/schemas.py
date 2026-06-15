"""API-Schemata des Kalender-Moduls (#ics)."""

from __future__ import annotations

from pydantic import BaseModel


class CalendarFeedOut(BaseModel):
    """Persönliche iCal-Abo-URL. ``url`` ist ``None``, solange kein Token erzeugt wurde."""

    url: str | None = None
