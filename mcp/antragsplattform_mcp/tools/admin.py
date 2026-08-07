"""Admin tools.

This group covers Gremien, RBAC, application types, webhooks, deadline policies,
notifications, site config, and the audit log.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def list_gremien() -> dict:
    """List all Gremien."""
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
async def list_cd_variants() -> dict:
    """List the corporate-design variants with their logos. Requires admin.cd_variants.

    Use `list_cd_variant_options` instead when you only need the id for a Gremium.
    """
    return await api().get("/admin/cd-variants")


@group.tool
async def list_cd_variant_options() -> dict:
    """List id, key and name of the corporate-design variants.

    Requires admin.gremien or admin.cd_variants. Use the returned id as `cdVariantId`
    when you create or patch a Gremium.
    """
    return await api().get("/cd-variants")


@group.tool
async def create_cd_variant(variant: S.CdVariantCreate) -> dict:
    """Create a corporate-design variant. Requires admin.cd_variants."""
    return await api().post("/admin/cd-variants", json=dump_create(variant))


@group.tool
async def update_cd_variant(variant_id: str, patch: S.CdVariantUpdate) -> dict:
    """Patch a corporate-design variant. Requires admin.cd_variants."""
    return await api().patch(f"/admin/cd-variants/{variant_id}", json=dump_patch(patch))


@group.tool
async def delete_cd_variant(variant_id: str) -> dict:
    """Delete a corporate-design variant. Requires admin.cd_variants.

    The call gives 409 while a Gremium still uses the variant.
    """
    return await api().delete(f"/admin/cd-variants/{variant_id}")


@group.tool
async def add_cd_variant_vendored_logo(
    variant_id: str, logo: S.CdVariantLogoVendoredCreate
) -> dict:
    """Add a logo that pytex ships to a variant. Requires admin.cd_variants."""
    return await api().post(
        f"/admin/cd-variants/{variant_id}/logos/vendored", json=dump_create(logo)
    )


@group.tool
async def delete_cd_variant_logo(logo_id: str) -> dict:
    """Remove one logo from a corporate-design variant. Requires admin.cd_variants."""
    return await api().delete(f"/admin/cd-variant-logos/{logo_id}")


@group.tool
async def get_gremium_mail_recipients(gremium_id: str) -> dict:
    """List the extra protocol recipients of a Gremium.

    A finalized protocol goes to the active members and also to these addresses.
    """
    return await api().get(f"/admin/gremien/{gremium_id}/mail-recipients")


@group.tool
async def set_gremium_mail_recipients(gremium_id: str, recipients: list[str]) -> dict:
    """Replace the extra protocol recipients of a Gremium.

    The call is an idempotent PUT. An empty list sends the protocol to the members
    only. Requires admin.gremien.
    """
    return await api().put(
        f"/admin/gremien/{gremium_id}/mail-recipients", json={"recipients": recipients}
    )


@group.tool
async def list_gremium_roles(gremium_id: str) -> dict:
    """List the roles that are scoped to a Gremium."""
    return await api().get(f"/admin/gremien/{gremium_id}/roles")


@group.tool
async def create_gremium_role(gremium_id: str, role: S.GremiumRoleCreate) -> dict:
    """Create a role that is scoped to a Gremium. Requires admin.gremien."""
    return await api().post(f"/admin/gremien/{gremium_id}/roles", json=dump_create(role))


@group.tool
async def update_gremium_role(role_id: str, patch: S.GremiumRoleUpdate) -> dict:
    """Patch a role that is scoped to a Gremium. Requires admin.gremien."""
    return await api().patch(f"/admin/gremium-roles/{role_id}", json=dump_patch(patch))


@group.tool
async def delete_gremium_role(role_id: str) -> dict:
    """Delete a role that is scoped to a Gremium. Requires admin.gremien."""
    return await api().delete(f"/admin/gremium-roles/{role_id}")


@group.tool
async def list_gremium_memberships(gremium_id: str) -> dict:
    """List the memberships of a Gremium.

    A membership links a member to a role of that Gremium.
    """
    return await api().get(f"/admin/gremien/{gremium_id}/memberships")


@group.tool
async def create_gremium_membership(
    gremium_id: str, membership: S.GremiumMembershipCreate
) -> dict:
    """Add a member to a Gremium with a Gremium role. Requires admin.gremien."""
    return await api().post(
        f"/admin/gremien/{gremium_id}/memberships", json=dump_create(membership)
    )


@group.tool
async def delete_gremium_membership(membership_id: str) -> dict:
    """End a Gremium membership. Requires admin.gremien."""
    return await api().delete(f"/admin/gremium-memberships/{membership_id}")


@group.tool
async def list_permissions() -> dict:
    """List the catalog of assignable permissions."""
    return await api().get("/admin/permissions")


@group.tool
async def list_roles() -> dict:
    """List the global roles and their permissions."""
    return await api().get("/admin/roles")


@group.tool
async def create_role(role: S.RoleCreate) -> dict:
    """Create a global role. Requires admin.roles."""
    return await api().post("/admin/roles", json=dump_create(role))


@group.tool
async def update_role(role_id: str, patch: S.RoleUpdate) -> dict:
    """Patch the label or the permissions of a global role. Requires admin.roles."""
    return await api().patch(f"/admin/roles/{role_id}", json=dump_patch(patch))


@group.tool
async def delete_role(role_id: str) -> dict:
    """Delete a global role. Requires admin.roles."""
    return await api().delete(f"/admin/roles/{role_id}")


@group.tool
async def list_role_assignments() -> dict:
    """List the RBAC role assignments.

    An assignment links a principal to a role. It can also carry a Gremium scope.
    """
    return await api().get("/admin/role-assignments")


@group.tool
async def create_role_assignment(assignment: S.RoleAssignmentCreate) -> dict:
    """Assign a role to a principal.

    The assignment can carry a Gremium scope and a validity period.
    Requires admin.roles.
    """
    return await api().post("/admin/role-assignments", json=dump_create(assignment))


@group.tool
async def update_role_assignment(
    assignment_id: str, patch: S.RoleAssignmentUpdate
) -> dict:
    """Patch the role, the Gremium or the validity of an assignment. Requires admin.roles."""
    return await api().patch(
        f"/admin/role-assignments/{assignment_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_role_assignment(assignment_id: str) -> dict:
    """Remove a role assignment. Requires admin.roles."""
    return await api().delete(f"/admin/role-assignments/{assignment_id}")


@group.tool
async def list_principals(q: str | None = None) -> dict:
    """List the principals (users).

    Args:
        q: Filter by a substring of the sub or the email.
    """
    return await api().get("/admin/principals", params=params(q=q))


@group.tool
async def update_principal(principal_id: str, active: bool) -> dict:
    """Activate or deactivate a principal. Requires admin.roles."""
    return await api().patch(
        f"/admin/principals/{principal_id}", json={"active": active}
    )


@group.tool
async def list_group_mappings() -> dict:
    """List the mappings from an OIDC group to a role."""
    return await api().get("/admin/group-mappings")


@group.tool
async def create_group_mapping(mapping: S.GroupMappingCreate) -> dict:
    """Map an OIDC group to a role.

    The mapping can carry a Gremium scope. Requires admin.roles.
    """
    return await api().post("/admin/group-mappings", json=dump_create(mapping))


@group.tool
async def update_group_mapping(mapping_id: str, patch: S.GroupMappingUpdate) -> dict:
    """Patch an OIDC group mapping. Requires admin.roles."""
    return await api().patch(f"/admin/group-mappings/{mapping_id}", json=dump_patch(patch))


@group.tool
async def list_application_types() -> dict:
    """List the application types in the admin view."""
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


@group.tool
async def list_webhooks() -> dict:
    """List the configured webhooks."""
    return await api().get("/admin/webhooks")


@group.tool
async def create_webhook(webhook: S.WebhookCreate) -> dict:
    """Create a webhook. Requires webhook.manage."""
    return await api().post("/admin/webhooks", json=dump_create(webhook))


@group.tool
async def update_webhook(webhook_id: str, patch: S.WebhookUpdate) -> dict:
    """Patch a webhook. Requires webhook.manage."""
    return await api().patch(f"/admin/webhooks/{webhook_id}", json=dump_patch(patch))


@group.tool
async def list_deadline_policies() -> dict:
    """List the named deadline policies.

    A flow state refers to a policy through `config.deadlinePolicyKey`.
    """
    return await api().get("/admin/deadline-policies")


@group.tool
async def create_deadline_policy(policy: S.DeadlinePolicyCreate) -> dict:
    """Create a deadline policy with an absolute date or a relative offset.

    Entry into a flow state that refers to the key of the policy creates a deadline.
    Requires admin.types.
    """
    return await api().post("/admin/deadline-policies", json=dump_create(policy))


@group.tool
async def update_deadline_policy(policy_id: str, patch: S.DeadlinePolicyUpdate) -> dict:
    """Patch a deadline policy.

    Use this to move the absolute date each semester. A new flow version is not needed.
    Requires admin.types.
    """
    return await api().patch(
        f"/admin/deadline-policies/{policy_id}", json=dump_patch(patch)
    )


@group.tool
async def delete_deadline_policy(policy_id: str) -> dict:
    """Delete a deadline policy.

    A state that refers to the policy then holds without a deadline.
    Requires admin.types.
    """
    return await api().delete(f"/admin/deadline-policies/{policy_id}")


@group.tool
async def get_notification_settings() -> dict:
    """Get the platform notification settings, such as the task reminder cadence. Admin."""
    return await api().get("/admin/notification-settings")


@group.tool
async def update_notification_settings(patch: S.NotificationSettingsUpdate) -> dict:
    """Patch the platform notification settings.

    The fields are `taskReminderEnabled`, `taskReminderAfterDays` and
    `taskReminderRepeatDays`. Admin.
    """
    return await api().put("/admin/notification-settings", json=dump_patch(patch))


@group.tool
async def get_notification_preferences() -> dict:
    """Get the notification preferences of the logged-in user."""
    return await api().get("/notifications/preferences")


@group.tool
async def set_notification_preferences(preferences: list[dict[str, Any]]) -> dict:
    """Replace the notification preferences of the logged-in user.

    Use the same shape that `get_notification_preferences` returns.
    """
    return await api().put(
        "/notifications/preferences", json={"preferences": preferences}
    )


@group.tool
async def get_site_config() -> dict:
    """Get the current site and branding config, both the active one and the draft."""
    return await api().get("/admin/site-config")


@group.tool
async def set_site_config_draft(branding: dict[str, Any]) -> dict:
    """Set the branding draft.

    Use the same shape as the draft in `get_site_config`. Call `activate_site_config`
    to make the draft active. Requires admin.site.
    """
    return await api().put("/admin/site-config/draft", json=branding)


@group.tool
async def activate_site_config() -> dict:
    """Activate the current branding draft. Requires admin.site."""
    return await api().post("/admin/site-config/activate")


@group.tool
async def list_audit(
    action: str | None = None,
    actor: str | None = None,
    since: str | None = None,
    until: str | None = None,
    before: int | None = None,
    limit: int | None = None,
) -> dict:
    """Read the audit log.

    The log is keyset-paged. Pass the smallest id you have seen as `before` to get
    the next page. Give `since` and `until` as ISO datetimes. Requires audit.read.
    """
    return await api().get(
        "/admin/audit",
        params=params(
            action=action, actor=actor, since=since, until=until,
            before=before, limit=limit,
        ),
    )


@group.tool
async def verify_audit_chain() -> dict:
    """Verify the hash chain of the audit log to find tampering. Requires audit.verify."""
    return await api().get("/admin/audit/verify")


def register(mcp: FastMCP) -> None:
    """Register the admin tool group."""
    group.register(mcp)
