"""FastMCP server exposing platform API actions as tools.

Auth is handled transparently by :mod:`antragsplattform_mcp.client` /
:mod:`antragsplattform_mcp.auth`: the first tool call triggers a browser login
(OAuth2 + PKCE), the token is cached and refreshed automatically. All rights are capped
server-side by the logged-in user's permissions intersected with the granted scope.

Forbidden by design: agents can manage votes (create/open/close) but can NEVER cast a
ballot — there is intentionally no ``cast_ballot`` tool, and ``vote.cast`` is never
grantable to a token.

Request bodies are **typed** (:mod:`antragsplattform_mcp.schemas` mirrors the backend's
wire schemas in camelCase); the server still validates authoritatively. Big JSON blobs
(global flow, form versions) additionally have **atomic ops** (``flow_*`` / ``form_*``)
that read the current document, apply one small change and write it back — prefer those
over resending the whole JSON.
"""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from . import auth, graphops, schemas as S
from .client import ApiClient, ApiError
from .config import Config
from .schemas import dump_create, dump_patch

_INSTRUCTIONS = """\
antragsplattform — act on a student-government application/budget/meeting platform via its API.

AUTH: the first tool call opens a browser login (OAuth2 + PKCE) and caches a token; it
refreshes automatically. If a call returns an auth error, call `login` to re-authenticate.
`whoami` shows your identity, roles, permissions and committees (gremien). Everything you do
is authorized server-side by YOUR permissions ∩ the granted scope — a tool may return 403
if your account lacks the permission; that is expected, not a bug.

HARD RULE: you can create/open/close/manage votes, but you can NEVER cast a ballot — there is
no such tool and the server refuses it. Voting is reserved for humans.

TYPICAL FLOWS:
- Decide on an application: `list_applications` → `get_application` → `list_transitions`
  (shows the firable transition ids) → `fire_transition(application_id, transition_id, note)`.
  `list_tasks` shows the applications the logged-in user can currently act on.
- Create an application: `list_application_types` → `get_effective_form(type_id)` →
  `create_application(type_id, data={...})` with the form-field values.
- Edit the flow: prefer the ATOMIC ops — `flow_add_state`, `flow_update_state`,
  `flow_remove_state`, `flow_add_transition`, `flow_update_transition(index, …)`,
  `flow_remove_transition(index)`, `flow_set_positions`, `flow_set_group`,
  `flow_delete_group`. Transition indices are positions in the `transitions` array as
  returned by `get_global_flow` — read first, then patch by index. Each op re-reads the
  current flow, applies the change and activates a new version. Use `set_global_flow`
  only for full rebuilds.
- Edit a form: same pattern — `get_latest_form_version(type_id)` then `form_add_field`,
  `form_update_field`, `form_remove_field`, `form_move_field`. Each op creates + activates
  a new form version. `create_form_version` replaces the whole field list.
- Run a meeting: `create_meeting` → `add_agenda_item` → `create_meeting_vote` → `close_vote`.
- Minutes (Protokoll): `get_or_create_protocol(meeting_id)` → `update_protocol(markdown)` →
  `finalize_protocol`. Finalize is ASYNC: re-fetch until `status` is `final`, a fall back to
  `draft` means the render failed.
- Budget: `list_budgets` (tree), `update_budget`, `book_expense`, `set_allocation`,
  `create_budget_transfer`; bind an application via `assign_application_budget`.

SCHEMAS: tool parameters are typed and mirror the API (camelCase keys). For guard/action
shapes and form-field types call `get_config_schemas` (authoritative JSON-Schemas).
Money amounts are decimal strings ("1500.00"). Ids are UUID strings. Prefer reading
(get/list) before writing, and echo back what you changed.
"""

mcp = FastMCP("antragsplattform", instructions=_INSTRUCTIONS)

_config: Config | None = None
_client: ApiClient | None = None


def _cfg() -> Config:
    global _config
    if _config is None:
        _config = Config.from_env()
    return _config


def _api() -> ApiClient:
    global _client
    if _client is None:
        _client = ApiClient(_cfg())
    return _client


def _params(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items() if v is not None}


# ============================================================ auth / identity
@mcp.tool()
async def login() -> dict:
    """Force an interactive browser login (opens the platform OAuth page) and return the
    current identity. Use this if calls fail with auth errors, or to switch users."""
    await _api()._token(force_login=True)  # noqa: SLF001 — intentional re-auth
    return await _api().get("/auth/me")


@mcp.tool()
async def whoami() -> dict:
    """Return the logged-in identity: sub, email, roles, permissions, groups, gremien.
    Triggers a browser login on first use."""
    return await _api().get("/auth/me")


@mcp.tool()
def logout() -> dict:
    """Forget the cached token. The next call requires a fresh browser login."""
    return {"loggedOut": auth.logout(_cfg())}


@mcp.tool()
async def get_config_schemas() -> dict:
    """Authoritative JSON-Schemas for flow graphs (states/transitions/guards/actions)
    and form fields — consult before building complex flow/form bodies."""
    return await _api().get("/admin/config-schemas")


