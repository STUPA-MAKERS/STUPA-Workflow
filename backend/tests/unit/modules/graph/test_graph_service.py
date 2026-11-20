"""The helpers of the graph service and of its reads, without a database."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from app.modules.graph.build import Relation
from app.modules.graph.relations import _date_read, as_date, builtin_reads
from app.modules.graph.service import card_opened, node_of, offset_of
from app.modules.todos.links import HIDDEN, Resolved
from app.modules.todos.models import LINK_KINDS
from app.shared.errors import ValidationProblem

CARD = ("todo", uuid.UUID(int=1))
HIDDEN_CARD = ("todo", uuid.UUID(int=2))
BUDGET = ("budget", uuid.UUID(int=3))
OTHER_BUDGET = ("budget", uuid.UUID(int=4))
APP = ("application", uuid.UUID(int=5))


def test_the_cursor_is_a_count() -> None:
    assert offset_of(None) == 0
    assert offset_of("120") == 120
    for bad in ("-1", "abc", "1.5", "١٢"):
        with pytest.raises(ValidationProblem):
            offset_of(bad)


def test_a_card_opens_the_cost_centre_of_its_link_only() -> None:
    """Spec 000552: a readable card names its cost centre; a built-in relation does not."""
    shown = Resolved(accessible=True, title="x")
    resolved = {CARD: shown, HIDDEN_CARD: HIDDEN, BUDGET: shown, OTHER_BUDGET: shown, APP: shown}
    relations = [
        Relation(BUDGET, CARD, "link"),
        Relation(HIDDEN_CARD, OTHER_BUDGET, "link"),
        Relation(APP, OTHER_BUDGET, "builtin"),
        Relation(APP, OTHER_BUDGET, "link"),
    ]
    assert card_opened(relations, resolved) == frozenset({BUDGET})


def test_a_cost_centre_needs_the_budget_right_or_a_card() -> None:
    """Spec 001422: without the budget read right a cost centre shows through a card only."""
    found = Resolved(accessible=True, title="Kultur", url="/budget?costCentre=x")
    reader = node_of(BUDGET, found, None, known=True, budget_reader=True, opened=frozenset())
    assert (reader.accessible, reader.granted, reader.url) == (True, False, found.url)

    by_card = node_of(
        BUDGET, found, None, known=True, budget_reader=False, opened=frozenset({BUDGET})
    )
    assert (by_card.accessible, by_card.granted) == (True, True)

    closed = node_of(BUDGET, found, None, known=True, budget_reader=False, opened=frozenset())
    assert (closed.accessible, closed.title) == (False, None)


def test_a_node_takes_the_resolved_element_and_its_facts() -> None:
    found = Resolved(accessible=True, title="Antrag", url="/applications/x", granted=True)
    node = node_of(
        APP, found, date(2026, 5, 1), known=True, budget_reader=False, opened=frozenset()
    )
    assert (node.title, node.url, node.granted, node.date) == (
        "Antrag",
        "/applications/x",
        True,
        date(2026, 5, 1),
    )
    for element, known in ((HIDDEN, True), (found, False)):
        gone = node_of(APP, element, None, known=known, budget_reader=True, opened=frozenset())
        assert gone.accessible is False


def test_a_date_or_a_timestamp_is_a_date() -> None:
    assert as_date(datetime(2026, 5, 1, 23, tzinfo=UTC)) == date(2026, 5, 1)
    assert as_date(date(2026, 5, 2)) == date(2026, 5, 2)
    assert as_date(None) is None


def test_every_kind_has_a_date_read_and_every_relation_two_known_kinds() -> None:
    for kind in LINK_KINDS:
        assert _date_read(kind, [uuid.UUID(int=1)]) is not None
    with pytest.raises(ValueError, match="unknown kind"):
        _date_read("wiki", [])
    for a_kind, b_kind, _ in builtin_reads():
        assert a_kind in LINK_KINDS
        assert b_kind in LINK_KINDS
