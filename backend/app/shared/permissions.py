"""Permission catalogue — the single source of selectable keys for the admin UI.

The authoritative record of *assigned* permissions stays in ``role_permission``
(DB); this list is only the catalogue of keys the roles/permissions UI offers, so
the frontend never hardcodes which permissions exist.
"""

from __future__ import annotations

# Grouped by area for a stable, deterministic contract.
PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    # Read every application, independent of gremium/ownership (global).
    "application.read_all",
    "application.create",
    "application.transition",
    "application.manage",
    # Edit application data in ANY flow state — overrides the state edit lock.
    "application.edit_any",
    "form.configure",
    "flow.configure",
    "vote.cast",
    "vote.manage",
    "meeting.manage",
    # Global, purely additive READ permission: sees every meeting across gremien
    # (timeline/list, detail, agenda, protocol, vote results) but never writes/votes.
    "meeting.view_all",
    "protocol.finalize",
    # Delete meetings with a finalized protocol; separate from meeting.manage.
    # Each delete is audited as meeting_delete.
    "meeting.delete_finalized",
    "budget.view",
    "budget.structure",
    "budget.book",
    "budget.export",
    # Ignore a staged bank statement line (hide it from reconciliation). Kept
    # SEPARATE from budget.book because it removes a transaction from the treasurer's
    # to-reconcile view — an audit-sensitive act (every ignore/reactivate is logged
    # as bank_line_ignore / bank_line_reactivate). Grant deliberately.
    "budget.reconcile_ignore",
    "account.manage",
    "application.export",
    "webhook.manage",
    # audit.read is deliberately GLOBAL (no gremium scope): the audit log is an
    # org-wide forensic/integrity view (hash chain) that can expose cross-cutting PII.
    "audit.read",
    "audit.verify",
    # Revert a config change from the audit log (restore the prior state).
    # Destructive; admin-only by default.
    "audit.revert",
    "admin.site",
    "admin.gremien",
    "admin.types",
    # Delete application types; separate from admin.types (create/edit).
    # Destructive (form/flow attached).
    "admin.types_delete",
    # Per-page admin split: admin.roles keeps the role-definition page
    # (/admin/roles); the other admin pages get their own keys below.
    "admin.roles",
    # /admin/users - (de)activate users and manage role assignments.
    "admin.users",
    # /admin/group-mappings - IdP group -> role mappings.
    "admin.group_mappings",
    # /admin/gremien/:id/roles - gremium role definitions.
    "admin.gremium_roles",
    # /admin/delegations - manage delegations/substitute pool platform-wide.
    "admin.delegations",
    # /admin/deadlines - deadline policies.
    "admin.deadlines",
    # Platform notification config: reminder thresholds and mail templates.
    "admin.notifications",
    # /admin/privacy - GDPR: erasure requests, principal/application deletion,
    # Auskunft export, retention config.
    "privacy.manage",
    # MCP/agent access: issue OAuth tokens for API agents. Admins have it via the
    # bypass; assignable to non-admins.
    "mcp.use",
)
