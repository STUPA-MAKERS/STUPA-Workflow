"""Admin config tools for the global flow graph and the form versions.

The group also holds the atomic `flow_*` and `form_*` operations. An atomic operation
reads the current document, applies one change through `graphops`, and writes back an
activated new version. Concurrent small edits stay safe this way. A full replace is not
safe.
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
    """Fetch the graph of the active global flow version.

    The graph holds `states`, `transitions` and `layout`. The transition INDICES in the
    `transitions` array address the atomic `flow_*` operations.
    """
    return await api().get("/admin/flow-versions/global")


@group.tool
async def set_global_flow(graph: dict[str, Any], activate: bool = True) -> dict:
    """REPLACE the whole global flow with `graph`.

    The `graph` holds `states`, `transitions` and `layout`. Use this for a full rebuild
    only. For a small change, prefer the atomic `flow_*` operations.
    Requires admin.types.
    """
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
    """ATOMIC: add one state to the global flow and activate the result.

    You can also give an editor position. Requires admin.types.
    """
    graph = graphops.add_state(await _flow_graph(), dump_create(state), x, y)
    return await _save_flow(graph)


@group.tool
async def flow_update_state(key: str, patch: S.StateDefPatch) -> dict:
    """ATOMIC: patch one state of the global flow.

    Only the keys you give change. A rename through `patch.key` cascades to the
    transitions, the layout and the groups. Requires admin.types.
    """
    graph = graphops.update_state(await _flow_graph(), key, dump_patch(patch))
    return await _save_flow(graph)


@group.tool
async def flow_remove_state(key: str) -> dict:
    """ATOMIC: remove one state from the global flow.

    The call also removes the transitions, the position and the group membership of the
    state. Requires admin.types.
    """
    graph = graphops.remove_state(await _flow_graph(), key)
    return await _save_flow(graph)


@group.tool
async def flow_add_transition(transition: S.TransitionDef) -> dict:
    """ATOMIC: append one transition to the global flow. Requires admin.types."""
    graph = graphops.add_transition(await _flow_graph(), dump_create(transition))
    return await _save_flow(graph)


@group.tool
async def flow_update_transition(index: int, patch: S.TransitionDefPatch) -> dict:
    """ATOMIC: patch the transition at `index`.

    The `index` is the position of the transition in the `transitions` array of
    `get_global_flow`. Only the keys you give change. An explicit null REMOVES a key.
    For example, `guard=null` drops the guard. Read the flow first, because the indices
    shift after an add or a remove. Requires admin.types.
    """
    raw = patch.model_dump(by_alias=True, exclude_unset=True)
    graph = graphops.update_transition(await _flow_graph(), index, raw)
    return await _save_flow(graph)


@group.tool
async def flow_remove_transition(index: int) -> dict:
    """ATOMIC: remove the transition at `index`.

    The `index` is the position in the `transitions` array. Requires admin.types.
    """
    graph = graphops.remove_transition(await _flow_graph(), index)
    return await _save_flow(graph)


@group.tool
async def flow_set_positions(positions: dict[str, dict[str, int]]) -> dict:
    """ATOMIC: merge editor positions into the flow layout.

    The shape is `{stateKey: {x, y}, ...}`. Requires admin.types.
    """
    graph = graphops.merge_positions(await _flow_graph(), positions)
    return await _save_flow(graph)


@group.tool
async def flow_set_group(group: S.FlowGroupDef) -> dict:
    """ATOMIC: create or update a visual node group in `layout.groups`.

    The call upserts by `group.id`. A group is editor-only. It renders as ONE labeled
    box, and its content opens by drill-down. The flow engine ignores a group. Groups
    NEST through `groupIds`, and the server rejects a cycle. A state or a sub-group
    belongs to at most one parent. Adding it here removes it from the others.
    Requires admin.types.
    """
    graph = graphops.upsert_group(await _flow_graph(), dump_create(group))
    return await _save_flow(graph)


@group.tool
async def flow_delete_group(group_id: str) -> dict:
    """ATOMIC: delete a visual node group.

    The states stay untouched. The sub-groups of the group move up one level.
    Requires admin.types.
    """
    graph = graphops.delete_group(await _flow_graph(), group_id)
    return await _save_flow(graph)


@group.tool
async def get_latest_form_version(type_id: str) -> dict:
    """Fetch the latest form version of an application type.

    The call returns the raw field list for editing. The atomic `form_*` operations
    address a field by its `key`.
    """
    return await api().get(f"/admin/application-types/{type_id}/form-versions/latest")


@group.tool
async def get_effective_form(type_id: str) -> dict:
    """Get the effective (public) form of an application type.

    The form holds the sections and the fields as an applicant sees them. Read it to
    learn which `data` keys `create_application` expects.
    """
    return await api().get(f"/application-types/{type_id}/form")


@group.tool
async def create_form_version(
    type_id: str,
    fields: list[S.FormFieldDef],
    activate: bool = True,
    description: dict[str, str] | None = None,
) -> dict:
    """REPLACE the whole field list with a new form version.

    Use this for a full rebuild only. For a small change, prefer the atomic `form_*`
    operations. Requires form.configure.
    """
    body: dict[str, Any] = {"fields": [dump_create(f) for f in fields], "activate": activate}
    if description:
        body["description"] = description
    return await api().post(f"/admin/application-types/{type_id}/form-versions", json=body)


@group.tool
async def set_active_form(type_id: str, active: bool) -> dict:
    """Activate or deactivate the form of an application type.

    An activation uses the latest version. A deactivated type is closed for a new
    application. Requires form.configure.
    """
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
    """ATOMIC: add one field to the form of a type and activate the new version.

    The field goes to `index`. The default appends the field. Requires form.configure.
    """
    fields, description = await _form_state(type_id)
    return await _save_form(
        type_id, graphops.add_field(fields, dump_create(field), index), description
    )


@group.tool
async def form_update_field(type_id: str, key: str, patch: S.FormFieldPatch) -> dict:
    """ATOMIC: patch one form field and activate the new version.

    The `key` addresses the field. Only the keys you give change.
    Requires form.configure.
    """
    fields, description = await _form_state(type_id)
    return await _save_form(
        type_id, graphops.update_field(fields, key, dump_patch(patch)), description
    )


@group.tool
async def form_remove_field(type_id: str, key: str) -> dict:
    """ATOMIC: remove one form field by `key` and activate the new version.

    Requires form.configure.
    """
    fields, description = await _form_state(type_id)
    return await _save_form(type_id, graphops.remove_field(fields, key), description)


@group.tool
async def form_move_field(type_id: str, key: str, index: int) -> dict:
    """ATOMIC: move one form field to position `index` and activate the new version.

    Requires form.configure.
    """
    fields, description = await _form_state(type_id)
    return await _save_form(type_id, graphops.move_field(fields, key, index), description)


def register(mcp: FastMCP) -> None:
    """Register the flow/form config tool group."""
    group.register(mcp)
