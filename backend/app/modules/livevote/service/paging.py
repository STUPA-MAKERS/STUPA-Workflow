"""Cursor and sort-key helpers for the meeting timeline."""

from __future__ import annotations

import base64
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time as _time
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, cast, func

from app.modules.livevote.models import Meeting
from app.shared.errors import BadRequestError

# Timeline sort and boundary key: the scheduled moment of the meeting. A missing
# time means midnight. A missing date (an openly planned meeting) sorts the meeting
# to the far future.
_MIDNIGHT = _time(0, 0)
_UNDATED_FALLBACK = _date(9999, 12, 31)


def _sort_ts_expr() -> Any:
    """SQL expression ``date + start_time`` as ``timestamp`` (keyset key)."""
    return cast(
        func.coalesce(Meeting.date, _UNDATED_FALLBACK)
        + func.coalesce(Meeting.start_time, _MIDNIGHT),
        DateTime,
    )


def _encode_cursor(ts: _datetime, meeting_id: UUID) -> str:
    """Opaque keyset cursor from (sort timestamp, id)."""
    raw = f"{ts.isoformat()}|{meeting_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[_datetime, UUID] | None:
    """Decode a keyset cursor into a timestamp and an id.

    Returns:
        The pair from the cursor, or ``None`` for an empty cursor.

    Raises:
        BadRequestError: The cursor is malformed.
    """
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return _datetime.fromisoformat(ts_str), UUID(id_str)
    except (ValueError, TypeError) as exc:
        raise BadRequestError("invalid pagination cursor") from exc


def _encode_offset(offset: int) -> str:
    """Opaque offset cursor for the search timeline (relevance ranking, no keyset)."""
    return base64.urlsafe_b64encode(f"o|{offset}".encode()).decode()


def _decode_offset(cursor: str | None) -> int:
    """Decode an offset cursor.

    Returns:
        The offset, or ``0`` for an empty cursor.

    Raises:
        BadRequestError: The cursor is malformed or the offset is negative.
    """
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        tag, num = raw.split("|", 1)
        if tag != "o":
            raise ValueError("not an offset cursor")
        offset = int(num)
        if offset < 0:
            raise ValueError("negative offset")
        return offset
    except (ValueError, TypeError) as exc:
        raise BadRequestError("invalid pagination cursor") from exc
