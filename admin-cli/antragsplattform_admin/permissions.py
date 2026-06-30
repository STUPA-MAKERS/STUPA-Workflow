"""Vendored copy of the backend permission catalogue.

The authoritative truth about *assigned* permissions stays in ``role_permission`` (DB); this is
the catalogue of *selectable* keys the role-editor offers. Kept in sync by hand with
``backend/app/shared/permissions.py`` — if the backend gains a permission key, add it here too
(the editor also shows any key already present in the DB, even if missing from this list, so it
degrades gracefully).
"""

from __future__ import annotations

# Mirror of backend/app/shared/permissions.py:PERMISSION_CATALOGUE (keep in sync).
PERMISSION_CATALOGUE: tuple[str, ...] = (
    "application.read",
    "application.read_all",
    "application.create",
    "application.transition",
    "application.manage",
    "application.edit_any",
    "form.configure",
    "flow.configure",
    "vote.cast",
    "vote.manage",
    "meeting.manage",
    "meeting.view_all",
    "protocol.finalize",
    "meeting.delete_finalized",
    "budget.view",
    "budget.structure",
    "budget.book",
    "budget.export",
    "account.manage",
    "application.export",
    "webhook.manage",
    "audit.read",
    "audit.verify",
    "audit.revert",
    "admin.site",
    "admin.gremien",
    "admin.types",
    "admin.types_delete",
    "admin.roles",
    "admin.users",
    "admin.group_mappings",
    "admin.gremium_roles",
    "admin.delegations",
    "admin.deadlines",
    "admin.notifications",
    "privacy.manage",
    "mcp.use",
)

# vote.cast is never grantable through the API (human-only). The CLI hits the DB directly so it
# *could* set it — we still surface a warning in the editor; not technically blocked here.
FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset({"vote.cast"})
