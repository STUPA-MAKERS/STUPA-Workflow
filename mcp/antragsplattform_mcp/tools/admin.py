"""Admin tools: gremien, RBAC, application types, webhooks, deadline policies,
notifications, site config, and audit log."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


# --- gremien
@group.tool
async def list_gremien() -> dict:
    """List Gremien (committees)."""
    return await api().get("/admin/gremien")


@group.tool
async def create_gremium(gremium: S.GremiumCreate) -> dict:
    """Create a Gremium. Requires admin.gremien."""
    return await api().post("/admin/gremien", json=dump_create(gremium))


@group.tool
async def update_gremium(gremium_id: str, patch: S.GremiumUpdate) -> dict:
    """Patch a Gremium. Requires admin.gremien."""
    return await api().patch(f"/admin/gremien/{gremium_id}", json=dump_patch(patch))


@group.tool
async def delete_gremium(gremium_id: str) -> dict:
    """Delete a Gremium. Requires admin.gremien."""
    return await api().delete(f"/admin/gremien/{gremium_id}")


@group.tool
async def get_gremium_mail_recipients(gremium_id: str) -> dict:
    """Additional minutes (protocol) recipients of a committee — finalized minutes
    go to the active members AND these addresses."""
    return await api().get(f"/admin/gremien/{gremium_id}/mail-recipients")


@group.tool
async def set_gremium_mail_recipients(gremium_id: str, recipients: list[str]) -> dict:
    """Replace the committee's additional minutes recipients (idempotent PUT; an
    empty list means members-only delivery). Requires admin.gremien."""
    return await api().put(
        f"/admin/gremien/{gremium_id}/mail-recipients", json={"recipients": recipients}
    )


@group.tool
async def list_gremium_roles(gremium_id: str) -> dict:
    """List the committee-scoped roles of a Gremium."""
    return await api().get(f"/admin/gremien/{gremium_id}/roles")


@group.tool
async def create_gremium_role(gremium_id: str, role: S.GremiumRoleCreate) -> dict:
    """Create a committee-scoped role. Requires admin.gremien."""
    return await api().post(f"/admin/gremien/{gremium_id}/roles", json=dump_create(role))


@group.tool
async def update_gremium_role(role_id: str, patch: S.GremiumRoleUpdate) -> dict:
    """Patch a committee-scoped role. Requires admin.gremien."""
    return await api().patch(f"/admin/gremium-roles/{role_id}", json=dump_patch(patch))


@group.tool
async def delete_gremium_role(role_id: str) -> dict:
    """Delete a committee-scoped role. Requires admin.gremien."""
    return await api().delete(f"/admin/gremium-roles/{role_id}")


@group.tool
async def list_gremium_memberships(gremium_id: str) -> dict:
    """List the memberships (member ↔ committee role) of a Gremium."""
    return await api().get(f"/admin/gremien/{gremium_id}/memberships")


@group.tool
async def create_gremium_membership(
    gremium_id: str, membership: S.GremiumMembershipCreate
) -> dict:
    """Add a member to a Gremium with a committee role. Requires admin.gremien."""
    return await api().post(
        f"/admin/gremien/{gremium_id}/memberships", json=dump_create(membership)
    )


@group.tool
async def delete_gremium_membership(membership_id: str) -> dict:
    """End a Gremium membership. Requires admin.gremien."""
    return await api().delete(f"/admin/gremium-memberships/{membership_id}")


# --- roles / RBAC
@group.tool
async def list_permissions() -> dict:
    """List the assignable permission catalogue."""
    return await api().get("/admin/permissions")


@group.tool
async def list_roles() -> dict:
    """List global roles + their permissions."""
    return await api().get("/admin/roles")


@group.tool
async def create_role(role: S.RoleCreate) -> dict:
    """Create a global role. Requires admin.roles."""
    return await api().post("/admin/roles", json=dump_create(role))


@group.tool
async def update_role(role_id: str, patch: S.RoleUpdate) -> dict:
    """Patch a global role (label/permissions). Requires admin.roles."""
    return await api().patch(f"/admin/roles/{role_id}", json=dump_patch(patch))


@group.tool
async def delete_role(role_id: str) -> dict:
    """Delete a global role. Requires admin.roles."""
    return await api().delete(f"/admin/roles/{role_id}")


@group.tool
async def list_role_assignments() -> dict:
    """List RBAC role assignments (principal ↔ role, optional gremium scope)."""
    return await api().get("/admin/role-assignments")


@group.tool
async def create_role_assignment(assignment: S.RoleAssignmentCreate) -> dict:
    """Assign a role to a principal (optionally gremium-scoped/time-boxed).
    Requires admin.roles."""
    return await api().post("/admin/role-assignments", json=dump_create(assignment))


@group.tool
async def update_role_assignment(
    assignment_id: str, patch: S.RoleAssignmentUpdate
) -> dict:
    """Patch a role assignment (role/gremium/validity). Requires admin.roles."""
    return await api().patch(
        f"/admin/role-assignments/{assignment_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_role_assignment(assignment_id: str) -> dict:
    """Remove a role assignment. Requires admin.roles."""
    return await api().delete(f"/admin/role-assignments/{assignment_id}")


@group.tool
async def list_principals(q: str | None = None) -> dict:
    """List principals (users), optionally filtered by sub/email substring."""
    return await api().get("/admin/principals", params=params(q=q))


@group.tool
async def update_principal(principal_id: str, active: bool) -> dict:
    """Activate/deactivate a principal. Requires admin.roles."""
    return await api().patch(
        f"/admin/principals/{principal_id}", json={"active": active}
    )


@group.tool
async def list_group_mappings() -> dict:
    """List OIDC group → role mappings."""
    return await api().get("/admin/group-mappings")


@group.tool
async def create_group_mapping(mapping: S.GroupMappingCreate) -> dict:
    """Map an OIDC group to a role (optionally gremium-scoped). Requires admin.roles."""
    return await api().post("/admin/group-mappings", json=dump_create(mapping))


@group.tool
async def update_group_mapping(mapping_id: str, patch: S.GroupMappingUpdate) -> dict:
    """Patch an OIDC group mapping. Requires admin.roles."""
    return await api().patch(f"/admin/group-mappings/{mapping_id}", json=dump_patch(patch))


# --- application types
@group.tool
async def list_application_types() -> dict:
    """List application types (admin view)."""
    return await api().get("/admin/application-types")


@group.tool
async def create_application_type(type: S.ApplicationTypeCreate) -> dict:
    """Create an application type. Requires admin.types."""
    return await api().post("/admin/application-types", json=dump_create(type))


@group.tool
async def update_application_type(type_id: str, patch: S.ApplicationTypeUpdate) -> dict:
    """Patch an application type. Requires admin.types."""
    return await api().patch(
        f"/admin/application-types/{type_id}", json=dump_patch(patch)
    )


# --- webhooks
@group.tool
async def list_webhooks() -> dict:
    """List configured webhooks."""
    return await api().get("/admin/webhooks")


@group.tool
async def create_webhook(webhook: S.WebhookCreate) -> dict:
    """Create a webhook. Requires webhook.manage."""
    return await api().post("/admin/webhooks", json=dump_create(webhook))


@group.tool
async def update_webhook(webhook_id: str, patch: S.WebhookUpdate) -> dict:
    """Patch a webhook. Requires webhook.manage."""
    return await api().patch(f"/admin/webhooks/{webhook_id}", json=dump_patch(patch))


# --- deadline policies
@group.tool
async def list_deadline_policies() -> dict:
    """List named deadline policies (referenced by flow states via
    config.deadlinePolicyKey)."""
    return await api().get("/admin/deadline-policies")


@group.tool
async def create_deadline_policy(policy: S.DeadlinePolicyCreate) -> dict:
    """Create a deadline policy (absolute date or relative offset). Entering a flow
    state that references its key materialises a deadline. Requires admin.types."""
    return await api().post("/admin/deadline-policies", json=dump_create(policy))


@group.tool
async def update_deadline_policy(policy_id: str, patch: S.DeadlinePolicyUpdate) -> dict:
    """Patch a deadline policy (e.g. bump the absolute date each semester — no new
    flow version needed). Requires admin.types."""
    return await api().patch(
        f"/admin/deadline-policies/{policy_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_deadline_policy(policy_id: str) -> dict:
    """Delete a deadline policy. States referencing it then hold without a deadline.
    Requires admin.types."""
    return await api().delete(f"/admin/deadline-policies/{policy_id}")


# --- notifications
@group.tool
async def get_notification_settings() -> dict:
    """Platform notification settings (task reminder cadence). Admin."""
    return await api().get("/admin/notifications")


@group.tool
async def update_notification_settings(patch: S.NotificationSettingsUpdate) -> dict:
    """Patch platform notification settings (taskReminderEnabled/AfterDays/RepeatDays).
    Admin."""
    return await api().put("/admin/notifications", json=dump_patch(patch))


@group.tool
async def get_notification_preferences() -> dict:
    """The logged-in user's own notification preferences."""
    return await api().get("/notifications/preferences")


