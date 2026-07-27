"""Vendored copy of the backend permission catalog.

The ``role_permission`` table holds the authoritative set of assigned permissions.
This module only lists the selectable keys that the role editor offers. Keep the
list in sync by hand with ``backend/app/shared/permissions.py``. When the backend
gains a permission key, add the key here too. The editor also shows a key that the
database already holds, even when this list misses it.
"""

from __future__ import annotations

# Mirror of backend/app/shared/permissions.py:PERMISSION_CATALOGUE. Keep it in sync.
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

# The API never grants vote.cast, because voting is human-only. The CLI writes to the
# database directly, so it can still set the key. The editor shows a warning. This module
# does not block the key.
FORBIDDEN_PERMISSIONS: frozenset[str] = frozenset({"vote.cast"})
