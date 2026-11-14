"""Pure budget-tree domain logic without database access.

All cost center tree decisions live here as pure functions. They are
deterministic and testable without a backing service. The service layer stays
thin I/O wiring.

Rule of thumb: allocation flows DOWN (top-down, NO roll-up). Consumption flows
UP (roll-up of the bound sum from approved applications).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

#: Path segment: alphanumeric, for example `VS`, `800` or `04`. Path composition
#: reserves the separator `-`, so a segment must not contain it.
_KEY_RE = re.compile(r"[A-Za-z0-9]+")
_SEP = "-"
_ZERO = Decimal(0)
#: Length cap per path segment. It matches `max_length` in the schemas and bounds
#: the free text in the `tree_path` prefix comparisons.
_KEY_MAX = 64


def is_valid_key(key: str) -> bool:
    """Check for a valid path segment: alphanumeric, no `-`, length-capped.

    The whole text must match, because `$` also matches before a line feed at the end.
    """
    return len(key) <= _KEY_MAX and _KEY_RE.fullmatch(key) is not None


def compose_tree_path(parent_path: str | None, key: str) -> str:
    """Compose the tree path, the keys from the top level down with `-` between them.

    A top-level node gets `key`. Any other node gets `<parent_path>-<key>`. The tree
    path says where a node is in the tree. No person reads it.
    """
    return key if parent_path is None else f"{parent_path}{_SEP}{key}"


def path_key_of(tree_path: str) -> str:
    """Give the path key that a person reads: `VSM-80133` for the tree path `VSM-801-33`.

    The key of the top level, one hyphen, then the keys of each level with nothing
    between them. The path key of a top-level node is its key.
    """
    top, _, below = tree_path.partition(_SEP)
    return f"{top}{_SEP}{below.replace(_SEP, '')}" if below else top


def is_descendant_path(ancestor_path: str, node_path: str) -> bool:
    """Check whether `node_path` lies strictly below `ancestor_path`.

    The check follows the prefix of the tree path (`VS` > `VS-800` > `VS-800-04`).
    The node itself does NOT count as a descendant.
    """
    return node_path.startswith(ancestor_path + _SEP)


def is_self_or_descendant_path(ancestor_path: str, node_path: str) -> bool:
    """Check for the node itself OR a descendant.

    Roll-up aggregation uses this rule, so a leaf counts toward itself.
    """
    return node_path == ancestor_path or is_descendant_path(ancestor_path, node_path)


def fiscal_year_delete_blocker(
    has_bookings: bool, has_allocations: bool, has_applications: bool
) -> str | None:
    """Name the first reason that blocks the delete of a fiscal year.

    A fiscal year carries money rows. `budget_allocation` and `budget_expense`
    hang on it with `ON DELETE CASCADE`, so a delete would silently drop the
    planning figures and the bookings. `application.fiscal_year_id` has no
    cascade at all, so a delete would fail on the foreign key. All three cases
    therefore refuse the delete with 409, and the user clears the rows first.

    Returns:
        The blocking reason, or `None` when the delete may proceed.
    """
    match (has_bookings, has_allocations, has_applications):
        case (True, _, _):
            return "bookings"
        case (_, True, _):
            return "allocations"
        case (_, _, True):
            return "applications"
        case _:
            return None


def transfer_pair_changed(
    current_from: object,
    current_to: object,
    requested_from: object | None,
    requested_to: object | None,
) -> bool:
    """Tell whether a transfer patch asks for a different pair of cost centres.

    The two cost centres of a transfer are immutable. A different pair is a
    different transfer, so the caller books a new one instead. A patch that
    repeats the current pair, or that omits both fields, changes nothing.
    """
    from_changed = requested_from is not None and requested_from != current_from
    return from_changed or (requested_to is not None and requested_to != current_to)


def as_amount(value: Decimal | None) -> Decimal:
    """Return 0 for `None`, else the amount."""
    return value if value is not None else _ZERO


def children_allocation_exceeds_parent(
    parent_allocated: Decimal | None,
    siblings_sum_excluding: Decimal,
    new_value: Decimal,
) -> bool:
    """Check whether a new child allocation exceeds the parent budget.

    A missing parent allocation counts as 0. Any positive child allocation then
    breaks the rule, because top-down distribution has nothing to hand out.
    `siblings_sum_excluding` is the sum of the allocations of the OTHER direct
    children.
    """
    return siblings_sum_excluding + new_value > as_amount(parent_allocated)


def parent_allocation_below_children(
    new_parent_value: Decimal,
    children_sum: Decimal,
) -> bool:
    """Check whether the new parent allocation drops below the distributed sum.

    The distributed sum covers the allocations the children already hold. The
    service maps a violation to 422.
    """
    return new_parent_value < children_sum


def rollup_committed(
    node_paths: Iterable[tuple[object, str]],
    leaf_amounts: Iterable[tuple[str, Decimal | None]],
) -> dict[object, Decimal]:
    """Roll the approved application amounts up into a bound sum per node.

    Each application counts toward its own cost center and toward every
    ancestor through the path prefix. Consumption flows up. The allocated
    amount stays untouched.

    Args:
        node_paths: `(node_id, tree_path)` of every tree node.
        leaf_amounts: `(leaf_tree_path, amount)` per bound application.

    Returns:
        The bound sum per node id.
    """
    leaves = tuple((path, as_amount(amount)) for path, amount in leaf_amounts)
    return {
        node_id: sum(
            (
                amount
                for leaf_path, amount in leaves
                if is_self_or_descendant_path(node_path, leaf_path)
            ),
            _ZERO,
        )
        for node_id, node_path in node_paths
    }


def node_available(
    allocated: Decimal | None,
    bound: Decimal,
    expended: Decimal = _ZERO,
    income: Decimal = _ZERO,
) -> Decimal:
    """Compute the free sum of a node.

    The formula is `available = allocated - bound - expended + income`. Bound
    counts the accepted applications, reduced pro rata by the expenses bound to
    them. Expended counts the actual expenses. Income raises the available
    budget. The result can go negative on an overbooking. The code does not
    clamp it, on purpose.
    """
    return as_amount(allocated) - bound - expended + income


def pick_fiscal_year[T](candidates: Sequence[tuple[T, date, date]], today: date) -> T | None:
    """Derive the fiscal year for an operation without an explicit fiscal year.

    `candidates` holds `(id, start_date, end_date)` of every active open year of
    the top-level budget. Exactly one candidate selects that year. With several
    candidates, the one whose date range contains `today` is the current year
    and is selected, because several years stay active while the old year is
    still being settled. Every other case returns `None`, and the caller asks
    for an explicit fiscal year or leaves it open.
    """
    current = tuple(fid for fid, start, end in candidates if start <= today <= end)
    match (candidates, current):
        case ([(only, _, _)], _):
            return only
        case (_, [only]):
            return only
        case _:
            return None


def is_valid_fiscal_start(start_month: int, start_day: int) -> bool:
    """Check that the fiscal cutoff day and month form a valid date in EVERY year.

    Days 1 to 28 exist in every month. Days 29 to 31 are missing in some
    months. Such a day makes `fiscal_year_bounds` raise ValueError, which ends
    as a 500.
    """
    return 1 <= start_month <= 12 and 1 <= start_day <= 28


def fiscal_year_bounds(year: int, start_month: int, start_day: int) -> tuple[date, date]:
    """Compute the fiscal-year start and end from the year and the budget cutoff.

    The rule is `start = cutoff(year)` and `end = cutoff(year + 1) - 1 day`.
    Consecutive years therefore form a gapless and disjoint sequence.

    Raises:
        ValueError: The cutoff day and month are impossible. The service maps
            this to 422 instead of a 500.
    """
    if not is_valid_fiscal_start(start_month, start_day):
        raise ValueError(
            f"invalid fiscal start day/month: {start_day:02d}.{start_month:02d}"
        )
    start = date(year, start_month, start_day)
    end = date(year + 1, start_month, start_day) - timedelta(days=1)
    return start, end


def fiscal_year_display(year: int, start_month: int, start_day: int) -> str:
    """Format a fiscal year: `YYYY` for a Jan 1 cutoff, else `YYYY/YY`."""
    return (
        str(year)
        if start_month == 1 and start_day == 1
        else f"{year}/{(year + 1) % 100:02d}"
    )


def resolve_decision_gremium[K, G](
    node_id: K,
    parent_of: Mapping[K, K | None],
    own_of: Mapping[K, G | None],
) -> tuple[G | None, K | None]:
    """Resolve the effective deciding Gremium of a cost center.

    The effective value is the own `decision_gremium_id` of the node, else the value
    of the nearest ancestor, else none. `parent_of` maps a node id to its parent id,
    and `own_of` maps a node id to its own deciding Gremium. A node that is missing
    from `parent_of` ends the walk. A cycle in the parent chain also ends it, so bad
    data cannot loop.

    Returns:
        `(gremium_id, source_node_id)`. `source_node_id` is the node that holds the
        value: the node itself or an ancestor. Both are `None` when no node on the
        path holds a value.
    """
    return _decision_from(node_id, parent_of, own_of, frozenset())


def _decision_from[K, G](
    node_id: K | None,
    parent_of: Mapping[K, K | None],
    own_of: Mapping[K, G | None],
    seen: frozenset[K],
) -> tuple[G | None, K | None]:
    """Walk up from `node_id` to the first node with an own deciding Gremium.

    `seen` holds the nodes already visited, so a cycle in bad data ends the walk.
    """
    if node_id is None or node_id in seen or node_id not in parent_of:
        return None, None
    own = own_of.get(node_id)
    return (
        (own, node_id)
        if own is not None
        else _decision_from(parent_of[node_id], parent_of, own_of, seen | {node_id})
    )


#: Field order of a node tuple: id, parent_id, gremium_id, key, tree_path, name,
#: currency, active, color, fiscal_start_month, fiscal_start_day, view_gremium_id,
#: decision_gremium_id.
NodeTuple = tuple[
    object, object | None, object | None, str, str, str, str, bool,
    str | None, int, int, object | None, object | None,
]


def scope_forest(forest: list[dict[str, Any]], root_ids: set[object]) -> list[dict[str, Any]]:
    """Scope the forest to the subtrees that a reader may see.

    `root_ids` are the nodes that one of the Gremien of the reader reads. The function
    returns the subtree of every such node. Each such subtree becomes a new tab root.
    The walk goes depth first. A hit takes its WHOLE subtree, so a nested match is not
    duplicated. The outer match wins.
    """
    return [hit for root in forest for hit in _scoped(root, root_ids)] if root_ids else []


def _scoped(node: dict[str, Any], root_ids: set[object]) -> tuple[dict[str, Any], ...]:
    """Return the outermost nodes of the subtree of `node` that the reader may see."""
    return (
        (node,)
        if node.get("id") in root_ids
        else tuple(hit for child in node.get("children", []) for hit in _scoped(child, root_ids))
    )


def _views_for_node(
    node_id: object,
    alloc_by_node: dict[tuple[object, object], Decimal],
    bound_by_node: dict[tuple[object, object], Decimal],
    requested_by_node: dict[tuple[object, object], Decimal],
    expended_by_node: dict[tuple[object, object], Decimal],
    income_by_node: dict[tuple[object, object], Decimal],
) -> list[dict[str, Any]]:
    """Build the `AllocationView` dicts of a node, one per relevant fiscal year.

    `committed` is `bound + expended`, the total consumption. It stays for
    backward compatibility.
    """
    tables = (alloc_by_node, bound_by_node, requested_by_node, expended_by_node, income_by_node)
    fys = {fy for table in tables for (nid, fy) in table if nid == node_id}
    return [_view(node_id, fy, *tables) for fy in sorted(fys, key=str)]


def _view(
    node_id: object,
    fy: object,
    alloc_by_node: dict[tuple[object, object], Decimal],
    bound_by_node: dict[tuple[object, object], Decimal],
    requested_by_node: dict[tuple[object, object], Decimal],
    expended_by_node: dict[tuple[object, object], Decimal],
    income_by_node: dict[tuple[object, object], Decimal],
) -> dict[str, Any]:
    """Build the `AllocationView` dict of a node in one fiscal year."""
    allocated = alloc_by_node.get((node_id, fy), _ZERO)
    bound = bound_by_node.get((node_id, fy), _ZERO)
    expended = expended_by_node.get((node_id, fy), _ZERO)
    income = income_by_node.get((node_id, fy), _ZERO)
    return {
        "fiscal_year_id": fy,
        "allocated": allocated,
        "bound": bound,
        "expended": expended,
        "income": income,
        "committed": bound + expended,
        "requested": requested_by_node.get((node_id, fy), _ZERO),
        "available": node_available(allocated, bound, expended, income),
    }


def _rollup_by_fy(
    node_paths: Sequence[tuple[object, str]],
    rows: Sequence[tuple[object, str, Decimal | None]],
) -> dict[tuple[object, object], Decimal]:
    """Roll `(fy, leaf_path, amount)` rows up per fiscal year over the path prefix."""
    fy_leaves = {
        fy_id: tuple((leaf_path, amount) for row_fy, leaf_path, amount in rows if row_fy == fy_id)
        for fy_id in dict.fromkeys(fy_id for fy_id, _, _ in rows)
    }
    return {
        (nid, fy_id): total
        for fy_id, leaves in fy_leaves.items()
        for nid, total in rollup_committed(node_paths, leaves).items()
        if total != _ZERO
    }


def build_forest(
    nodes: Sequence[NodeTuple],
    allocations: Sequence[tuple[object, object, Decimal | None]],
    bound_rows: Sequence[tuple[object, str, Decimal | None]],
    requested_rows: Sequence[tuple[object, str, Decimal | None]] = (),
    expended_rows: Sequence[tuple[object, str, Decimal | None]] = (),
    income_rows: Sequence[tuple[object, str, Decimal | None]] = (),
    *,
    gremium_id: object | None = None,
) -> list[dict[str, Any]]:
    """Build the tree for `GET /budgets` as DTO-ready snake_case dicts.

    Consumption (bound plus expended) rolls up. The allocation stays at its own
    node. Income raises the available sum. The result reports each figure per
    fiscal year.

    `allocations` holds `(budget_id, fiscal_year_id, allocated)` rows, top-down.
    `bound_rows` holds `(fiscal_year_id, leaf_tree_path, amount)` per bound
    application. `requested_rows`, `expended_rows` and `income_rows` use the same
    shape, one per in-flight application, per actual expense and per income.
    `gremium_id` filters the roots. `None` keeps every root.
    """
    node_paths = [(nid, path) for nid, _, _, _, path, *_ in nodes]
    bound_by_node = _rollup_by_fy(node_paths, bound_rows)
    requested_by_node = _rollup_by_fy(node_paths, requested_rows)
    expended_by_node = _rollup_by_fy(node_paths, expended_rows)
    income_by_node = _rollup_by_fy(node_paths, income_rows)

    alloc_by_node: dict[tuple[object, object], Decimal] = {
        (bid, fy): as_amount(value) for bid, fy, value in allocations
    }

    parents = dict.fromkeys(n[1] for n in nodes)
    children_of = {parent: [n for n in nodes if n[1] == parent] for parent in parents}
    parent_of = {n[0]: n[1] for n in nodes}
    decision_of = {n[0]: n[12] for n in nodes}

    def to_dict(n: NodeTuple) -> dict[str, Any]:
        (nid, parent_id, n_gremium, key, path, name, currency, active, color,
         fy_month, fy_day, view_gremium_id, decision_gremium_id) = n
        effective, source = resolve_decision_gremium(nid, parent_of, decision_of)
        return {
            "id": nid,
            "parent_id": parent_id,
            "gremium_id": n_gremium,
            "key": key,
            "path_key": path_key_of(path),
            "name": name,
            "currency": currency,
            "active": active,
            "color": color,
            "view_gremium_id": view_gremium_id,
            "decision_gremium_id": decision_gremium_id,
            "effective_decision_gremium_id": effective,
            "decision_gremium_source_id": source,
            "fiscal_start_month": fy_month,
            "fiscal_start_day": fy_day,
            "by_fiscal_year": _views_for_node(
                nid,
                alloc_by_node,
                bound_by_node,
                requested_by_node,
                expended_by_node,
                income_by_node,
            ),
            "children": [to_dict(c) for c in children_of.get(nid, [])],
        }

    roots = children_of.get(None, [])
    return [
        to_dict(r)
        for r in roots
        if gremium_id is None or r[2] == gremium_id
    ]