# ============================================================= applications
@mcp.tool()
async def list_applications(
    state: str | None = None,
    gremium: str | None = None,
    type: str | None = None,
    q: str | None = None,
    sort: Literal["createdAt", "amount"] | None = None,
    order: Literal["asc", "desc"] | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List applications (paged). Filters: state (id), gremium (id), type (id),
    q (full-text), sort, order."""
    return await _api().get(
        "/applications",
        params=_params(
            state=state, gremium=gremium, type=type, q=q,
            sort=sort, order=order, limit=limit, offset=offset,
        ),
    )


@mcp.tool()
async def get_application(application_id: str) -> dict:
    """Fetch one application (data, state, applicant, budget binding)."""
    return await _api().get(f"/applications/{application_id}")


@mcp.tool()
async def get_application_timeline(application_id: str) -> dict:
    """Status/transition history of an application."""
    return await _api().get(f"/applications/{application_id}/timeline")


@mcp.tool()
async def list_application_versions(application_id: str) -> dict:
    """Version history of an application's form data (with diffs)."""
    return await _api().get(f"/applications/{application_id}/versions")


@mcp.tool()
async def get_application_form(application_id: str) -> dict:
    """The form version pinned to an application (fields as the applicant saw them)."""
    return await _api().get(f"/applications/{application_id}/form")


@mcp.tool()
async def create_application(
    type_id: str,
    data: dict[str, Any],
    applicant_email: str | None = None,
    applicant_name: str | None = None,
    lang: str | None = None,
    budget_pot_id: str | None = None,
) -> dict:
    """Create an application of the given type. `data` = form-field values (validated
    against the type's effective form — see get_effective_form). For a logged-in user,
    email/name are derived from the account if omitted."""
    return await _api().post(
        "/applications",
        json=_params(
            typeId=type_id, data=data, applicantEmail=applicant_email,
            applicantName=applicant_name, lang=lang, budgetPotId=budget_pot_id,
        ),
    )


@mcp.tool()
async def update_application(application_id: str, data: dict[str, Any]) -> dict:
    """Patch an application's form data (creates a new data version). Subject to edit
    permissions and the state's editAllowed flag."""
    return await _api().patch(f"/applications/{application_id}", json={"data": data})


@mcp.tool()
async def delete_application(application_id: str) -> dict:
    """Delete an application (admin-only, irreversible)."""
    return await _api().delete(f"/applications/{application_id}")


@mcp.tool()
async def comment_application(
    application_id: str, body: str, visibility: Literal["public", "internal"] = "public"
) -> dict:
    """Add a comment to an application. `internal` comments are hidden from the applicant."""
    return await _api().post(
        f"/applications/{application_id}/comments",
        json={"body": body, "visibility": visibility},
    )


@mcp.tool()
async def list_comments(application_id: str) -> dict:
    """List the comments on an application."""
    return await _api().get(f"/applications/{application_id}/comments")


@mcp.tool()
async def create_application_pdf(application_id: str) -> dict:
    """Enqueue PDF generation for an application — ASYNC, returns a job; poll with
    `get_job(job_id)` until done."""
    return await _api().post(f"/applications/{application_id}/pdf")


@mcp.tool()
async def get_job(job_id: str) -> dict:
    """Status of an async job (e.g. PDF generation)."""
    return await _api().get(f"/jobs/{job_id}")


# ============================================ flow decisions on applications
@mcp.tool()
async def list_tasks() -> dict:
    """List the logged-in user's open tasks: applications in vote states of their
    committees, or with at least one firable transition that requires action."""
    return await _api().get("/applications/tasks")


@mcp.tool()
async def list_transitions(application_id: str) -> dict:
    """List the flow transitions currently firable on an application (for this user).
    Each carries `requiresAction` — false marks an optional action (no open task)."""
    return await _api().get(f"/applications/{application_id}/transitions")


@mcp.tool()
async def fire_transition(
    application_id: str, transition_id: str, note: str | None = None
) -> dict:
    """Decide on an application: fire a manual flow transition (approve/reject/etc).
    Get valid transition ids from `list_transitions`."""
    return await _api().post(
        f"/applications/{application_id}/transition",
        json=_params(transitionId=transition_id, note=note),
    )


# ================================================ flow editing (admin/config)
@mcp.tool()
async def get_global_flow() -> dict:
    """Fetch the graph of the active global flow version: {states, transitions, layout}.
    Transition INDICES in the `transitions` array address the flow_* atomic ops."""
    return await _api().get("/admin/flow-versions/global")


@mcp.tool()
async def set_global_flow(graph: dict[str, Any], activate: bool = True) -> dict:
    """REPLACE the whole global flow with `graph` ({states, transitions, layout}) —
    only for full rebuilds; prefer the atomic flow_* ops for small changes.
    Requires admin.types."""
    return await _api().post(
        "/admin/flow-versions/global", json={"graph": graph, "activate": activate}
    )


async def _flow_graph() -> dict[str, Any]:
    graph = await _api().get("/admin/flow-versions/global")
    if not graph or not isinstance(graph, dict) or not graph.get("states"):
        raise ApiError(404, "no global flow exists yet — create one with set_global_flow")
    return graph


async def _save_flow(graph: dict[str, Any]) -> dict:
    result = await _api().post(
        "/admin/flow-versions/global", json={"graph": graph, "activate": True}
    )
    return {
        "saved": True,
        "states": len(graph.get("states") or []),
        "transitions": len(graph.get("transitions") or []),
        "flowVersion": result,
    }


@mcp.tool()
async def flow_add_state(
    state: S.StateDef, x: int | None = None, y: int | None = None
) -> dict:
    """ATOMIC: add one state to the global flow (optionally with an editor position)
    and activate the result. Requires admin.types."""
    graph = graphops.add_state(await _flow_graph(), dump_create(state), x, y)
    return await _save_flow(graph)


@mcp.tool()
async def flow_update_state(key: str, patch: S.StateDefPatch) -> dict:
    """ATOMIC: patch one state of the global flow (only the provided keys change).
    Renaming via patch.key cascades to transitions/layout/groups. Requires admin.types."""
    graph = graphops.update_state(await _flow_graph(), key, dump_patch(patch))
    return await _save_flow(graph)


@mcp.tool()
async def flow_remove_state(key: str) -> dict:
    """ATOMIC: remove one state from the global flow, including its transitions,
    position and group membership. Requires admin.types."""
    graph = graphops.remove_state(await _flow_graph(), key)
    return await _save_flow(graph)


@mcp.tool()
async def flow_add_transition(transition: S.TransitionDef) -> dict:
    """ATOMIC: append one transition to the global flow. Requires admin.types."""
    graph = graphops.add_transition(await _flow_graph(), dump_create(transition))
    return await _save_flow(graph)


@mcp.tool()
async def flow_update_transition(index: int, patch: S.TransitionDefPatch) -> dict:
    """ATOMIC: patch the transition at `index` (its position in the `transitions` array
    of get_global_flow). Only provided keys change; an explicit null REMOVES a key
    (e.g. guard=null drops the guard). Read the flow first — indices shift after
    add/remove. Requires admin.types."""
    raw = patch.model_dump(by_alias=True, exclude_unset=True)
    graph = graphops.update_transition(await _flow_graph(), index, raw)
    return await _save_flow(graph)


@mcp.tool()
async def flow_remove_transition(index: int) -> dict:
    """ATOMIC: remove the transition at `index` (position in the `transitions` array).
    Requires admin.types."""
    graph = graphops.remove_transition(await _flow_graph(), index)
    return await _save_flow(graph)


@mcp.tool()
async def flow_set_positions(positions: dict[str, dict[str, int]]) -> dict:
    """ATOMIC: merge editor positions into the flow layout —
    {stateKey: {x, y}, ...}. Requires admin.types."""
    graph = graphops.merge_positions(await _flow_graph(), positions)
    return await _save_flow(graph)


@mcp.tool()
async def flow_set_group(group: S.FlowGroupDef) -> dict:
    """ATOMIC: create or update a visual node group (upsert by group.id) in
    layout.groups. Groups are editor-only: a collapsed group renders as one labelled
    box; the flow engine ignores them. A state belongs to at most one group — adding
    it here removes it from others. Requires admin.types."""
    graph = graphops.upsert_group(await _flow_graph(), dump_create(group))
    return await _save_flow(graph)


@mcp.tool()
async def flow_delete_group(group_id: str) -> dict:
    """ATOMIC: delete a visual node group (states stay untouched). Requires admin.types."""
    graph = graphops.delete_group(await _flow_graph(), group_id)
    return await _save_flow(graph)


# ================================================== form editing (admin/config)
@mcp.tool()
async def get_latest_form_version(type_id: str) -> dict:
    """Fetch the latest form version of an application type (raw field list for
    editing; the form_* atomic ops address fields by their `key`)."""
    return await _api().get(f"/admin/application-types/{type_id}/form-versions/latest")


@mcp.tool()
async def get_effective_form(type_id: str, budget_pot_id: str | None = None) -> dict:
    """The effective (public) form of a type — sections + fields as applicants see
    them. Use this to know which `data` keys create_application expects."""
    return await _api().get(
        f"/application-types/{type_id}/form",
        params=_params(budgetPotId=budget_pot_id),
    )


@mcp.tool()
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
    return await _api().post(f"/admin/application-types/{type_id}/form-versions", json=body)


@mcp.tool()
async def set_active_form(type_id: str, active: bool) -> dict:
    """Activate (latest version) or deactivate the form of an application type —
    deactivated types are closed for new applications. Requires form.configure."""
    return await _api().patch(
        f"/admin/application-types/{type_id}/form-active", json={"active": active}
    )


async def _form_state(type_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    draft = await _api().get(f"/admin/application-types/{type_id}/form-versions/latest")
    return list(draft.get("fields") or []), draft.get("description")


async def _save_form(
    type_id: str, fields: list[dict[str, Any]], description: dict[str, Any] | None
) -> dict:
    body: dict[str, Any] = {"fields": fields, "activate": True}
    if description:
        body["description"] = description
    result = await _api().post(
        f"/admin/application-types/{type_id}/form-versions", json=body
    )
    return {"saved": True, "fields": len(fields), "formVersion": result}


@mcp.tool()
async def form_add_field(
    type_id: str, field: S.FormFieldDef, index: int | None = None
) -> dict:
    """ATOMIC: add one field to the type's form (at `index`, default: append) and
    activate the new version. Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(
        type_id, graphops.add_field(fields, dump_create(field), index), description
    )


@mcp.tool()
async def form_update_field(type_id: str, key: str, patch: S.FormFieldPatch) -> dict:
    """ATOMIC: patch one form field (addressed by its `key`; only provided keys
    change) and activate the new version. Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(
        type_id, graphops.update_field(fields, key, dump_patch(patch)), description
    )


@mcp.tool()
async def form_remove_field(type_id: str, key: str) -> dict:
    """ATOMIC: remove one form field by `key` and activate the new version.
    Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(type_id, graphops.remove_field(fields, key), description)


@mcp.tool()
async def form_move_field(type_id: str, key: str, index: int) -> dict:
    """ATOMIC: move one form field to position `index` and activate the new version.
    Requires form.configure."""
    fields, description = await _form_state(type_id)
    return await _save_form(type_id, graphops.move_field(fields, key, index), description)


# ====================================================== votes (manage, NOT cast)
@mcp.tool()
async def get_vote(vote_id: str) -> dict:
    """Fetch a vote's state + aggregated tally (secret votes expose counts only)."""
    return await _api().get(f"/votes/{vote_id}")


@mcp.tool()
async def create_application_vote(application_id: str, vote: S.VoteCreate) -> dict:
    """Create a vote bound to an application. Requires vote.manage."""
    return await _api().post(
        f"/applications/{application_id}/votes", json=dump_create(vote)
    )


@mcp.tool()
async def open_vote(vote_id: str) -> dict:
    """Open a vote for balloting. Requires vote.manage."""
    return await _api().post(f"/votes/{vote_id}/open")


@mcp.tool()
async def close_vote(vote_id: str) -> dict:
    """Close a vote, tally it, fire the result branch. Requires vote.manage.
    (Agents manage votes but cannot cast ballots — that is human-only.)"""
    return await _api().post(f"/votes/{vote_id}/close")


# ============================================================ meetings (manage)
@mcp.tool()
async def list_meetings() -> dict:
    """List meetings."""
    return await _api().get("/meetings")


@mcp.tool()
async def get_meeting(meeting_id: str) -> dict:
    """Fetch one meeting (agenda, attendance, votes)."""
    return await _api().get(f"/meetings/{meeting_id}")


@mcp.tool()
async def create_meeting(meeting: S.MeetingCreate) -> dict:
    """Create a meeting. Requires meeting.manage."""
    return await _api().post("/meetings", json=dump_create(meeting))


@mcp.tool()
async def update_meeting(meeting_id: str, patch: S.MeetingPatch) -> dict:
    """Patch a meeting (status planned|live|closed, date, startTime, protokollantId,
    activeApplicationId). Requires meeting.manage."""
    return await _api().patch(f"/meetings/{meeting_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_meeting(meeting_id: str) -> dict:
    """Delete a meeting. Requires meeting.manage."""
    return await _api().delete(f"/meetings/{meeting_id}")


@mcp.tool()
async def get_attendance(meeting_id: str) -> dict:
    """Attendance list of a meeting (present/excused/absent per member)."""
    return await _api().get(f"/meetings/{meeting_id}/attendance")


@mcp.tool()
async def set_attendance(
    meeting_id: str,
    principal_id: str,
    status: Literal["present", "excused", "absent"],
) -> dict:
    """Set a member's attendance for a meeting. Requires meeting.manage."""
    return await _api().put(
        f"/meetings/{meeting_id}/attendance/{principal_id}", json={"status": status}
    )


@mcp.tool()
async def add_agenda_item(
    meeting_id: str,
    application_id: str | None = None,
    title: str | None = None,
) -> dict:
    """Add an agenda item (TOP): EXACTLY ONE of application_id (application TOP) or
    title (free-text TOP). Requires meeting.manage."""
    return await _api().post(
        f"/meetings/{meeting_id}/agenda",
        json=_params(applicationId=application_id, title=title),
    )


@mcp.tool()
async def update_agenda_item(
    meeting_id: str,
    item_id: str,
    body: str | None = None,
    title: str | None = None,
) -> dict:
    """Update an agenda item: `body` sets the markdown text; `title` renames a
    free-text TOP (application TOPs inherit their title). Requires meeting.manage."""
    return await _api().patch(
        f"/meetings/{meeting_id}/agenda/{item_id}",
        json=_params(body=body, title=title),
    )


@mcp.tool()
async def delete_agenda_item(meeting_id: str, item_id: str) -> dict:
    """Remove an agenda item from a meeting. Requires meeting.manage."""
    return await _api().delete(f"/meetings/{meeting_id}/agenda/{item_id}")


@mcp.tool()
async def reorder_agenda(meeting_id: str, item_ids: list[str]) -> dict:
    """Reorder the agenda: item_ids in the desired order. Requires meeting.manage."""
    return await _api().put(
        f"/meetings/{meeting_id}/agenda/order", json={"itemIds": item_ids}
    )


@mcp.tool()
async def list_assignable_agenda_items(meeting_id: str) -> dict:
    """Applications available to be added as agenda items for this meeting."""
    return await _api().get(f"/meetings/{meeting_id}/agenda/assignable")


@mcp.tool()
async def create_meeting_vote(meeting_id: str, vote: S.MeetingVoteOpenBody) -> dict:
    """Open a live vote within a meeting on an agenda item (generic TOP or
    application-bound). Requires vote.manage."""
    return await _api().post(f"/meetings/{meeting_id}/votes", json=dump_create(vote))


@mcp.tool()
async def delete_meeting_vote(meeting_id: str, vote_id: str) -> dict:
    """Delete a meeting vote. Requires vote.manage."""
    return await _api().delete(f"/meetings/{meeting_id}/votes/{vote_id}")


# ===================================================== protocol (minutes)
@mcp.tool()
async def get_or_create_protocol(meeting_id: str) -> dict:
    """Create OR load the meeting's protocol (idempotent, 1:1 per meeting).
    Requires meeting.manage."""
    return await _api().post(f"/meetings/{meeting_id}/protocol")


@mcp.tool()
async def update_protocol(protocol_id: str, markdown: str) -> dict:
    """Update the protocol's markdown body. 409 while it is final or rendering.
    Requires meeting.manage."""
    return await _api().patch(f"/protocols/{protocol_id}", json={"markdown": markdown})


@mcp.tool()
async def embed_protocol_votes(protocol_id: str, vote_ids: list[str]) -> dict:
    """Append closed votes as markdown snippets to the protocol (idempotent per vote).
    Requires meeting.manage."""
    return await _api().post(
        f"/protocols/{protocol_id}/votes", json={"voteIds": vote_ids}
    )


@mcp.tool()
async def finalize_protocol(protocol_id: str) -> dict:
    """Finalize the protocol: ASYNC — returns `status: "rendering"` while a worker
    renders the PDF and mails it to the committee. Re-fetch via
    `get_or_create_protocol(meeting_id)` until `status` is `final`; a fall back to
    `draft` means the render failed (fix content, finalize again). Idempotent.
    Requires meeting.manage."""
    return await _api().post(f"/protocols/{protocol_id}/finalize")


# ============================================================ delegations
@mcp.tool()
async def list_delegations() -> dict:
    """List meeting delegations (who delegates attendance/voting to whom)."""
    return await _api().get("/delegations")


@mcp.tool()
async def create_delegation(delegation: S.DelegationCreate) -> dict:
    """Delegate attendance (and optionally voting) for a meeting to another member."""
    return await _api().post("/delegations", json=dump_create(delegation))


@mcp.tool()
async def revoke_delegation(delegation_id: str) -> dict:
    """Revoke a delegation."""
    return await _api().delete(f"/delegations/{delegation_id}")


@mcp.tool()
async def list_substitutes() -> dict:
    """List the substitute pool (standing stand-ins per committee)."""
    return await _api().get("/delegations/substitutes")


@mcp.tool()
async def create_substitute(substitute: S.SubstituteCreate) -> dict:
    """Add a stand-in to a committee's substitute pool."""
    return await _api().post("/delegations/substitutes", json=dump_create(substitute))


@mcp.tool()
async def delete_substitute(substitute_id: str) -> dict:
    """Remove a stand-in from the substitute pool."""
    return await _api().delete(f"/delegations/substitutes/{substitute_id}")


# ============================================================ attachments (meta)
@mcp.tool()
async def list_attachments(application_id: str) -> dict:
    """List an application's file attachments (metadata only — up/download is
    UI/REST territory)."""
    return await _api().get(f"/applications/{application_id}/attachments")


@mcp.tool()
async def delete_attachment(attachment_id: str) -> dict:
    """Delete a file attachment."""
    return await _api().delete(f"/attachments/{attachment_id}")


# ============================================================ budget (manage)
@mcp.tool()
async def list_budgets(gremium: str | None = None) -> dict:
    """List the cost-centre (budget) tree with allocations/rollups, optionally
    filtered to one committee."""
    return await _api().get("/budgets", params=_params(gremium=gremium))


@mcp.tool()
async def get_budget_applications(budget_id: str) -> dict:
    """List applications bound to a cost centre (incl. subtree)."""
    return await _api().get(f"/budgets/{budget_id}/applications")


@mcp.tool()
async def create_budget(node: S.BudgetNodeCreate) -> dict:
    """Create a cost-centre (budget) node. gremiumId only on top-level nodes;
    parentId/gremiumId are immutable afterwards. Requires budget.manage."""
    return await _api().post("/budgets", json=dump_create(node))


@mcp.tool()
async def update_budget(budget_id: str, patch: S.BudgetNodeUpdate) -> dict:
    """Patch a cost-centre node (key/name/color/active/acceptedStateKeys/…).
    Requires budget.manage."""
    return await _api().patch(f"/budgets/{budget_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_budget(budget_id: str) -> dict:
    """Delete a cost-centre node (conflicts if it has children). Requires budget.manage."""
    return await _api().delete(f"/budgets/{budget_id}")


@mcp.tool()
async def list_fiscal_years(budget_id: str) -> dict:
    """List the fiscal years of a top-level budget. Requires budget.manage."""
    return await _api().get(f"/budgets/{budget_id}/fiscal-years")


@mcp.tool()
async def create_fiscal_year(budget_id: str, year: int, active: bool = True) -> dict:
    """Create a fiscal year on a top-level budget (bounds derive from the budget's
    fiscal start day/month; overlapping years → 422). Requires budget.manage."""
    return await _api().post(
        f"/budgets/{budget_id}/fiscal-years", json={"year": year, "active": active}
    )


@mcp.tool()
async def update_fiscal_year(
    budget_id: str, fiscal_year_id: str, year: int | None = None, active: bool | None = None
) -> dict:
    """Patch a fiscal year (year/active). Requires budget.manage."""
    return await _api().patch(
        f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}",
        json=_params(year=year, active=active),
    )


@mcp.tool()
async def set_allocation(budget_id: str, fiscal_year_id: str, allocated: str) -> dict:
    """Set the top-down allocation (Soll) of a cost centre for one fiscal year.
    allocated = decimal string; 422 if the children's sum exceeds the parent.
    Requires budget.manage."""
    return await _api().put(
        f"/budgets/{budget_id}/allocations/{fiscal_year_id}",
        json={"allocated": allocated},
    )


@mcp.tool()
async def book_expense(
    budget_id: str,
    amount: str,
    description: str,
    kind: Literal["expense", "income"] = "expense",
    fiscal_year_id: str | None = None,
    application_id: str | None = None,
    account_id: str | None = None,
) -> dict:
    """Book an expense/income on a cost centre. amount = decimal string; optionally
    linked to an application and a bank account. Requires budget.manage."""
    return await _api().post(
        f"/budgets/{budget_id}/expenses",
        json=_params(
            amount=amount, description=description, kind=kind,
            fiscalYearId=fiscal_year_id, applicationId=application_id,
            accountId=account_id,
        ),
    )


@mcp.tool()
async def list_budget_expenses(budget_id: str) -> dict:
    """List the bookings (expenses/income) of a cost centre."""
    return await _api().get(f"/budgets/{budget_id}/expenses")


@mcp.tool()
async def update_expense(expense_id: str, patch: S.ExpenseUpdate) -> dict:
    """Patch a booking (amount/description). Requires budget.manage."""
    return await _api().patch(f"/budget-expenses/{expense_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_expense(expense_id: str) -> dict:
    """Delete a booking. Requires budget.manage."""
    return await _api().delete(f"/budget-expenses/{expense_id}")


@mcp.tool()
async def create_budget_transfer(transfer: S.TransferCreate) -> dict:
    """Transfer budget between two cost centres within one fiscal year.
    Requires budget.manage."""
    return await _api().post("/budget-transfers", json=dump_create(transfer))


@mcp.tool()
async def list_accounts() -> dict:
    """List bank accounts (for expense booking)."""
    return await _api().get("/accounts")


@mcp.tool()
async def create_account(account: S.AccountCreate) -> dict:
    """Create a bank account. Requires budget.manage."""
    return await _api().post("/accounts", json=dump_create(account))


@mcp.tool()
async def update_account(account_id: str, patch: S.AccountUpdate) -> dict:
    """Patch a bank account. Requires budget.manage."""
    return await _api().patch(f"/accounts/{account_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_account(account_id: str) -> dict:
    """Delete a bank account. Requires budget.manage."""
    return await _api().delete(f"/accounts/{account_id}")


@mcp.tool()
async def assign_application_budget(
    application_id: str, budget_id: str | None
) -> dict:
    """Bind an application to a cost centre (null unbinds). The fiscal year derives
    from the top-level node's single active year. Requires budget.manage."""
    return await _api().post(
        f"/applications/{application_id}/assign-budget", json={"budgetId": budget_id}
    )


@mcp.tool()
async def move_application_fiscal_year(application_id: str, fiscal_year_id: str) -> dict:
    """Move an application's budget binding to another fiscal year.
    Requires budget.manage."""
    return await _api().post(
        f"/applications/{application_id}/move-fiscal-year",
        json={"fiscalYearId": fiscal_year_id},
    )


# ============================================================ admin: gremien
@mcp.tool()
async def list_gremien() -> dict:
    """List Gremien (committees)."""
    return await _api().get("/admin/gremien")


@mcp.tool()
async def create_gremium(gremium: S.GremiumCreate) -> dict:
    """Create a Gremium. Requires admin.gremien."""
    return await _api().post("/admin/gremien", json=dump_create(gremium))


@mcp.tool()
async def update_gremium(gremium_id: str, patch: S.GremiumUpdate) -> dict:
    """Patch a Gremium. Requires admin.gremien."""
    return await _api().patch(f"/admin/gremien/{gremium_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_gremium(gremium_id: str) -> dict:
    """Delete a Gremium. Requires admin.gremien."""
    return await _api().delete(f"/admin/gremien/{gremium_id}")


@mcp.tool()
async def get_gremium_mail_recipients(gremium_id: str) -> dict:
    """Additional minutes (protocol) recipients of a committee — finalized minutes
    go to the active members AND these addresses."""
    return await _api().get(f"/admin/gremien/{gremium_id}/mail-recipients")


@mcp.tool()
async def set_gremium_mail_recipients(gremium_id: str, recipients: list[str]) -> dict:
    """Replace the committee's additional minutes recipients (idempotent PUT; an
    empty list means members-only delivery). Requires admin.gremien."""
    return await _api().put(
        f"/admin/gremien/{gremium_id}/mail-recipients", json={"recipients": recipients}
    )


@mcp.tool()
async def list_gremium_roles(gremium_id: str) -> dict:
    """List the committee-scoped roles of a Gremium."""
    return await _api().get(f"/admin/gremien/{gremium_id}/roles")


@mcp.tool()
async def create_gremium_role(gremium_id: str, role: S.GremiumRoleCreate) -> dict:
    """Create a committee-scoped role. Requires admin.gremien."""
    return await _api().post(f"/admin/gremien/{gremium_id}/roles", json=dump_create(role))


@mcp.tool()
async def update_gremium_role(role_id: str, patch: S.GremiumRoleUpdate) -> dict:
    """Patch a committee-scoped role. Requires admin.gremien."""
    return await _api().patch(f"/admin/gremium-roles/{role_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_gremium_role(role_id: str) -> dict:
    """Delete a committee-scoped role. Requires admin.gremien."""
    return await _api().delete(f"/admin/gremium-roles/{role_id}")


@mcp.tool()
async def list_gremium_memberships(gremium_id: str) -> dict:
    """List the memberships (member ↔ committee role) of a Gremium."""
    return await _api().get(f"/admin/gremien/{gremium_id}/memberships")


@mcp.tool()
async def create_gremium_membership(
    gremium_id: str, membership: S.GremiumMembershipCreate
) -> dict:
    """Add a member to a Gremium with a committee role. Requires admin.gremien."""
    return await _api().post(
        f"/admin/gremien/{gremium_id}/memberships", json=dump_create(membership)
    )


@mcp.tool()
async def delete_gremium_membership(membership_id: str) -> dict:
    """End a Gremium membership. Requires admin.gremien."""
    return await _api().delete(f"/admin/gremium-memberships/{membership_id}")


# ============================================================ admin: roles/RBAC
@mcp.tool()
async def list_permissions() -> dict:
    """List the assignable permission catalogue."""
    return await _api().get("/admin/permissions")


@mcp.tool()
async def list_roles() -> dict:
    """List global roles + their permissions."""
    return await _api().get("/admin/roles")


@mcp.tool()
async def create_role(role: S.RoleCreate) -> dict:
    """Create a global role. Requires admin.roles."""
    return await _api().post("/admin/roles", json=dump_create(role))


@mcp.tool()
async def update_role(role_id: str, patch: S.RoleUpdate) -> dict:
    """Patch a global role (label/permissions). Requires admin.roles."""
    return await _api().patch(f"/admin/roles/{role_id}", json=dump_patch(patch))


@mcp.tool()
async def delete_role(role_id: str) -> dict:
    """Delete a global role. Requires admin.roles."""
    return await _api().delete(f"/admin/roles/{role_id}")


@mcp.tool()
async def list_role_assignments() -> dict:
    """List RBAC role assignments (principal ↔ role, optional gremium scope)."""
    return await _api().get("/admin/role-assignments")


@mcp.tool()
async def create_role_assignment(assignment: S.RoleAssignmentCreate) -> dict:
    """Assign a role to a principal (optionally gremium-scoped/time-boxed).
    Requires admin.roles."""
    return await _api().post("/admin/role-assignments", json=dump_create(assignment))


@mcp.tool()
async def update_role_assignment(
    assignment_id: str, patch: S.RoleAssignmentUpdate
) -> dict:
    """Patch a role assignment (role/gremium/validity). Requires admin.roles."""
    return await _api().patch(
        f"/admin/role-assignments/{assignment_id}", json=dump_patch(patch)
    )


@mcp.tool()
async def delete_role_assignment(assignment_id: str) -> dict:
    """Remove a role assignment. Requires admin.roles."""
    return await _api().delete(f"/admin/role-assignments/{assignment_id}")


@mcp.tool()
async def list_principals(q: str | None = None) -> dict:
    """List principals (users), optionally filtered by sub/email substring."""
    return await _api().get("/admin/principals", params=_params(q=q))


@mcp.tool()
async def update_principal(principal_id: str, active: bool) -> dict:
    """Activate/deactivate a principal. Requires admin.roles."""
    return await _api().patch(
        f"/admin/principals/{principal_id}", json={"active": active}
    )


@mcp.tool()
async def list_group_mappings() -> dict:
    """List OIDC group → role mappings."""
    return await _api().get("/admin/group-mappings")


@mcp.tool()
async def create_group_mapping(mapping: S.GroupMappingCreate) -> dict:
    """Map an OIDC group to a role (optionally gremium-scoped). Requires admin.roles."""
    return await _api().post("/admin/group-mappings", json=dump_create(mapping))


@mcp.tool()
async def update_group_mapping(mapping_id: str, patch: S.GroupMappingUpdate) -> dict:
    """Patch an OIDC group mapping. Requires admin.roles."""
    return await _api().patch(f"/admin/group-mappings/{mapping_id}", json=dump_patch(patch))


# ====================================================== admin: application types
@mcp.tool()
async def list_application_types() -> dict:
    """List application types (admin view)."""
    return await _api().get("/admin/application-types")


@mcp.tool()
async def create_application_type(type: S.ApplicationTypeCreate) -> dict:
    """Create an application type. Requires admin.types."""
    return await _api().post("/admin/application-types", json=dump_create(type))


@mcp.tool()
async def update_application_type(type_id: str, patch: S.ApplicationTypeUpdate) -> dict:
    """Patch an application type. Requires admin.types."""
    return await _api().patch(
        f"/admin/application-types/{type_id}", json=dump_patch(patch)
    )


# ============================================================ admin: webhooks
@mcp.tool()
async def list_webhooks() -> dict:
    """List configured webhooks."""
    return await _api().get("/admin/webhooks")


@mcp.tool()
async def create_webhook(webhook: S.WebhookCreate) -> dict:
    """Create a webhook. Requires webhook.manage."""
    return await _api().post("/admin/webhooks", json=dump_create(webhook))


@mcp.tool()
async def update_webhook(webhook_id: str, patch: S.WebhookUpdate) -> dict:
    """Patch a webhook. Requires webhook.manage."""
    return await _api().patch(f"/admin/webhooks/{webhook_id}", json=dump_patch(patch))


# ====================================================== admin: deadline policies
@mcp.tool()
async def list_deadline_policies() -> dict:
    """List named deadline policies (referenced by flow states via
    config.deadlinePolicyKey)."""
    return await _api().get("/admin/deadline-policies")


@mcp.tool()
async def create_deadline_policy(policy: S.DeadlinePolicyCreate) -> dict:
    """Create a deadline policy (absolute date or relative offset). Entering a flow
    state that references its key materialises a deadline. Requires admin.types."""
    return await _api().post("/admin/deadline-policies", json=dump_create(policy))


@mcp.tool()
async def update_deadline_policy(policy_id: str, patch: S.DeadlinePolicyUpdate) -> dict:
    """Patch a deadline policy (e.g. bump the absolute date each semester — no new
    flow version needed). Requires admin.types."""
    return await _api().patch(
        f"/admin/deadline-policies/{policy_id}", json=dump_patch(patch)
    )


@mcp.tool()
async def delete_deadline_policy(policy_id: str) -> dict:
    """Delete a deadline policy. States referencing it then hold without a deadline.
    Requires admin.types."""
    return await _api().delete(f"/admin/deadline-policies/{policy_id}")


# ============================================================ notifications
@mcp.tool()
async def get_notification_settings() -> dict:
    """Platform notification settings (task reminder cadence). Admin."""
    return await _api().get("/admin/notifications")


@mcp.tool()
async def update_notification_settings(patch: S.NotificationSettingsUpdate) -> dict:
    """Patch platform notification settings (taskReminderEnabled/AfterDays/RepeatDays).
    Admin."""
    return await _api().put("/admin/notifications", json=dump_patch(patch))


@mcp.tool()
async def get_notification_preferences() -> dict:
    """The logged-in user's own notification preferences."""
    return await _api().get("/notifications/preferences")


@mcp.tool()
async def set_notification_preferences(preferences: list[dict[str, Any]]) -> dict:
    """Replace the logged-in user's notification preferences (same shape as returned
    by get_notification_preferences)."""
    return await _api().put(
        "/notifications/preferences", json={"preferences": preferences}
    )


# ============================================================ admin: site config
@mcp.tool()
async def get_site_config() -> dict:
    """Fetch the current site/branding config (active + draft)."""
    return await _api().get("/admin/site-config")


@mcp.tool()
async def set_site_config_draft(branding: dict[str, Any]) -> dict:
    """Set the branding DRAFT (same shape as the draft in get_site_config); activate
    it with activate_site_config. Requires admin.site."""
    return await _api().put("/admin/site-config/draft", json=branding)


@mcp.tool()
async def activate_site_config() -> dict:
    """Activate the current branding draft. Requires admin.site."""
    return await _api().post("/admin/site-config/activate")


# ============================================================ audit
@mcp.tool()
async def list_audit(
    action: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    before: int | None = None,
    limit: int | None = None,
) -> dict:
    """Read the audit log (keyset-paged: pass the smallest seen id as `before` to
    continue; since/until = ISO datetimes). Requires audit.read."""
    return await _api().get(
        "/admin/audit",
        params=_params(
            action=action, actor=actor, since=since, until=until,
            before=before, limit=limit,
        ),
    )


@mcp.tool()
async def verify_audit_chain() -> dict:
    """Verify the audit log's hash chain (tamper check). Requires audit.verify."""
    return await _api().get("/admin/audit/verify")


def main() -> None:
    """Console entry point (stdio transport)."""
    _cfg()  # fail fast if ANTRAGSPLATTFORM_URL is missing
    mcp.run()


if __name__ == "__main__":
    main()
