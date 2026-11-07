"""API schemas for the calendar module."""

from __future__ import annotations

from app.shared.schemas import FrozenModel


class CalendarFeedOut(FrozenModel, frozen=True):
    """Personal iCal subscription URL.

    The value is `None` until the principal generates a token.
    """

    url: str | None = None
