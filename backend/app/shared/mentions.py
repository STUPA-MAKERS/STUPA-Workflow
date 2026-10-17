"""@-mentions in a chat message: the shared rules of the comment and the note chats.

A chat message (an application comment, a ticket note) stores the principal ids of
the persons it mentions as strings in a JSONB list ``mentions``, like
``todo_comment.mentions``. The module that owns the chat decides who is mentionable.
This module holds what is the same for every chat:

- ``unique_mentions`` removes duplicates and keeps the order of the request.
- ``check_mentions`` refuses a mention outside the mentionable set with 422
  ``mention_not_member`` on the field ``mentions``.
- ``stored_mentions`` and ``mention_ids`` convert between the wire ids and the
  stored strings. A stored value that is not a UUID drops out, so a bad row never
  breaks a read.
- ``new_mentions`` returns the mentions that a write added. Only these get a mail, so
  an edit never mails the same person twice.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any
from uuid import UUID

from app.shared.errors import ValidationProblem

#: The problem code of a mention outside the mentionable set.
MENTION_NOT_MEMBER = "mention_not_member"

#: The most mentions that one message stores.
MAX_MENTIONS = 50


def mention_error() -> ValidationProblem:
    """Return the 422 problem of a mention that the caller may not make."""
    msg = "Mentions must be persons who read this chat."
    return ValidationProblem(
        msg, code=MENTION_NOT_MEMBER, errors=[{"field": "mentions", "msg": msg}]
    )


def unique_mentions(ids: Iterable[UUID]) -> list[UUID]:
    """Return ``ids`` without duplicates, in the order of their first occurrence."""
    return list(dict.fromkeys(ids))


def check_mentions(wanted: Collection[UUID], allowed: Collection[UUID]) -> None:
    """Refuse a mention outside ``allowed``.

    Raises:
        ValidationProblem: One id of ``wanted`` is not in ``allowed`` (HTTP 422,
            ``mention_not_member``).
    """
    if wanted and not set(wanted) <= set(allowed):
        raise mention_error()


def stored_mentions(ids: Sequence[UUID]) -> list[str]:
    """Return the JSONB value of ``ids``: the ids as strings."""
    return [str(pid) for pid in ids]


def mention_ids(raw: Iterable[Any] | None) -> list[UUID]:
    """Return the ids of a stored ``mentions`` value; a value that is no UUID drops out."""
    out: list[UUID] = []
    for item in raw or ():
        try:
            out.append(UUID(str(item)))
        except ValueError:
            continue
    return out


def new_mentions(wanted: Sequence[UUID], before: Iterable[UUID]) -> list[UUID]:
    """Return the ids of ``wanted`` that ``before`` does not hold, in order."""
    old = set(before)
    return [pid for pid in wanted if pid not in old]
