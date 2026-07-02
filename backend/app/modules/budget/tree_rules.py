"""Budget-tree domain logic (pure, no DB).

All cost-centre tree decisions live here as pure functions — deterministic and
testable without backing services; the service stays thin I/O wiring.

Rule of thumb: allocation flows DOWN (top-down, NO roll-up); consumption flows
UP (roll-up of the bound sum from approved applications).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from decimal import Decimal

# Path segment: alphanumeric (e.g. ``VS``/``800``/``04``). The separator ``-``
# is reserved for path composition and thus forbidden inside a segment.
_KEY_RE = re.compile(r"^[A-Za-z0-9]+$")
_SEP = "-"
_ZERO = Decimal("0")
# Length cap per path segment — matches the schemas' ``max_length`` and bounds
# free text in the ``path_key`` prefix comparisons.
_KEY_MAX = 64


def is_valid_key(key: str) -> bool:
    """Check for a valid path segment: alphanumeric, no ``-``, length-capped."""
    return len(key) <= _KEY_MAX and bool(_KEY_RE.match(key))


def compose_path_key(parent_path: str | None, key: str) -> str:
    """Compose the path key: top level -> ``key``; else ``<parent_path>-<key>``."""
    if parent_path is None:
        return key
    return f"{parent_path}{_SEP}{key}"


def is_descendant_path(ancestor_path: str, node_path: str) -> bool:
    """Check whether ``node_path`` lies strictly below ``ancestor_path``.

    Via the path-prefix convention (``VS`` > ``VS-800`` > ``VS-800-04``). The
    node itself does NOT count as a descendant.
    """
    return node_path.startswith(ancestor_path + _SEP)


def is_self_or_descendant_path(ancestor_path: str, node_path: str) -> bool:
    """Node itself OR descendant (for roll-up aggregation: a leaf counts to itself)."""
    return node_path == ancestor_path or is_descendant_path(ancestor_path, node_path)


def intervals_overlap(
    a_start: date, a_end: date, b_start: date, b_end: date
) -> bool:
    """Check whether two closed date intervals ``[start, end]`` overlap.

    Classic overlap test: ``a.start <= b.end AND b.start <= a.end``. Gaps
    between fiscal years are allowed — only overlap is forbidden.
    """
    return a_start <= b_end and b_start <= a_end


def overlaps_any(
    new_start: date,
    new_end: date,
    existing: Iterable[tuple[date, date]],
) -> bool:
    """Check whether ``[new_start, new_end]`` intersects any existing interval."""
    return any(
        intervals_overlap(new_start, new_end, s, e) for s, e in existing
    )


def as_amount(value: Decimal | None) -> Decimal:
    """Return 0 for ``None``, else the amount."""
    return value if value is not None else _ZERO


def children_allocation_exceeds_parent(
    parent_allocated: Decimal | None,
    siblings_sum_excluding: Decimal,
    new_value: Decimal,
) -> bool:
    """Check whether setting a child allocation exceeds the parent budget.

    ``siblings_sum_excluding`` = sum of the OTHER direct children's allocations.
    A missing parent allocation counts as 0, so any positive child allocation
    violates (top-down: nothing to distribute without a parent budget).
    """
    return siblings_sum_excluding + new_value > as_amount(parent_allocated)


def parent_allocation_below_children(
    new_parent_value: Decimal,
    children_sum: Decimal,
) -> bool:
    """Check whether the new parent allocation drops below the sum already
    distributed to children (violation -> 422)."""
    return new_parent_value < children_sum


def rollup_committed(
    node_paths: Iterable[tuple[object, str]],
    leaf_amounts: Iterable[tuple[str, Decimal | None]],
) -> dict[object, Decimal]:
    """Bound sum per node = roll-up of approved application amounts.

    ``node_paths`` = ``(node_id, path_key)`` of all tree nodes; ``leaf_amounts``
    = ``(leaf_path_key, amount)`` per bound application. Each application counts
    to its own cost centre and all ancestors (path prefix). Consumption flows
    up — allocated stays untouched.
    """
    leaves = [(path, as_amount(amount)) for path, amount in leaf_amounts]
    out: dict[object, Decimal] = {}
    for node_id, node_path in node_paths:
        total = _ZERO
        for leaf_path, amount in leaves:
            if is_self_or_descendant_path(node_path, leaf_path):
                total += amount
        out[node_id] = total
    return out


def node_available(
    allocated: Decimal | None,
    bound: Decimal,
    expended: Decimal = _ZERO,
    income: Decimal = _ZERO,
) -> Decimal:
    """Free sum of a node: ``available = allocated - bound - expended + income``.

    Bound = accepted applications (reduced pro rata by expenses bound to them);
    expended = actual expenses; income increases the available budget. May go
    negative (overbooking) — deliberately not clamped.
    """
    return as_amount(allocated) - bound - expended + income


def pick_fiscal_year[T](active_ids: Sequence[T]) -> T | None:
    """Derive the fiscal year on budget assignment: exactly one active year ->
    that one; else ``None`` (ambiguous/none -> service leaves it open)."""
    return active_ids[0] if len(active_ids) == 1 else None


def is_valid_fiscal_start(start_month: int, start_day: int) -> bool:
    """Check that the fiscal cutoff (day/month) is a valid date in EVERY year.

    Days 1..28 exist in every month; days 29-31 can be missing depending on the
    month and would raise ValueError (-> 500) in :func:`fiscal_year_bounds`.
    """
    return 1 <= start_month <= 12 and 1 <= start_day <= 28


def fiscal_year_bounds(year: int, start_month: int, start_day: int) -> tuple[date, date]:
    """Compute fiscal-year start/end from year + budget cutoff (day/month).

    ``start = cutoff(year)``, ``end = cutoff(year+1) - 1 day`` — a gapless,
    disjoint sequence of consecutive years. Raises ``ValueError`` for an
    impossible cutoff; the service maps that to 422 instead of a 500."""
    if not is_valid_fiscal_start(start_month, start_day):
        raise ValueError(
            f"invalid fiscal start day/month: {start_day:02d}.{start_month:02d}"
        )
    start = date(year, start_month, start_day)
    end = date(year + 1, start_month, start_day) - timedelta(days=1)
    return start, end


def fiscal_year_display(year: int, start_month: int, start_day: int) -> str:
    """Display a fiscal year: ``YYYY`` for a Jan-1 cutoff, else ``YYYY/YY``."""
    if start_month == 1 and start_day == 1:
        return str(year)
    return f"{year}/{(year + 1) % 100:02d}"


# Node tuple: (id, parent_id, gremium_id, key, path_key, name, currency, active,
# color, accepted_state_keys, denied_state_keys, fiscal_start_month, fiscal_start_day,
# hidden_in_budget, view_gremium_id).
NodeTuple = tuple[
    object, object | None, object | None, str, str, str, str, bool,
    str | None, list, list, int, int, bool, object | None,
]


def scope_forest(forest: list[dict], gremium_ids: set[object]) -> list[dict]:
    """Visibility scope: return subtrees whose root carries a ``view_gremium_id``
    from ``gremium_ids``, as new tab roots.

    Depth-first over the built forest; a hit takes its WHOLE subtree (nested
    matches are not duplicated — the outer one wins).
    """
    if not gremium_ids:
        return []
    out: list[dict] = []

    def walk(node: dict) -> None:
        if node.get("view_gremium_id") in gremium_ids:
            out.append(node)
            return
        for child in node.get("children", []):
            walk(child)

    for root in forest:
        walk(root)
    return out


def _views_for_node(
    node_id: object,
    alloc_by_node: dict[tuple[object, object], Decimal],
    bound_by_node: dict[tuple[object, object], Decimal],
    requested_by_node: dict[tuple[object, object], Decimal],
    expended_by_node: dict[tuple[object, object], Decimal],
    income_by_node: dict[tuple[object, object], Decimal],
) -> list[dict]:
    """Build ``AllocationView`` dicts of a node per relevant fiscal year.

    ``committed`` = bound + expended (total consumption, backward compat).
    """
    fys = {fy for (nid, fy) in alloc_by_node if nid == node_id}
    fys |= {fy for (nid, fy) in bound_by_node if nid == node_id}
    fys |= {fy for (nid, fy) in requested_by_node if nid == node_id}
    fys |= {fy for (nid, fy) in expended_by_node if nid == node_id}
    fys |= {fy for (nid, fy) in income_by_node if nid == node_id}
    views: list[dict] = []
    for fy in sorted(fys, key=str):
        allocated = alloc_by_node.get((node_id, fy), _ZERO)
        bound = bound_by_node.get((node_id, fy), _ZERO)
        requested = requested_by_node.get((node_id, fy), _ZERO)
        expended = expended_by_node.get((node_id, fy), _ZERO)
        income = income_by_node.get((node_id, fy), _ZERO)
        views.append(
            {
                "fiscal_year_id": fy,
                "allocated": allocated,
                "bound": bound,
                "expended": expended,
                "income": income,
                "committed": bound + expended,
                "requested": requested,
                "available": node_available(allocated, bound, expended, income),
            }
        )
    return views


def _rollup_by_fy(
    node_paths: Sequence[tuple[object, str]],
    rows: Sequence[tuple[object, str, Decimal | None]],
) -> dict[tuple[object, object], Decimal]:
    """Roll ``(fy, leaf_path, amount)`` rows up per fiscal year via the path prefix."""
    fy_leaves: dict[object, list[tuple[str, Decimal | None]]] = {}
    for fy_id, leaf_path, amount in rows:
        fy_leaves.setdefault(fy_id, []).append((leaf_path, amount))
    out: dict[tuple[object, object], Decimal] = {}
    for fy_id, leaves in fy_leaves.items():
        for nid, total in rollup_committed(node_paths, leaves).items():
            if total != _ZERO:
                out[(nid, fy_id)] = total
    return out


def build_forest(
    nodes: Sequence[NodeTuple],
    allocations: Sequence[tuple[object, object, Decimal | None]],
    bound_rows: Sequence[tuple[object, str, Decimal | None]],
    requested_rows: Sequence[tuple[object, str, Decimal | None]] = (),
    expended_rows: Sequence[tuple[object, str, Decimal | None]] = (),
    income_rows: Sequence[tuple[object, str, Decimal | None]] = (),
    *,
    gremium_id: object | None = None,
) -> list[dict]:
    """Pure tree build for ``GET /budgets`` — DTO-ready (snake_case) dicts.

    ``allocations`` = ``(budget_id, fiscal_year_id, allocated)`` (top-down);
    ``bound_rows``/``requested_rows``/``expended_rows``/``income_rows`` =
    ``(fiscal_year_id, leaf_path_key, amount)`` per bound/in-flight application,
    actual expense, and income respectively. ``gremium_id`` optionally filters
    the roots. Consumption (bound + expended) rolls up, allocation stays at the
    node, income raises available — reported separately per fiscal year.
    """
    node_paths = [(nid, path) for nid, _, _, _, path, *_ in nodes]
    bound_by_node = _rollup_by_fy(node_paths, bound_rows)
    requested_by_node = _rollup_by_fy(node_paths, requested_rows)
    expended_by_node = _rollup_by_fy(node_paths, expended_rows)
    income_by_node = _rollup_by_fy(node_paths, income_rows)

    alloc_by_node: dict[tuple[object, object], Decimal] = {
        (bid, fy): as_amount(value) for bid, fy, value in allocations
    }

    children_of: dict[object | None, list[NodeTuple]] = {}
    for n in nodes:
        children_of.setdefault(n[1], []).append(n)

    def to_dict(n: NodeTuple) -> dict:
        (nid, parent_id, n_gremium, key, path, name, currency, active, color, acc,
         den, fy_month, fy_day, hidden_in_budget, view_gremium_id) = n
        return {
            "id": nid,
            "parent_id": parent_id,
            "gremium_id": n_gremium,
            "key": key,
            "path_key": path,
            "name": name,
            "currency": currency,
            "active": active,
            "color": color,
            "accepted_state_keys": list(acc or []),
            "denied_state_keys": list(den or []),
            "hidden_in_budget": hidden_in_budget,
            "view_gremium_id": view_gremium_id,
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
