"""Permission catalog: the single source of selectable keys for the admin UI.

The `role_permission` table in the database stays the authoritative record of the
*assigned* permissions. This list is only the catalog of keys that the roles and
permissions UI offers. The frontend therefore never hardcodes which permissions exist.
"""

from __future__ import annotations

# The keys stay grouped by area to keep the contract stable and deterministic.
PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    # Read every application, independent of Gremium and ownership. This is global.
    "application.read_all",
    "application.create",
    "application.transition",
    # Force an application into ANY state directly. This bypasses the flow guards and
    # the transitions. The override is audit-sensitive: the log records every use as
    # a forced status_change, and you can revert it. It stays SEPARATE from
    # application.transition. Grant it deliberately.
    "application.force_status",
    "application.manage",
    # Edit application data in ANY flow state. This overrides the state edit lock.
    "application.edit_any",
    # Delete an application with its versions, comments and timeline. No revert
    # brings it back, so it stays separate from application.manage.
    "application.delete",
    "form.configure",
    "flow.configure",
    "vote.cast",
    "vote.manage",
    "meeting.manage",
    # A global READ permission that only adds. The holder sees every meeting across all
    # Gremien: timeline, list, detail, agenda, protocol and vote results. The holder
    # never writes and never votes.
    "meeting.view_all",
    "protocol.finalize",
    # Delete a meeting that has a finalized protocol. This is separate from
    # meeting.manage. The audit log records each delete as meeting_delete.
    "meeting.delete_finalized",
    "budget.view",
    "budget.structure",
    "budget.book",
    "budget.export",
    "application.export",
    "webhook.manage",
    # audit.read is deliberately GLOBAL and carries no Gremium scope. The audit log is
    # an organization-wide forensic and integrity view over the hash chain. It can
    # expose PII across Gremien.
    "audit.read",
    "audit.verify",
    # Revert a config change from the audit log and restore the prior state. This is
    # destructive. It is admin-only by default.
    "audit.revert",
    "admin.site",
    "admin.gremien",
    "admin.types",
    # Delete an application type. This is separate from admin.types, which covers create
    # and edit. It is destructive, because a form and a flow hang on the type.
    "admin.types_delete",
    # Per-page admin split: admin.roles covers the role-definition page /admin/roles.
    # The other admin pages have their own keys below.
    "admin.roles",
    # /admin/users: activate or deactivate a user and manage role assignments.
    "admin.users",
    # /admin/group-mappings: map an IdP group to a role.
    "admin.group_mappings",
    # /admin/gremien/:id/roles: Gremium role definitions.
    "admin.gremium_roles",
    # /admin/cd-variants: corporate-design variants (document logos), incl. the
    # logo upload and download.
    "admin.cd_variants",
    # /admin/delegations: manage the delegations and the substitute pool platform-wide.
    "admin.delegations",
    # /admin/deadlines: deadline policies.
    "admin.deadlines",
    # Platform notification config: reminder thresholds and mail templates.
    "admin.notifications",
    # /admin/privacy: GDPR erasure requests, principal and application deletion,
    # subject-access export and retention config.
    "privacy.manage",
    # MCP and agent access: issue OAuth tokens for API agents. An admin holds it through
    # the bypass. You can also assign it to a non-admin.
    "mcp.use",
)
