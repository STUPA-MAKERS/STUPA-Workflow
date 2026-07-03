"""API schemas for the calendar module."""

from __future__ import annotations

from pydantic import BaseModel


class CalendarFeedOut(BaseModel):
    """Personal iCal subscription URL; ``None`` until a token is generated."""

    url: str | None = None
