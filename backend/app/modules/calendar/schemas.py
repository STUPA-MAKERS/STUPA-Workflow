"""API schemas for the calendar module."""

from __future__ import annotations

from pydantic import BaseModel


class CalendarFeedOut(BaseModel):
    """Personal iCal subscription URL.

    The value is `None` until the principal generates a token.
    """

    url: str | None = None
