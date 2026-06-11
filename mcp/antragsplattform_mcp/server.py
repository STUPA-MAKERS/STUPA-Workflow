"""FastMCP server exposing platform API actions as tools.

Auth is handled transparently by :mod:`antragsplattform_mcp.client` /
:mod:`antragsplattform_mcp.auth`: the first tool call triggers a browser login
(OAuth2 + PKCE), the token is cached and refreshed automatically. All rights are capped
server-side by the logged-in user's permissions intersected with the granted scope.

Forbidden by design: agents can manage votes (create/open/close) but can NEVER cast a
ballot — there is intentionally no ``cast_ballot`` tool, and ``vote.cast`` is never
grantable to a token. Everything else (applications, decisions/transitions, flows, forms,
meetings, budget, admin CRUD) is exposed, gated server-side by the user's permissions.

Complex create/update bodies are passed through as ``body: dict`` (the raw API JSON, camelCase
keys); validation errors from the server describe the expected shape.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import auth
from .client import ApiClient
from .config import Config

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
  `list_tasks` shows the applications the logged-in user can currently act on; transitions
  carry `requiresAction` (false = optional action that does not count as an open task).
- Create an application: `list_application_types` → `create_application(type_id, data={...})`
  where `data` are the form-field values for that type's form.
- Edit a flow/form: `get_global_flow`/`get_latest_form_version` to read the current shape,
  then `set_global_flow`/`create_form_version` with the same shape modified.
- Run a meeting: `create_meeting` → `add_agenda_item` → `create_meeting_vote` → `close_vote`.
  A vote becomes `cancelled` (no result) when its application leaves the vote state via a
  manual transition (e.g. an aborted election).
- Minutes (Protokoll): `get_or_create_protocol(meeting_id)` → `update_protocol(markdown)` →
  `finalize_protocol`. Finalize is ASYNC: it returns `status: "rendering"` and a worker
  renders the PDF + mails it; re-fetch until `status` is `final` (success) or back at
  `draft` (render failed — fix the content and finalize again).
- Budget: `list_budgets` (tree), `update_budget` (name/key/color), `book_expense`.

CONVENTIONS: ids are UUID strings. Money amounts are decimal strings ("1500.00"). Request
bodies use camelCase keys (e.g. transitionId, gremiumId). For `body: dict` params, pass the
raw API JSON; validation errors describe the expected shape. Prefer reading (get/list) before
writing, and echo back what you changed.
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


# ============================================================= applications
@mcp.tool()
async def list_applications(
    state: str | None = None,
    gremium: str | None = None,
    type: str | None = None,
    q: str | None = None,
    sort: str | None = None,
    order: str | None = None,
) -> dict:
    """List applications. Filters: state (id), gremium (id), type (id), q (full-text),
    sort (createdAt|amount), order (asc|desc)."""
    return await _api().get(
        "/applications",
        params=_params(state=state, gremium=gremium, type=type, q=q, sort=sort, order=order),
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
async def create_application(
    type_id: str,
    data: dict[str, Any],
    applicant_email: str | None = None,
    applicant_name: str | None = None,
    lang: str | None = None,
) -> dict:
    """Create an application of the given type. `data` = form-field values (validated
    against the type's effective form). For a logged-in user, email/name are derived
    from the account if omitted."""
    return await _api().post(
        "/applications",
        json=_params(
            typeId=type_id, data=data, applicantEmail=applicant_email,
            applicantName=applicant_name, lang=lang,
        ),
    )


@mcp.tool()
async def update_application(application_id: str, body: dict[str, Any]) -> dict:
    """Patch an application (e.g. {"data": {...}}). Subject to edit permissions/state."""
    return await _api().patch(f"/applications/{application_id}", json=body)


@mcp.tool()
async def comment_application(
    application_id: str, body: str, visibility: str = "public"
) -> dict:
    """Add a comment to an application. visibility = public | internal."""
    return await _api().post(
        f"/applications/{application_id}/comments",
        json={"body": body, "visibility": visibility},
    )


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
    """Fetch the active global flow version (states + transitions)."""
    return await _api().get("/admin/flow-versions/global")


@mcp.tool()
async def set_global_flow(body: dict[str, Any]) -> dict:
    """Create/replace the global flow version. `body` = the flow definition
    (states + transitions, camelCase). Requires flow.configure."""
    return await _api().post("/admin/flow-versions/global", json=body)


# ================================================== form editing (admin/config)
@mcp.tool()
async def get_latest_form_version(type_id: str) -> dict:
    """Fetch the latest form version of an application type."""
    return await _api().get(
        f"/admin/application-types/{type_id}/form-versions/latest"
    )


@mcp.tool()
async def create_form_version(type_id: str, body: dict[str, Any]) -> dict:
    """Create a new form version for an application type. `body` = {fields:[...]}.
    Requires form.configure."""
    return await _api().post(
        f"/admin/application-types/{type_id}/form-versions", json=body
    )


@mcp.tool()
async def set_active_form(type_id: str, body: dict[str, Any]) -> dict:
    """Activate a form version for an application type. Requires form.configure."""
    return await _api().patch(
        f"/admin/application-types/{type_id}/form-active", json=body
    )


# ====================================================== votes (manage, NOT cast)
@mcp.tool()
async def get_vote(vote_id: str) -> dict:
    """Fetch a vote's state + aggregated tally (secret votes expose counts only)."""
    return await _api().get(f"/votes/{vote_id}")


@mcp.tool()
async def create_application_vote(application_id: str, body: dict[str, Any]) -> dict:
    """Create a vote bound to an application. Requires vote.manage."""
    return await _api().post(f"/applications/{application_id}/votes", json=body)


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
async def create_meeting(body: dict[str, Any]) -> dict:
    """Create a meeting. `body` = {gremiumId, title, startsAt, ...}. Requires meeting.manage."""
    return await _api().post("/meetings", json=body)


@mcp.tool()
async def update_meeting(meeting_id: str, body: dict[str, Any]) -> dict:
    """Patch a meeting (state/title/etc). Requires meeting.manage."""
    return await _api().patch(f"/meetings/{meeting_id}", json=body)


@mcp.tool()
async def delete_meeting(meeting_id: str) -> dict:
    """Delete a meeting. Requires meeting.manage."""
    return await _api().delete(f"/meetings/{meeting_id}")


@mcp.tool()
async def add_agenda_item(meeting_id: str, body: dict[str, Any]) -> dict:
    """Add an agenda item (TOP) to a meeting. Requires meeting.manage."""
    return await _api().post(f"/meetings/{meeting_id}/agenda", json=body)


@mcp.tool()
async def create_meeting_vote(meeting_id: str, body: dict[str, Any]) -> dict:
    """Open a vote within a meeting (generic TOP or application-bound). Requires vote.manage."""
    return await _api().post(f"/meetings/{meeting_id}/votes", json=body)


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
    `draft` means the render failed (fix content, finalize again). Idempotent:
    rendering/final protocols are returned unchanged. Requires meeting.manage."""
    return await _api().post(f"/protocols/{protocol_id}/finalize")


# ============================================================ budget (manage)
@mcp.tool()
async def list_budgets() -> dict:
    """List the cost-centre (budget) tree with allocations/rollups."""
    return await _api().get("/budgets")


@mcp.tool()
async def get_budget_applications(budget_id: str) -> dict:
    """List applications bound to a cost centre."""
    return await _api().get(f"/budgets/{budget_id}/applications")


@mcp.tool()
async def book_expense(
    budget_id: str,
    amount: str,
    description: str,
    kind: str = "expense",
    fiscal_year_id: str | None = None,
) -> dict:
    """Book an expense/income on a cost centre. amount = decimal string; kind =
    expense | income. Requires budget.manage."""
    return await _api().post(
        f"/budgets/{budget_id}/expenses",
        json=_params(amount=amount, description=description, kind=kind, fiscalYearId=fiscal_year_id),
    )


@mcp.tool()
async def create_budget(body: dict[str, Any]) -> dict:
    """Create a cost-centre (budget) node. Requires budget.manage."""
    return await _api().post("/budgets", json=body)


@mcp.tool()
async def update_budget(budget_id: str, body: dict[str, Any]) -> dict:
    """Patch a cost-centre node — name, color, and now its `key` are editable
    (e.g. {"key": "VS-800-40", "name": "..."}). Requires budget.manage."""
    return await _api().patch(f"/budgets/{budget_id}", json=body)


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
async def set_allocation(budget_id: str, fiscal_year_id: str, allocated: str) -> dict:
    """Set the top-down allocation (Soll) of a cost centre for one fiscal year.
    allocated = decimal string; 422 if the children's sum exceeds the parent.
    Requires budget.manage."""
    return await _api().put(
        f"/budgets/{budget_id}/allocations/{fiscal_year_id}",
        json={"allocated": allocated},
    )


# ============================================================ admin: catalogues
@mcp.tool()
async def list_permissions() -> dict:
    """List the assignable permission catalogue."""
    return await _api().get("/admin/permissions")


@mcp.tool()
async def list_gremien() -> dict:
    """List Gremien (committees)."""
    return await _api().get("/admin/gremien")


@mcp.tool()
async def create_gremium(body: dict[str, Any]) -> dict:
    """Create a Gremium. Requires admin.config."""
    return await _api().post("/admin/gremien", json=body)


@mcp.tool()
async def update_gremium(gremium_id: str, body: dict[str, Any]) -> dict:
    """Patch a Gremium. Requires admin.config."""
    return await _api().patch(f"/admin/gremien/{gremium_id}", json=body)


@mcp.tool()
async def delete_gremium(gremium_id: str) -> dict:
    """Delete a Gremium. Requires admin.config."""
    return await _api().delete(f"/admin/gremien/{gremium_id}")


@mcp.tool()
async def get_gremium_mail_recipients(gremium_id: str) -> dict:
    """Additional minutes (protocol) recipients of a committee — finalized minutes
    go to the active members AND these addresses. Requires admin.config."""
    return await _api().get(f"/admin/gremien/{gremium_id}/mail-recipients")


@mcp.tool()
async def set_gremium_mail_recipients(gremium_id: str, recipients: list[str]) -> dict:
    """Replace the committee's additional minutes recipients (idempotent PUT; an
    empty list means members-only delivery). Requires admin.config."""
    return await _api().put(
        f"/admin/gremien/{gremium_id}/mail-recipients", json={"recipients": recipients}
    )


# ============================================================ admin: roles/RBAC
@mcp.tool()
async def list_roles() -> dict:
    """List roles + their permissions."""
    return await _api().get("/admin/roles")


@mcp.tool()
async def create_role(body: dict[str, Any]) -> dict:
    """Create a role. `body` = {key, name, permissions:[...]}. Requires admin.roles."""
    return await _api().post("/admin/roles", json=body)


@mcp.tool()
async def update_role(role_id: str, body: dict[str, Any]) -> dict:
    """Patch a role (e.g. its permissions). Requires admin.roles."""
    return await _api().patch(f"/admin/roles/{role_id}", json=body)


@mcp.tool()
async def delete_role(role_id: str) -> dict:
    """Delete a role. Requires admin.roles."""
    return await _api().delete(f"/admin/roles/{role_id}")


@mcp.tool()
async def list_role_assignments() -> dict:
    """List RBAC role assignments (principal ↔ role, optional gremium scope)."""
    return await _api().get("/admin/role-assignments")


@mcp.tool()
async def create_role_assignment(body: dict[str, Any]) -> dict:
    """Assign a role to a principal. `body` = {principalId, roleId, gremiumId?, validUntil?}.
    Requires admin.roles."""
    return await _api().post("/admin/role-assignments", json=body)


@mcp.tool()
async def delete_role_assignment(assignment_id: str) -> dict:
    """Remove a role assignment. Requires admin.roles."""
    return await _api().delete(f"/admin/role-assignments/{assignment_id}")


# ====================================================== admin: principals/types
@mcp.tool()
async def list_principals() -> dict:
    """List principals (users) with their active/role state."""
    return await _api().get("/admin/principals")


@mcp.tool()
async def update_principal(principal_id: str, body: dict[str, Any]) -> dict:
    """Patch a principal — e.g. activate/deactivate ({"active": false}). Requires admin.roles."""
    return await _api().patch(f"/admin/principals/{principal_id}", json=body)


@mcp.tool()
async def list_application_types() -> dict:
    """List application types."""
    return await _api().get("/admin/application-types")


@mcp.tool()
async def create_application_type(body: dict[str, Any]) -> dict:
    """Create an application type. Requires admin.config."""
    return await _api().post("/admin/application-types", json=body)


@mcp.tool()
async def update_application_type(type_id: str, body: dict[str, Any]) -> dict:
    """Patch an application type. Requires admin.config."""
    return await _api().patch(f"/admin/application-types/{type_id}", json=body)


# ============================================================ admin: webhooks
@mcp.tool()
async def list_webhooks() -> dict:
    """List configured webhooks."""
    return await _api().get("/admin/webhooks")


@mcp.tool()
async def create_webhook(body: dict[str, Any]) -> dict:
    """Create a webhook. Requires webhook.manage."""
    return await _api().post("/admin/webhooks", json=body)


@mcp.tool()
async def update_webhook(webhook_id: str, body: dict[str, Any]) -> dict:
    """Patch a webhook. Requires webhook.manage."""
    return await _api().patch(f"/admin/webhooks/{webhook_id}", json=body)


# ============================================================ admin: site config
@mcp.tool()
async def get_site_config() -> dict:
    """Fetch the current site/branding config."""
    return await _api().get("/admin/site-config")


def main() -> None:
    """Console entry point (stdio transport)."""
    _cfg()  # fail fast if ANTRAGSPLATTFORM_URL is missing
    mcp.run()


if __name__ == "__main__":
    main()
