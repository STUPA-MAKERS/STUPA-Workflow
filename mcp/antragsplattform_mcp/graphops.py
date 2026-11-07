"""Pure operations on the global-flow graph dict (read-modify-write helpers).

Each function takes the graph that `GET /admin/flow-versions/global` returns, that is
`{states, transitions, layout}`. It builds a new graph from a deep copy and returns it, so the
input stays unchanged. A `ValueError` from here surfaces as a clean tool error before the server
writes anything.
"""

from __future__ import annotations

from copy import deepcopy
from functools import reduce
from typing import Any

Graph = dict[str, Any]


def _states(graph: Graph) -> list[dict[str, Any]]:
    return graph.get("states", [])


def _transitions(graph: Graph) -> list[dict[str, Any]]:
    return graph.get("transitions", [])


def _layout(graph: Graph) -> dict[str, Any]:
    layout = graph.get("layout")
    return layout if isinstance(layout, dict) else {}


def _without(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    """Return a copy of a dict without one key."""
    return {k: v for k, v in mapping.items() if k != key}


def _clamped(index: int, length: int) -> int:
    """Return an insert position inside `0..length`, as `list.insert` takes it."""
    return max(0, min(index, length))


def _state_index(graph: Graph, key: str) -> int:
    index = next((i for i, s in enumerate(_states(graph)) if s.get("key") == key), None)
    if index is None:
        raise ValueError(f"unknown state key: {key!r}")
    return index


def add_state(graph: Graph, state: dict[str, Any], x: int | None, y: int | None) -> Graph:
    g = deepcopy(graph)
    key = state["key"]
    if any(s.get("key") == key for s in _states(g)):
        raise ValueError(f"state key already exists: {key!r}")
    layout = _layout(g)
    placed = (
        {"layout": {**layout, "positions": {**layout.get("positions", {}), key: {"x": x, "y": y}}}}
        if x is not None and y is not None
        else {}
    )
    return {**g, "states": [*_states(g), state], **placed}


def _renamed_transition(t: dict[str, Any], key: str, new_key: str) -> dict[str, Any]:
    """Return a transition with the state `key` renamed to `new_key` at both ends."""
    return {
        **t,
        **({"from": new_key} if t.get("from") == key else {}),
        **({"to": new_key} if t.get("to") == key else {}),
    }


def _renamed_layout(layout: dict[str, Any], key: str, new_key: str) -> dict[str, Any]:
    """Return a layout with the state `key` renamed in the positions and in the groups."""
    positions = layout.get("positions") or {}
    groups = layout.get("groups") or []
    moved = (
        {"positions": {**_without(positions, key), new_key: positions[key]}}
        if key in positions
        else {}
    )
    regrouped = (
        {
            "groups": [
                {**grp, "stateKeys": [new_key if k == key else k for k in grp.get("stateKeys", [])]}
                for grp in groups
            ]
        }
        if groups
        else {}
    )
    return {**layout, **moved, **regrouped}


def update_state(graph: Graph, key: str, patch: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    i = _state_index(g, key)
    new_key = patch.get("key")
    renamed = bool(new_key) and new_key != key
    if renamed and any(s.get("key") == new_key for j, s in enumerate(_states(g)) if j != i):
        raise ValueError(f"state key already exists: {new_key!r}")
    states = [{**s, **patch} if j == i else s for j, s in enumerate(_states(g))]
    cascade = _rename_cascade(g, key, new_key) if new_key and new_key != key else {}
    return {**g, "states": states, **cascade}


def _rename_cascade(g: Graph, key: str, new_key: str) -> Graph:
    """Return the transitions and the layout of a graph with the state `key` renamed."""
    return {
        "transitions": [_renamed_transition(t, key, new_key) for t in _transitions(g)],
        "layout": _renamed_layout(_layout(g), key, new_key),
    }


def remove_state(graph: Graph, key: str) -> Graph:
    g = deepcopy(graph)
    _state_index(g, key)  # raises on unknown key
    layout = _layout(g)
    positions = layout.get("positions")
    stripped = (
        {**grp, "stateKeys": [k for k in grp.get("stateKeys", []) if k != key]}
        for grp in (layout.get("groups") or [])
    )
    groups = [grp for grp in stripped if grp["stateKeys"] or _group_children(grp)]
    placed = {**layout, "positions": _without(positions, key)} if positions else layout
    return {
        **g,
        "states": [s for s in _states(g) if s.get("key") != key],
        "transitions": [
            t for t in _transitions(g) if t.get("from") != key and t.get("to") != key
        ],
        "layout": {**placed, "groups": groups} if groups else _without(placed, "groups"),
    }


def add_transition(graph: Graph, transition: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    keys = {s.get("key") for s in _states(g)}
    unknown_end = next((end for end in ("from", "to") if transition.get(end) not in keys), None)
    if unknown_end is not None:
        raise ValueError(
            f"transition references unknown {unknown_end}-state: "
            f"{transition.get(unknown_end)!r}"
        )
    return {**g, "transitions": [*_transitions(g), transition]}


def _transition_at(graph: Graph, index: int) -> dict[str, Any]:
    transitions = _transitions(graph)
    if not 0 <= index < len(transitions):
        raise ValueError(
            f"transition index {index} out of range (0..{len(transitions) - 1})"
        )
    return transitions[index]


def update_transition(graph: Graph, index: int, patch: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    t = _transition_at(g, index)
    # An explicit null removes the key (e.g. drop a guard).
    kept = {k: v for k, v in t.items() if not (k in patch and patch[k] is None)}
    updated = {**kept, **{k: v for k, v in patch.items() if v is not None}}
    return {
        **g,
        "transitions": [updated if j == index else x for j, x in enumerate(_transitions(g))],
    }


def remove_transition(graph: Graph, index: int) -> Graph:
    g = deepcopy(graph)
    _transition_at(g, index)
    return {**g, "transitions": [x for j, x in enumerate(_transitions(g)) if j != index]}


def merge_positions(graph: Graph, positions: dict[str, dict[str, int]]) -> Graph:
    g = deepcopy(graph)
    keys = {s.get("key") for s in _states(g)}
    unknown = sorted(set(positions) - keys)
    if unknown:
        raise ValueError(f"unknown state keys in positions: {unknown}")
    layout = _layout(g)
    return {
        **g,
        "states": _states(g),
        "layout": {**layout, "positions": {**layout.get("positions", {}), **positions}},
    }


def _group_children(grp: dict[str, Any]) -> list[str]:
    return list(grp.get("groupIds") or [])


def _visit(
    gid: str, children: dict[Any, list[str]], path: frozenset[str], done: frozenset[str]
) -> frozenset[str]:
    """Walk the groups below `gid` depth first and return the set of the finished groups.

    Raises:
        ValueError: `gid` is on its own path, so the nesting has a cycle.
    """
    if gid in path:
        raise ValueError(f"group nesting cycle involving {gid!r}")
    below = (
        done
        if gid in done
        else reduce(
            lambda acc, child: _visit(child, children, path | {gid}, acc),
            children.get(gid, []),
            done,
        )
    )
    return below | {gid}


def _assert_acyclic(groups: list[dict[str, Any]]) -> None:
    children = {grp.get("id"): _group_children(grp) for grp in groups}
    reduce(
        lambda done, gid: _visit(gid, children, frozenset(), done),
        (gid for gid in children if gid is not None),
        frozenset[str](),
    )


def _left_out(
    grp: dict[str, Any], member: set[str], children: set[str]
) -> dict[str, Any]:
    """Return a group without the states and sub-groups that join another group."""
    return {
        **grp,
        "stateKeys": [k for k in grp.get("stateKeys", []) if k not in member],
        **(
            {"groupIds": [c for c in _group_children(grp) if c not in children]}
            if children
            else {}
        ),
    }


def upsert_group(graph: Graph, group: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    keys = {s.get("key") for s in _states(g)}
    unknown = sorted(set(group.get("stateKeys", [])) - keys)
    if unknown:
        raise ValueError(f"unknown state keys in group: {unknown}")
    layout = _layout(g)
    groups: list[dict[str, Any]] = layout.get("groups", [])
    group_ids = {grp.get("id") for grp in groups} | {group["id"]}
    children = set(group.get("groupIds") or [])
    if group["id"] in children:
        raise ValueError("group cannot contain itself")
    unknown_groups = sorted(children - group_ids)
    if unknown_groups:
        raise ValueError(f"unknown group ids in groupIds: {unknown_groups}")
    if not group.get("stateKeys") and not children:
        raise ValueError("group needs at least one state key or sub-group")
    # A state or a group lives in at most one parent. A join removes it everywhere else.
    member = set(group["stateKeys"])
    stripped = (
        grp if grp.get("id") == group["id"] else _left_out(grp, member, children)
        for grp in groups
    )
    kept = [
        grp
        for grp in stripped
        if grp.get("id") == group["id"] or grp["stateKeys"] or _group_children(grp)
    ]
    first = next((i for i, grp in enumerate(kept) if grp.get("id") == group["id"]), None)
    result = (
        [*kept, group]
        if first is None
        else [group if i == first else grp for i, grp in enumerate(kept)]
    )
    _assert_acyclic(result)
    return {**g, "states": _states(g), "layout": {**layout, "groups": result}}


def _without_child(grp: dict[str, Any], group_id: str) -> dict[str, Any]:
    """Return a group without the sub-group `group_id`, and without an empty `groupIds`."""
    ids = [c for c in _group_children(grp) if c != group_id]
    return {**grp, "groupIds": ids} if ids else _without(grp, "groupIds")


def delete_group(graph: Graph, group_id: str) -> Graph:
    g = deepcopy(graph)
    layout = _layout(g)
    groups = layout.get("groups") or []
    if not any(grp.get("id") == group_id for grp in groups):
        raise ValueError(f"unknown group id: {group_id!r}")
    # The children of the deleted group move up to the top level. The code drops the
    # reference to the deleted group.
    remaining = [_without_child(grp, group_id) for grp in groups if grp.get("id") != group_id]
    return {
        **g,
        "layout": {**layout, "groups": remaining} if remaining else _without(layout, "groups"),
    }


Fields = list[dict[str, Any]]


def _field_index(fields: Fields, key: str) -> int:
    index = next((i for i, f in enumerate(fields) if f.get("key") == key), None)
    if index is None:
        raise ValueError(f"unknown field key: {key!r}")
    return index


def add_field(fields: Fields, field: dict[str, Any], index: int | None) -> Fields:
    out = deepcopy(fields)
    if any(f.get("key") == field["key"] for f in out):
        raise ValueError(f"field key already exists: {field['key']!r}")
    position = len(out) if index is None else _clamped(index, len(out))
    return [*out[:position], field, *out[position:]]


def update_field(fields: Fields, key: str, patch: dict[str, Any]) -> Fields:
    out = deepcopy(fields)
    i = _field_index(out, key)
    new_key = patch.get("key")
    if new_key and new_key != key and any(f.get("key") == new_key for f in out):
        raise ValueError(f"field key already exists: {new_key!r}")
    return [{**f, **patch} if j == i else f for j, f in enumerate(out)]


def remove_field(fields: Fields, key: str) -> Fields:
    out = deepcopy(fields)
    i = _field_index(out, key)
    return [f for j, f in enumerate(out) if j != i]


def move_field(fields: Fields, key: str, index: int) -> Fields:
    out = deepcopy(fields)
    i = _field_index(out, key)
    rest = [f for j, f in enumerate(out) if j != i]
    position = _clamped(index, len(rest))
    return [*rest[:position], out[i], *rest[position:]]
