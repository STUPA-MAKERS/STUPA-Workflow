"""Group pairs by their key without a mutable accumulator (§ S/shared/functional/000085)."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import groupby
from operator import itemgetter


def grouped[K, V](pairs: Iterable[tuple[K, V]]) -> dict[K, tuple[V, ...]]:
    """Group the values by their key; the keys and the values keep their first order.

    The stable sort by the first position of each key keeps the order of the values.
    """
    items = tuple(pairs)
    first = {key: index for index, key in enumerate(dict.fromkeys(key for key, _ in items))}
    ranked = sorted(items, key=lambda pair: first[pair[0]])
    return {
        key: tuple(value for _, value in group) for key, group in groupby(ranked, key=itemgetter(0))
    }


__all__ = ["grouped"]