@group.tool
async def set_notification_preferences(preferences: list[dict[str, Any]]) -> dict:
    """Replace the logged-in user's notification preferences (same shape as returned
    by get_notification_preferences)."""
    return await api().put(
        "/notifications/preferences", json={"preferences": preferences}
    )


# --- site config
@group.tool
async def get_site_config() -> dict:
    """Fetch the current site/branding config (active + draft)."""
    return await api().get("/admin/site-config")


@group.tool
async def set_site_config_draft(branding: dict[str, Any]) -> dict:
    """Set the branding DRAFT (same shape as the draft in get_site_config); activate
    it with activate_site_config. Requires admin.site."""
    return await api().put("/admin/site-config/draft", json=branding)


@group.tool
async def activate_site_config() -> dict:
    """Activate the current branding draft. Requires admin.site."""
    return await api().post("/admin/site-config/activate")


# --- audit
@group.tool
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
    return await api().get(
        "/admin/audit",
        params=params(
            action=action, actor=actor, since=since, until=until,
            before=before, limit=limit,
        ),
    )


@group.tool
async def verify_audit_chain() -> dict:
    """Verify the audit log's hash chain (tamper check). Requires audit.verify."""
    return await api().get("/admin/audit/verify")


def register(mcp: FastMCP) -> None:
    """Register the admin tool group."""
    group.register(mcp)
