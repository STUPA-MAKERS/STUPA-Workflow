"""Pure domain logic of the budget tree. The tests cover every branch (critical, 100 %).

The constraints come from CR #76/#78: path composition, fiscal year disjointness (R7.1f),
top-down allocation (R7.1b) and roll-up of the bound sum (R7.1c).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.modules.budget import tree_rules as r


def test_is_valid_key() -> None:
    assert r.is_valid_key("VS")
    assert r.is_valid_key("800")
    assert not r.is_valid_key("VS-800")  # the separator is not allowed
    assert not r.is_valid_key("")
    # Length limit (#sec-audit): exactly _KEY_MAX is valid, one more is rejected.
    assert r.is_valid_key("A" * r._KEY_MAX)
    assert not r.is_valid_key("A" * (r._KEY_MAX + 1))


def test_compose_path_key() -> None:
    assert r.compose_path_key(None, "VS") == "VS"
    assert r.compose_path_key("VS-800", "04") == "VS-800-04"


def test_descendant_paths() -> None:
    assert r.is_descendant_path("VS", "VS-800")
    assert r.is_descendant_path("VS-800", "VS-800-04")
    assert not r.is_descendant_path("VS", "VST")  # the separator stops a false prefix match
    assert not r.is_descendant_path("VS", "VS")
    assert r.is_self_or_descendant_path("VS", "VS")
    assert r.is_self_or_descendant_path("VS", "VS-800")
    assert not r.is_self_or_descendant_path("VS", "WS")


def test_intervals_overlap() -> None:
    d = date
    assert r.intervals_overlap(d(2026, 1, 1), d(2026, 6, 1), d(2026, 5, 1), d(2026, 12, 1))
    # b lies fully after a, so there is no overlap and the second AND branch is false
    assert not r.intervals_overlap(d(2026, 1, 1), d(2026, 6, 1), d(2026, 7, 1), d(2026, 12, 1))
    # b lies fully before a, so there is no overlap and the first AND branch is false
    assert not r.intervals_overlap(d(2026, 7, 1), d(2026, 12, 1), d(2026, 1, 1), d(2026, 6, 1))


def test_overlaps_any() -> None:
    d = date
    existing = [(d(2025, 1, 1), d(2025, 12, 31)), (d(2027, 1, 1), d(2027, 12, 31))]
    assert not r.overlaps_any(d(2026, 1, 1), d(2026, 12, 31), existing)  # a gap is allowed
    assert r.overlaps_any(d(2025, 6, 1), d(2026, 6, 1), existing)
    assert not r.overlaps_any(d(2026, 1, 1), d(2026, 6, 1), [])


def test_as_amount() -> None:
    assert r.as_amount(None) == Decimal("0")
    assert r.as_amount(Decimal("5")) == Decimal("5")


def test_children_allocation_exceeds_parent() -> None:
    parent = Decimal("1000")
    # 600 (siblings) + 500 = 1100 > 1000 → exceeds
    assert r.children_allocation_exceeds_parent(parent, Decimal("600"), Decimal("500"))
    # 600 + 400 = 1000 ≤ 1000 → ok
    assert not r.children_allocation_exceeds_parent(parent, Decimal("600"), Decimal("400"))
    # without a parent budget every positive child allocation breaks the rule
    assert r.children_allocation_exceeds_parent(None, Decimal("0"), Decimal("1"))


def test_parent_allocation_below_children() -> None:
    assert r.parent_allocation_below_children(Decimal("500"), Decimal("700"))
    assert not r.parent_allocation_below_children(Decimal("800"), Decimal("700"))


def test_node_available() -> None:
    assert r.node_available(Decimal("1000"), Decimal("300")) == Decimal("700")
    assert r.node_available(None, Decimal("0")) == Decimal("0")


def test_pick_fiscal_year() -> None:
    one = uuid.uuid4()
    assert r.pick_fiscal_year([one]) == one
    assert r.pick_fiscal_year([]) is None
    assert r.pick_fiscal_year([uuid.uuid4(), uuid.uuid4()]) is None


def test_rollup_committed() -> None:
    nodes = [("top", "VS"), ("mid", "VS-800"), ("leaf", "VS-800-04"), ("other", "WS")]
    leaves = [("VS-800-04", Decimal("100")), ("VS-800-04", None), ("WS", Decimal("5"))]
    out = r.rollup_committed(nodes, leaves)
    assert out["leaf"] == Decimal("100")  # own use, with None counted as 0
    assert out["mid"] == Decimal("100")   # roll-up from the child
    assert out["top"] == Decimal("100")   # roll-up up to the root
    assert out["other"] == Decimal("5")   # separate subtree


def _node(  # noqa: ANN001
    nid, parent, gremium, key, path, name="N", currency="EUR", active=True,
    color=None, accepted=(), denied=(), fiscal_start_month=1, fiscal_start_day=1,
    hidden_in_budget=False, view_gremium_id=None,
):
    return (
        nid, parent, gremium, key, path, name, currency, active,
        color, list(accepted), list(denied), fiscal_start_month, fiscal_start_day,
        hidden_in_budget, view_gremium_id,
    )


def test_build_forest_tree_and_rollup() -> None:
    g = uuid.uuid4()
    fy = uuid.uuid4()
    nodes = [
        _node("top", None, g, "VS", "VS"),
        _node("mid", "top", None, "800", "VS-800"),
        _node("leaf", "mid", None, "04", "VS-800-04"),
        _node("empty", "top", None, "900", "VS-900"),  # no allocation and no use
    ]
    allocations = [("top", fy, Decimal("1000")), ("mid", fy, Decimal("400"))]
    committed = [(fy, "VS-800-04", Decimal("250"))]
    forest = r.build_forest(nodes, allocations, committed)
    assert len(forest) == 1
    top = forest[0]
    assert top["id"] == "top"
    top_view = top["by_fiscal_year"][0]
    assert top_view["allocated"] == Decimal("1000")
    assert top_view["committed"] == Decimal("250")     # roll-up up to the root
    assert top_view["available"] == Decimal("750")
    children = {c["id"]: c for c in top["children"]}
    mid = children["mid"]
    assert mid["by_fiscal_year"][0]["committed"] == Decimal("250")
    assert mid["by_fiscal_year"][0]["available"] == Decimal("150")  # 400-250
    # 'empty' has no allocation and no use, so the filter drops the views with committed 0
    assert children["empty"]["by_fiscal_year"] == []
    leaf = mid["children"][0]
    assert leaf["by_fiscal_year"][0]["committed"] == Decimal("250")


def test_build_forest_gremium_filter() -> None:
    g1, g2 = uuid.uuid4(), uuid.uuid4()
    nodes = [
        _node("a", None, g1, "A", "A"),
        _node("b", None, g2, "B", "B"),
    ]
    assert {n["id"] for n in r.build_forest(nodes, [], [])} == {"a", "b"}
    only = r.build_forest(nodes, [], [], gremium_id=g1)
    assert {n["id"] for n in only} == {"a"}


def test_fiscal_year_bounds() -> None:
    assert r.fiscal_year_bounds(2026, 1, 1) == (date(2026, 1, 1), date(2026, 12, 31))
    assert r.fiscal_year_bounds(2026, 7, 1) == (date(2026, 7, 1), date(2027, 6, 30))


def test_is_valid_fiscal_start() -> None:
    # Day 1 to 28 is valid in every month.
    assert r.is_valid_fiscal_start(1, 1)
    assert r.is_valid_fiscal_start(12, 28)
    # Day 29 and later can be missing in a month, so the code rejects it. A month outside
    # 1 to 12 is invalid as well.
    assert not r.is_valid_fiscal_start(2, 30)
    assert not r.is_valid_fiscal_start(4, 31)
    assert not r.is_valid_fiscal_start(0, 1)
    assert not r.is_valid_fiscal_start(13, 1)
    assert not r.is_valid_fiscal_start(1, 0)


def test_fiscal_year_bounds_rejects_impossible_stichtag() -> None:
    # An impossible cut-off date such as 30.02. or 31.04. raises ValueError instead of a
    # 500 at INSERT time.
    import pytest

    with pytest.raises(ValueError, match="invalid fiscal start"):
        r.fiscal_year_bounds(2026, 2, 30)
    with pytest.raises(ValueError, match="invalid fiscal start"):
        r.fiscal_year_bounds(2026, 4, 31)


def test_fiscal_year_display() -> None:
    # A cut-off date of 01.01. gives a plain year. Any other date gives YYYY/YY with the
    # short next year.
    assert r.fiscal_year_display(2026, 1, 1) == "2026"
    assert r.fiscal_year_display(2026, 7, 1) == "2026/27"
    assert r.fiscal_year_display(2099, 4, 1) == "2099/00"
    assert r.fiscal_year_display(2026, 1, 2) == "2026/27"  # a day other than 1 is not plain


def test_build_forest_carries_stichtag() -> None:
    nodes = [_node("t", None, uuid.uuid4(), "VS", "VS", fiscal_start_month=7, fiscal_start_day=1)]
    forest = r.build_forest(nodes, [], [])
    assert forest[0]["fiscal_start_month"] == 7 and forest[0]["fiscal_start_day"] == 1


def test_build_forest_committed_only_node() -> None:
    # A node with use but without an allocation gets a view with allocated 0.
    fy = uuid.uuid4()
    nodes = [_node("leaf", None, uuid.uuid4(), "L", "L")]
    forest = r.build_forest(nodes, [], [(fy, "L", Decimal("30"))])
    view = forest[0]["by_fiscal_year"][0]
    assert view["allocated"] == Decimal("0")
    assert view["committed"] == Decimal("30")
    assert view["available"] == Decimal("-30")


# Gremium scope (#budget-scope)
def test_scope_forest_picks_assigned_subtrees_as_roots() -> None:
    g = uuid.uuid4()
    nodes = [
        _node("top", None, None, "VS", "VS"),
        _node("mid", "top", None, "800", "VS-800", view_gremium_id=g),
        _node("leaf", "mid", None, "04", "VS-800-04"),
        _node("other", "top", None, "900", "VS-900"),
    ]
    forest = r.build_forest(nodes, [], [])
    scoped = r.scope_forest(forest, {g})
    assert [n["id"] for n in scoped] == ["mid"]
    assert [c["id"] for c in scoped[0]["children"]] == ["leaf"]


def test_scope_forest_outer_assignment_wins_and_empty_scope() -> None:
    g = uuid.uuid4()
    nodes = [
        _node("top", None, None, "VS", "VS", view_gremium_id=g),
        _node("mid", "top", None, "800", "VS-800", view_gremium_id=g),
    ]
    forest = r.build_forest(nodes, [], [])
    scoped = r.scope_forest(forest, {g})
    assert [n["id"] for n in scoped] == ["top"]  # the outer subtree wins, with no duplicate
    assert r.scope_forest(forest, set()) == []
    assert r.scope_forest(forest, {uuid.uuid4()}) == []


def test_fiscal_year_delete_blocker_reports_first_reason() -> None:
    assert r.fiscal_year_delete_blocker(False, False, False) is None
    assert r.fiscal_year_delete_blocker(True, False, False) == "bookings"
    assert r.fiscal_year_delete_blocker(False, True, False) == "allocations"
    assert r.fiscal_year_delete_blocker(False, False, True) == "applications"
    # Bookings win over the other two, so the message names the strongest reason.
    assert r.fiscal_year_delete_blocker(True, True, True) == "bookings"
    assert r.fiscal_year_delete_blocker(False, True, True) == "allocations"


def test_transfer_pair_changed() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    # Omitting both ends changes nothing, and repeating the pair changes nothing.
    assert not r.transfer_pair_changed(a, b, None, None)
    assert not r.transfer_pair_changed(a, b, a, b)
    assert not r.transfer_pair_changed(a, b, a, None)
    assert not r.transfer_pair_changed(a, b, None, b)
    # A different source or a different target is a different transfer.
    assert r.transfer_pair_changed(a, b, b, None)
    assert r.transfer_pair_changed(a, b, None, a)
    assert r.transfer_pair_changed(a, b, b, a)
