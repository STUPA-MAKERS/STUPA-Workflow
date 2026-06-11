"""Pure mutations on the global-flow graph dict (read-modify-write helpers).

Each function takes the graph as returned by ``GET /admin/flow-versions/global``
(``{states, transitions, layout}``), mutates a **copy**, and returns it. Raising
``ValueError`` here surfaces as a clean tool error before anything is written.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

Graph = dict[str, Any]


def _states(graph: Graph) -> list[dict[str, Any]]:
    return graph.setdefault("states", [])


def _transitions(graph: Graph) -> list[dict[str, Any]]:
    return graph.setdefault("transitions", [])


def _layout(graph: Graph) -> dict[str, Any]:
    layout = graph.get("layout")
    if not isinstance(layout, dict):
        layout = {}
        graph["layout"] = layout
    return layout


def _state_index(graph: Graph, key: str) -> int:
    for i, s in enumerate(_states(graph)):
        if s.get("key") == key:
            return i
    raise ValueError(f"unknown state key: {key!r}")


def add_state(graph: Graph, state: dict[str, Any], x: int | None, y: int | None) -> Graph:
    g = deepcopy(graph)
    key = state["key"]
    if any(s.get("key") == key for s in _states(g)):
        raise ValueError(f"state key already exists: {key!r}")
    _states(g).append(state)
    if x is not None and y is not None:
        _layout(g).setdefault("positions", {})[key] = {"x": x, "y": y}
    return g


def update_state(graph: Graph, key: str, patch: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    i = _state_index(g, key)
    new_key = patch.get("key")
    _states(g)[i] = {**_states(g)[i], **patch}
    if new_key and new_key != key:
        if any(s.get("key") == new_key for j, s in enumerate(_states(g)) if j != i):
            raise ValueError(f"state key already exists: {new_key!r}")
        # Rename cascades: transitions, layout positions, group membership.
        for t in _transitions(g):
            if t.get("from") == key:
                t["from"] = new_key
            if t.get("to") == key:
                t["to"] = new_key
        positions = _layout(g).get("positions") or {}
        if key in positions:
            positions[new_key] = positions.pop(key)
        for grp in _layout(g).get("groups") or []:
            grp["stateKeys"] = [new_key if k == key else k for k in grp.get("stateKeys", [])]
    return g


def remove_state(graph: Graph, key: str) -> Graph:
    g = deepcopy(graph)
    _state_index(g, key)  # raises on unknown key
    g["states"] = [s for s in _states(g) if s.get("key") != key]
    g["transitions"] = [
        t for t in _transitions(g) if t.get("from") != key and t.get("to") != key
    ]
    positions = _layout(g).get("positions") or {}
    positions.pop(key, None)
    groups = [
        {**grp, "stateKeys": [k for k in grp.get("stateKeys", []) if k != key]}
        for grp in (_layout(g).get("groups") or [])
    ]
    groups = [grp for grp in groups if grp["stateKeys"] or _group_children(grp)]
    if groups:
        _layout(g)["groups"] = groups
    else:
        _layout(g).pop("groups", None)
    return g


def add_transition(graph: Graph, transition: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    keys = {s.get("key") for s in _states(g)}
    for end in ("from", "to"):
        if transition.get(end) not in keys:
            raise ValueError(f"transition references unknown {end}-state: {transition.get(end)!r}")
    _transitions(g).append(transition)
    return g


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
    for k, v in patch.items():
        if v is None:
            t.pop(k, None)  # explicit null removes the key (e.g. drop a guard)
        else:
            t[k] = v
    return g


def remove_transition(graph: Graph, index: int) -> Graph:
    g = deepcopy(graph)
    _transition_at(g, index)
    _transitions(g).pop(index)
    return g


def merge_positions(graph: Graph, positions: dict[str, dict[str, int]]) -> Graph:
    g = deepcopy(graph)
    keys = {s.get("key") for s in _states(g)}
    unknown = sorted(set(positions) - keys)
    if unknown:
        raise ValueError(f"unknown state keys in positions: {unknown}")
    _layout(g).setdefault("positions", {}).update(positions)
    return g


def _group_children(grp: dict[str, Any]) -> list[str]:
    return list(grp.get("groupIds") or [])


def _assert_acyclic(groups: list[dict[str, Any]]) -> None:
    children = {grp.get("id"): _group_children(grp) for grp in groups}
    state: dict[str, int] = {}  # 0=visiting, 1=done

    def visit(gid: str) -> None:
        if state.get(gid) == 1:
            return
        if state.get(gid) == 0:
            raise ValueError(f"group nesting cycle involving {gid!r}")
        state[gid] = 0
        for child in children.get(gid, []):
            visit(child)
        state[gid] = 1

    for gid in children:
        if gid is not None:
            visit(gid)


def upsert_group(graph: Graph, group: dict[str, Any]) -> Graph:
    g = deepcopy(graph)
    keys = {s.get("key") for s in _states(g)}
    unknown = sorted(set(group.get("stateKeys", [])) - keys)
    if unknown:
        raise ValueError(f"unknown state keys in group: {unknown}")
    groups: list[dict[str, Any]] = _layout(g).setdefault("groups", [])
    group_ids = {grp.get("id") for grp in groups} | {group["id"]}
    children = set(group.get("groupIds") or [])
    if group["id"] in children:
        raise ValueError("group cannot contain itself")
    unknown_groups = sorted(children - group_ids)
    if unknown_groups:
        raise ValueError(f"unknown group ids in groupIds: {unknown_groups}")
    if not group.get("stateKeys") and not children:
        raise ValueError("group needs at least one state key or sub-group")
    # A state/group lives in at most one parent — joining removes it elsewhere.
    member = set(group["stateKeys"])
    for grp in groups:
        if grp.get("id") != group["id"]:
            grp["stateKeys"] = [k for k in grp.get("stateKeys", []) if k not in member]
            if children:
                grp["groupIds"] = [c for c in _group_children(grp) if c not in children]
    groups[:] = [
        grp
        for grp in groups
        if grp.get("id") == group["id"] or grp["stateKeys"] or _group_children(grp)
    ]
    for i, grp in enumerate(groups):
        if grp.get("id") == group["id"]:
            groups[i] = group
            break
    else:
        groups.append(group)
    _assert_acyclic(groups)
    return g


def delete_group(graph: Graph, group_id: str) -> Graph:
    g = deepcopy(graph)
    groups = _layout(g).get("groups") or []
    if not any(grp.get("id") == group_id for grp in groups):
        raise ValueError(f"unknown group id: {group_id!r}")
    # Kinder der gelöschten Gruppe rücken auf die oberste Ebene (Referenz weg).
    remaining = [
        {**grp, "groupIds": [c for c in _group_children(grp) if c != group_id]}
        for grp in groups
        if grp.get("id") != group_id
    ]
    remaining = [
        {k: v for k, v in grp.items() if not (k == "groupIds" and not v)}
        for grp in remaining
    ]
    if remaining:
        _layout(g)["groups"] = remaining
    else:
        _layout(g).pop("groups", None)
    return g


# ============================================================ form field ops
Fields = list[dict[str, Any]]


def _field_index(fields: Fields, key: str) -> int:
    for i, f in enumerate(fields):
        if f.get("key") == key:
            return i
    raise ValueError(f"unknown field key: {key!r}")


def add_field(fields: Fields, field: dict[str, Any], index: int | None) -> Fields:
    out = deepcopy(fields)
    if any(f.get("key") == field["key"] for f in out):
        raise ValueError(f"field key already exists: {field['key']!r}")
    if index is None:
        out.append(field)
    else:
        out.insert(max(0, min(index, len(out))), field)
    return out


def update_field(fields: Fields, key: str, patch: dict[str, Any]) -> Fields:
    out = deepcopy(fields)
    i = _field_index(out, key)
    new_key = patch.get("key")
    if new_key and new_key != key and any(f.get("key") == new_key for f in out):
        raise ValueError(f"field key already exists: {new_key!r}")
    out[i] = {**out[i], **patch}
    return out


def remove_field(fields: Fields, key: str) -> Fields:
    out = deepcopy(fields)
    out.pop(_field_index(out, key))
    return out


def move_field(fields: Fields, key: str, index: int) -> Fields:
    out = deepcopy(fields)
    f = out.pop(_field_index(out, key))
    out.insert(max(0, min(index, len(out))), f)
    return out
