"""Lexorank: a rank between any two neighbors, the open ends, and the rebalance."""

from __future__ import annotations

import random

import pytest

from app.modules.todos.lexorank import RankError, between, spread


def test_the_open_ends() -> None:
    first = between(None, None)
    assert first == "i"
    assert between(first, None) > first
    assert between(None, first) < first


@pytest.mark.parametrize(
    ("low", "high"),
    [
        ("a", "b"),
        ("a", "b1"),
        ("a", "a1"),
        ("az", "b"),
        ("1", "2"),
        ("y", "z"),
        ("zz", None),
        (None, "01"),
    ],
)
def test_between_lies_strictly_inside(low: str | None, high: str | None) -> None:
    rank = between(low, high)
    assert (low is None or low < rank) and (high is None or rank < high)
    assert not rank.endswith("0")


def test_many_inserts_keep_the_order() -> None:
    rng = random.Random(7)
    ranks = [between(None, None)]
    for _ in range(400):
        index = rng.randint(0, len(ranks))
        low = ranks[index - 1] if index > 0 else None
        high = ranks[index] if index < len(ranks) else None
        ranks.insert(index, between(low, high))
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


@pytest.mark.parametrize(
    ("low", "high"), [("b", "a"), ("a", "a"), ("", None), ("a0", None), ("A", None), (None, "-")]
)
def test_invalid_bounds_raise(low: str | None, high: str | None) -> None:
    with pytest.raises(RankError):
        between(low, high)


@pytest.mark.parametrize("count", [1, 2, 35, 36, 1300])
def test_spread_is_sorted_and_unique(count: int) -> None:
    ranks = spread(count)
    assert len(ranks) == count
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == count
    assert all(r and not r.endswith("0") for r in ranks)
