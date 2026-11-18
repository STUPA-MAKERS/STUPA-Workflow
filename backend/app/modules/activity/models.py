"""The table ``activity_visit``: the last visit of the activity page per person.

One row per principal. ``seen_at`` is the time up to which the person has seen the events
(spec 001275). An event after it carries the mark "neu", and the navigation shows a dot. The
row cascades with the principal. The account merge leaves the row of the source alone,
because the target has its own mark.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ActivityVisit(Base):
    """The last visit of the activity page by one principal."""

    __tablename__ = "activity_visit"

    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE"), primary_key=True
    )
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
