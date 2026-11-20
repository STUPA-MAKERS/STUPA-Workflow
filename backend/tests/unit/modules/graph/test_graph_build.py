"""The rules of the graph (specs 001422-001426), without a database."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.modules.graph.build import (
    Filters,
    Node,
    Ref,
    Relation,
    merged,
    page_of,
    passes,
    shown,
)


def _ref(kind: str, number: int) -> Ref:
    return (kind, uuid.UUID(int=number))


APP = _ref("application", 1)
OLD_APP = _ref("application", 2)
MEETING = _ref("meeting", 3)
TOP = _ref("agenda_item", 4)
INVOICE = _ref("invoice", 5)
GREMIUM = _ref("gremium", 6)
CARD = _ref("todo", 7)
LONELY = _ref("ticket", 8)


def _node(ref: Ref, day: date | None = None, **more: object) -> Node:
    return Node(ref=ref, accessible=True, title=f"{ref[0]} {ref[1].int}", date=day, **more)  # type: ignore[arg-type]


def _nodes(*nodes: Node) -> dict[Ref, Node]:
    return {n.ref: n for n in nodes}


def _refs(nodes: tuple[Node, ...]) -> list[Ref]:
    return [n.ref for n in nodes]


def _pairs(lines: tuple[Relation, ...]) -> set[frozenset[Ref]]:
    return {frozenset((r.a, r.b)) for r in lines}


def test_a_link_wins_over_a_builtin_relation_of_the_same_pair() -> None:
    """Spec 001424: two elements with both relations show one solid line."""
    lines = merged(
        [
            Relation(APP, TOP, "link"),
            Relation(TOP, APP, "builtin"),
            Relation(TOP, MEETING, "builtin"),
            Relation(APP, APP, "link"),
        ]
    )
    assert {(frozenset((r.a, r.b)), r.source) for r in lines} == {
        (frozenset((APP, TOP)), "link"),
        (frozenset((TOP, MEETING)), "builtin"),
    }


def test_a_node_shows_only_with_a_relation() -> None:
    """Spec 001423: a single element shows with the switch only."""
    candidates = _nodes(
        _node(APP, date(2026, 5, 1)), _node(TOP, date(2026, 6, 1)), _node(LONELY, date(2026, 7, 1))
    )
    relations = [Relation(APP, TOP, "builtin")]

    nodes, lines = shown(candidates, relations, Filters())
    assert _refs(nodes) == [TOP, APP]
    assert _pairs(lines) == {frozenset((APP, TOP))}

    with_single, _ = shown(candidates, relations, Filters(single=True))
    assert _refs(with_single) == [LONELY, TOP, APP]


def test_an_unreadable_end_hides_with_its_line() -> None:
    """Spec 001422: no node, no line and nothing else of a hidden element."""
    candidates = _nodes(
        _node(APP, date(2026, 5, 1)),
        Node(ref=INVOICE, accessible=False),
        Node(ref=CARD, accessible=False),
    )
    relations = [Relation(APP, INVOICE, "link"), Relation(INVOICE, CARD, "link")]

    nodes, lines = shown(candidates, relations, Filters())
    assert nodes == ()
    assert lines == ()

    grey, grey_lines = shown(candidates, relations, Filters(no_access=True, single=True))
    assert _refs(grey) == [APP, INVOICE]
    assert [n.accessible for n in grey] == [True, False]
    assert grey[1].title is None
    assert _pairs(grey_lines) == {frozenset((APP, INVOICE))}


def test_the_kind_filter_drops_nodes_and_their_lines() -> None:
    """Spec 001425: only nodes of the chosen kinds show."""
    candidates = _nodes(
        _node(APP, date(2026, 5, 1)), _node(TOP, date(2026, 6, 1)), _node(MEETING, date(2026, 6, 1))
    )
    relations = [Relation(APP, TOP, "builtin"), Relation(TOP, MEETING, "builtin")]

    nodes, lines = shown(
        candidates, relations, Filters(kinds=frozenset({"agenda_item", "meeting"}))
    )
    assert set(_refs(nodes)) == {TOP, MEETING}
    assert _pairs(lines) == {frozenset((TOP, MEETING))}


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 6, 1), None, {TOP, GREMIUM}),
        (None, date(2026, 5, 31), {APP, GREMIUM}),
        (date(2026, 5, 1), date(2026, 6, 1), {APP, TOP, GREMIUM}),
        (date(2027, 1, 1), None, set()),
    ],
)
def test_the_period_keeps_dated_nodes_inside_and_undated_kinds(
    start: date | None, end: date | None, expected: set[Ref]
) -> None:
    """Spec 001425: a Gremium has no date and passes every period, a meeting without a date not."""
    candidates = _nodes(
        _node(APP, date(2026, 5, 1)), _node(TOP, date(2026, 6, 1)), _node(GREMIUM), _node(MEETING)
    )
    relations = [
        Relation(APP, GREMIUM, "link"),
        Relation(TOP, GREMIUM, "link"),
        Relation(MEETING, GREMIUM, "builtin"),
    ]
    nodes, _ = shown(candidates, relations, Filters(start=start, end=end))
    assert set(_refs(nodes)) == expected


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("all", {frozenset((APP, TOP)), frozenset((TOP, MEETING))}),
        ("links", {frozenset((APP, TOP))}),
        ("builtin", {frozenset((TOP, MEETING))}),
    ],
)
def test_the_relation_filter(choice: str, expected: set[frozenset[Ref]]) -> None:
    """Spec 001424: all, links only, built-in only."""
    candidates = _nodes(
        _node(APP, date(2026, 5, 1)), _node(TOP, date(2026, 6, 1)), _node(MEETING, date(2026, 6, 1))
    )
    relations = [Relation(APP, TOP, "link"), Relation(TOP, MEETING, "builtin")]
    _, lines = shown(candidates, relations, Filters(relations=choice))  # type: ignore[arg-type]
    assert _pairs(lines) == expected


def test_the_search_shows_the_hits_and_their_neighbours() -> None:
    """Specs 001425, 001434: a hit and its neighbours one step away."""
    candidates = _nodes(
        Node(ref=APP, accessible=True, title="Erstiparty", date=date(2026, 5, 1)),
        Node(ref=TOP, accessible=True, title="TOP 3", date=date(2026, 6, 1)),
        Node(ref=MEETING, accessible=True, title="Sitzung", date=date(2026, 6, 1)),
        Node(ref=LONELY, accessible=True, title="Party-Ticket", date=date(2026, 4, 1)),
        Node(ref=INVOICE, accessible=False),
    )
    relations = [
        Relation(APP, TOP, "builtin"),
        Relation(TOP, MEETING, "builtin"),
        Relation(APP, INVOICE, "link"),
    ]

    nodes, lines = shown(candidates, relations, Filters(q="  PARTY ", depth=1))
    assert set(_refs(nodes)) == {APP, TOP}
    assert _pairs(lines) == {frozenset((APP, TOP))}

    with_single, _ = shown(candidates, relations, Filters(q="party", single=True, depth=1))
    assert set(_refs(with_single)) == {APP, TOP, LONELY}

    grey, _ = shown(candidates, relations, Filters(q="party", no_access=True, depth=1))
    assert set(_refs(grey)) == {APP, TOP, INVOICE}


def test_the_neighbours_of_a_hit_show_up_to_the_steps() -> None:
    """Spec 001434: a neighbour shows also when it does not pass the filters."""
    candidates = _nodes(
        Node(ref=APP, accessible=True, title="Erstiparty", date=date(2026, 5, 1)),
        Node(ref=TOP, accessible=True, title="TOP 3", date=date(2020, 6, 1)),
        Node(ref=MEETING, accessible=True, title="Sitzung", date=date(2020, 6, 1)),
        Node(ref=GREMIUM, accessible=True, title="StuPa"),
        Node(ref=CARD, accessible=True, title="Karte", date=date(2020, 1, 1)),
        Node(ref=INVOICE, accessible=False),
        Node(ref=LONELY, accessible=True, title="Ticket", date=date(2020, 1, 1)),
    )
    relations = [
        Relation(APP, TOP, "link"),
        Relation(TOP, MEETING, "link"),
        Relation(MEETING, CARD, "link"),
        Relation(TOP, GREMIUM, "builtin"),
        Relation(APP, INVOICE, "link"),
        Relation(INVOICE, LONELY, "link"),
    ]
    hit = {"kinds": frozenset({"application"}), "start": date(2026, 1, 1), "q": "party"}

    def refs(**more: object) -> set[Ref]:
        nodes, _ = shown(candidates, relations, Filters(**hit, relations="links", **more))
        return set(_refs(nodes))

    assert refs(depth=0) == set()
    assert refs(depth=0, single=True) == {APP}
    assert refs(depth=1) == {APP, TOP}
    assert refs(depth=2) == {APP, TOP, MEETING}
    assert refs(depth=3) == {APP, TOP, MEETING, CARD}
    # A neighbour without a line is no hit: the switch does not add it.
    assert refs(depth=1, single=True) == {APP, TOP}
    # An element that the reader does not read shows with its switch only, and a step
    # leads through it.
    assert refs(depth=2, no_access=True) == {APP, TOP, MEETING, INVOICE, LONELY}

    every, lines = shown(candidates, relations, Filters(**hit, depth=2))  # type: ignore[arg-type]
    assert set(_refs(every)) == {APP, TOP, MEETING, GREMIUM}
    assert _pairs(lines) == {
        frozenset((APP, TOP)),
        frozenset((TOP, MEETING)),
        frozenset((TOP, GREMIUM)),
    }


def test_a_node_without_a_date_comes_with_its_newest_neighbour() -> None:
    """Spec 001426: the newest first, a Gremium next to the element that it connects."""
    candidates = _nodes(
        _node(APP, date(2026, 5, 1)),
        _node(OLD_APP, date(2025, 1, 1)),
        _node(TOP, date(2026, 6, 1)),
        _node(GREMIUM),
        _node(CARD),
        _node(MEETING),
    )
    relations = [
        Relation(GREMIUM, APP, "link"),
        Relation(GREMIUM, OLD_APP, "link"),
        Relation(TOP, OLD_APP, "builtin"),
        Relation(CARD, MEETING, "link"),
    ]
    nodes, _ = shown(candidates, relations, Filters())
    assert _refs(nodes) == [TOP, APP, GREMIUM, OLD_APP, MEETING, CARD]


def test_a_page_holds_each_line_once_and_never_before_its_nodes() -> None:
    """Spec 001431: a line comes with the page of its later end."""
    candidates = _nodes(
        _node(TOP, date(2026, 6, 1)),
        _node(APP, date(2026, 5, 1)),
        _node(OLD_APP, date(2025, 1, 1)),
        _node(MEETING, date(2024, 1, 1)),
    )
    relations = [
        Relation(TOP, APP, "builtin"),
        Relation(APP, OLD_APP, "builtin"),
        Relation(TOP, MEETING, "builtin"),
    ]
    nodes, lines = shown(candidates, relations, Filters())

    first, first_lines, following = page_of(nodes, lines, 0, size=2)
    assert _refs(first) == [TOP, APP]
    assert _pairs(first_lines) == {frozenset((TOP, APP))}
    assert following == 2

    second, second_lines, end = page_of(nodes, lines, 2, size=2)
    assert _refs(second) == [OLD_APP, MEETING]
    assert _pairs(second_lines) == {frozenset((APP, OLD_APP)), frozenset((TOP, MEETING))}
    assert end is None

    assert page_of(nodes, lines, 9) == ((), (), None)


def test_an_unreadable_node_skips_the_period() -> None:
    """Spec 001422: the period would tell the facts of a hidden element."""
    hidden = Node(ref=INVOICE, accessible=False)
    assert passes(hidden, Filters()) is False
    assert passes(hidden, Filters(no_access=True, start=date(2026, 1, 1))) is True
    assert passes(hidden, Filters(no_access=True, kinds=frozenset({"todo"}))) is False
