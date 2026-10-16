"""Lexorank: sort keys between two neighbors, so a move writes one row only.

A rank is a string over ``0-9a-z`` that never ends with ``0``. Strings compare
byte-wise (``todo_card.rank`` has the collation ``C``), and between two ranks there
is always a third one, because a rank can grow by one digit. This is the
fractional-indexing scheme: ``between(a, b)`` returns a rank strictly between
``a`` and ``b``; ``None`` stands for the open end of the column.

``spread(n)`` gives ``n`` evenly spaced ranks for a fresh order (the rebalance after
two cards got the same rank).
"""

from __future__ import annotations

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
_BASE = len(DIGITS)


class RankError(ValueError):
    """The bounds are not a valid open interval."""


def _digit(char: str) -> int:
    index = DIGITS.find(char)
    if index < 0:
        raise RankError(f"invalid rank digit {char!r}")
    return index


def _check(rank: str) -> None:
    if not rank or rank.endswith("0"):
        raise RankError(f"invalid rank {rank!r}")
    for char in rank:
        _digit(char)


def _midpoint(low: str, high: str | None) -> str:
    """Return a string strictly between ``low`` and ``high`` (``low`` may be empty)."""
    if high is not None:
        shared = 0
        while (low[shared] if shared < len(low) else "0") == high[shared]:
            shared += 1
        if shared > 0:
            return high[:shared] + _midpoint(low[shared:], high[shared:])
    lo = _digit(low[0]) if low else 0
    hi = _digit(high[0]) if high is not None else _BASE
    if hi - lo > 1:
        return DIGITS[(lo + hi) // 2]
    if high is not None and len(high) > 1:
        return high[0]
    return DIGITS[lo] + _midpoint(low[1:], None)


def between(low: str | None, high: str | None) -> str:
    """Return a rank strictly between ``low`` and ``high``.

    ``None`` is the open end: ``between(None, None)`` is the first rank of an empty
    column, ``between(last, None)`` appends and ``between(None, first)`` prepends.

    Raises:
        RankError: A bound is not a rank, or ``low`` is not below ``high``.
    """
    if low is not None:
        _check(low)
    if high is not None:
        _check(high)
    if low is not None and high is not None and low >= high:
        raise RankError(f"{low!r} is not below {high!r}")
    return _midpoint(low or "", high)


def spread(count: int) -> list[str]:
    """Return ``count`` evenly spaced ascending ranks for a fresh order of a column.

    All ranks have the same width before the trailing zeros go, so the order of the
    strings is the order of the numbers.
    """
    width = 1
    while _BASE**width <= count:
        width += 1
    step = _BASE**width // (count + 1)
    ranks: list[str] = []
    for index in range(1, count + 1):
        value = index * step
        chars = []
        for _ in range(width):
            value, rest = divmod(value, _BASE)
            chars.append(DIGITS[rest])
        ranks.append("".join(reversed(chars)).rstrip("0"))
    return ranks
