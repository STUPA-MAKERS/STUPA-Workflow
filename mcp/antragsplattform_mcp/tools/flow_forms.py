"""Admin config tools: global flow graph and form versions, incl. atomic flow_*/form_* ops.

Atomic ops read the current document, apply one change via :mod:`..graphops`, and write
back an activated new version — safe for concurrent small edits, unlike full replaces.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import graphops
from .. import schemas as S
from ..client import ApiError
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def get_global_flow() -> dict:
    """Fetch the graph of the active global flow version: {states, transitions, layout}.
    Transition INDICES in the `transitions` array address the flow_* atomic ops."""
    return await api().get("/admin/flow-versions/global")


@group.tool
async def set_global_flow(graph: dict[str, Any], activate: bool = True) -> dict:
    """REPLACE the whole global flow with `graph` ({states, transitions, layout}) —
    only for full rebuilds; prefer the atomic flow_* ops for small changes.
    Requires admin.types."""
    return await api().post(
        "/admin/flow-versions/global", json={"graph": graph, "activate": activate}
    )


async def _flow_graph() -> dict[str, Any]:
    graph = await api().get("/admin/flow-versions/global")
    if not graph or not isinstance(graph, dict) or not graph.get("states"):
        raise ApiError(404, "no global flow exists yet — create one with set_global_flow")
    return graph


async def _save_flow(graph: dict[str, Any]) -> dict:
    result = await api().post(
        "/admin/flow-versions/global", json={"graph": graph, "activate": True}
    )
    return {
        "saved": True,
        "states": len(graph.get("states") or []),
        "transitions": len(graph.get("transitions") or []),
        "flowVersion": result,
    }


@group.tool
async def flow_add_state(
    state: S.StateDef, x: int | None = None, y: int | None = None
) -> dict:
    """ATOMIC: add one state to the global flow (optionally with an editor position)
    and activate the result. Requires admin.types."""
    graph = graphops.add_state(await _flow_graph(), dump_create(state), x, y)
    return await _save_flow(graph)


@group.tool
async def flow_update_state(key: str, patch: S.StateDefPatch) -> dict:
    """ATOMIC: patch one state of the global flow (only the provided keys change).
    Renaming via patch.key cascades to transitions/layout/groups. Requires admin.types."""
    graph = graphops.update_state(await _flow_graph(), key, dump_patch(patch))
    return await _save_flow(graph)


@group.tool
async def flow_remove_state(key: str) -> dict:
    """ATOMIC: remove one state from the global flow, including its transitions,
    position and group membership. Requires admin.types."""
    graph = graphops.remove_state(await _flow_graph(), key)
    return await _save_flow(graph)


@group.tool
async def flow_add_transition(transition: S.TransitionDef) -> dict:
    """ATOMIC: append one transition to the global flow. Requires admin.types."""
    graph = graphops.add_transition(await _flow_graph(), dump_create(transition))
    return await _save_flow(graph)


@group.tool
async def flow_update_transition(index: int, patch: S.TransitionDefPatch) -> dict:
    """ATOMIC: patch the transition at `index` (its position in the `transitions` array
    of get_global_flow). Only provided keys change; an explicit null REMOVES a key
    (e.g. guard=null drops the guard). Read the flow first — indices shift after
    add/remove. Requires admin.types."""
    raw = patch.model_dump(by_alias=True, exclude_unset=True)
    graph = graphops.update_transition(await _flow_graph(), index, raw)
    return await _save_flow(graph)


@group.tool
async def flow_remove_transition(index: int) -> dict:
    """ATOMIC: remove the transition at `index` (position in the `transitions` array).
    Requires admin.types."""
    graph = graphops.remove_transition(await _flow_graph(), index)
    return await _save_flow(graph)


@group.tool
async def flow_set_positions(positions: dict[str, dict[str, int]]) -> dict:
    """ATOMIC: merge editor positions into the flow layout —
    {stateKey: {x, y}, ...}. Requires admin.types."""
    graph = graphops.merge_positions(await _flow_graph(), positions)
    return await _save_flow(graph)


@group.tool
async def flow_set_group(group: S.FlowGroupDef) -> dict:
    """ATOMIC: create or update a visual node group (upsert by group.id) in
    layout.groups. Groups are editor-only: each renders as ONE labelled box whose
    content opens by drill-down; the flow engine ignores them. Groups NEST via
    groupIds (cycles rejected). A state/sub-group belongs to at most one parent —
    adding it here removes it from others. Requires admin.types."""
    graph = graphops.upsert_group(await _flow_graph(), dump_create(group))
    return await _save_flow(graph)


@group.tool
async def flow_delete_group(group_id: str) -> dict:
    """ATOMIC: delete a visual node group (states stay untouched; its sub-groups
    move up one level). Requires admin.types."""
    graph = graphops.delete_group(await _flow_graph(), group_id)
    return await _save_flow(graph)


@group.tool
async def get_latest_form_version(type_id: str) -> dict:
    """Fetch the latest form version of an application type (raw field list for
    editing; the form_* atomic ops address fields by their `key`)."""
    return await api().get(f"/admin/application-types/{type_id}/form-versions/latest")


@group.tool
async def get_effective_form(type_id: str, budget_pot_id: str | None = None) -> dict:
    """The effective (public) form of a type — sections + fields as applicants see
    them. Use this to know which `data` keys create_application expects."""
    return await api().get(
        f"/application-types/{type_id}/form",
        params=params(budgetPotId=budget_pot_id),
    )


@group.tool
async def create_form_version(
    type_id: str,
    fields: list[S.FormFieldDef],
    activate: bool = True,
    description: dict[str, str] | None = None,
) -> dict:
    """REPLACE the whole field list with a new form version — only for full rebuilds;
    prefer the atomic form_* ops for small changes. Requires form.configure."""
    body: dict[str, Any] = {"fields": [dump_create(f) for f in fields], "activate": activate}
    if description:
        body["description"] = description
    return await api().post(f"/admin/application-types/{type_id}/form-versions", json=body)


@group.tool
async def set_active_form(type_id: str, active: bool) -> dict:
    """Activate (latest version) or deactivate the form of an application type —
    deactivated types are closed for new applications. Requires form.configure."""
    return await api().patch(
        f"/admin/application-types/{type_id}/form-active", json={"active": active}
    )


async def _form_state(type_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    draft = await api().get(f"/admin/application-types/{type_id}/form-versions/latest")
    return list(draft.get("fields") or []), draft.get("description")


async def _save_form(
    type_id: str, fields: list[dict[str, Any]], description: dict[str, Any] | None
) -> dict:
    body: dict[str, Any] = {"fields": fields, "activate": True}
    if description:
        body["description"] = description
    result = await api().post(
        f"/admin/application-types/{type_id}/form-versions", json=body
    )
    return {"saved": True, "fields": len(fields), "formVersion": result}


@group.tool
async def form_add_field(
    type_id: str, field: S.FormFieldDef, index: int | None = None
) -> dict:
    """ATOMIC: add one field to the type's form (at `index`, default: append) and
    activate the new version. Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(
        type_id, graphops.add_field(fields, dump_create(field), index), description
    )


@group.tool
async def form_update_field(type_id: str, key: str, patch: S.FormFieldPatch) -> dict:
    """ATOMIC: patch one form field (addressed by its `key`; only provided keys
    change) and activate the new version. Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(
        type_id, graphops.update_field(fields, key, dump_patch(patch)), description
    )


@group.tool
async def form_remove_field(type_id: str, key: str) -> dict:
    """ATOMIC: remove one form field by `key` and activate the new version.
    Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(type_id, graphops.remove_field(fields, key), description)


@group.tool
async def form_move_field(type_id: str, key: str, index: int) -> dict:
    """ATOMIC: move one form field to position `index` and activate the new version.
    Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(type_id, graphops.move_field(fields, key, index), description)


def register(mcp: FastMCP) -> None:
    """Register the flow/form config tool group."""
    group.register(mcp)
